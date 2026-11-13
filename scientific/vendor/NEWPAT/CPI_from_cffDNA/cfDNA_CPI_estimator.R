#!/usr/bin/env Rscript
# NIPAT 0.8.50 integrates NEWPAT 9c2a8be SNP/DNP model; reuse invariant CPI calculations and
# identical threshold selections; retain the formulas and every output row.
# NIPAT 0.8.12: bounded, ordered parallel work across pairs, cutoffs or
# independent threshold intervals. Scientific reductions retain their order.

suppressPackageStartupMessages({
  library(dplyr)
  library(readxl)
  library(ggplot2)
  library(patchwork)
  library(argparse)
  library(stringr)
  library(tidyr)
})

source(Sys.getenv("NIPAT_PARALLEL_HELPER",
                  unset = "/opt/nipat/lib/nipat_scientific/parallel.R"))
source(Sys.getenv("NIPAT_PLOTS_HELPER", unset = "/opt/nipat/lib/nipat_scientific/plots.R"))

source(Sys.getenv("NIPAT_SETTINGS_HELPER", unset="/opt/nipat/lib/nipat_scientific/settings.R"))
nipat_cfg <- nipat_settings("cpi")

## cli parser
parser <- ArgumentParser()

parser$add_argument("--pileup_dir",    required=TRUE)
parser$add_argument("--out_dir",       required=TRUE)
parser$add_argument("--pairs",         required=TRUE)
parser$add_argument("--mother_prefix", required=TRUE)
parser$add_argument("--father_prefix", required=TRUE)
parser$add_argument("--popfreq",       required=TRUE)

parser$add_argument("--cutoff_map", required=FALSE,
                    help='named marker panels: label=/path/panel.tsv,...')
parser$add_argument("--markers", required=FALSE)
parser$add_argument("--err_const", default=NULL,
                    help="Explicit override for the detected marker type")
parser$add_argument("--err_const_snp", default=NULL)
parser$add_argument("--err_const_dnp", default=NULL)
parser$add_argument("--min_fetal_reads", type="double", default=NULL)
args <- parser$parse_args()
args$err_const_snp <- if (is.null(args$err_const_snp)) nipat_cfg$err_const_snp else args$err_const_snp
args$err_const_dnp <- if (is.null(args$err_const_dnp)) nipat_cfg$err_const_dnp else args$err_const_dnp
min_fetal_reads <- if (is.null(args$min_fetal_reads)) nipat_cfg$min_fetal_reads else args$min_fetal_reads
if (!is.finite(min_fetal_reads) || min_fetal_reads < 1 ||
    min_fetal_reads != floor(min_fetal_reads) || min_fetal_reads >= .Machine$integer.max)
  stop("--min_fetal_reads must be a positive integer below the R integer limit")
min_fetal_reads <- as.integer(min_fetal_reads)
if (!dir.exists(args$out_dir)) dir.create(args$out_dir, recursive=TRUE)
plots_dir <- file.path(args$out_dir, "plots")
dir.create(plots_dir, recursive=TRUE, showWarnings=FALSE)
parts <- lapply(strsplit(args$pairs, ",", fixed=TRUE)[[1]], function(z) trimws(strsplit(z, ":", fixed=TRUE)[[1]]))
if (!length(parts) || any(lengths(parts) != 2L) || any(!nzchar(unlist(parts)))) stop("Invalid mother:father pairs")
keys <- vapply(parts, paste, collapse=":", FUN.VALUE="")
if (anyDuplicated(tolower(keys))) stop("Duplicate mother:father pairs")
coppie <- data.frame(mamma=vapply(parts, `[`, "", 1), papa=vapply(parts, `[`, "", 2))
if (any(tolower(paste0(args$mother_prefix, coppie$mamma)) ==
        tolower(paste0(args$father_prefix, coppie$papa))))
  stop("Mother and father must refer to distinct input samples")
if (any(!grepl("^[A-Za-z0-9_.-]+$", unlist(parts)))) stop("Invalid sample identifiers")
if (anyDuplicated(tolower(paste0("Mother", coppie$mamma, "-Father", coppie$papa))))
  stop("Distinct pairs would overwrite the same result")

## Read coordinates from the frequency table and use them in every join.
if (!file.exists(args$popfreq)) stop("popfreq file not found")
population <- read.table(args$popfreq, header=TRUE, sep="\t",
                         stringsAsFactors=FALSE, check.names=FALSE,
                         quote="", comment.char="")

marker_type <- function(x, label) {
  has_snp <- "pos" %in% names(x)
  has_dnp <- all(c("pos1", "pos2") %in% names(x))
  if (has_snp == has_dnp) {
    stop(label, ": use either pos for SNPs or pos1 and pos2 for DNPs")
  }
  if (has_snp) "SNP" else "DNP"
}

