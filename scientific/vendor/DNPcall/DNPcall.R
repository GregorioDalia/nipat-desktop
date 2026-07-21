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



# check if parallel mode is enabled
parallel_mode <- "--parallel" %in% args

# determine the number of cores to use (automatically use all if --parallel is specified)
if ("--parallel" %in% args) {
  ncores <- parallel::detectCores()
} else {
  ncores <- 1
}



# read the df
r_bamlist<-read.table(bamlist,header=F,col.names = "samples")
r_DNPlist<-read.table(DNPlist,header=F,col.names = c("chr","pos1","pos2","REF","ALT"))

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



# pileup calling with samtools
cat("\nMaking mpileup...\n")
commA <- paste0("samtools mpileup -b ", bamlist,
                " -l bedfile_for_mpileup.bed -f ", reference,
                " --output-QNAME --no-output-ins --no-output-del --no-output-ends > mpileup.txt")


system(commA, ignore.stderr=T)

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
pileup_bamlist <- read.csv("mpileup.txt", quote="", row.names=NULL, stringsAsFactors=F, header =F, sep="\t")
common_columns <- 3
final_merged_data <- NULL

update_peak()

# calling processing for each sample
process_individual <- function(i) {
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

  # extract sample-specific columns
  depth_col <- common_columns + (which(samplelist == i) - 1) * 4 + 1
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

  # substitution of characters to modify the df
  clean_df <- function(df2) {
    df2 <- df2

    # wrap df.V7 between ","
    df2$df.V7 <- paste0(",", df2$df.V7, ",")

    # substitute * with @
    df2$df.V5 <- gsub("\\*", "@", df2$df.V5)

    # substitute indels patterns with @
    df2$df.V5 <- gsub("[actgACTG]([+-]\\d+)+", "@", df2$df.V5)

    df2$df.V5    <- gsub("", " ", df2$df.V5)
    df2$df.V7    <- gsub(",", " ", df2$df.V7)
    df2$df.qual  <- gsub("", " ", df2$df.qual)
    return(df2)
  }

  df2 <- clean_df(df2)

  update_peak_ind()


  # split bases and reads columns in single cells
  split_and_filter_df <- function(df2) {
    df3 <- df2 %>%
      separate_rows(df.V5, df.V7, df.qual, sep = " ")
    df4 <- df3[, c(3, 1, 2, 4)]
    df4.1 <- df4[ df4$df.V7 != "", ]
    return(df4.1)
  }

  df4.1 <- split_and_filter_df(df2)

  update_peak_ind()

  # get unique label for each DNP
  unique_labels <- function(df4.1, ForUniqReads) {
    df5 <- dplyr::left_join(df4.1, ForUniqReads, by = "df.chr")
    df5$readUniq <- paste(df5$df.V7, df5$uniq, sep = "_")
    df6 <- df5[, c(6, 2, 3, 4)]
    return(df6)
  }

  df6 <- unique_labels(df4.1, ForUniqReads)

  # convert ASCII pred score to number
  df6$df.qual <- sapply(df6$df.qual, function(x) as.integer(charToRaw(x)) - 33)


  # group by new read label
  DF_chr <- df6 %>%
    group_by(readUniq) %>%
    summarise(BASE = paste(df.chr, collapse = "|"))
  DF_pos <- df6 %>%
    group_by(readUniq) %>%
    summarise(BASE = paste(df.V5, collapse = "|"))
  DF_qual <- df6 %>%
    group_by(readUniq) %>%
    summarise(BASE = paste(df.qual, collapse = "|"))

  # merge and rename col
  merge_DF <- function(DF_chr, DF_pos, DF_qual) {
    DF1 <- merge(DF_chr, DF_pos, by = "readUniq")
    DF <- merge(DF1, DF_qual, by = "readUniq")
    names(DF) <- c("ID_DNP", "chr", "pos", "qual")
    return(DF)
  }

  DF <- merge_DF(DF_chr, DF_pos, DF_qual)

  # substitute characters strand specific characters (unecessary) with only uppercase letters
  UppLowSub <- function(DF) {
    DF$pos <- gsub('g', 'G', DF$pos)
    DF$pos <- gsub('a', 'A', DF$pos)
    DF$pos <- gsub('c', 'C', DF$pos)
    DF$pos <- gsub('t', 'T', DF$pos)
    DF$pos <- gsub(',', '.', DF$pos)
    return(DF)
  }

  DF <- UppLowSub(DF)



  # count INDEL reads and their ratio over total reads per DNP
  compute_indel_summary <- function(DF) {
    DF_with_INDEL <- DF[nchar(DF$pos) > 6, ]

    DF_INDEL <- DF_with_INDEL %>%
      mutate(
        pos1 = substr(pos, 1, 2),
        pos2 = substr(pos, 3, 5),
        pos3 = substr(pos, 6, 7)
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
        observed_comb = paste(pos2, collapse = ";"),
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

  # keep only micro haplotype
  righe_modificate <- DFnoINDEL[nchar(DFnoINDEL$pos)>6,]

  # extract DNP info
  df_3coppie <- righe_modificate %>%
    mutate(pos1 = substr(pos, 1, 2),
           pos2 = substr(pos, 3, 5),
           pos3 = substr(pos, 6, 7),
           qual1=sapply(qual, function(x) {
             parts <- strsplit(x, "\\|")[[1]]
             paste(parts[2:3], collapse = "|")
           }),
           chr1=sapply(chr, function(x) {
             parts <- strsplit(x, "\\|")[[1]]
             paste(parts[2:3], collapse = "|")
           }))

  good_reads <- df_3coppie[,c(9,6,8)]

  # compute BQ average between the two DNP positions
  good_reads <- good_reads%>%
    mutate(mean_quality = sapply(qual1, function(x) {
    values <- as.numeric(strsplit(x, "\\|")[[1]])
    mean(values)
  }))


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

  # create df for other (error) alleles
  altro_dt <- subset(data_info, pos2 != ref & pos2 != alt)

  altro_dt_grouped <- altro_dt %>%
    group_by(chr1, pos2) %>%
    summarise(n = n())

  altro_dt2 <- data.frame(DNPs = altro_dt_grouped$chr1, n = altro_dt_grouped$n)
  altro_dt3 <- altro_dt2 %>% group_by(DNPs) %>% summarise(n_altro = sum(n))

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

  for (k in seq_along(positions)) {
    pos <- positions[k]
    sub <- ref_alt_dt[ref_alt_dt$chr1 == pos, ]

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


  # merge the 3 dfs
  merge_3_dfs <- function(ref_dt_grouped, alt_dt_grouped, altro_dt3, RefAltDNP, res) {
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

  # compute ratio of other reads and total, mark GT as NA if ratio >= 0.1 (too many "errors" to assign the GT correctly)
  dataframe_final2 <- dataframe_final %>%
    mutate(GT=ifelse(N_Altro/(N_Altro+N_Reference+N_Alternative) >= 0.1, NA, GT))

  final_df_elab <- function(dataframe_final2, df_grouped) {
    FINAL_df <- merge(dataframe_final2, df_grouped, by.x = "DNPs", by.y = "chr1", all = TRUE)

    FINAL_df2 <- separate(FINAL_df, col = "DNPs", into = c("pos1", "pos2"), sep = "\\|")
    FINAL_df3 <- separate(FINAL_df2, col = "pos1", into = c("chr", "pos1"), sep = "\\:")
    FINAL_df4 <- separate(FINAL_df3, col = "pos2", into = c("chr", "pos2"), sep = "\\:")

    final <- FINAL_df4[, c(2, 1, 3:ncol(FINAL_df4))]

    final$Reference <- gsub('\\|', '', final$Reference)
    final$Alternative <- gsub('\\|', '', final$Alternative)
    final$combined_bases <- gsub('\\|', '', final$combined_bases)

    final <- final %>%
      mutate(pos1 = as.numeric(pos1),
             pos2 = as.numeric(pos2)) %>%
      left_join(dfIND_summary, by = c("chr", "pos1", "pos2"))

    final <- final %>%
      relocate(indel_reads, indel_ratio, .after = total_count)

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

    return(list(indiv_final = indiv_final, final = final, peak_mem = peak_ind_mem))

  }


  result_list <- final_df_elab(dataframe_final2, df_grouped)

  indiv_final <- result_list$indiv_final
  final <- result_list$final
  peak_ind_mem <- result_list$peak_mem


  colnames(indiv_final)[6] <- paste0("GT_", i)


  # format numeric columns and save individual output files
  final_formatted <- format_df_decimals(final)
  write.table(final_formatted, file.path(output, "individual_outputs", paste0("full_output_", i, ".txt")), sep = "\t", row.names = FALSE, quote = FALSE)


 # create individual folder inside plots
  indiv_plot_dir <- file.path(output, "plots", i)
  dir.create(indiv_plot_dir, showWarnings = FALSE, recursive = TRUE)


  # plot number of genotypes per sample
  p <- ggplot(final, aes(GT))+
    geom_histogram(stat="count")+
    labs(x = "Genotypes")
    ggsave(file.path(indiv_plot_dir, paste0(i,"_N_genotypes.pdf")), plot=p, width = 11, height=5)

  # make reads frequency plots
  count_class <- function(vettore) {
    # get max value
    max_val <- max(vettore, na.rm = TRUE)

    # get max break
    max_break <- ceiling((max_val + 10) / 10) * 10

    # make breaks and labels
    breaks <- seq(1, max_break, by = 5)
    labels <- paste(breaks, breaks + 4, sep = "-")

    # make categorized vector
    classi <- cut(vettore, breaks = c(breaks, Inf), labels = labels, right = TRUE, include.lowest = TRUE)

    # count
    tabella <- as.data.frame(table(classi))
    names(tabella) <- c("class", "Freq")

    return(tabella)
  }
  for_N_REF_plot <- count_class(final$N_REF)

  q <- ggplot(for_N_REF_plot, aes(x = class, y = Freq)) +
    geom_col(fill = "green3", color = "black", width = 1) +  # bordo nero, nessuno spazio tra le barre
    labs(
      title = "Reference reads count",
      x = "Number of reads",
      y = "Occurences"
    ) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 90, hjust = 1, size = 5)) +
    scale_x_discrete(breaks = for_N_REF_plot$class[seq(1, length(for_N_REF_plot$class), 5)])
  ggsave(file.path(indiv_plot_dir, paste0(i, "_Ref_read_count.pdf")), plot=q, width = 11, height=5)


  for_N_ALT_plot <- count_class(final$N_ALT)

  s <- ggplot(for_N_ALT_plot, aes(x = class, y = Freq)) +
    geom_col(fill = "red3", color = "black", width = 1) +  # bordo nero, nessuno spazio tra le barre
    labs(
      title = "Alternative reads count",
      x = "Number of reads",
      y = "Occurences"
    ) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 90, hjust = 1, size = 5)) +
    scale_x_discrete(breaks = for_N_ALT_plot$class[seq(1, length(for_N_ALT_plot$class), 5)])
  ggsave(file.path(indiv_plot_dir, paste0(i, "_Alt_read_count.pdf")), plot = s, width = 11, height = 5)

  for_N_Other_plot <- count_class(final$N_Other)

  r <- ggplot(for_N_Other_plot, aes(x = class, y = Freq)) +
    geom_col(fill = "steelblue", color = "black", width = 1) +  # bordo nero, nessuno spazio tra le barre
    labs(
      title = "Other reads count",
      x = "Number of reads",
      y = "Occurences"
    ) +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 90, hjust = 1, size = 5)) +
    scale_x_discrete(breaks = for_N_Other_plot$class[seq(1, length(for_N_Other_plot$class), 5)])
  ggsave(file.path(indiv_plot_dir, paste0(i, "_Other_read_count.pdf")), plot = r, width = 11, height = 5)

  end_ind_time <- Sys.time()
  end_ind_mem <- get_memory_usage_mb()

  ind_mem_delta <- end_ind_mem - start_ind_mem
  ind_exec_time <- round(difftime(end_ind_time, start_ind_time, units = "secs"), 2)

  cat(paste0("\n>>> Summary for ", i, ":\n"))
  cat(paste0("Execution Time (seconds): ", ind_exec_time, "\n"))
  cat(paste0("Peak RAM (MB): ", peak_ind_mem, "\n"))
  return(list(indiv_final = indiv_final, final = final, peak_mem = peak_ind_mem))
}

