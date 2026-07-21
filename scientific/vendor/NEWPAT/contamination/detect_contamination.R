#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(openxlsx)
  library(dplyr)
  library(tools)
})

# load arguments
args <- commandArgs(trailingOnly = TRUE)

if (length(args) < 3) {
  stop("\nusage:\n  rscript detect_contamination.R <dnpanel.txt> <input_path> <output_dir>\n\n")
}

panel_file <- args[1]
input_path <- args[2]
output_dir <- args[3]

dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

# load the DNP panel
dnplist <- read.table(panel_file, header = TRUE, sep = "\t",
                      stringsAsFactors = FALSE, check.names = FALSE)

expected_cols <- c("n°DNP", "chr", "pos1", "pos2")

# check and normalize the DNP panel column names
clean <- function(x) {
  x <- tolower(x)
  x <- gsub("[^a-z0-9]+", "", x)
  return(x)
}

clean_expected <- clean(expected_cols)
clean_current  <- clean(colnames(dnplist))

for (i in seq_along(clean_expected)) {
  match_idx <- which(clean_current == clean_expected[i])
  if (length(match_idx) == 1) {
    colnames(dnplist)[match_idx] <- expected_cols[i]
  }
}

if (!all(expected_cols %in% colnames(dnplist))) {
  stop("error: cannot normalize column names in dnpanel.txt\n")
}

# detect whether input_path is a file or directory
if (file.exists(input_path) && !dir.exists(input_path)) {
  chip_files <- input_path
} else if (dir.exists(input_path)) {
  chip_files <- list.files(path = input_path, full.names = TRUE, recursive = TRUE)
} else {
  stop("error: input_path does not exist: ", input_path)
}

if (length(chip_files) == 0) {
  stop("no input files found in: ", input_path)
}

# remove the DNP panel file from chip_files
chip_files <- chip_files[ chip_files != normalizePath(panel_file) ]

# initialize summary dataframe
contamination_summary <- data.frame(
  individuo = character(),
  mean_contamination = numeric(),
  sd_contamination = numeric(),
  stringsAsFactors = FALSE
)

# main processing function
process_df <- function(file_path) {
  
  df <- read.table(file_path, header = TRUE, sep = "\t", quote = "", fill = TRUE)
  
  required_cols <- c("ratio_REF_ALT", "N_REF", "N_ALT", "N_Other",
                     "chr", "pos1", "pos2")
  
  if (!all(required_cols %in% colnames(df))) return(NULL)
  
  # convert numeric fields
  df <- df %>% mutate(across(c(ratio_REF_ALT, N_REF, N_ALT, N_Other), as.numeric))
  
  # keep only DNP panel positions
  df <- semi_join(df, dnplist, by = c("chr", "pos1", "pos2"))
  
  # filter out positions with high N_Other
  df <- df[(df$N_Other / (df$N_REF + df$N_ALT)) <= 0.1, ]
  
  # keep informative positions and compute contamination per site
  filtered_df <- df %>%
    filter((ratio_REF_ALT >= 0.9 & ratio_REF_ALT < 1) |
             (ratio_REF_ALT > 0 & ratio_REF_ALT <= 0.1)) %>%
    mutate(contamination = ifelse(ratio_REF_ALT >= 0.9,
                                  N_ALT / (N_REF + N_ALT),
                                  N_REF / (N_REF + N_ALT)))
  
  # compute mean contamination
  mean_contam <- mean(filtered_df$contamination, na.rm = TRUE)
  
  # compute sd contamination
  sd_contam <- sd(filtered_df$contamination, na.rm = TRUE)
  
  sample_name <- file_path_sans_ext(basename(file_path))
  
  # add to summary
  contamination_summary <<- rbind(
    contamination_summary,
    data.frame(individuo = sample_name,
               mean_contamination = mean_contam,
               sd_contamination = sd_contam)
  )
  
  # save processed file
  write.table(filtered_df,
              file = file.path(output_dir, paste0("contamination_", sample_name, ".txt")),
              sep = "\t", row.names = FALSE, quote = FALSE)
}

# process all files
lapply(chip_files, process_df)

# save final summary
write.xlsx(contamination_summary,
           file = file.path(output_dir, "contamination_summary.xlsx"),
           rownames = FALSE)