has_markers <- !is.null(args$markers) && nzchar(trimws(args$markers))
marker_list <- NULL
marker <- marker_type(population, "population frequencies")
if (has_markers) {
  # DNPcall lists have five columns without a header; SNPcall lists have four.
  # A header is also accepted, with lower- or upper-case allele column names.
  marker_list <- read.table(args$markers, header=FALSE, sep="", quote="",
                            comment.char="", colClasses="character",
                            stringsAsFactors=FALSE, check.names=FALSE)
  marker_columns <- switch(as.character(ncol(marker_list)),
    "4" = c("chr", "pos", "REF", "ALT"),
    "5" = c("chr", "pos1", "pos2", "REF", "ALT"),
    stop("Marker list must contain four SNP columns or five DNP columns")
  )
  first_row <- unlist(marker_list[1, ], use.names=FALSE)
  if (identical(tolower(first_row), tolower(marker_columns))) {
    marker_list <- marker_list[-1, , drop=FALSE]
  }
  names(marker_list) <- marker_columns
  if (!nrow(marker_list)) stop("Marker list is empty")
  marker <- marker_type(marker_list, "marker list")
  if (marker_type(population, "population frequencies") != marker) {
    stop("Population frequency coordinates do not match the marker list format")
  }
}
message("Panel: ", if (has_markers) args$markers else "all calling-output sites")
site_columns <- if (marker == "SNP") c("chr", "pos") else c("chr", "pos1", "pos2")
message("Marker type: ", marker)

# Select the constant for the detected marker type.
read_error_constant <- function(value, option) {
  if (is.null(value)) return(NULL)
  number <- suppressWarnings(as.numeric(value))
  if (length(number) != 1L || !is.finite(number) || number <= 0 || number > 1) {
    stop(option, " must be a finite number in (0, 1], for example 1e-04")
  }
  number
}

error_constants <- list(
  SNP = read_error_constant(args$err_const_snp, "--err_const_snp"),
  DNP = read_error_constant(args$err_const_dnp, "--err_const_dnp")
)
err_const <- error_constants[[marker]]
if (!is.null(args$err_const)) err_const <- read_error_constant(args$err_const, "--err_const")
nipat_cfg$err_const_snp <- error_constants$SNP
nipat_cfg$err_const_dnp <- error_constants$DNP
nipat_cfg[[paste0("err_const_", tolower(marker))]] <- err_const
nipat_cfg$min_fetal_reads <- min_fetal_reads
message("Mismatch constant used for ", marker, ": ", sprintf("%.17g", err_const))

site_key <- function(x) {
  do.call(paste, c(unname(as.list(x[site_columns])), sep="\t"))
}

check_sites <- function(x, required, label) {
  missing <- setdiff(required, names(x))
  if (length(missing)) stop(label, ": missing columns ", paste(missing, collapse=", "))
  if (anyNA(x[site_columns]) || anyDuplicated(site_key(x))) {
    stop(label, ": missing or duplicate coordinates")
  }
  if (any(!nzchar(trimws(as.character(x$chr))))) stop(label, ": empty chromosome")
  for (column in setdiff(site_columns, "chr")) {
    values <- suppressWarnings(as.numeric(x[[column]]))
    if (any(!is.finite(values) | values < 1 | values != floor(values)))
      stop(label, ": coordinates must be positive integers")
  }
}

if (has_markers) {
  check_sites(marker_list, marker_columns, "marker list")
  for (column in setdiff(site_columns, "chr")) {
    position <- suppressWarnings(as.numeric(marker_list[[column]]))
    if (any(!is.finite(position) | position < 1 | position != floor(position))) {
      stop("Marker list positions must be positive integers")
    }
    marker_list[[column]] <- position
  }
  marker_list$REF <- toupper(marker_list$REF)
  marker_list$ALT <- toupper(marker_list$ALT)
  allele_pattern <- if (marker == "SNP") "^[ACGT]$" else "^[ACGT]{2}$"
  if (anyNA(marker_list[c("REF", "ALT")]) ||
      any(!grepl(allele_pattern, marker_list$REF) |
          !grepl(allele_pattern, marker_list$ALT) |
          marker_list$REF == marker_list$ALT)) {
    stop("Marker list must contain distinct REF and ALT alleles for the selected marker type")
  }
  # Check again after converting positions, so equivalent coordinates cannot repeat.
  check_sites(marker_list, marker_columns, "marker list")
  
}

check_sites(population, c(site_columns, "Ref_f.pop", "Alt_f.pop"),
            "population frequencies")
population$chr <- as.character(population$chr)
if (has_markers) {
  frequency_index <- match(site_key(marker_list), site_key(population))
  if (anyNA(frequency_index)) {
    missing_sites <- site_key(marker_list)[is.na(frequency_index)]
    stop("Missing population frequencies for marker-list sites: ",
         paste(head(missing_sites, 5), collapse=", "))
  }
  population <- population[frequency_index, , drop=FALSE]
  if (all(c("REF", "ALT") %in% names(population))) {
    if (anyNA(population[c("REF", "ALT")]) ||
        any(toupper(population$REF) != marker_list$REF |
            toupper(population$ALT) != marker_list$ALT)) {
      stop("Population frequency alleles differ from the marker list")
    }
  }
}
population$Ref_f.pop <- as.numeric(gsub(",", ".", population$Ref_f.pop))
population$Alt_f.pop <- as.numeric(gsub(",", ".", population$Alt_f.pop))
if (any(!is.finite(population$Ref_f.pop) | !is.finite(population$Alt_f.pop) |
        population$Ref_f.pop <= 0 | population$Ref_f.pop > 1 |
        population$Alt_f.pop <= 0 | population$Alt_f.pop > 1)) {
  stop("Population frequencies must be finite and in (0, 1]")
}

