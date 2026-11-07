#!/usr/bin/env Rscript
# Modified by NIPAT contributors, 2026-11-07 (0.8.9): project input columns,
# tokenize observations directly and aggregate read features without constructing
# discarded base strings; scientific rules and global read grouping unchanged.

suppressPackageStartupMessages({
  library(optparse)
  library(tidyverse)
  library(readr)
  library(stringr)
})

option_list <- list(
  make_option(c("-p","--pileup"),  type="character", help="pileup input file (.txt without header, tab separated)", metavar="file"),
  make_option(c("-s","--snplist"), type="character", help="snp list file (.tsv with header: pos, ref, alt)",       metavar="file"),
  make_option(c("-o","--out"),     type="character", default="SNPcall_output.txt",
              help="output file name [default = %default]", metavar="file")
)

opt <- parse_args(OptionParser(option_list=option_list))

# check required flags before continuing
if ( is.null(opt$pileup) | is.null(opt$snplist) ) {
  write("error: you must specify --pileup and --snplist\n", stderr())
  quit(status=1)
}

pileup_file  <- opt$pileup
snplist_file <- opt$snplist
out_file     <- opt$out

cat(">> snpscall started\n")
cat(">> pileup file : ", pileup_file,  "\n", sep = "")
cat(">> snplist file: ", snplist_file, "\n", sep = "")
cat(">> output file : ", out_file,     "\n\n", sep = "")

# read snplist file
cat(">> reading snp list...\n")
fake_DNP <- readr::read_tsv(snplist_file, show_col_types = FALSE)

# Probe up to five records, matching read.table() column-width inference.
# Reuse the same parser and type conversion for the complete selective read;
# optional columns beyond QNAME are skipped after this bounded schema probe.
cat(">> reading pileup...\n")
pileup_arguments <- list(file = pileup_file, row.names = NULL,
                         stringsAsFactors = FALSE, header = FALSE, sep = "\t")
pileup_columns <- names(do.call(read.csv, c(pileup_arguments, list(nrows = 5L))))
pileup_classes <- rep("NULL", length(pileup_columns))
pileup_classes[match(c("V1", "V2", "V5", "V7"), pileup_columns)] <- NA_character_
df <- do.call(read.csv, c(pileup_arguments, list(colClasses = pileup_classes)))

cat(">> input loaded correctly\n")

df2 <- data.frame(df.chr = paste(df$V1, df$V2, sep = ":"),
                  df.V5 = df$V5, df.V7 = df$V7)
rm(df)

# Preserve the original indel replacement before pairing observations.
df2$df.V5 <- gsub('\\*', '@', df2$df.V5)
df2$df.V5 <- gsub('[.,actgACTG]([+-]\\d+)+', '@', df2$df.V5)

# A normal mpileup row has one base and one nonempty QNAME per observation.
# Splitting these directly avoids inserting/removing separator characters and
# the two artificial empty observations previously added to every pileup row.
# Inputs with missing values, whitespace or recycling keep the legacy path.
base_parts <- strsplit(df2$df.V5, "", fixed = TRUE)
name_parts <- strsplit(as.character(df2$df.V7), ",", fixed = TRUE)
part_lengths <- lengths(base_parts)
direct_observations <- all(!is.na(df2$df.V5) & !is.na(df2$df.V7)) &&
  all(part_lengths > 0L & part_lengths == lengths(name_parts)) &&
  !any(grepl("[[:space:]]", df2$df.V5) | grepl("[[:space:]]", df2$df.V7)) &&
  !any(grepl("(^,|,$|,,)", df2$df.V7))

