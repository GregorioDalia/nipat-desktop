#!/usr/bin/env Rscript
# SNPcall 2.0 scientific core from NEWPAT ce59f4beeeec710b1b42d425cb87d7aad729f71d.
# Modified by NIPAT contributors, 2026-11-10 (0.8.30): retain the desktop
# pileup adapter; bound parsing and parallel read aggregation; preserve the
# upstream counts, natural-log likelihood model, genotype and indel semantics.
# The byte-identical upstream source is frozen in tests/reference_r/2.0.
suppressPackageStartupMessages({
  library(optparse)
  library(tidyverse)
})

source(Sys.getenv("NIPAT_PARALLEL_HELPER", unset = "/opt/nipat/lib/nipat_scientific/parallel.R"))

nipat_snp_empty <- function(panel) {
  data.frame(chr = panel$chr, pos = as.integer(panel$pos),
    REF = toupper(panel$ref), ALT = toupper(panel$alt), N_REF = 0L, N_ALT = 0L,
    N_Other = 0L, total_count = 0L, ratio = NA_real_, GL0 = NA_real_,
    GL1 = NA_real_, GL2 = NA_real_, GT = NA_character_,
    reads_discarded_for_indels = NA_integer_,
    ratio_reads_discarded_for_indels = NA_real_,
    combined_bases = NA_character_, combined_counts = NA_character_,
    stringsAsFactors = FALSE)
}

nipat_snp_group_reads <- function(observations) {
  aggregate_reads <- function(x) x %>%
    group_by(SNP_id, df.V7) %>%
    summarise(df.V5 = paste(df.V5, collapse = "|"),
              df.chr = paste(df.chr, collapse = "|"),
              df.qual = paste(df.qual, collapse = "|"), .groups = "drop")
  workers <- nipat_parallel_workers(max(1L, nrow(observations)),
    memory_mib = max(2048, as.numeric(object.size(observations)) * 3 / 1024^2))
  if (workers <= 1L || nrow(observations) < 2L) {
    return(nipat_parallel_lapply(list(NULL), function(task) aggregate_reads(observations),
      label = "snp-read-groups", workers = 1L)[[1L]])
  }
  # Input is sorted by SNP_id, QNAME and position_order. Adjacent comparisons
  # build complete group IDs without duplicating long read-name strings.
  previous <- seq_len(nrow(observations) - 1L)
  following <- previous + 1L
  boundaries <- c(TRUE,
    observations$SNP_id[previous] != observations$SNP_id[following] |
    observations$df.V7[previous] != observations$df.V7[following])
  group_ids <- cumsum(boundaries)
  task_count <- min(max(group_ids), 2L * workers)
  rows <- split(seq_len(nrow(observations)), (group_ids - 1L) %% task_count)
  parts <- nipat_parallel_lapply(rows,
    function(index) aggregate_reads(observations[index, , drop = FALSE]),
    label = "snp-read-groups", workers = workers,
    memory_mib = max(2048, as.numeric(object.size(observations)) * 3 / 1024^2))
  bind_rows(parts) %>% arrange(SNP_id, df.V7)
}

validate_panel <- function(x) {
  if (!identical(names(x), c("chr", "pos", "ref", "alt")))
    stop("SNP list must have header: chr, pos, ref, alt")
  if (nrow(x) == 0L || anyNA(x)) stop("Empty SNP list or missing values")
  if (any(!nzchar(x$chr)) || any(grepl(":", x$chr, fixed=TRUE)) ||
      any(!grepl("^[0-9]+$", x$pos))) stop("Invalid coordinates")
  p <- as.numeric(x$pos)
  if (any(!is.finite(p) | p < 2 | p > .Machine$integer.max-1))
    stop("Positions must be integers between 2 and 2147483646")
  if (any(!toupper(x$ref) %in% c("A","C","G","T")) ||
      any(!toupper(x$alt) %in% c("A","C","G","T")) ||
      any(toupper(x$ref) == toupper(x$alt))) stop("Invalid REF/ALT")
  if (anyDuplicated(paste(x$chr, as.integer(p), sep=":")))
    stop("Duplicate SNP coordinates")
  invisible(TRUE)
}