# Keep allele columns outside the join to avoid REF and ALT suffix conflicts.
PopFreqDNPs <- population[, c(site_columns, "Ref_f.pop", "Alt_f.pop"), drop=FALSE]

read_calls <- function(path) {
  x <- read.table(path, header=TRUE, check.names=FALSE, stringsAsFactors=FALSE)
  if (marker_type(x, path) != marker) stop(path, ": format differs from population frequencies")
  check_sites(x, c(site_columns, "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count"), path)
  x$chr <- as.character(x$chr)
  if (has_markers) {
    # Restrict all downstream calculations to the supplied marker list.
    x <- x[site_key(x) %in% site_key(marker_list), , drop=FALSE]
    j <- match(site_key(x), site_key(marker_list))
    if (anyNA(x[c("REF", "ALT")]) ||
        any(toupper(x$REF) != marker_list$REF[j] |
            toupper(x$ALT) != marker_list$ALT[j])) {
      stop(path, ": alleles differ from the marker list")
    }
  }
  expected_length <- if (marker == "SNP") 1L else 2L
  if (anyNA(x[c("REF", "ALT")]) ||
      any(nchar(x$REF) != expected_length | nchar(x$ALT) != expected_length |
          toupper(x$REF) == toupper(x$ALT))) {
    stop(path, ": invalid REF or ALT alleles")
  }
  # Older DNP frequency tables have no REF or ALT columns.
  if (all(c("REF", "ALT") %in% names(population))) {
    j <- match(site_key(x), site_key(population))
    present <- which(!is.na(j))
    if (anyNA(population[j[present], c("REF", "ALT"), drop=FALSE])) {
      stop("Population frequencies contain missing alleles")
    }
    if (any(toupper(x$REF[present]) != toupper(population$REF[j[present]]) |
            toupper(x$ALT[present]) != toupper(population$ALT[j[present]]))) {
      stop(path, ": alleles differ from population frequencies")
    }
  }
  pattern <- if (marker == "SNP") "^[ACGT]$" else "^[ACGT]{2}$"
  if (any(!grepl(pattern, toupper(x$REF)) | !grepl(pattern, toupper(x$ALT))))
    stop(path, ": alleles must contain only A/C/G/T")
  for (column in c("N_REF", "N_ALT", "N_Other"))
    x[[column]] <- suppressWarnings(as.numeric(x[[column]]))
  counts <- as.matrix(x[c("N_REF", "N_ALT", "N_Other")])
  if (anyNA(counts) || any(!is.finite(counts) | counts < 0 | counts != floor(counts)))
    stop(path, ": counts must be finite nonnegative integers")
  allowed_missing <- is.na(x$total_count) & rowSums(counts) == 0
  total <- suppressWarnings(as.numeric(x$total_count))
  if (any(is.na(total) & !allowed_missing) ||
      any(!is.finite(total[!allowed_missing]) | total[!allowed_missing] < 0 |
          total[!allowed_missing] != floor(total[!allowed_missing])))
    stop(path, ": invalid total_count")
  x$total_count <- total
  x
}

check_pair <- function(mother, father) {
  j <- match(site_key(mother), site_key(father))
  present <- which(!is.na(j))
  if (any(toupper(mother$REF[present]) != toupper(father$REF[j[present]]) |
          toupper(mother$ALT[present]) != toupper(father$ALT[j[present]]))) {
    stop("Mother and father have different REF or ALT alleles at shared coordinates")
  }
}

# Multiple panels are a NIPAT feature; preserve them with marker-aware validation.
if (has_markers && !is.null(args$cutoff_map) && nzchar(args$cutoff_map))
  stop("Choose --markers or --cutoff_map")
