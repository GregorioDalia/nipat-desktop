# NIPAT 0.8.13: one resource budget for pileup acquisition and R processing.
# Scientific formulas and within-locus observation order remain unchanged.
# NIPAT 0.8.50: declared scientific parameters and readable model constants.
cat("\n###### DNPcall ######\n\n\n\n")


# Track start time and memory
start_time <- Sys.time()
get_memory_usage_mb <- function() {
  mem_kb <- as.numeric(gsub("VmRSS:\\s+| kB", "", grep("VmRSS", readLines("/proc/self/status"), value = TRUE)))
  mem_mb <- mem_kb / 1024
  return(round(mem_mb, 2))
}

start_mem <- get_memory_usage_mb()

peak_mem <- start_mem

update_peak <- function() {
  current_mem <- get_memory_usage_mb()
  if (current_mem > peak_mem) {
    assign("peak_mem", current_mem, envir = .GlobalEnv)
  }
}




# package needed
suppressPackageStartupMessages(library('tidyverse'))
suppressPackageStartupMessages(library('stringr'))
suppressPackageStartupMessages(library('purrr'))
suppressPackageStartupMessages(library('ComplexUpset'))
suppressPackageStartupMessages(library('parallel'))

# read the arguments given
args <- commandArgs(trailingOnly = TRUE)
error0 = c()

if(length(grep("bamlist",args)) != 0) {
  bamlist = strsplit(args[grep("--bamlist*",args)],"=")[[1]][[2]]
} else {
  error0 = c(error0,"bamlist")
}
if(length(grep("DNPs",args)) != 0) {
  DNPlist = strsplit(args[grep("--DNPs*",args)],"=")[[1]][[2]]
} else {
  error0 = c(error0,"DNPs")
}
if(length(grep("reference",args)) != 0) {
  reference = strsplit(args[grep("--reference*",args)],"=")[[1]][[2]]
} else {
  error0 = c(error0,"reference")
}
if(length(grep("out",args)) != 0) {
  output = strsplit(args[grep("--out*",args)],"=")[[1]][[2]]
} else {
  error0 = c(error0,"out")
}
if(length(error0)>0) {
  cat("\n\t # ERROR: These required arguments could not be found:\n")
  cat(paste0("\t\t"),paste0(error0,collapse = ", "))
  cat("\n")
  quit()
}

# create output directories
dir.create(output, showWarnings = FALSE)
dir.create(file.path(output, "individual_outputs"), showWarnings = FALSE)
dir.create(file.path(output, "plots"), showWarnings = FALSE)
dir.create(file.path(output, "summary"), showWarnings = FALSE)

# function to format all numeric columns to fixed decimal places (e.g., 3 decimals)
format_df_decimals <- function(df, digits = 3) {
  df[] <- lapply(df, function(col) {
    if (is.numeric(col)) {
      # Only format values that are not whole numbers
      col_formatted <- ifelse(col %% 1 == 0, col, round(col, digits))
      return(col_formatted)
    } else {
      return(col)
    }
  })
  return(df)
}



# The legacy --parallel argument remains accepted. The common execution policy
# selects automatic or serial work for all R modules and caps the global pool.
source(Sys.getenv("NIPAT_PARALLEL_HELPER", unset = "/opt/nipat/lib/nipat_scientific/parallel.R"))
source(Sys.getenv("NIPAT_SETTINGS_HELPER", unset = file.path(dirname(Sys.getenv(
  "NIPAT_PARALLEL_HELPER", unset = "/opt/nipat/lib/nipat_scientific/parallel.R")), "settings.R")))
nipat_cfg <- nipat_settings("dnp-call")
nipat_write_settings("dnp-call", nipat_cfg, output)
source(Sys.getenv("NIPAT_PLOTS_HELPER", unset = "/opt/nipat/lib/nipat_scientific/plots.R"))



# read the df
r_bamlist<-read.table(bamlist,header=F,col.names = "samples")
r_DNPlist <- read.table(DNPlist, header=FALSE, col.names=c("chr","pos1","pos2","REF","ALT"),
                        colClasses=c("character","integer","integer","character","character"),
                        na.strings=NULL, quote="", comment.char="")

update_peak()

cat("Samples analyzed:\n")
print(r_bamlist)
cat("\n")

# make .bed file for calling
bedfile <- as.data.frame(cbind(r_DNPlist$chr, r_DNPlist$pos1-2, r_DNPlist$pos2+1))
write.table(bedfile,file = "bedfile_for_mpileup.bed",row.names = F,col.names = F,quote=F,sep="\t")

# make a df to assign a unique label for each DNP, necessary if there are very close DNPs falling in the same read
make_ForUniqReads1 <- function(r_DNPlist) {
  df <- data.frame(
    pos_before = paste0(r_DNPlist$chr, ":", r_DNPlist$pos1 - 1),
    pos1       = paste0(r_DNPlist$chr, ":", r_DNPlist$pos1),
    pos2       = paste0(r_DNPlist$chr, ":", r_DNPlist$pos2),
    pos_after  = paste0(r_DNPlist$chr, ":", r_DNPlist$pos2 + 1),
    orig_idx   = seq_len(nrow(r_DNPlist)),
    stringsAsFactors = FALSE
  )
  return(df)
}

