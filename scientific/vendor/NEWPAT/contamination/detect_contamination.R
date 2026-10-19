suppressPackageStartupMessages({
  library(dplyr)
  library(tools)
})

# load arguments
args <- commandArgs(trailingOnly = TRUE)

if (length(args) < 3) {
  stop("\nusage:\n  Rscript detect_contamination.R <dnpanel.txt> <input_path> <output_dir>\n\n")
}

panel_file <- args[1]
input_path <- args[2]
output_dir <- args[3]

dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

# load the DNP panel
first_line <- readLines(panel_file, n = 1, warn = FALSE)
first_fields <- strsplit(first_line, "\t", fixed = TRUE)[[1]]

clean <- function(x) {
  x <- tolower(x)
  x <- gsub("[^a-z0-9]+", "", x)
  return(x)
}

clean_first_fields <- clean(first_fields)

has_header <- all(c("chr", "pos1", "pos2") %in% clean_first_fields)

if (has_header) {

  dnplist <- read.table(
    panel_file,
    header = TRUE,
    sep = "\t",
    stringsAsFactors = FALSE,
    check.names = FALSE,
    quote = "",
    comment.char = ""
  )

  clean_current <- clean(colnames(dnplist))

  expected_cols <- c("chr", "pos1", "pos2", "REF", "ALT")

  for (i in seq_along(expected_cols)) {
    match_idx <- which(clean_current == clean(expected_cols[i]))

    if (length(match_idx) == 1) {
      colnames(dnplist)[match_idx] <- expected_cols[i]
    }
  }

} else {

  dnplist <- read.table(
    panel_file,
    header = FALSE,
    sep = "\t",
    stringsAsFactors = FALSE,
    check.names = FALSE,
    quote = "",
    comment.char = ""
  )

  if (ncol(dnplist) < 3) {
    stop("error: DNP panel must contain at least chr, pos1 and pos2\n")
  }

  colnames(dnplist)[1:3] <- c("chr", "pos1", "pos2")

  if (ncol(dnplist) >= 4) {
    colnames(dnplist)[4] <- "REF"
  }

  if (ncol(dnplist) >= 5) {
    colnames(dnplist)[5] <- "ALT"
  }
}

required_panel_cols <- c("chr", "pos1", "pos2")

if (!all(required_panel_cols %in% colnames(dnplist))) {
  stop("error: cannot identify chr, pos1 and pos2 in DNP panel\n")
}

dnplist <- dnplist %>%
  mutate(
    chr = as.character(chr),
    pos1 = as.numeric(pos1),
    pos2 = as.numeric(pos2)
  )

# detect whether input_path is a file or directory
if (file.exists(input_path) && !dir.exists(input_path)) {

  chip_files <- input_path

} else if (dir.exists(input_path)) {

  chip_files <- list.files(
    path = input_path,
    pattern = "\\.txt$",
    full.names = TRUE,
    recursive = TRUE
  )

} else {

  stop("error: input_path does not exist: ", input_path)
}

if (length(chip_files) == 0) {
  stop("no input files found in: ", input_path)
}

# remove the DNP panel file from chip_files
panel_normalized <- normalizePath(panel_file, mustWork = TRUE)
chip_normalized <- normalizePath(chip_files, mustWork = TRUE)

chip_files <- chip_files[chip_normalized != panel_normalized]

# initialize summary dataframe
contamination_summary <- data.frame(
  individuo = character(),
  informative_DNPs = integer(),
  mean_contamination = numeric(),
  sd_contamination = numeric(),
  stringsAsFactors = FALSE
)

# main processing function
process_df <- function(file_path) {

  df <- read.table(
    file_path,
    header = TRUE,
    sep = "\t",
    quote = "",
    comment.char = "",
    fill = TRUE,
    stringsAsFactors = FALSE,
    check.names = FALSE
  )

  required_cols <- c(
    "chr",
    "pos1",
    "pos2",
    "N_REF",
    "N_ALT",
    "N_Other"
  )

  missing_cols <- setdiff(required_cols, colnames(df))

  if (length(missing_cols) > 0) {
    stop(
      "error: missing columns in ",
      basename(file_path),
      ": ",
      paste(missing_cols, collapse = ", ")
    )
  }

  # convert numeric fields
  df <- df %>%
    mutate(
      chr = as.character(chr),
      pos1 = as.numeric(pos1),
      pos2 = as.numeric(pos2),
      N_REF = as.numeric(N_REF),
      N_ALT = as.numeric(N_ALT),
      N_Other = as.numeric(N_Other)
    )

  # calculate ratio_REF_ALT if it is not present
  if ("ratio_REF_ALT" %in% colnames(df)) {

    df$ratio_REF_ALT <- as.numeric(df$ratio_REF_ALT)

  } else {

    df <- df %>%
      mutate(
        ratio_REF_ALT = ifelse(
          (N_REF + N_ALT) > 0,
          N_REF / (N_REF + N_ALT),
          NA_real_
        )
      )
  }

  # remove positions without REF or ALT reads
  df <- df %>%
    filter(
      !is.na(chr),
      !is.na(pos1),
      !is.na(pos2),
      !is.na(N_REF),
      !is.na(N_ALT),
      !is.na(N_Other),
      !is.na(ratio_REF_ALT),
      (N_REF + N_ALT) > 0
    )

  # keep only DNP panel positions
  df <- semi_join(
    df,
    dnplist,
    by = c("chr", "pos1", "pos2")
  )

  # filter out positions with high N_Other
  df <- df %>%
    mutate(
      ratio_Other = N_Other / (N_REF + N_ALT)
    ) %>%
    filter(
      !is.na(ratio_Other),
      ratio_Other <= 0.1
    )

  # keep informative positions and compute contamination per site
  filtered_df <- df %>%
    filter(
      ratio_REF_ALT >= 0.9 |
        ratio_REF_ALT <= 0.1
    ) %>%
    mutate(
      N_unexpected = ifelse(
        ratio_REF_ALT >= 0.9,
        N_ALT,
        N_REF
      ),
      contamination = N_unexpected / (N_REF + N_ALT)
    )

  # compute mean contamination
  if (nrow(filtered_df) > 0) {
    mean_contam <- mean(filtered_df$contamination, na.rm = TRUE)
  } else {
    mean_contam <- NA_real_
  }

  # compute sd contamination
  if (nrow(filtered_df) > 1) {
    sd_contam <- sd(filtered_df$contamination, na.rm = TRUE)
  } else {
    sd_contam <- NA_real_
  }

  sample_name <- file_path_sans_ext(basename(file_path))

  # add to summary
  contamination_summary <<- rbind(
    contamination_summary,
    data.frame(
      individuo = sample_name,
      informative_DNPs = nrow(filtered_df),
      mean_contamination = mean_contam,
      sd_contamination = sd_contam,
      stringsAsFactors = FALSE
    )
  )

  # save processed file
  write.table(
    filtered_df,
    file = file.path(
      output_dir,
      paste0("contamination_", sample_name, ".txt")
    ),
    sep = "\t",
    row.names = FALSE,
    quote = FALSE
  )
}

# process all files
invisible(lapply(chip_files, process_df))

# save final summary
write.table(
  contamination_summary,
  file = file.path(output_dir, "contamination_summary.txt"),
  sep = "\t",
  row.names = FALSE,
  quote = FALSE
)