call_sample <- function(pileup_file, snplist_file) {
# read snplist file
cat(">> reading snp list...\n")
# Read SNP list with separate chromosome and position.
snp_input <- readr::read_tsv(
  snplist_file,
  col_types = readr::cols(.default = readr::col_character()),
  show_col_types = FALSE, num_threads = 1L
)
# Retain the historical NIPAT three-column panel as an input adapter only.
if (identical(names(snp_input), c("pos", "ref", "alt"))) {
  keys <- strsplit(snp_input$pos, ":", fixed = TRUE)
  if (any(lengths(keys) != 2L)) stop("Invalid legacy SNP coordinates")
  snp_input <- data.frame(
    chr = vapply(keys, `[`, "", 1L),
    pos = vapply(keys, `[`, "", 2L),
    ref = snp_input$ref, alt = snp_input$alt, stringsAsFactors = FALSE)
}
if (!identical(names(snp_input), c("chr", "pos", "ref", "alt"))) {
  stop("SNP list must have columns: chr, pos, ref, alt")
}
if (nrow(snp_input) == 0L || anyNA(snp_input)) {
  stop("SNP list is empty or contains missing values")
}
if (any(!nzchar(snp_input$chr)) ||
    any(grepl(":", snp_input$chr, fixed = TRUE)) ||
    any(!grepl("^[0-9]+$", snp_input$pos))) {
  stop("Invalid chromosome or position")
}
positions_numeric <- as.numeric(snp_input$pos)
if (any(!is.finite(positions_numeric) |
        positions_numeric < 2 |
        positions_numeric > .Machine$integer.max - 1)) {
  stop("SNP positions must be integers between 2 and 2147483646")
}
snp_input$ref <- toupper(snp_input$ref)
snp_input$alt <- toupper(snp_input$alt)
if (any(!snp_input$ref %in% c("A", "C", "G", "T")) ||
    any(!snp_input$alt %in% c("A", "C", "G", "T")) ||
    any(snp_input$ref == snp_input$alt)) {
  stop("REF and ALT must be different single A/C/G/T bases")
}
# Internal key remains unchanged.
fake_DNP <- snp_input %>%
  transmute(
    pos = paste(chr, as.integer(positions_numeric), sep = ":"),
    ref,
    alt
  )
if (anyDuplicated(fake_DNP$pos)) {
  stop("Duplicate SNP coordinates")
}
# read pileup file
cat(">> reading pileup...\n")
if (file.info(pileup_file)$size == 0) return(nipat_snp_empty(snp_input))
pileup_arguments <- list(file = pileup_file, quote = "", row.names = NULL,
                        stringsAsFactors = FALSE, header = FALSE, sep = "\t")
probe <- do.call(read.csv, c(pileup_arguments, list(nrows = 5L)))
if (ncol(probe) < 7L) stop("SNP pileup requires seven columns including qualities and QNAME")
# Optional trailing mpileup fields need not be materialized in memory.
classes <- c(rep(NA_character_, 7L), rep("NULL", ncol(probe) - 7L))
df <- do.call(read.csv, c(pileup_arguments, list(colClasses = classes)))
rm(probe)
depth <- suppressWarnings(as.numeric(df$V4))
if (any(!is.finite(depth) | depth < 0 | depth != floor(depth))) stop("Invalid pileup depth")
df <- df[depth > 0, , drop = FALSE]
if (!nrow(df)) return(nipat_snp_empty(snp_input))
cat(">> input loaded correctly\n")
# STEP2: normalize reference bases
df$V5 <- mapply(
  function(reference, bases) {
    gsub("[.,]", toupper(reference), bases)
  },
  df$V3,
  df$V5,
  USE.NAMES = FALSE
)
df$V5 <- toupper(df$V5)
fake_DNP <- fake_DNP %>%
  mutate(
    ref = toupper(ref),
    alt = toupper(alt)
  )
# add chr:pos column
df$chr <- paste(df$V1, df$V2, sep = ":")
# keep only needed columns
df2 <- data.frame(
  df.chr = df$chr,
  df.V5 = df$V5,
  df.V7 = df$V7,
  df.qual = df$V6
)
# Preserve the upstream indel marker before aligning bases, names and qualities.
marked_bases <- gsub('\\*', '@', df2$df.V5)
marked_bases <- gsub('[.,actgACTG]([+-]\\d+)+', '@', marked_bases)
base_parts <- strsplit(marked_bases, "", fixed = TRUE)
name_parts <- strsplit(as.character(df2$df.V7), ",", fixed = TRUE)
quality_parts <- strsplit(as.character(df2$df.qual), "", fixed = TRUE)
sizes <- lengths(base_parts)
direct <- all(!is.na(marked_bases) & !is.na(df2$df.V7) & !is.na(df2$df.qual)) &&
  all(sizes > 0L & sizes == lengths(name_parts) & sizes == lengths(quality_parts)) &&
  !any(grepl("[[:space:]]", marked_bases) | grepl("[[:space:]]", df2$df.V7) |
         grepl("[[:space:]]", df2$df.qual)) &&
  !any(grepl("(^,|,$|,,)", df2$df.V7)) &&
  all(nchar(df2$df.qual, type = "bytes") == nchar(df2$df.qual, type = "chars"))
if (direct) {
  df3 <- data.frame(
    df.chr = rep.int(df2$df.chr, sizes),
    df.V5 = unlist(base_parts, use.names = FALSE),
    df.V7 = unlist(name_parts, use.names = FALSE),
    df.qual = unlist(lapply(df2$df.qual, function(x) as.integer(charToRaw(x)) - 33L),
                     use.names = FALSE), stringsAsFactors = FALSE)
} else {
# add commas at both ends of read names to enable the next step
df2$df.V7 <- paste0(",", df2$df.V7, ",")
# replace indels with a special character
df2$df.V5 <- gsub('\\*', '@', df2$df.V5)
df2$df.V5 <- gsub('[.,actgACTG]([+-]\\d+)+', '@', df2$df.V5)
# replace delimiters in bases and read names with a single space
df2$df.V5 <- gsub('', ' ', df2$df.V5)
df2$df.V7 <- gsub(',', ' ', df2$df.V7)
df2$df.qual <- gsub('', ' ', df2$df.qual)
# split values pairing base with the corresponding read
df3 <- df2 %>%
  separate_rows(df.V5, df.V7, df.qual, sep = " ") %>%
  mutate(
    df.qual = vapply(
      df.qual,
      function(x) {
        if (is.na(x) || !nzchar(x)) return(NA_integer_)
        values <- as.integer(charToRaw(x))
        if (length(values) != 1L) {
          stop("Invalid quality character")
        }
        as.integer(values - 33L)
      },
      integer(1)
    )
  )
}
rm(df, df2, base_parts, name_parts, quality_parts, marked_bases, sizes)
# Assign each SNP an identifier and its three expected positions.
snp_coordinates <- fake_DNP %>%
  transmute(
    SNP_id = row_number(),
    SNP_key = pos
  ) %>%
  separate(
    SNP_key,
    into = c("snp_chr", "snp_pos"),
    sep = ":",
    convert = TRUE
  )
position_map <- bind_rows(
  snp_coordinates %>%
    transmute(
      SNP_id,
      position_order = 1L,
      df.chr = paste0(snp_chr, ":", snp_pos - 1L)
    ),
  snp_coordinates %>%
    transmute(
      SNP_id,
      position_order = 2L,
      df.chr = paste0(snp_chr, ":", snp_pos)
    ),
  snp_coordinates %>%
    transmute(
      SNP_id,
      position_order = 3L,
      df.chr = paste0(snp_chr, ":", snp_pos + 1L)
    )
)
# Associate observations with their SNP.
# A position shared by nearby SNP windows belongs to both groups.
df3_marked <- df3 %>%
  filter(!is.na(df.V7), df.V7 != "") %>%
  inner_join(
    position_map,
    by = "df.chr",
    relationship = "many-to-many"
  ) %>%
  arrange(SNP_id, df.V7, position_order)
# One aggregation replaces three independent groupings and joins. Parallel
# tasks always contain the complete (SNP_id, QNAME) group, including overlapping
# windows; canonical group order is restored before all scientific calculations.
df_merged <- nipat_snp_group_reads(df3_marked) %>% select(-SNP_id)
rm(df3, df3_marked)
# keep only reads called on both positions of a single read (micro haplotypes)
df_merged2 <- df_merged[nchar(df_merged$df.V5) > 4, ]
df_merged3 <- df_merged2[nchar(df_merged2$df.V7) > 0, ]
# harmonize strand characters
df_merged3$df.V5 <- gsub('g', 'G', df_merged3$df.V5)
df_merged3$df.V5 <- gsub('a', 'A', df_merged3$df.V5)
df_merged3$df.V5 <- gsub('c', 'C', df_merged3$df.V5)
df_merged3$df.V5 <- gsub('t', 'T', df_merged3$df.V5)
df_merged3$df.V5 <- gsub(',', '.', df_merged3$df.V5)
# STEP5: indel statistics before removing indel observations
indel_observations <- df_merged3 %>%
  mutate(
    SNP_key = vapply(
      strsplit(df.chr, "|", fixed = TRUE),
      function(x) {
        if (length(x) != 3L) {
          stop("Expected three positions for indel statistics")
        }
        x[2]
      },
      character(1)
    ),
    SNP_base = vapply(
      strsplit(df.V5, "|", fixed = TRUE),
      function(x) {
        if (length(x) != 3L) {
          stop("Expected three bases for indel statistics")
        }
        x[2]
      },
      character(1)
    )
  )
indel_summary <- indel_observations %>%
  group_by(SNP_key) %>%
  summarise(
    reads_discarded_for_indels = sum(SNP_base == "@"),
    ratio_reads_discarded_for_indels =
      reads_discarded_for_indels / n(),
    .groups = "drop"
  )
# count rows containing @
conteggio <- sum(grepl("@", df_merged3$df.V5))
print(conteggio)
# remove rows containing @
df_merged4 <- df_merged3 %>% filter_all(all_vars(!grepl("@", .)))
# recount rows containing @
conteggio2 <- sum(grepl("@", df_merged4$df.V5))
print(conteggio2)
# extract the third character as genotype and drop the original base string
df_merged5 <- df_merged4 %>% mutate(df.V5.1 = substring(df.V5, 3, 3))
df_merged5 <- subset(df_merged5, select = -df.V5)
# count all genotypes found
df_count2 <- df_merged5 %>% group_by(df.chr, df.V5.1) %>% summarise(n = n(), .groups = "drop")
# extract the text between pipes and remove the first and last pipe
df_count2$df.chr <- str_extract(df_count2$df.chr, "\\|.*\\|")
df_count2$df.chr <- substr(df_count2$df.chr, 2, nchar(df_count2$df.chr) - 1)
# merge with the dataset containing ref and alt for dnp
data_info <- merge(df_count2, fake_DNP, by.x = "df.chr", by.y = "pos")
# create a flag to identify alternative genotypes
data_info2 <- data_info %>%
  mutate(is.alt = case_when(
    df.V5.1 == alt ~ "ALT",
    df.V5.1 != alt ~ "NO"
  ))
# create dataset with reference only
ref_dt <- subset(data_info2, df.V5.1 == ref)
colnames(ref_dt) <- c("SNPs", "geno", "n_ref", "ref", "alt", "is.alt")
# create dataset with alternative only
alt_dt <- subset(data_info2, is.alt == "ALT")
colnames(alt_dt) <- c("SNPs", "geno", "n_alt", "ref", "alt", "is.alt")
# create dataset with all other genotypes
altro_dt <- subset(data_info2, df.V5.1 != alt & df.V5.1 != ref)
altro_dt2 <- data.frame(altro_dt$df.chr, altro_dt$n)
altro_dt3 <- altro_dt2 %>% group_by(altro_dt.df.chr) %>% summarise(sum = sum(altro_dt.n), .groups = "drop")
colnames(altro_dt3) <- c("SNPs", "n_altro")
# merge datasets on dnp ids
merged1 <- merge(ref_dt, alt_dt,  by.x = "SNPs", by.y = "SNPs", all = TRUE)
merged2 <- merge(merged1, altro_dt3, by.x = "SNPs", by.y = "SNPs", all = TRUE)
merged3 <- merge(merged2, fake_DNP, by.x = "SNPs", by.y = "pos",   all = TRUE)
# replace na with zero
merged3[is.na(merged3)] <- 0
# select and rename final columns
dataframe_final <- merged3[, c(1, 13, 14, 3, 8, 12)]
colnames(dataframe_final) <- c("SNPs", "Reference", "Alternative", "N_Reference", "N_Alternative", "N_Altro")
# split snp into chr and pos
dataframe_final <- dataframe_final %>% separate(SNPs, into = c("chr", "pos"), sep = ":")
# compute totals and ratio
dataframe_final$total_count <- dataframe_final$N_Reference + dataframe_final$N_Alternative + dataframe_final$N_Altro
dataframe_final$ratio <- dataframe_final$N_Reference / (dataframe_final$N_Reference + dataframe_final$N_Alternative)
# STEP4: genotype likelihoods
# Same likelihood model as DNPcall.
computeGL_snp <- function(haps, Qavg, ref_hap, ploidy = 2) {
  n <- length(haps)
  if (length(Qavg) != n) {
    stop("haps e Qavg need to be of the same length")
  }
  eps <- 10^(-Qavg/10)
  isRef <- (haps == ref_hap)
  logL <- numeric(ploidy + 1)
  names(logL) <- 0:ploidy
  for (g in 0:ploidy) {
    p_ref <- (ploidy - g)/ploidy * (1 - eps) +
      g/ploidy * eps
    p_alt <- (ploidy - g)/ploidy * eps +
      g/ploidy * (1 - eps)
    pj <- ifelse(isRef, p_ref, p_alt)
    logL[as.character(g)] <- sum(log(pj))
  }
  logL
}
# Use only REF and ALT observations.
gl_reads <- df_merged5 %>%
  mutate(
    df.chr = vapply(
      strsplit(df.chr, "|", fixed = TRUE),
      function(x) {
        if (length(x) != 3L) {
          stop("Expected three positions per SNP read")
        }
        x[2]
      },
      character(1)
    )
  ) %>%
  inner_join(fake_DNP, by = c("df.chr" = "pos")) %>%
  filter(df.V5.1 == ref | df.V5.1 == alt) %>%
  mutate(
    Q_snp = vapply(
      strsplit(df.qual, "|", fixed = TRUE),
      function(x) {
        if (length(x) < 2L) {
          stop("Missing quality for central SNP base")
        }
        as.numeric(x[2])
      },
      numeric(1)
    )
  )
if (any(!is.finite(gl_reads$Q_snp) | gl_reads$Q_snp < 0)) {
  stop("Invalid quality for SNP likelihood calculation")
}
positions <- unique(gl_reads$df.chr)
# Index once instead of rescanning every read for each SNP; ordering is the
# same as the upstream unique(gl_reads$df.chr) / subset sequence.
gl_rows <- split(seq_len(nrow(gl_reads)), match(gl_reads$df.chr, positions))
gl_list <- lapply(seq_along(positions), function(index) {
  position <- positions[[index]]
  sub <- gl_reads[gl_rows[[as.character(index)]], , drop = FALSE]
  logL <- computeGL_snp(
    haps = sub$df.V5.1,
    Qavg = sub$Q_snp,
    ref_hap = sub$ref[1],
    ploidy = 2
  )
  data.frame(
    SNPs = position,
    GL0 = unname(logL["0"]),
    GL1 = unname(logL["1"]),
    GL2 = unname(logL["2"]),
    GT = c("0/0", "0/1", "1/1")[which.max(logL)],
    stringsAsFactors = FALSE
  )
})
gl_table <- if (length(gl_list) > 0L) {
  bind_rows(gl_list)
} else {
  data.frame(
    SNPs = character(),
    GL0 = numeric(),
    GL1 = numeric(),
    GL2 = numeric(),
    GT = character()
  )
}
idx <- match(
  paste(dataframe_final$chr, dataframe_final$pos, sep = ":"),
  gl_table$SNPs
)
dataframe_final$GL0 <- gl_table$GL0[idx]
dataframe_final$GL1 <- gl_table$GL1[idx]
dataframe_final$GL2 <- gl_table$GL2[idx]
dataframe_final$GT <- gl_table$GT[idx]
other_fraction <- with(
  dataframe_final,
  N_Altro / (N_Reference + N_Alternative + N_Altro)
)
dataframe_final$GT[
  which(!is.na(other_fraction) & other_fraction >= 0.1)
] <- NA_character_
# Attach indel statistics without changing previous columns.
indel_idx <- match(
  paste(dataframe_final$chr, dataframe_final$pos, sep = ":"),
  indel_summary$SNP_key
)
dataframe_final$reads_discarded_for_indels <-
  indel_summary$reads_discarded_for_indels[indel_idx]
dataframe_final$ratio_reads_discarded_for_indels <-
  indel_summary$ratio_reads_discarded_for_indels[indel_idx]
# STEP6: harmonize output names
dataframe_final <- dataframe_final %>%
  rename(
    REF = Reference,
    ALT = Alternative,
    N_REF = N_Reference,
    N_ALT = N_Alternative,
    N_Other = N_Altro
  )

# Per-allele observations, equivalent to DNPcall combined_bases/counts.
allele_counts <- df_merged5 %>%
  mutate(SNP_key = vapply(strsplit(df.chr, "|", fixed=TRUE),
                         function(x) x[2], character(1))) %>%
  group_by(SNP_key, df.V5.1) %>%
  summarise(n = n(), .groups="drop") %>%
  group_by(SNP_key) %>%
  summarise(combined_bases=paste(df.V5.1,collapse="-"),
            combined_counts=paste(n,collapse="-"), .groups="drop")
allele_idx <- match(paste(dataframe_final$chr,dataframe_final$pos,sep=":"),
                    allele_counts$SNP_key)
dataframe_final$combined_bases <- allele_counts$combined_bases[allele_idx]
dataframe_final$combined_counts <- allele_counts$combined_counts[allele_idx]

return(dataframe_final)

}