ForUniqReads1 <- make_ForUniqReads1(r_DNPlist)

df_int <- gather(data=ForUniqReads1,key="col", value="pos", 1:4)
ForUniqReads <- df_int[,c(3,1)]
colnames(ForUniqReads) <- c("df.chr","uniq")

# make a DNP-based df
make_RefAltDNP <- function(r_DNPlist) {
  RefAltDNP <- data.frame(
    POS = paste0(r_DNPlist$chr, ":", r_DNPlist$pos1, "|", r_DNPlist$chr, ":", r_DNPlist$pos2),
    ref = gsub('^(.{1})(.*)$', '\\1|\\2', r_DNPlist$REF),
    alt = gsub('^(.{1})(.*)$', '\\1|\\2', r_DNPlist$ALT),
    stringsAsFactors = FALSE
  )
  return(RefAltDNP)
}
RefAltDNP <- make_RefAltDNP(r_DNPlist)



# Scientific formulas stay below; this helper only indexes and bounds input.
source(Sys.getenv("NIPAT_DNP_BLOCKS_HELPER", unset = "/opt/nipat/lib/nipat_scientific/dnp_blocks.R"))
nipat_progress <- function(...) invisible(NULL)
progress_helper <- Sys.getenv("NIPAT_PROGRESS_R_HELPER")
if (nzchar(progress_helper)) {
  tryCatch(source(progress_helper), error = function(error) invisible(NULL))
}

# pileup calling with samtools
cat("\nMaking mpileup...\n")
dnp_scratch <- Sys.getenv("NIPAT_DNP_SCRATCH")
if (!nzchar(dnp_scratch)) {
  dir.create("work", showWarnings = FALSE)
  dnp_scratch <- tempfile("dnp-", tmpdir = "work")
}
dir.create(dnp_scratch, recursive = TRUE, showWarnings = FALSE)
dnp_scratch <- normalizePath(dnp_scratch, mustWork = TRUE)
pileup_path <- file.path(dnp_scratch, "mpileup.txt")
pileup_helper <- Sys.getenv("NIPAT_DNP_PILEUP_HELPER", unset = "/opt/nipat/lib/nipat_scientific/dnp_pileup.py")
# Acquisition finishes before the R block pool starts. Export the same resource
# policy to the Python scheduler instead of creating a second independent pool
# or interpreting the legacy --parallel flag. The helper caps this upper bound
# by the actual number of chromosome tasks and counts each samtools process.
acquisition_budget <- nipat_parallel_budget(.Machine$integer.max)
acquisition_budget_path <- file.path("work", "dnp-acquisition-budget.json")
dir.create(dirname(acquisition_budget_path), recursive = TRUE, showWarnings = FALSE)
jsonlite::write_json(c(list(schema_version = 1L, interface = "nipat-parallel-v1"),
                       acquisition_budget), acquisition_budget_path,
                     auto_unbox = TRUE, pretty = TRUE, digits = NA, null = "null")
acquisition_started <- proc.time()[["elapsed"]]
acquisition_status <- system2("python3", c(shQuote(pileup_helper),
  "--bamlist", shQuote(bamlist), "--bed", "bedfile_for_mpileup.bed",
  "--reference", shQuote(reference), "--output", shQuote(pileup_path),
  "--scratch-dir", shQuote(dnp_scratch), "--metadata", "work/dnp-pileup.json",
  "--budget", shQuote(acquisition_budget_path)))
if (acquisition_status != 0L) stop("DNP pileup acquisition failed")
acquisition_seconds <- unname(proc.time()[["elapsed"]] - acquisition_started)
if (identical(Sys.getenv("NIPAT_DNP_KEEP_PILEUP"), "1")) {
  if (!file.copy(pileup_path, "mpileup.txt", overwrite = FALSE)) stop("Cannot retain test pileup")
}

# read sample list, remove path and ".bam" extension in the name
read_samplelist <- function(bamlist_file) {
  list0<-scan(bamlist_file,character(),quiet=T)
  list <- gsub("(.*/\\s*(.*$))", "\\2", list0)
  samplelist<-gsub(".bam", "", list)
  return(samplelist)
}
samplelist <- read_samplelist(bamlist)

# reading pileup file in r
cat("\nReading mpileup...\n")
nipat_progress("start", "pileup-index")
pileup_index <- nipat_dnp_index(pileup_path, empty_samples=length(samplelist))
# Observed reference bases belong to the reference assembly, independent of
# what the reads carry. A swapped REF/ALT would invert an otherwise plausible call.
pileup_keys <- paste(pileup_index$chromosomes[pileup_index$chromosome], pileup_index$positions, sep=":")
panel_keys <- c(paste(r_DNPlist$chr, r_DNPlist$pos1, sep=":"),
                paste(r_DNPlist$chr, r_DNPlist$pos2, sep=":"))