if (has_markers) {
  cutoff_df <- data.frame(Cutoff=args$markers, Path=args$markers)
  cutoff_panels <- list(marker_list)
  has_cutoffs <- TRUE
} else if (!is.null(args$cutoff_map) && nzchar(args$cutoff_map)) {
  panels <- lapply(strsplit(args$cutoff_map, ",", fixed=TRUE)[[1]], function(z) {
    kv <- strsplit(z, "=", fixed=TRUE)[[1]]
    if (length(kv) == 1L) list(Cutoff=kv[1], Path=kv[1]) else {
      if (length(kv) != 2L || any(!nzchar(kv))) stop("Invalid cutoff_map entry")
      list(Cutoff=kv[1], Path=kv[2])
    }
  })
  cutoff_df <- do.call(rbind, lapply(panels, as.data.frame))
  if (anyDuplicated(cutoff_df$Cutoff)) stop("Duplicate cutoff label")
  cutoff_panels <- lapply(cutoff_df$Path, function(path) {
    x <- read.table(path, header=TRUE, sep="\t", check.names=FALSE, stringsAsFactors=FALSE)
    if (marker_type(x, path) != marker) stop("Marker panel differs from population type")
    check_sites(x, site_columns, path)
    x$chr <- as.character(x$chr)
    for (key in setdiff(site_columns, "chr")) {
      x[[key]] <- suppressWarnings(as.numeric(x[[key]]))
      if (any(!is.finite(x[[key]]) | x[[key]] < 1 | x[[key]] != floor(x[[key]]))) stop("Invalid panel coordinates")
    }
    check_sites(x, site_columns, path)
    if (anyNA(match(site_key(x), site_key(population)))) stop("Missing population frequencies for marker panel")
    x
  })
  has_cutoffs <- TRUE
} else {
  cutoff_df <- data.frame(Cutoff="ALL", Path=NA_character_)
  cutoff_panels <- list(NULL)
  has_cutoffs <- FALSE
}
# Cache raw tables by path so shared parents are read/validated only once.
call_paths <- unique(c(file.path(args$pileup_dir, paste0(args$mother_prefix, coppie$mamma, ".txt")),
                       file.path(args$pileup_dir, paste0(args$father_prefix, coppie$papa, ".txt"))))
calls_cache <- setNames(lapply(call_paths, read_calls), call_paths)
for (x in calls_cache) {
  for (panel in cutoff_panels) {
    if (is.null(panel) || !all(c("REF", "ALT") %in% names(panel))) next
    j <- match(site_key(x), site_key(panel)); present <- which(!is.na(j))
    if (any(toupper(x$REF[present]) != toupper(panel$REF[j[present]]) |
            toupper(x$ALT[present]) != toupper(panel$ALT[j[present]]))) stop("Calling-output alleles differ from panel")
  }
}

## helper: compute fetal_reads on mother dataframe
nipat_write_settings("cpi", nipat_cfg, args$out_dir)
## note: this mirrors the logic used in cpi iteration
compute_madre_info <- function(madre_df) {
  madre_df %>%
    dplyr::filter(
      (ratio_Ref_mother >= nipat_cfg$homozygous_ref_min & Alt_mother >= min_fetal_reads) |
        (ratio_Ref_mother <= nipat_cfg$homozygous_alt_max & Ref_mother >= min_fetal_reads)
    ) %>%
    dplyr::mutate(
      fetal_reads = ifelse(ratio_Ref_mother >= nipat_cfg$homozygous_ref_min, Alt_mother, Ref_mother)
    )
}