nipat_snp_memory_mb <- function() {
  if (file.exists("/proc/self/status")) {
    line <- grep("^VmRSS:", readLines("/proc/self/status", warn = FALSE), value = TRUE)
    if (length(line)) return(as.numeric(gsub("[^0-9]", "", line[[1L]])) / 1024)
  }
  NA_real_
}

nipat_snp_main <- function() {
  options <- list(
    make_option(c("-p", "--pileup"), type = "character"),
    make_option(c("-s", "--snplist"), type = "character"),
    make_option(c("-o", "--out"), type = "character", default = "SNPcall_output.txt"))
  arguments <- parse_args(OptionParser(option_list = options))
  if (is.null(arguments$pileup) || is.null(arguments$snplist))
    stop("Required: --pileup --snplist --out")
  cat(">> SNPcall 2.0 started\n")
  started <- unname(proc.time()[["elapsed"]])
  resident_start <- nipat_snp_memory_mb()
  final <- call_sample(arguments$pileup, arguments$snplist)
  write.table(final, arguments$out, sep = "\t", quote = FALSE, row.names = FALSE)
  source(Sys.getenv("NIPAT_PLOTS_HELPER", unset = "/opt/nipat/lib/nipat_scientific/plots.R"))
  directory <- dirname(arguments$out)
  sample <- "sample_0001"
  nipat_sample_plots(final, file.path(directory, "plots", sample), sample, "SNP")
  summary_directory <- file.path(directory, "summary")
  dir.create(summary_directory, recursive = TRUE, showWarnings = FALSE)
  genotype <- final[, c("chr", "pos", "REF", "ALT", "GT")]
  names(genotype)[[5L]] <- paste0("GT_", sample)
  write.table(genotype, file.path(summary_directory, "SNPcall_AllGenotypes.txt"),
              sep = "\t", quote = FALSE, row.names = FALSE)
  nipat_genotype_summary(genotype, summary_directory, "SNP")
  resources <- data.frame(sample = sample,
    seconds = unname(proc.time()[["elapsed"]]) - started,
    resident_MB_start = resident_start, resident_MB_end = nipat_snp_memory_mb())
  write.table(resources, file.path(summary_directory, "resources.tsv"),
              sep = "\t", quote = FALSE, row.names = FALSE)
  cat(">> done\n")
}

if (sys.nframe() == 0L) nipat_snp_main()