expected <- c(substr(r_DNPlist$REF, 1L, 1L), substr(r_DNPlist$REF, 2L, 2L))
bases <- toupper(pileup_index$reference[match(panel_keys, pileup_keys)])
mismatch <- which(!is.na(bases) & bases != toupper(expected))
if (length(mismatch)) stop("DNP panel REF differs from pileup at ", panel_keys[mismatch[[1L]]])
block_plan <- nipat_dnp_plan(pileup_index, ForUniqReads, RefAltDNP)
# Persist the strategy before scientific processing, including on later errors.
nipat_dnp_write_metrics("work/dnp-blocks.json", list(
  schema_version = 1L, status = "started", index_rows = pileup_index$rows,
  index_bytes = pileup_index$bytes, column_classes = pileup_index$classes,
  acquisition_seconds = acquisition_seconds, index_seconds = pileup_index$elapsed_seconds,
  block_loci_limit = block_plan$max_loci, block_raw_bytes_limit = block_plan$max_bytes,
  compatibility_reasons = I(block_plan$compatibility_reasons),
  unmatched_coordinate_rows = block_plan$unmatched_rows,
  repeated_qname_rows = pileup_index$repeated_qname_rows,
  memory_limit_scope = "raw input proxy; complete windows and legacy compatibility groups are never split or truncated"
))
nipat_progress("end", "pileup-index", outcome = "succeeded")
# Every sample/block pair shares one bounded pool. Complete global index and
# compatibility groups are constructed once before any worker is started.
common_columns <- 3
final_merged_data <- NULL

update_peak()

