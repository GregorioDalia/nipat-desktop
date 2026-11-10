#!/usr/bin/env Rscript
# Single-file SNP pipeline: BAM list -> samtools mpileup -> counts/GL/GT -> plots.
# Calling core retained from the user's tested SNPcall_equivalent.R (steps 1-6).
suppressPackageStartupMessages({
  library(optparse)
  library(tidyverse)
  library(ComplexUpset)
  library(parallel)
})

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
  show_col_types = FALSE
)
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
df <- read.csv(pileup_file, quote = "",
               row.names = NULL,
               stringsAsFactors = FALSE,
               header = FALSE,
               sep = "\t")
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
# Aggregate separately for each read and SNP.
df5 <- df3_marked %>%
  group_by(SNP_id, df.V7) %>%
  summarise(
    df.V5 = paste(df.V5, collapse = "|"),
    .groups = "drop"
  )
df6 <- df3_marked %>%
  group_by(SNP_id, df.V7) %>%
  summarise(
    df.chr = paste(df.chr, collapse = "|"),
    .groups = "drop"
  )
# STEP3: carry Phred qualities for each read and SNP.
df_quality <- df3_marked %>%
  group_by(SNP_id, df.V7) %>%
  summarise(
    df.qual = paste(df.qual, collapse = "|"),
    .groups = "drop"
  )