## core: compute cpi for one list (or all sites if dnp_list is NULL)
run_CPI_iteration <- function(madre_df, padre_df, dnp_list, cutoff_label, err_const) {
  if (!is.null(dnp_list)) {
    madre <- madre_df %>% dplyr::semi_join(dnp_list, by=site_columns)
    padre <- padre_df %>% dplyr::semi_join(dnp_list, by=site_columns)
  } else {
    madre <- madre_df
    padre <- padre_df
  }

  madre_info <- compute_madre_info(madre)
  max_fetal <- suppressWarnings(max(madre_info$fetal_reads, na.rm=TRUE))
  if (!is.finite(max_fetal) || max_fetal < min_fetal_reads) {
    empty <- data.frame(Iteration=integer(), InfSites_mother=integer(),
      InfSites_father=integer(), CPI=double(), log_CPI=double(), Mismatch=integer(),
      NotMismatch=integer(), Cutoff=character())
    return(list(results=empty, madre_info=madre_info))
  }

  ## Carry the maternal row identity through joins rather than relying on the
  ## joined fetal_reads name, which population metadata may also contain.
  row_id <- ".nipat_cpi_maternal_row"
  input_names <- c(names(madre_info), names(padre), names(PopFreqDNPs))
  while (row_id %in% input_names) row_id <- paste0(row_id, "_")
  madre_indexed <- madre_info
  madre_indexed[[row_id]] <- seq_len(nrow(madre_indexed))

  df_merged <- dplyr::inner_join(madre_indexed, padre, by=site_columns) %>%
    dplyr::mutate(threshold = dplyr::case_when(
      ratio_Ref_mother >= nipat_cfg$homozygous_ref_min & Alt_father >= 0 ~ "informative",
      ratio_Ref_mother <= nipat_cfg$homozygous_alt_max & Ref_father >= 0 ~ "informative",
      TRUE ~ "non informative"
    )) %>%
    dplyr::inner_join(PopFreqDNPs, by=site_columns) %>%
    dplyr::mutate(dplyr::across(c(Ref_f.pop,Alt_f.pop), as.numeric))

  informative_all <- df_merged %>% dplyr::filter(threshold=="informative")
  PI_all <- informative_all %>%
    dplyr::mutate(Paternity_Index = dplyr::case_when(
      ratio_Ref_mother >= nipat_cfg$homozygous_ref_min & ratio_Ref_father <= nipat_cfg$homozygous_alt_max ~ 1/Alt_f.pop,
      ratio_Ref_mother >= nipat_cfg$homozygous_ref_min & between(ratio_Ref_father,nipat_cfg$heterozygous_min,nipat_cfg$heterozygous_max) ~ 0.5/Alt_f.pop,
      ratio_Ref_mother >= nipat_cfg$homozygous_ref_min & ratio_Ref_father >= nipat_cfg$homozygous_ref_min ~ err_const/Alt_f.pop,
      ratio_Ref_mother <= nipat_cfg$homozygous_alt_max & ratio_Ref_father <= nipat_cfg$homozygous_alt_max ~ err_const/Ref_f.pop,
      ratio_Ref_mother <= nipat_cfg$homozygous_alt_max & between(ratio_Ref_father,nipat_cfg$heterozygous_min,nipat_cfg$heterozygous_max) ~ 0.5/Ref_f.pop,
      ratio_Ref_mother <= nipat_cfg$homozygous_alt_max & ratio_Ref_father >= nipat_cfg$homozygous_ref_min ~ 1/Ref_f.pop,
      TRUE ~ NA_real_
    )) %>% tidyr::drop_na()

  ## Population metadata is projected out before joins; irrelevant NA cannot remove sites.
  ## The added row identity is always present and has no missing values.
  pi_fetal_reads <- madre_info$fetal_reads[PI_all[[row_id]]]
  informative_fetal_reads <- madre_info$fetal_reads[informative_all[[row_id]]]
  mismatch <- (informative_all$ratio_Ref_mother >= nipat_cfg$homozygous_ref_min &
                 informative_all$ratio_Ref_father >= nipat_cfg$homozygous_ref_min) |
    (informative_all$ratio_Ref_mother <= nipat_cfg$homozygous_alt_max &
       informative_all$ratio_Ref_father <= nipat_cfg$homozygous_alt_max)

  iterations <- seq.int(min_fetal_reads, max_fetal)
  ## A locus with f fetal reads disappears at threshold floor(f) + 1.
  ## Index 1 corresponds to min_fetal_reads; disappearance has index
  ## floor(f) - min_fetal_reads + 2. All joined rows originate from these maternal loci, so their
  ## PI and mismatch selections are constant between the same boundaries.
  ## Keep every threshold in the final table: its repetitions affect the
  ## summary statistics, median-threshold lookup and plots.
  interval_starts <- sort(unique(c(1L, floor(madre_info$fetal_reads) - min_fetal_reads + 2L)))
  interval_starts <- interval_starts[interval_starts <= length(iterations)]
  interval_lengths <- diff(c(interval_starts, length(iterations) + 1))
  interval_count <- length(interval_starts)
  pi_values <- PI_all$Paternity_Index

  mother_counts <- integer(interval_count)
  father_counts <- integer(interval_count)
  cpi_values <- numeric(interval_count)
  log_cpi_values <- numeric(interval_count)
  mismatch_counts <- integer(interval_count)
  matching_counts <- integer(interval_count)

  compute_interval <- function(interval_index) {
    i <- iterations[interval_starts[interval_index]]
    mother_count <- sum(madre_info$fetal_reads >= i)
    pi_selected <- pi_fetal_reads >= i
    father_count <- sum(pi_selected)

    ## Retain the original ordered product, including its handling of zero,
    ## underflow and overflow. Neither cumulative division nor sums of logs
    ## are equivalent substitutes for prod() on the selected PI values.
    CPI_val <- ifelse(father_count > 0,
                      prod(pi_values[pi_selected], na.rm=TRUE), NA_real_)
    log_CPI_val <- ifelse(
      !is.na(CPI_val) & CPI_val > 0, log10(CPI_val), NA_real_)

    informative_selected <- informative_fetal_reads >= i
    n_mismatch <- sum(mismatch[informative_selected])
    list(mother = mother_count, father = father_count, cpi = CPI_val,
         log_cpi = log_CPI_val, mismatch = n_mismatch,
         matching = sum(informative_selected) - n_mismatch)
  }
  interval_workers <- nipat_parallel_workers(interval_count)
  # Fork at most a few contiguous chunks per worker, not one process for every
  # threshold interval. The interval order inside each chunk is unchanged.
  chunk_size <- max(1L, ceiling(interval_count / (4L * interval_workers)))
  if (interval_workers == 1L) chunk_size <- interval_count
  interval_chunks <- split(seq_along(interval_starts),
                           ceiling(seq_along(interval_starts) / chunk_size))
  chunk_values <- nipat_parallel_lapply(interval_chunks, function(indices) {
    lapply(indices, compute_interval)
  }, label = "cpi-thresholds", workers = interval_workers)
  interval_values <- unname(unlist(chunk_values, recursive = FALSE))
  # Assign into the original typed vectors in input order. Each product and
  # each sum above still processes exactly the original ordered observations.
  for (interval_index in seq_along(interval_values)) {
    value <- interval_values[[interval_index]]
    mother_counts[interval_index] <- value$mother
    father_counts[interval_index] <- value$father
    cpi_values[interval_index] <- value$cpi
    log_cpi_values[interval_index] <- value$log_cpi
    mismatch_counts[interval_index] <- value$mismatch
    matching_counts[interval_index] <- value$matching
  }
  results <- data.frame(
    Iteration=iterations,
    InfSites_mother=rep(mother_counts, interval_lengths),
    InfSites_father=rep(father_counts, interval_lengths),
    CPI=rep(cpi_values, interval_lengths),
    log_CPI=rep(log_cpi_values, interval_lengths),
    Mismatch=rep(mismatch_counts, interval_lengths),
    NotMismatch=rep(matching_counts, interval_lengths),
    Cutoff=cutoff_label
  )
  return(list(results=results, madre_info=madre_info))
}