# calling processing for each sample
prepare_individual <- function(i) {
  force(i)
  cat(paste0("\nProcessing sample: ", i, "\n"))

  start_ind_time <- Sys.time()
  start_ind_mem <- get_memory_usage_mb()
  peak_ind_mem <- start_ind_mem

  # update the peak memory usage for the current individual
  update_peak_ind <- function() {
    current_mem <- get_memory_usage_mb()
    if (current_mem > peak_ind_mem) {
      peak_ind_mem <<- current_mem  # use <<- to update the enclosing function's variable
    }
  }

  nipat_progress("start", "dnp-processing", sample_ids = i)
  final_df_elab <- function(dataframe_final2, df_grouped, dfIND_summary) {
    FINAL_df <- merge(dataframe_final2, df_grouped, by.x = "DNPs", by.y = "chr1", all = TRUE)

    FINAL_df2 <- separate(FINAL_df, col = "DNPs", into = c("pos1", "pos2"), sep = "\\|")
    FINAL_df3 <- separate(FINAL_df2, col = "pos1", into = c("chr", "pos1"), sep = "\\:")
    FINAL_df4 <- separate(FINAL_df3, col = "pos2", into = c("chr", "pos2"), sep = "\\:")

    final <- FINAL_df4[, c(2, 1, 3:ncol(FINAL_df4))]

    final$Reference <- gsub('\\|', '', final$Reference)
    final$Alternative <- gsub('\\|', '', final$Alternative)
    final$combined_bases <- gsub('\\|', '', final$combined_bases)

    final$.nipat_sort_key <- FINAL_df$DNPs
    final <- final %>%
      mutate(pos1 = as.numeric(pos1),
             pos2 = as.numeric(pos2)) %>%
      left_join(dfIND_summary, by = c("chr", "pos1", "pos2"))

    final <- final %>%
      relocate(indel_reads, indel_ratio, .after = total_count)
    sort_keys <- final$.nipat_sort_key
    final$.nipat_sort_key <- NULL

      colnames(final) <- c("chr", "pos1", "pos2",
                          "REF", "ALT", "N_REF",
                          "N_ALT", "N_Other",
                          "GL0", "GL1", "GL2", "GT",
                          "combined_bases",
                          "combined_counts", "total_count", "reads_discarded_for_indels", "ratio_reads_discarded_for_indels")

    indiv_final <- final[, c("chr", "pos1", "pos2", "REF", "ALT", "GT")]

    update_peak_ind()

    # final memory check in case the peak occurred at the end of the function
    final_mem <- get_memory_usage_mb()
    if (final_mem > peak_ind_mem) {
     peak_ind_mem <- final_mem
    }

    return(list(indiv_final = indiv_final, final = final, peak_mem = peak_ind_mem,
                sort_keys = sort_keys))

  }


  compute_block <- function(pileup_bamlist, ForUniqReads, RefAltDNP) {
  depth_col <- common_columns + (which(samplelist == i) - 1) * 4 + 1
  covered <- any(pileup_bamlist[[paste0("V", depth_col)]] > 0L, na.rm=TRUE)
  if (!nrow(pileup_bamlist)) {
    # An uncovered block still occurs in the whole-sample final merge. Supply
    # its missing counts/likelihoods to the unchanged final formatter.
    missing <- data.frame(
      DNPs = RefAltDNP$POS, Reference = RefAltDNP$ref, Alternative = RefAltDNP$alt,
      N_Reference = 0, N_Alternative = 0, N_Altro = 0,
      GL0 = 0, GL1 = 0, GL2 = 0, GT = NA, stringsAsFactors = FALSE)
    grouped <- data.frame(chr1 = character(), combined_bases = character(),
                          combined_counts = character(), total_count = integer())
    indels <- data.frame(chr = character(), pos1 = numeric(), pos2 = numeric(),
                         indel_reads = integer(), indel_ratio = numeric())
    result <- final_df_elab(missing, grouped, indels)
    result$has_likelihoods <- FALSE
    result$covered <- FALSE
    return(result)
  }
  # extract sample-specific columns
  reads_col <- depth_col + 1
  qual_col <- reads_col + 1
  id_col <- qual_col + 1

  select_indiv_df <- function(pileup_bamlist, depth_col, reads_col, qual_col, id_col) {
    depth_sym <- sym(paste0("V", depth_col))
    reads_sym <- sym(paste0("V", reads_col))
    qual_sym  <- sym(paste0("V", qual_col))
    id_sym    <- sym(paste0("V", id_col))
    pileup_bamlist %>%
      select(
        V1 = V1,
        V2 = V2,
        V3 = V3,
        V4 = !!depth_sym,
        V5 = !!reads_sym,
        V6 = !!qual_sym,
        V7 = !!id_sym
      )
  }

  indiv_df <- select_indiv_df(
    pileup_bamlist,
    depth_col = depth_col,
    reads_col = reads_col,
    qual_col  = qual_col,
    id_col    = id_col
  )

  update_peak_ind()

  # substitute . and , with reference base
  indiv_df$V5 <- mapply(function(v3, v5) gsub("[.,]", v3, v5), indiv_df$V3, indiv_df$V5)

  # create "chr:position" column
  indiv_df$chr <- paste(indiv_df$V1, indiv_df$V2, sep = ":")

  # select necessary columns
  df2 <- data.frame(df.chr = indiv_df$chr, df.V5 = indiv_df$V5, df.V7 = indiv_df$V7, df.qual = indiv_df$V6)
  rm(indiv_df)

  # substitution of characters to modify the df
  clean_df <- function(df2) {
    df2$df.V5 <- gsub("\\*", "@", df2$df.V5)
    df2$df.V5 <- gsub("[actgACTG]([+-]\\d+)+", "@", df2$df.V5)
    return(df2)
  }

  df2 <- clean_df(df2)

  update_peak_ind()

  # Tokenize valid pileup observations directly. The original separator-based
  # path remains the fallback for missing fields, embedded whitespace or unequal
  # lengths, retaining its recycling and validation semantics for those inputs.
  split_and_filter_df <- function(df2) {
    fields <- df2[, c("df.V5", "df.V7", "df.qual")]
    direct <- nrow(df2) > 0L && !anyNA(fields) &&
      !any(vapply(fields, function(x) any(grepl("[[:space:]]", x)), logical(1)))
    if (direct) {
      bases <- strsplit(as.character(df2$df.V5), "", fixed = TRUE)
      reads <- strsplit(as.character(df2$df.V7), ",", fixed = TRUE)
      qualities <- strsplit(as.character(df2$df.qual), "", fixed = TRUE)
      counts <- lengths(bases)
      direct <- all(counts > 0L & counts == lengths(reads) &
                    counts == lengths(qualities)) &&
        !any(vapply(reads, function(x) any(!nzchar(x)), logical(1))) &&
        !any(endsWith(as.character(df2$df.V7), ","))
      if (direct) {
        return(tibble(
          df.V7 = unlist(reads, use.names = FALSE),
          df.chr = rep(df2$df.chr, counts),
          df.V5 = unlist(bases, use.names = FALSE),
          df.qual = unlist(qualities, use.names = FALSE)
        ))
      }
      rm(bases, reads, qualities, counts)
    }
    df2$df.V7 <- paste0(",", df2$df.V7, ",")
    df2$df.V5 <- gsub("", " ", df2$df.V5)
    df2$df.V7 <- gsub(",", " ", df2$df.V7)
    df2$df.qual <- gsub("", " ", df2$df.qual)
    df3 <- df2 %>%
      separate_rows(df.V5, df.V7, df.qual, sep = " ")
    df4 <- df3[, c(3, 1, 2, 4)]
    df4.1 <- df4[df4$df.V7 != "", ]
    return(df4.1)
  }

  df4.1 <- split_and_filter_df(df2)
  rm(df2)

  update_peak_ind()

  # get unique label for each DNP
  unique_labels <- function(df4.1, ForUniqReads) {
    df5 <- dplyr::left_join(df4.1, ForUniqReads, by = "df.chr")
    df5$readUniq <- paste(df5$df.V7, df5$uniq, sep = "_")
    df6 <- df5[, c(6, 2, 3, 4)]
    return(df6)
  }

  df6 <- unique_labels(df4.1, ForUniqReads)
  rm(df4.1)

  # convert ASCII pred score to number
  # A single lookup replaces one R callback per observation for SAM quality
  # characters. Keep the original conversion for nonstandard direct R input.
  quality_codes <- match(df6$df.qual, intToUtf8(33:126, multiple = TRUE))
  if (is.character(df6$df.qual) && length(quality_codes) > 0L && !anyNA(quality_codes)) {
    quality_names <- if (is.null(names(df6$df.qual))) df6$df.qual else names(df6$df.qual)
    df6$df.qual <- setNames(quality_codes - 1, quality_names)
    rm(quality_names)
  } else {
    df6$df.qual <- sapply(df6$df.qual, function(x) as.integer(charToRaw(x)) - 33)
  }
  rm(quality_codes)


  # group by new read label
  DF <- df6 %>%
    group_by(readUniq) %>%
    summarise(
      chr = paste(df.chr, collapse = "|"),
      pos = paste(df.V5, collapse = "|"),
      qual = paste(df.qual, collapse = "|"),
      .groups = "drop"
    )
  # The original merges return a data.frame sorted using the current locale.
  DF <- as.data.frame(DF)
  names(DF)[1] <- "ID_DNP"
  DF <- DF[order(DF$ID_DNP), , drop = FALSE]
  rownames(DF) <- NULL
  rm(df6)

  # substitute characters strand specific characters (unecessary) with only uppercase letters
  UppLowSub <- function(DF) {
    DF$pos <- chartr("gact,", "GACT.", DF$pos)
    return(DF)
  }

  DF <- UppLowSub(DF)



  # count INDEL reads and their ratio over total reads per DNP
  compute_indel_summary <- function(DF) {
    DF_with_INDEL <- DF[nchar(DF$pos) > 6, ]

    DF_INDEL <- DF_with_INDEL %>%
      mutate(
        pos2 = substr(pos, 3, 5)
      ) %>%
      select(-pos)

    dfIND_count <- DF_INDEL %>%
      group_by(chr, pos2) %>%
      summarise(n = n(), .groups = "drop")

    # Pulizia colonna chr
    dfIND_count$chr <- str_extract(dfIND_count$chr, "\\|.*\\|")
    dfIND_count$chr <- substr(dfIND_count$chr, 2, nchar(dfIND_count$chr) - 1)

    dfIND_count <- dfIND_count %>%
      mutate(is_indel = grepl("@", pos2))

    dfIND_summary <- dfIND_count %>%
      group_by(chr) %>%
      summarise(
        total_reads = sum(n),
        indel_reads = sum(n[is_indel]),
        indel_ratio = indel_reads / total_reads,
        .groups = "drop"
      )

    dfIND_summary <- dfIND_summary %>%
      rename(chr_full = chr) %>%
      separate(chr_full, into = c("part1", "part2"), sep = "\\|") %>%
      separate(part1, into = c("chr", "pos1"), sep = ":") %>%
      separate(part2, into = c("chr2", "pos2"), sep = ":") %>%
      select(-chr2) %>%
      mutate(
        pos1 = as.numeric(pos1),
        pos2 = as.numeric(pos2)
      )

    dfIND_summary_min <- dfIND_summary %>%
      select(chr, pos1, pos2, indel_reads, indel_ratio)

    return(dfIND_summary_min)
  }


  dfIND_summary <- compute_indel_summary(DF)



  # eliminate reads with "@", indicating reads with INDELs
  DFnoINDEL <- DF %>%
    filter_all(all_vars(!grepl("@", .)))
  rm(DF)

  # keep only micro haplotype
  righe_modificate <- DFnoINDEL[nchar(DFnoINDEL$pos)>6,]
  rm(DFnoINDEL)

  # extract DNP info
  # Coordinates and quality patterns recur across reads. Extract each distinct
  # pattern once; preserve the original strsplit handling of short/empty values
  # and the names produced by sapply on character vectors.
  extract_middle_pair <- function(values) {
    extract <- function(x) {
      parts <- strsplit(x, "\\|")[[1]]
      paste(parts[2:3], collapse = "|")
    }
    if (!length(values)) return(character())
    patterns <- unique(values)
    pairs <- vapply(patterns, extract, character(1), USE.NAMES = FALSE)
    result <- pairs[match(values, patterns)]
    names(result) <- if (is.null(names(values))) values else names(values)
    return(result)
  }

  # Retain only the three columns used downstream, avoiding a wider copy of all
  # per-read data merely to select these columns immediately afterwards.
  good_reads <- righe_modificate[, c("chr", "pos", "qual"), drop = FALSE]
  names(good_reads) <- c("chr1", "pos2", "qual1")
  good_reads <- good_reads %>%
    mutate(chr1 = extract_middle_pair(chr1),
           pos2 = substr(pos2, 3, 5),
           qual1 = extract_middle_pair(qual1))
  rm(righe_modificate)

  # compute BQ average between the two DNP positions
  # Compute each distinct pair once with the original mean(), including its
  # missing-value behavior, then restore the exact per-read order.
  quality_pairs <- unique(good_reads$qual1)
  pair_means <- sapply(quality_pairs, function(x) {
    values <- as.numeric(strsplit(x, "\\|")[[1]])
    mean(values)
  })
  mean_quality <- pair_means[match(good_reads$qual1, quality_pairs)]
  if (length(good_reads$qual1)) {
    names(mean_quality) <- if (is.null(names(good_reads$qual1))) {
      good_reads$qual1
    } else {
      names(good_reads$qual1)
    }
  }
  good_reads <- good_reads %>% mutate(mean_quality = mean_quality)
  rm(quality_pairs, pair_means, mean_quality)


  # for full* dataset final
  group_reads <- function(good_reads) {
    df_count <- good_reads %>%
      group_by(chr1, pos2) %>%
      summarise(n = n(), .groups = 'drop')

    df_grouped <- df_count %>%
      group_by(chr1) %>%
      summarise(
        combined_bases = paste(unique(pos2), collapse = "-"),
        combined_counts = paste(n, collapse = "-"),
        total_count = sum(n),
        .groups = 'drop'
      )

    return(df_grouped)
  }

  df_grouped <- group_reads(good_reads)

  # merge with ref alt data
  data_info <- merge(good_reads, RefAltDNP, by.x = "chr1", by.y = "POS")
  rm(good_reads)

  # create df for other (error) alleles
  make_df_other <- function(data_info) {
    altro_dt <- subset(data_info, pos2 != ref & pos2 != alt)

    altro_dt_grouped <- altro_dt %>%
      group_by(chr1, pos2) %>%
      summarise(n = n(), .groups = 'drop')

    altro_dt2 <- data.frame(DNPs = altro_dt_grouped$chr1, n = altro_dt_grouped$n)

    altro_dt3 <- altro_dt2 %>%
      group_by(DNPs) %>%
      summarise(n_altro = sum(n), .groups = 'drop')

    return(altro_dt3)
  }

  altro_dt3 <- make_df_other(data_info)


  # create df only for alleles ref or alt
  ref_alt_dt <- subset(data_info, pos2 == ref | pos2 == alt)

  ############## GL ###########

  # likelihood function
  computeGL_dinuc_safe <- function(haps, Qavg, ref_hap, ploidy = 2) {
    n <- length(haps)
    if (length(Qavg) != n) stop("haps e Qavg need to be of the same length")

    # eps_j for every read
    eps   <- 10^(-Qavg/10)
    isRef <- (haps == ref_hap)

    logL <- numeric(ploidy + 1)
    names(logL) <- 0:ploidy

    for (g in 0:ploidy) {
      # P(obs|g) for read
      p_ref <- (ploidy - g)/ploidy * (1 - eps) + (g)/ploidy * eps
      p_alt <- (ploidy - g)/ploidy * eps       + (g)/ploidy * (1 - eps)
      pj    <- ifelse(isRef, p_ref, p_alt)
      logL[as.character(g)] <- sum(log(pj))
    }
    logL
  }

  # loop on DNPs
  positions <- unique(ref_alt_dt$chr1)
  out <- vector("list", length(positions))
  # Build row indices once, preserving both locus and within-locus read order.
  # Retain the native logical-subset behavior for missing keys in direct R input.
  position_rows <- if (anyNA(ref_alt_dt$chr1)) {
    NULL
  } else {
    split(seq_len(nrow(ref_alt_dt)), match(ref_alt_dt$chr1, positions))
  }

  for (k in seq_along(positions)) {
    pos <- positions[k]
    sub <- if (is.null(position_rows)) {
      ref_alt_dt[ref_alt_dt$chr1 == pos, ]
    } else {
      ref_alt_dt[position_rows[[k]], , drop = FALSE]
    }

    # alleles without'|'
    haps <- gsub("\\|", "", sub$pos2)
    Qavg <- sub$mean_quality

    # reference and alt alleles
    ref_hap <- gsub("\\|", "", sub$ref[1])
    alt_hap <- gsub("\\|", "", sub$alt[1])

    # compute log‐likelihood
    logL <- computeGL_dinuc_safe(haps, Qavg, ref_hap, ploidy = 2)

    # call GT
    gt   <- c("0/0","0/1","1/1")[which.max(logL)]

    out[[k]] <- data.frame(
      chr_pos = pos,
      ref_hap = ref_hap,
      alt_hap = alt_hap,
      GL0     = logL["0"],
      GL1     = logL["1"],
      GL2     = logL["2"],
      GT      = gt,
      stringsAsFactors = FALSE
    )
  }

  res <- do.call(rbind, out)
  rm(ref_alt_dt, position_rows)

  update_peak_ind()


###################################


  # create df for reference alleles
  make_df_ref <- function(data_info) {
    ref_dt <- subset(data_info, pos2 == ref)

    ref_dt_grouped <- ref_dt %>%
      group_by(chr1, pos2, ref, alt) %>%
      summarise(n = n(), .groups = 'drop')

    colnames(ref_dt_grouped) <- c("DNPs", "geno", "ref", "alt", "n_ref")

    return(ref_dt_grouped)
  }

  ref_dt_grouped <- make_df_ref(data_info)


  # create df for alternative alleles
  make_df_alt <- function(data_info) {
    alt_dt <- subset(data_info, pos2 == alt)

    alt_dt_grouped <- alt_dt %>%
      group_by(chr1, pos2, ref, alt) %>%
      summarise(n = n(), .groups = 'drop')

    colnames(alt_dt_grouped) <- c("DNPs", "geno", "ref", "alt", "n_alt")

    return(alt_dt_grouped)
  }

  alt_dt_grouped <- make_df_alt(data_info)
  rm(data_info)


  # merge the 3 dfs
  merge_3_dfs <- function(ref_dt_grouped, alt_dt_grouped, altro_dt3, RefAltDNP, res) {
    # A complete block can lack retained ref/alt reads although other blocks
    # have them. Preserve the whole-sample merge's empty likelihood schema.
    if (is.null(res)) res <- data.frame(
      chr_pos = character(), ref_hap = character(), alt_hap = character(),
      GL0 = numeric(), GL1 = numeric(), GL2 = numeric(), GT = character(),
      stringsAsFactors = FALSE)
    merged1 <- merge(ref_dt_grouped, alt_dt_grouped, by = "DNPs", all = TRUE)
    merged2 <- merge(merged1, altro_dt3, by = "DNPs", all = TRUE)
    merged3 <- merge(merged2, RefAltDNP, by.x = "DNPs", by.y = "POS", all = TRUE)
    merged4 <- merge(merged3, res, by.x = "DNPs", by.y = "chr_pos", all = TRUE)
    return(merged4)
  }

  merged4 <- merge_3_dfs(ref_dt_grouped, alt_dt_grouped, altro_dt3, RefAltDNP, res)

  # substitute NA with 0
  merged4[is.na(merged4)] <- 0

  # reorder and rename columns
  dataframe_final <- merged4[, c(1, 11, 12, 5,9,10, 15,16,17,18)]
  colnames(dataframe_final) <- c("DNPs", "Reference", "Alternative",
                                 "N_Reference", "N_Alternative", "N_Altro",
                                 "GL0", "GL1", "GL2", "GT")

  # Mark GT as NA when Other reaches the configured fraction of all reads.
  dataframe_final2 <- dataframe_final %>%
    mutate(GT=ifelse(N_Altro/(N_Altro+N_Reference+N_Alternative) >= nipat_cfg$other_fraction_max, NA, GT))

  result <- final_df_elab(dataframe_final2, df_grouped, dfIND_summary)
  result$has_likelihoods <- !is.null(res) && nrow(res) > 0L
  result$covered <- covered
  result
  }

  finish_individual <- function(processed) {
  block_results <- processed$results
  block_metrics <- processed$metrics
  block_workers <- processed$workers
  observed_block_workers <- processed$observed_workers
  processing_seconds <- processed$elapsed_seconds
  peak_ind_mem <<- max(peak_ind_mem,
                       vapply(block_results, function(value) value$peak_mem, numeric(1)))
  rm(processed)
  # Distinguish a sample with zero coverage from a covered sample for which
  # the likelihood calculation failed to yield any usable allele.
  if (any(vapply(block_results, function(value) value$covered, logical(1))) &&
      !any(vapply(block_results, function(value) value$has_likelihoods, logical(1)))) {
    stop("DNP sample has no retained reference/alternative likelihoods")
  }
  final <- nipat_dnp_combine(block_results)
  indiv_final <- final[, c("chr", "pos1", "pos2", "REF", "ALT", "GT")]
  rm(block_results)
  colnames(indiv_final)[6] <- paste0("GT_", i)
  nipat_progress("end", "dnp-processing", sample_ids = i, outcome = "succeeded")
  nipat_progress("start", "plots", sample_ids = i)


  # format numeric columns and save individual output files
  final_formatted <- format_df_decimals(final)
  write.table(final_formatted, file.path(output, "individual_outputs", paste0("full_output_", i, ".txt")), sep = "\t", row.names = FALSE, quote = FALSE)


 # create individual folder inside plots
  indiv_plot_dir <- file.path(output, "plots", i)
  dir.create(indiv_plot_dir, showWarnings = FALSE, recursive = TRUE)


  nipat_sample_plots(final, indiv_plot_dir, i, locus_kind = "DNP")

  end_ind_time <- Sys.time()
  end_ind_mem <- get_memory_usage_mb()

  ind_mem_delta <- end_ind_mem - start_ind_mem
  ind_exec_time <- round(difftime(end_ind_time, start_ind_time, units = "secs"), 2)

  cat(paste0("\n>>> Summary for ", i, ":\n"))
  cat(paste0("Execution Time (seconds): ", ind_exec_time, "\n"))
  cat(paste0("Maximum observed R-process RSS (MiB): ", peak_ind_mem, "\n"))
  nipat_progress("end", "plots", sample_ids = i, outcome = "succeeded")
  return(list(indiv_final = indiv_final, final = final, peak_mem = peak_ind_mem,
              block_metrics = block_metrics, block_workers = block_workers,
              observed_block_workers = observed_block_workers,
              processing_seconds = processing_seconds))
  }
  list(compute = compute_block, finish = finish_individual)
}

