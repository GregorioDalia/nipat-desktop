suppressPackageStartupMessages({
  library(dplyr)
  library(tools)
})

# load arguments
args <- commandArgs(trailingOnly = TRUE)

if (length(args) < 3) {
  stop("\nusage:\n  Rscript detect_contamination.R <marker_panel.txt> <input_path> <output_dir> [--include_zero | --exclude_zero]\n\nDefault: include sites with N_unexpected = 0.\n\n")
}

panel_file <- args[1]
input_path <- args[2]
output_dir <- args[3]

# Keep the original behaviour unless zero-support sites are explicitly excluded.
options <- if (length(args) > 3L) args[seq.int(4L, length(args))] else character()
unknown <- setdiff(options, c("--include_zero", "--exclude_zero"))
if (length(unknown)) {
  stop("unknown option(s): ", paste(unknown, collapse=", "))
}
if (all(c("--include_zero", "--exclude_zero") %in% options)) {
  stop("choose either --include_zero or --exclude_zero, not both")
}
include_zero_sites <- !("--exclude_zero" %in% options)
message("Sites with N_unexpected = 0: ",
        if (include_zero_sites) "included (original behaviour)" else "excluded")

dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

# Detect the panel format from its coordinate columns.
clean <- function(x) tolower(gsub("[^a-z0-9]+", "", tolower(x)))
marker_type <- function(x, label) {
  snp <- "pos" %in% names(x)
  dnp <- all(c("pos1", "pos2") %in% names(x))
  if (snp == dnp) {
    stop(label, ": use chr/pos for SNPs or chr/pos1/pos2 for DNPs")
  }
  if (snp) "SNP" else "DNP"
}

first_line <- readLines(panel_file, n=1, warn=FALSE)
if (!length(first_line)) stop("marker panel is empty")
first_fields <- clean(strsplit(first_line, "\t", fixed=TRUE)[[1]])
has_header <- "chr" %in% first_fields &&
  ("pos" %in% first_fields || all(c("pos1", "pos2") %in% first_fields))

dnplist <- read.table(panel_file, header=has_header, sep="\t",
                      stringsAsFactors=FALSE, check.names=FALSE,
                      quote="", comment.char="")
if (has_header) {
  cleaned <- clean(names(dnplist))
  for (column in c("chr", "pos", "pos1", "pos2", "REF", "ALT")) {
    index <- which(cleaned == clean(column))
    if (length(index) > 1L) stop("duplicate panel column: ", column)
    if (length(index) == 1L) names(dnplist)[index] <- column
  }
} else {
  names(dnplist) <- switch(as.character(ncol(dnplist)),
    "2"=c("chr", "pos"),
    "3"=c("chr", "pos1", "pos2"),
    "4"=c("chr", "pos", "REF", "ALT"),
    "5"=c("chr", "pos1", "pos2", "REF", "ALT"),
    stop("headerless panels require 2/4 SNP columns or 3/5 DNP columns"))
}
marker <- marker_type(dnplist, "marker panel")
site_columns <- if (marker == "SNP") c("chr", "pos") else c("chr", "pos1", "pos2")
position_columns <- setdiff(site_columns, "chr")
if (!all(site_columns %in% names(dnplist))) stop("missing panel coordinates")
dnplist <- dnplist %>%
  mutate(chr=as.character(chr), across(all_of(position_columns), as.numeric))
if (!nrow(dnplist) || anyNA(dnplist[site_columns])) {
  stop("marker panel is empty or contains missing/invalid coordinates")
}
message("Marker type: ", marker)

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

# remove the marker panel file from the input files
panel_normalized <- normalizePath(panel_file, mustWork = TRUE)
chip_normalized <- normalizePath(chip_files, mustWork = TRUE)

chip_files <- chip_files[chip_normalized != panel_normalized]

# initialize summary dataframe
contamination_summary <- data.frame(
  individuo = character(),
  informative_sites = integer(),
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

  if (marker_type(df, basename(file_path)) != marker) {
    stop("input format differs from marker panel: ", basename(file_path))
  }
  required_cols <- c(site_columns, "N_REF", "N_ALT", "N_Other")

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
      across(all_of(position_columns), as.numeric),
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
      if_all(all_of(site_columns), ~ !is.na(.x)),
      !is.na(N_REF),
      !is.na(N_ALT),
      !is.na(N_Other),
      !is.na(ratio_REF_ALT),
      (N_REF + N_ALT) > 0
    )

  # keep only marker panel positions
  df <- semi_join(
    df,
    dnplist,
    by = site_columns
  )

  # Use the same Other/total denominator as the CPI scripts.
  df <- df %>%
    mutate(
      ratio_Other = N_Other / (N_REF + N_ALT + N_Other)
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

  # This choice applies to the per-site output, site count, mean and SD.
  if (!include_zero_sites) {
    filtered_df <- filtered_df %>% filter(N_unexpected > 0)
  }

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
      informative_sites = nrow(filtered_df),
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