## get logCPI at iteration closest to target (median fetal reads)
closest_logCPI <- function(res_df, target_i) {
  if (nrow(res_df)==0 || is.na(target_i) || !is.finite(target_i)) return(NA_real_)
  idx <- which.min(abs(res_df$Iteration - target_i))
  res_df$log_CPI[idx]
}

plot_CPI <- function(df, cutoff_label, pair_name,
                     cfDNA_percent = NA_real_,
                     cpi_medff = NA_real_, median_reads = NA_real_) {

  if (nrow(df) == 0) {
    return(
      ggplot() +
        theme_void(base_size = 9) +
        annotate("text", x = 0, y = 0, label = "No informative loci available", size = 3) +
        labs(title = paste(pair_name, "-", cutoff_label, "(no data)")) +
        theme(plot.title = element_text(size = 9, hjust = 0))
    )
  }

  max_iter <- max(df$Iteration, na.rm = TRUE)

  ticks <- sort(unique(c(min_fetal_reads, pretty(c(min_fetal_reads, max_iter), n=8), max_iter)))
  ticks <- ticks[ticks >= min_fetal_reads & ticks <= max_iter]
  median_threshold <- if (is.finite(median_reads)) df$Iteration[which.min(abs(df$Iteration - median_reads))] else numeric()

  cfDNA_lbl <- if (is.finite(cfDNA_percent)) {
    sprintf("%.2f", cfDNA_percent)
  } else {
    "NA"
  }

  cpi_lbl <- if (is.finite(cpi_medff)) {
    sprintf("%.3f", cpi_medff)
  } else {
    "NA"
  }

  annot_text <- paste0(
    "atop(",
    "'cfDNA: ", cfDNA_lbl, "%',",
    "log[10](CPI) * ': ' * '", cpi_lbl, "'",
    ")"
  )

  cpi_plot <- ggplot(df, aes(x = Iteration)) +
    annotate("rect", xmin = -Inf, xmax = Inf,
             ymin = -Inf, ymax = nipat_cfg$log_cpi_lower, fill = "red", alpha = 0.05) +
    annotate("rect", xmin = -Inf, xmax = Inf,
             ymin = nipat_cfg$log_cpi_lower, ymax = nipat_cfg$log_cpi_upper, fill = "grey", alpha = 0.05) +
    annotate("rect", xmin = -Inf, xmax = Inf,
             ymin = nipat_cfg$log_cpi_upper, ymax = Inf, fill = "green", alpha = 0.05) +

    geom_vline(xintercept=median_threshold, colour="red", linetype="dashed") +
    geom_line(aes(y = log_CPI), colour = "black") +
    geom_point(aes(y = log_CPI), colour = "black", size = 1.3) +

    annotate(
      "label",
      x = Inf, y = Inf,
      label = annot_text,
      parse = TRUE,
      hjust = 1.05,
      vjust = 1.10,
      size = 3,
      fill = "white",
      colour = "black",
      label.size = 0.2
    ) +

    scale_y_continuous(
      name = expression(log[10](CPI)),
      expand = expansion(mult = c(0.02, 0.14))
    ) +

    scale_x_continuous(
      name = "minimum number of fetal reads considered",
      breaks = ticks,
      limits = c(min_fetal_reads, max(min_fetal_reads + 1, max_iter)),
      expand = expansion(mult = c(0.02, 0.02))
    ) +

    labs(title = paste(pair_name, "-", cutoff_label)) +

    theme_bw(base_size = 9) +
    theme(
      legend.position = "bottom",
      plot.caption = element_text(size = 7, hjust = 0),
      plot.title = element_text(size = 9, hjust = 0),
      axis.title = element_text(size = 8),
      axis.text.x = element_text(angle = 45, hjust = 1, size = 7),
      panel.border = element_rect(
        colour = "black", fill = NA, linewidth = 0.6
      ),
      plot.margin = margin(8, 12, 8, 8)
    )
  # Counts and log likelihood ratios have different units. Separate aligned
  # panels keep the original values and avoid negative/fractional site axes.
  sites_plot <- ggplot(df, aes(x = Iteration)) +
    geom_line(aes(y = NotMismatch, colour = "Matching sites")) +
    geom_point(aes(y = NotMismatch, colour = "Matching sites"), size = 1) +
    geom_line(aes(y = Mismatch, colour = "Mismatching sites"), linetype = "dashed") +
    geom_point(aes(y = Mismatch, colour = "Mismatching sites"), size = 1) +
    scale_colour_manual(name = NULL, values = c("Matching sites" = "#008A38", "Mismatching sites" = "#C46B00")) +
    scale_y_continuous(name = "Informative sites", limits = c(0, NA), breaks = nipat_integer_breaks) +
    scale_x_continuous(name = "Minimum number of fetal reads considered", breaks = ticks,
      limits = c(min_fetal_reads, max(min_fetal_reads + 1, max_iter)), expand = expansion(mult = c(0.02, 0.02))) +
    theme_bw(base_size = 9) +
    theme(legend.position = "bottom", axis.text.x = element_text(angle = 45, hjust = 1, size = 7))
  (cpi_plot / sites_plot) + patchwork::plot_layout(heights = c(2, 1))
}