update_peak()

processors <- lapply(samplelist, prepare_individual)
# Parsing retains common fields and only the current sample's four columns.
# It uses the full index's classes and original column names for every block.
sample_columns <- lapply(seq_along(samplelist), function(number) {
  c(seq_len(common_columns), common_columns + (number - 1L) * 4L + seq_len(4L))
})
processed_samples <- nipat_dnp_process_samples(pileup_index, block_plan, ForUniqReads,
  RefAltDNP, lapply(processors, function(processor) processor$compute), columns = sample_columns,
  progress = function(sample_number, completed, total) {
    nipat_progress("progress", "dnp-processing", sample_ids = samplelist[[sample_number]],
                   completed = completed, total = total, unit = "loci")
  })
ncores <- processed_samples$workers
observed_workers <- processed_samples$observed_workers
observed_sample_workers <- processed_samples$observed_samples
processing_seconds <- processed_samples$elapsed_seconds
processing_tasks <- processed_samples$task_count
cat(paste0("\nDNP shared sample/block pool: ", ncores, " worker(s), ",
           processing_tasks, " task(s) across ", length(samplelist), " sample(s)\n"))
results <- vector("list", length(samplelist))
for (number in seq_along(samplelist)) {
  results[[number]] <- processors[[number]]$finish(processed_samples$samples[[number]])
  # Scientific tables are retained for the final merge; release intermediate
  # block objects before formatting and plotting the following sample.
  processed_samples$samples[number] <- list(NULL)
}
rm(processed_samples, processors)