df_merged <- inner_join(
  df5,
  df6,
  by = c("SNP_id", "df.V7")
) %>%
  inner_join(
    df_quality,
    by = c("SNP_id", "df.V7")
  ) %>%
  select(-SNP_id)
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
gl_list <- lapply(positions, function(position) {
  sub <- gl_reads[gl_reads$df.chr == position, ]
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

get_memory_usage_mb <- function() {
  if (file.exists("/proc/self/status")) {
    line <- grep("^VmRSS:", readLines("/proc/self/status"), value=TRUE)
    return(as.numeric(gsub("[^0-9]", "", line))/1024)
  }
  rss <- system2("ps", c("-o", "rss=", "-p", Sys.getpid()), stdout=TRUE)
  as.numeric(trimws(rss[1]))/1024
}

main <- function() {
  opts <- list(
    make_option("--bamlist", type="character"),
    make_option("--SNPs", dest="snplist", type="character"),
    make_option("--reference", type="character"),
    make_option("--out", type="character"),
    make_option("--parallel", action="store_true", default=FALSE),
    make_option("--cores", type="integer", default=NA_integer_)
  )
  opt <- parse_args(OptionParser(option_list=opts))
  for (name in c("bamlist", "snplist", "reference", "out")) {
    if (is.null(opt[[name]]) || !nzchar(opt[[name]]))
      stop("Required: --bamlist --SNPs --reference --out")
  }
  if (!nzchar(Sys.which("samtools"))) stop("samtools not found in PATH")
  bamlist <- normalizePath(opt$bamlist, mustWork=TRUE)
  snplist <- normalizePath(opt$snplist, mustWork=TRUE)
  reference <- normalizePath(opt$reference, mustWork=TRUE)
  if (!file.exists(paste0(reference,".fai"))) stop("Reference .fai not found")
  panel <- readr::read_tsv(snplist,
    col_types=readr::cols(.default=readr::col_character()), show_col_types=FALSE)
  validate_panel(panel)
  bams <- sub("\r$", "", readLines(bamlist, warn=FALSE))
  bams <- bams[nzchar(bams) & !grepl("^#", bams)]
  if (!length(bams)) stop("Empty bamlist")
  bams <- vapply(bams, function(p) {
    if (!startsWith(p,"/")) p <- file.path(dirname(bamlist),p)
    normalizePath(p,mustWork=TRUE)
  }, character(1), USE.NAMES=FALSE)
  # Use a literal suffix pattern.
  samples <- tools::file_path_sans_ext(basename(bams))
  if (anyDuplicated(samples)) stop("Duplicate sample names")
  if (dir.exists(opt$out) || file.exists(opt$out)) stop("Output path already exists")
  if (!dir.create(opt$out, recursive=TRUE)) stop("Cannot create output directory")
  output <- normalizePath(opt$out, mustWork=TRUE)
  for (d in c("individual_outputs","plots","summary","logs"))
    dir.create(file.path(output,d))
  temp <- tempfile("SNPcall_")
  dir.create(temp)
  on.exit(unlink(temp,recursive=TRUE),add=TRUE)
  bed <- file.path(temp,"regions.bed")
  write.table(data.frame(panel$chr, as.integer(panel$pos)-2L,
                        as.integer(panel$pos)+1L), bed,
              sep="\t", quote=FALSE,row.names=FALSE,col.names=FALSE)
  resolved_bamlist <- file.path(temp,"bamlist.txt")
  writeLines(bams,resolved_bamlist)
  pileup <- file.path(temp,"mpileup.txt")
  cat("Making multi-sample mpileup...\n")
  status <- system2("samtools", c("mpileup", "-b", shQuote(resolved_bamlist),
    "-l", shQuote(bed), "-f", shQuote(reference), "--output-QNAME",
    "-d", "0", "--no-output-ins", "--no-output-del", "--no-output-ends"),
    stdout=pileup, stderr=file.path(output,"logs","samtools.log"))
  if (status != 0L) stop("samtools failed; inspect logs/samtools.log")
  if (file.info(pileup)$size == 0) stop("samtools produced an empty pileup")
  multi <- read.delim(pileup, header=FALSE, quote="", comment.char="",
                     stringsAsFactors=FALSE, check.names=FALSE)
  if (ncol(multi) != 3L+4L*length(bams))
    stop("Unexpected multi-sample pileup columns")
  invisible(gc())
  start <- Sys.time()
  worker <- function(index) {
    i <- samples[index]
    started <- Sys.time()
    mem_start <- get_memory_usage_mb()
    selected <- multi[,c(1:3, (4L+4L*(index-1L)):(7L+4L*(index-1L)))]
    # No-coverage placeholders are not read names or bases.
    selected <- selected[as.numeric(selected[[4]]) > 0, , drop=FALSE]
    input <- file.path(temp,paste0("sample_",index,".txt"))
    write.table(selected,input,sep="\t",quote=FALSE,row.names=FALSE,col.names=FALSE)
    log_connection <- file(file.path(output,"logs",paste0(i,"_SNPcall.log")),"wt")
    sink(log_connection)
    on.exit({sink();close(log_connection)},add=TRUE)
    if (nrow(selected) > 0L) {
      final <- call_sample(input,snplist)
    } else {
      final <- data.frame(chr=panel$chr,pos=as.integer(panel$pos),
        REF=toupper(panel$ref),ALT=toupper(panel$alt),N_REF=0L,N_ALT=0L,
        N_Other=0L,total_count=0L,ratio=NA_real_,GL0=NA_real_,GL1=NA_real_,
        GL2=NA_real_,GT=NA_character_,reads_discarded_for_indels=NA_integer_,
        ratio_reads_discarded_for_indels=NA_real_,
        combined_bases=NA_character_,combined_counts=NA_character_)
    }
    write.table(final,file.path(output,"individual_outputs",paste0("full_output_",i,".txt")),
                sep="\t",quote=FALSE,row.names=FALSE)
    indiv_plot_dir <- file.path(output,"plots",i)
    dir.create(indiv_plot_dir)
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


    genotype <- final[,c("chr","pos","REF","ALT","GT")]
    names(genotype)[5] <- paste0("GT_",i)
    cat("Completed:", i, "\n")
    list(genotype=genotype, sample=i,
         seconds=as.numeric(difftime(Sys.time(),started,units="secs")),
         resident_MB_start=mem_start, resident_MB_end=get_memory_usage_mb())
  }
  cores <- if (opt$parallel) parallel::detectCores() else 1L
  if (!is.na(opt$cores)) {
    if (opt$cores < 1L) stop("--cores must be >= 1")
    cores <- if (opt$parallel) opt$cores else 1L
  }
  if (is.na(cores)) cores <- 1L
  cores <- min(cores,length(bams))
  if (opt$parallel && .Platform$OS.type == "windows")
    stop("Fork parallel processing requires macOS or Linux")
  cat("Processing",length(bams),"samples with",cores,"worker(s)...\n")
  results <- if (opt$parallel) {
    parallel::mclapply(seq_along(bams),worker,mc.cores=cores)
  } else lapply(seq_along(bams),worker)
  if (any(vapply(results,function(x) inherits(x,"try-error") || is.null(x),logical(1))))
    stop("A sample failed; inspect per-sample logs")
  merged <- Reduce(function(x,y) merge(x,y,by=c("chr","pos","REF","ALT"),all=TRUE),
                   lapply(results,`[[`,"genotype"))
  write.table(merged,file.path(output,"summary",paste0(basename(output),"_AllGenotypes.txt")),
              sep="\t",quote=FALSE,row.names=FALSE)
  gt_cols <- grep("^GT_",names(merged),value=TRUE)
  merged$NA_count <- rowSums(is.na(merged[,gt_cols,drop=FALSE]))
  merged$SNP_name <- paste(merged$chr,merged$pos,sep=":")
  w <- ggplot(merged,aes(x=SNP_name,y=NA_count)) +
    geom_col(fill="steelblue2",color="black",width=1) +
    labs(title="Unassigned genotypes",x="SNPs",y="Occurrences") +
    theme_minimal() + theme(axis.text.x=element_text(angle=45,hjust=1))
  ggsave(file.path(output,"summary","Unassigned_genotypes.pdf"),w,
         width=nrow(merged),height=5,limitsize=FALSE)
  binary <- as.data.frame(lapply(merged[,gt_cols,drop=FALSE],function(x) as.integer(!is.na(x))))
  names(binary) <- sub("^GT_","",gt_cols)
  rownames(binary) <- merged$SNP_name
  if (ncol(binary) >= 2L) {
    u <- ComplexUpset::upset(binary,intersect=names(binary),min_size=0,name="SNPs covered")
    ggsave(file.path(output,"summary","SNPs_covered_UpSet_plot.pdf"),u,
           width=ncol(binary)*30,height=ncol(binary)*2,limitsize=FALSE)
  } else {
    message("UpSet plot skipped: requires at least two samples")
  }
  resources <- bind_rows(lapply(results,function(x) data.frame(
    sample=x$sample,seconds=x$seconds,resident_MB_start=x$resident_MB_start,
    resident_MB_end=x$resident_MB_end)))
  write.table(resources,file.path(output,"summary","resources.tsv"),
              sep="\t",quote=FALSE,row.names=FALSE)
  cat("All done. Sample processing time:",
      round(as.numeric(difftime(Sys.time(),start,units="mins")),2),"minutes\n")
}

main()