## main containers
fetal_fraction_rows <- vector("list", nrow(coppie) * nrow(cutoff_df))
all_combined_plots <- list()
## Reuse a parent shared by consecutive pairs, retaining at most the two
## prepared tables already needed by the current pair.
pair_cache <- new.env(parent = emptyenv())
pair_cache$mother_path <- NULL
pair_cache$father_path <- NULL

process_pair <- function(i) {
  mamma_id <- coppie$mamma[i]
  papa_id  <- coppie$papa[i]
  pair_name <- paste0("Mother", mamma_id, "-Father", papa_id, "_", marker, "s")

  mother_path <- file.path(args$pileup_dir, paste0(args$mother_prefix, mamma_id, ".txt"))
  father_path <- file.path(args$pileup_dir, paste0(args$father_prefix, papa_id, ".txt"))

  check_pair(calls_cache[[mother_path]], calls_cache[[father_path]])

  if (!identical(mother_path, pair_cache$mother_path)) {
    madre <- calls_cache[[mother_path]]
    madre$chr <- as.character(madre$chr)
    madre <- madre %>%
      dplyr::transmute(
        dplyr::across(dplyr::all_of(site_columns)), REF, ALT,
        Ref_mother = N_REF,
        Alt_mother = N_ALT,
        Error_mother = N_Other,
        ratio_Ref_mother = N_REF / (N_REF + N_ALT),
        total_count = total_count
      ) %>% dplyr::filter(Error_mother/total_count <= nipat_cfg$other_fraction_max)
    pair_cache$mother <- madre
    pair_cache$mother_path <- mother_path
  } else {
    madre <- pair_cache$mother
  }

  if (!identical(father_path, pair_cache$father_path)) {
    padre <- calls_cache[[father_path]]
    padre$chr <- as.character(padre$chr)
    padre <- padre %>%
      dplyr::transmute(
        dplyr::across(dplyr::all_of(site_columns)), REF, ALT,
        Ref_father = N_REF,
        Alt_father = N_ALT,
        Error_father = N_Other,
        ratio_Ref_father = N_REF / (N_REF + N_ALT),
        total_count = total_count
      ) %>%
      dplyr::mutate(
        Ref_father = ifelse(ratio_Ref_father < nipat_cfg$homozygous_alt_max, 0, Ref_father),
        Alt_father = ifelse(ratio_Ref_father > nipat_cfg$homozygous_ref_min, 0, Alt_father)
      ) %>% dplyr::filter(Error_father/total_count <= nipat_cfg$other_fraction_max)
    pair_cache$father <- padre
    pair_cache$father_path <- father_path
  } else {
    padre <- pair_cache$father
  }

  cutoff_results <- nipat_parallel_lapply(seq_len(nrow(cutoff_df)), function(k) {
    cutoff_label <- cutoff_df$Cutoff[k]
    dnp_list <- cutoff_panels[[k]]

    out <- run_CPI_iteration(madre, padre, dnp_list, cutoff_label, err_const)
    res <- out$results

    target_i <- out$madre_info %>%
      dplyr::pull(fetal_reads) %>%
      stats::median(na.rm = TRUE) %>%
      round()

    cpi_at_med <- closest_logCPI(res, target_i)

    median_fetal_fraction <- out$madre_info %>%
      dplyr::mutate(
        fetal_fraction_site = 2 * fetal_reads /
          (Ref_mother + Alt_mother)
      ) %>%
      dplyr::pull(fetal_fraction_site) %>%
      stats::median(na.rm = TRUE)

    cfDNA_percent <- median_fetal_fraction * 100

    ## The core has already selected this panel and the informative maternal
    ## rows. Every row admitted by the summary below is in madre_info; retain
    ## its original summary formula and positivity filter, including NA/Inf.
    madre_cutoff <- out$madre_info

    madre_cutoff <- madre_cutoff %>%
      mutate(
        fetal_reads = case_when(
          ratio_Ref_mother >= nipat_cfg$homozygous_ref_min ~ Alt_mother,
          ratio_Ref_mother <= nipat_cfg$homozygous_alt_max ~ Ref_mother,
          TRUE ~ NA_real_
        ),
        fetal_fraction_site = 2*fetal_reads/(Ref_mother+Alt_mother)
      ) %>% filter(!is.na(fetal_fraction_site), fetal_fraction_site > 0, fetal_reads >= min_fetal_reads)

    n_sites_mother <- nrow(madre_cutoff)

    ## Maternal keys are already limited to the panel. Joining the original
    ## father table therefore selects the same paternal rows (and duplicates)
    ## in the same order, without applying that panel a second time.
    df_merge_tmp <- inner_join(madre_cutoff, padre, by=site_columns) %>%
      mutate(threshold = case_when(
        ratio_Ref_mother >= nipat_cfg$homozygous_ref_min & Alt_father >= 0 ~ "informative",
        ratio_Ref_mother <= nipat_cfg$homozygous_alt_max & Ref_father >= 0 ~ "informative",
        TRUE ~ "non informative"
      ))

    n_sites_father <- sum(df_merge_tmp$threshold=="informative")


    median_fetal_fraction <- suppressWarnings(median(madre_cutoff$fetal_fraction_site, na.rm=TRUE))

    all_cpi_vals <- res$log_CPI[!is.na(res$log_CPI)]

    max_cpi <- ifelse(length(all_cpi_vals)==0, NA, max(all_cpi_vals))
    min_cpi <- ifelse(length(all_cpi_vals)==0, NA, min(all_cpi_vals))
    med_cpi <- ifelse(length(all_cpi_vals)==0, NA, median(all_cpi_vals))
    mean_cpi <- ifelse(length(all_cpi_vals)==0, NA, mean(all_cpi_vals))

    if (has_cutoffs) {
      summary_row <- data.frame(
        Pair = pair_name,
        Cutoff = cutoff_label,
        N_sites_mother = n_sites_mother,
        N_sites_father = n_sites_father,
        Median_fetal_fraction_raw = round(median_fetal_fraction,4),
        Median_fetal_fraction_percent = round(median_fetal_fraction*100,2),
        Max_logCPI = round(max_cpi,3),
        Min_logCPI = round(min_cpi,3),
        Median_logCPI = round(med_cpi,3),
        Mean_logCPI = round(mean_cpi,3),
        CPI_medianFF = round(cpi_at_med,3),
        Error_constant = err_const, Min_fetal_reads = min_fetal_reads, Marker_type = marker
      )
    } else {
      summary_row <- data.frame(
        Pair = pair_name,
        N_sites_mother = n_sites_mother,
        N_sites_father = n_sites_father,
        Median_fetal_fraction_raw = round(median_fetal_fraction,4),
        Median_fetal_fraction_percent = round(median_fetal_fraction*100,2),
        Max_logCPI = round(max_cpi,3),
        Min_logCPI = round(min_cpi,3),
        Median_logCPI = round(med_cpi,3),
        Mean_logCPI = round(mean_cpi,3),
        CPI_medianFF = round(cpi_at_med,3),
        Error_constant = err_const, Min_fetal_reads = min_fetal_reads, Marker_type = marker
      )
    }
    list(label = cutoff_label, plot_data = res, summary = summary_row,
         cfDNA_percent = cfDNA_percent, cpi_at_med = cpi_at_med, median_reads=target_i)
  }, label = "cpi-cutoffs")
  list(pair_name = pair_name, cutoffs = cutoff_results)
}