# combine GT columns from all individuals into a single dataframe
final_merged_data <- Reduce(function(x, y) merge(x, y,
                                                 by = c("chr", "pos1", "pos2", "REF", "ALT"),
                                                 all = TRUE),
                            lapply(results, function(res) res$indiv_final))

# These are discrete observations of individual R-process RSS, not the peak
# concurrent memory of all workers. The container observer records that measure.
all_peak_mems <- sapply(results, function(x) x$peak_mem)
global_peak <- max(all_peak_mems, na.rm = TRUE)
mean_peak <- round(mean(all_peak_mems, na.rm = TRUE), 2)


# format numeric columns before saving output table (simil-VCF)
final_merged_data_formatted <- format_df_decimals(final_merged_data)
write.table(final_merged_data_formatted,
            file.path(output, "summary", paste0(output, "_AllGenotypes.txt")),
            sep = "\t", row.names = FALSE, quote = FALSE)


# Print observed per-process memory and time without implying a container peak.
end_time <- Sys.time()
total_time <- round(difftime(end_time, start_time, units = "mins"), 2)
cat(paste0("\nTotal execution time: ", total_time, " minutes\n"))
cat(paste0("Maximum observed R-process RSS (MiB): ", global_peak, "\n"))
cat(paste0("Average per-sample maximum observed R-process RSS (MiB): ", mean_peak, "\n"))
cat("Per-process RSS observations are not the combined memory peak; see the container performance diagnostics.\n")
cat(paste0("Number of individuals processed: ", length(samplelist), "\n"))