update_peak()

# run the individual-level processing in parallel or serial mode
cat(paste0("\nRunning ", ifelse(parallel_mode, "in parallel", "sequentially"), "\n"))


if (parallel_mode) {
  results <- mclapply(samplelist, process_individual, mc.cores = ncores)
} else {
  results <- lapply(samplelist, process_individual)
}


# combine GT columns from all individuals into a single dataframe
final_merged_data <- Reduce(function(x, y) merge(x, y,
                                                 by = c("chr", "pos1", "pos2", "REF", "ALT"),
                                                 all = TRUE),
                            lapply(results, function(res) res$indiv_final))

# collect all peak RAM values
all_peak_mems <- sapply(results, function(x) x$peak_mem)
global_peak <- max(all_peak_mems, na.rm = TRUE)
mean_peak <- round(mean(all_peak_mems, na.rm = TRUE), 2)


# format numeric columns before saving output table (simil-VCF)
final_merged_data_formatted <- format_df_decimals(final_merged_data)
write.table(final_merged_data_formatted,
            file.path(output, "summary", paste0(output, "_AllGenotypes.txt")),
            sep = "\t", row.names = FALSE, quote = FALSE)


# Print peak memory usage and time
end_time <- Sys.time()
total_time <- round(difftime(end_time, start_time, units = "mins"), 2)
cat(paste0("\nTotal execution time: ", total_time, " minutes\n"))
cat(paste0("Peak RAM usage: ", global_peak, " MB\n"))
cat(paste0("Average per-sample Peak RAM usage (MB): ", mean_peak, "\n"))
cat(paste0("Number of individuals processed: ", length(samplelist), "\n"))