pair_results <- nipat_parallel_lapply(seq_len(nrow(coppie)), process_pair,
                                    label = "cpi-pairs")
for (i in seq_along(pair_results)) {
  pair_result <- pair_results[[i]]
  pair_name <- pair_result$pair_name
  per_cutoff_plots <- list()
  for (k in seq_along(pair_result$cutoffs)) {
    cutoff_result <- pair_result$cutoffs[[k]]
    per_cutoff_plots[[cutoff_result$label]] <- plot_CPI(
      cutoff_result$plot_data, cutoff_result$label, pair_name,
      cfDNA_percent = cutoff_result$cfDNA_percent,
      cpi_medff = cutoff_result$cpi_at_med, median_reads=cutoff_result$median_reads)
    curve_dir <- file.path(args$out_dir, "curves")
    dir.create(curve_dir, showWarnings=FALSE)
    write.table(cutoff_result$plot_data,
      file.path(curve_dir, paste0(pair_name, "_panel_", k, ".tsv")),
      sep="\t", quote=FALSE, row.names=FALSE, na="NA")
    summary_index <- (i - 1L) * nrow(cutoff_df) + k
    fetal_fraction_rows[[summary_index]] <- cutoff_result$summary
  }

  ## save combined plots in plots_dir
  if (length(per_cutoff_plots)>0) {
    combined <- nipat_cpi_pages(per_cutoff_plots[names(per_cutoff_plots)])
    ggsave(file.path(plots_dir, paste0(pair_name,"_CPIplot.pdf")),
           plot=combined, width=12, height=10)
    all_combined_plots <- c(all_combined_plots, unname(per_cutoff_plots))
  }

}

## save single big pdf with all pairs
if (length(all_combined_plots)>0) {
  final_plot <- nipat_cpi_pages(all_combined_plots)
  ggsave(file.path(plots_dir, "All_CPIplots.pdf"),
         plot=final_plot, width=12, height=10)
}

fetal_fraction_summary <- do.call(rbind, fetal_fraction_rows)
write.csv(
  fetal_fraction_summary,
  file.path(args$out_dir, "Summary_FetalFraction_CPI.csv"),
  row.names = FALSE
)

message("done: all summaries and plots saved.")