if (direct_observations) {
  df3 <- data.frame(
    df.chr = rep.int(df2$df.chr, part_lengths),
    df.V5 = unlist(base_parts, use.names = FALSE),
    df.V7 = unlist(name_parts, use.names = FALSE),
    stringsAsFactors = FALSE
  )
  rm(df2, base_parts, name_parts, part_lengths)

  # Group globally by QNAME, including reads spanning more than one SNP window.
  # A joined string of single bases is longer than four characters exactly when
  # at least three observations exist; its third character is the second base.
  # Retain the complete coordinate path because downstream counting uses it.
  read_features <- df3 %>%
    group_by(df.V7) %>%
    summarise(
      df.V5.1 = {
        if (length(df.V5) < 3L) NA_character_
        else if (any(df.V5 == "@")) "@"
        else df.V5[2L]
      },
      df.chr = paste(df.chr, collapse = "|"),
      .groups = "drop"
    ) %>%
    as.data.frame()
  rm(df3)
  read_features <- read_features[order(read_features$df.V7), , drop = FALSE]
  # Missing features mark short reads; @ marks indels anywhere in the read,
  # including flanking observations. Neither is a retained genotype.
  read_features <- read_features[!is.na(read_features$df.V5.1), , drop = FALSE]
  rownames(read_features) <- NULL
  print(sum(read_features$df.V5.1 == "@"))
  read_features <- read_features[
    read_features$df.V5.1 != "@" & !grepl("@", read_features$df.V7) &
      !grepl("@", read_features$df.chr), , drop = FALSE]
  print(0L)
  read_features$df.V5.1 <- chartr("acgt", "ACGT", read_features$df.V5.1)
  read_features$df.V5.1 <- gsub(",", ".", read_features$df.V5.1)
  df_merged5 <- read_features[, c("df.V7", "df.chr", "df.V5.1"), drop = FALSE]
  rm(read_features)
} else {
  rm(base_parts, name_parts, part_lengths)
  # Keep separate_rows() recycling/error behavior for nonstandard inputs.
  df2$df.V7 <- paste0(",", df2$df.V7, ",")
  df2$df.V5 <- gsub("", " ", df2$df.V5)
  df2$df.V7 <- gsub(",", " ", df2$df.V7)
  df3 <- df2 %>% separate_rows(df.V5, df.V7, sep = " ")
  rm(df2)
  df3 <- df3[is.na(df3$df.V7) | nchar(df3$df.V7) > 0, ]
  df_merged <- df3 %>%
    group_by(df.V7) %>%
    summarise(
      df.V5 = paste(df.V5, collapse = "|"),
      df.chr = paste(df.chr, collapse = "|"),
      .groups = "drop"
    ) %>%
    as.data.frame()
  rm(df3)
  df_merged <- df_merged[order(df_merged$df.V7), , drop = FALSE]
  rownames(df_merged) <- NULL
  df_merged2 <- df_merged[nchar(df_merged$df.V5) > 4, ]
  df_merged3 <- df_merged2[nchar(df_merged2$df.V7) > 0, ]
  rm(df_merged, df_merged2)
  df_merged3$df.V5 <- chartr("acgt", "ACGT", df_merged3$df.V5)
  df_merged3$df.V5 <- gsub(",", ".", df_merged3$df.V5)
  print(sum(grepl("@", df_merged3$df.V5)))
  df_merged4 <- df_merged3 %>% filter_all(all_vars(!grepl("@", .)))
  rm(df_merged3)
  print(sum(grepl("@", df_merged4$df.V5)))
  df_merged5 <- df_merged4 %>% mutate(df.V5.1 = substring(df.V5, 3, 3))
  df_merged5 <- subset(df_merged5, select = -df.V5)
  rm(df_merged4)
}

# count all genotypes found
df_count2 <- df_merged5 %>% group_by(df.chr, df.V5.1) %>% summarise(n = n(), .groups = "drop")
rm(df_merged5)

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
ref_dt <- subset(data_info2, df.V5.1 == ".")
colnames(ref_dt) <- c("SNPs", "geno", "n_ref", "ref", "alt", "is.alt")

# create dataset with alternative only
alt_dt <- subset(data_info2, is.alt == "ALT")
colnames(alt_dt) <- c("SNPs", "geno", "n_alt", "ref", "alt", "is.alt")

# create dataset with all other genotypes
altro_dt <- subset(data_info2, is.alt != "ALT" & df.V5.1 != ".")
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

# write final table to file
write.table(dataframe_final, file = out_file, sep = "\t", quote = FALSE, row.names = FALSE)

cat(">> done\n")