# plot unassigned genotypes
final_merged_data$NA_count <- rowSums(is.na(final_merged_data[, 6:ncol(final_merged_data)]))
final_merged_data$DNP_name <- paste0(final_merged_data$chr, ":", final_merged_data$pos1, "-", final_merged_data$pos2)

w <- ggplot(final_merged_data, aes(x = DNP_name, y = NA_count)) +
  geom_col(fill = "steelblue2", color = "black", width = 1) +
  labs(
    title = "Unassigned genotypes",
    x = "DNPs",
    y = "Occurences"
  ) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1))
  ggsave(file.path(output, "summary", "Unassigned_genotypes.pdf"),
         plot=w, width = nrow(final_merged_data), height=5, limitsize = FALSE)


######################

# make datset for upset plot
make_upset_df <- function(df) {
  df$DNP <- paste(df$chr, paste(df$pos1, df$pos2, sep = "-"), sep = ":")
  gt_cols <- grep("^GT_", colnames(df), value = TRUE)
  df_bin <- as.data.frame(lapply(df[, gt_cols], function(x) ifelse(is.na(x), 0, 1)))
  colnames(df_bin) <- gsub("^GT_", "", colnames(df_bin))
  rownames(df_bin) <- df$DNP
  return(df_bin)
}
df_for_upset <- make_upset_df(final_merged_data)


u <- upset(
  df_for_upset,
  intersect = colnames(df_for_upset),
  min_size = 0,
  name = "DNPs covered"
)
ggsave(file.path(output, "summary", "DNPs_covered_UpSet_plot.pdf"),
       plot=u, limitsize = FALSE, width =(ncol(df_for_upset) * 30), height=(ncol(df_for_upset) * 2))




# remove now useless files
commB = paste0("rm mpileup.txt")
system(commB, ignore.stderr=T)

commC = paste0("rm bedfile_for_mpileup.bed")
system(commC, ignore.stderr=T)

cat("\nAll done!\n")