# Plot only copies of the final genotype table; retain every scientific row.
nipat_genotype_summary(final_merged_data, file.path(output, "summary"), locus_kind = "DNP")

nipat_dnp_write_metrics("work/dnp-blocks.json", list(
  schema_version = 1L, status = "succeeded", acquisition_seconds = acquisition_seconds,
  index_seconds = pileup_index$elapsed_seconds, index_rows = pileup_index$rows,
  index_bytes = pileup_index$bytes, column_classes = pileup_index$classes,
  block_loci_limit = block_plan$max_loci, block_raw_bytes_limit = block_plan$max_bytes,
  memory_limit_scope = "raw input proxy; complete windows and legacy compatibility groups are never split or truncated",
  compatibility_reasons = I(block_plan$compatibility_reasons),
  unmatched_coordinate_rows = block_plan$unmatched_rows,
  repeated_qname_rows = pileup_index$repeated_qname_rows,
  scheduling_strategy = "global-sample-blocks",
  worker_scope = "one shared pool across all samples and blocks; no nested pools",
  workers = ncores, observed_workers = observed_workers, task_count = processing_tasks,
  processing_seconds = processing_seconds,
  sample_processing_seconds_scope = "first block start to last block finish; sample intervals may overlap",
  sample_workers = observed_sample_workers,
  block_workers = max(vapply(results, function(result) result$observed_block_workers, integer(1))),
  estimated_worker_memory_mib = nipat_dnp_worker_memory_mib(block_plan),
  samples = setNames(lapply(results, function(result) list(
    processing_seconds = result$processing_seconds, block_workers = result$block_workers,
    observed_block_workers = result$observed_block_workers, blocks = result$block_metrics)), samplelist),
  elapsed_seconds_including_acquisition_and_index = as.numeric(difftime(Sys.time(), start_time, units = "secs"))
))

# remove now useless files; the retained test copy is separate from scratch.
unlink(pileup_path)
unlink("bedfile_for_mpileup.bed")

cat("\nAll done!\n")
