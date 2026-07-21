#!/usr/bin/env Rscript

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

# read pileup file
cat(">> reading pileup...\n")
df <- read.csv(pileup_file,
               row.names = NULL,
               stringsAsFactors = FALSE,
               header = FALSE,
               sep = "\t")

cat(">> input loaded correctly\n")

# add chr:pos column
df$chr <- paste(df$V1, df$V2, sep = ":")

# keep only needed columns
df2 <- data.frame(df$chr, df$V5, df$V7)

# add commas at both ends of read names to enable the next step
df2$df.V7 <- paste0(",", df2$df.V7, ",")

# replace indels with a special character
df2$df.V5 <- gsub('\\*', '@', df2$df.V5)
df2$df.V5 <- gsub('[.,actgACTG]([+-]\\d+)+', '@', df2$df.V5)

# replace delimiters in bases and read names with a single space
df2$df.V5 <- gsub('', ' ', df2$df.V5)
df2$df.V7 <- gsub(',', ' ', df2$df.V7)

# split values pairing base with the corresponding read
df3 <- df2 %>% separate_rows(df.V5, df.V7, sep = " ")

# aggregate bases by read
df5 <- df3 %>% group_by(df.V7) %>% summarise(df.V5 = paste(df.V5, collapse = "|"), .groups = "drop")

# aggregate positions by read
df6 <- df3 %>% group_by(df.V7) %>% summarise(df.chr = paste(df.chr, collapse = "|"), .groups = "drop")

# merge the two datasets
df_merged <- merge(df5, df6)

# keep only reads called on both positions of a single read (micro haplotypes)
df_merged2 <- df_merged[nchar(df_merged$df.V5) > 4, ]
df_merged3 <- df_merged2[nchar(df_merged2$df.V7) > 0, ]

# harmonize strand characters
df_merged3$df.V5 <- gsub('g', 'G', df_merged3$df.V5)
df_merged3$df.V5 <- gsub('a', 'A', df_merged3$df.V5)
df_merged3$df.V5 <- gsub('c', 'C', df_merged3$df.V5)
df_merged3$df.V5 <- gsub('t', 'T', df_merged3$df.V5)
df_merged3$df.V5 <- gsub(',', '.', df_merged3$df.V5)

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
