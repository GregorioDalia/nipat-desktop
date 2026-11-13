#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(readxl)
  library(ggplot2)
  library(patchwork)
  library(argparse)
  library(stringr)
  library(tidyr)
})

## cli parser
parser <- ArgumentParser()

parser$add_argument("--pileup_dir",    required=TRUE)
parser$add_argument("--out_dir",       required=TRUE)
parser$add_argument("--pairs",         required=TRUE)
parser$add_argument("--mother_prefix", required=TRUE)
parser$add_argument("--father_prefix", required=TRUE)
parser$add_argument("--popfreq",       required=TRUE)
parser$add_argument("--markers",       required=FALSE,
                    help="Optional marker list; if omitted use all calling-output sites")

## Marker-specific mismatch constants.
parser$add_argument("--err_const_snp", default="0.001",
                    help="SNP mismatch constant [default: %(default)s]")
parser$add_argument("--err_const_dnp", default="0.0000892303778101497",
                    help="DNP mismatch constant [default: %(default)s]")

parser$add_argument("--min_fetal_reads", type="double", default=2,
                    help="Minimum minor-allele read support [default: %(default)s]")

args <- parser$parse_args()
min_fetal_reads <- args$min_fetal_reads
if (length(min_fetal_reads) != 1L || !is.finite(min_fetal_reads) ||
    min_fetal_reads < 1 || min_fetal_reads != floor(min_fetal_reads) ||
    min_fetal_reads > .Machine$integer.max) {
  stop("--min_fetal_reads must be a positive integer")
}
min_fetal_reads <- as.integer(min_fetal_reads)
message("Minimum fetal-read support: ", min_fetal_reads)

## make output dirs
if (!dir.exists(args$out_dir)) dir.create(args$out_dir, recursive = TRUE, showWarnings = FALSE)
plots_dir <- file.path(args$out_dir, "plots")
if (!dir.exists(plots_dir)) dir.create(plots_dir, recursive = TRUE, showWarnings = FALSE)

## parse pairs
pairs_vec <- strsplit(args$pairs, ",")[[1]] |> trimws()
coppie <- do.call(rbind, lapply(pairs_vec, function(x){
  sp <- strsplit(x, ":", fixed=TRUE)[[1]] |> trimws()
  data.frame(mamma=sp[1], papa=sp[2])
}))
rownames(coppie) <- NULL

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

## helper: compute fetal_reads on mother dataframe
## note: this mirrors the logic used in cpi iteration
compute_madre_info <- function(madre_df) {
  madre_df %>%
    dplyr::filter(
      (ratio_Ref_mother >= 0.9 & Alt_mother >= min_fetal_reads) |
        (ratio_Ref_mother <= 0.1 & Ref_mother >= min_fetal_reads)
    ) %>%
    dplyr::mutate(
      fetal_reads = ifelse(ratio_Ref_mother >= 0.9, Alt_mother, Ref_mother)
    )
}

## Compute CPI across minor-allele read thresholds.
run_CPI_iteration <- function(madre, padre, err_const) {
  madre_info <- compute_madre_info(madre)
  max_fetal <- suppressWarnings(max(madre_info$fetal_reads, na.rm=TRUE))
  if (!is.finite(max_fetal) || max_fetal < min_fetal_reads)
    return(list(results=data.frame(), madre_info=madre_info))

  results <- data.frame()
  for (i in seq.int(min_fetal_reads, max_fetal)) {
    madre_filt <- madre_info %>% dplyr::filter(fetal_reads >= i)

    df_merged <- dplyr::inner_join(madre_filt, padre, by=site_columns) %>%
      dplyr::mutate(threshold = dplyr::case_when(
        ratio_Ref_mother >= 0.9 & Alt_father >= 0 ~ "informative",
        ratio_Ref_mother <= 0.1 & Ref_father >= 0 ~ "informative",
        TRUE ~ "non informative"
      )) %>%
      dplyr::inner_join(PopFreqDNPs, by=site_columns) %>%
      dplyr::mutate(dplyr::across(c(Ref_f.pop,Alt_f.pop), as.numeric))

    PI <- df_merged %>% dplyr::filter(threshold=="informative") %>%
      dplyr::mutate(Paternity_Index = dplyr::case_when(
        ratio_Ref_mother >= 0.9 & ratio_Ref_father <= 0.1 ~ 1/Alt_f.pop,
        ratio_Ref_mother >= 0.9 & between(ratio_Ref_father,0.4,0.6) ~ 0.5/Alt_f.pop,
        ratio_Ref_mother >= 0.9 & ratio_Ref_father >= 0.9 ~ err_const/Alt_f.pop,
        ratio_Ref_mother <= 0.1 & ratio_Ref_father <= 0.1 ~ err_const/Ref_f.pop,
        ratio_Ref_mother <= 0.1 & between(ratio_Ref_father,0.4,0.6) ~ 0.5/Ref_f.pop,
        ratio_Ref_mother <= 0.1 & ratio_Ref_father >= 0.9 ~ 1/Ref_f.pop,
        TRUE ~ NA_real_
      )) %>% tidyr::drop_na()

    CPI_val <- ifelse(nrow(PI)>0, prod(PI$Paternity_Index, na.rm=TRUE), NA_real_)
    logCPI  <- ifelse(!is.na(CPI_val) & CPI_val>0, log10(CPI_val), NA_real_)

    mismatch_summary <- df_merged %>% dplyr::filter(threshold=="informative") %>%
      summarise(
        Mismatch = sum((ratio_Ref_mother>=0.9 & ratio_Ref_father>=0.9) |
                         (ratio_Ref_mother<=0.1 & ratio_Ref_father<=0.1)),
        NotMismatch = n() - Mismatch
      )

    results <- rbind(results, data.frame(
      Iteration=i,
      InfSites_mother=nrow(madre_filt),
      InfSites_father=nrow(PI),
      CPI=CPI_val,
      log_CPI=logCPI,
      Mismatch=mismatch_summary$Mismatch,
      NotMismatch=mismatch_summary$NotMismatch
    ))
  }
  return(list(results=results, madre_info=madre_info))
}

## get logCPI at iteration closest to target (median fetal reads)
closest_logCPI <- function(res_df, target_i) {
  if (nrow(res_df)==0 || is.na(target_i) || !is.finite(target_i)) return(NA_real_)
  idx <- which.min(abs(res_df$Iteration - target_i))
  res_df$log_CPI[idx]
}

plot_CPI <- function(df, pair_name,
                     cfDNA_percent = NA_real_,
                     cpi_medff = NA_real_,
                     median_reads = NA_real_) {

  if (nrow(df) == 0) {
    return(
      ggplot() +
        theme_void() +
        labs(title = paste(pair_name, "(no data)"))
    )
  }

  # Use the same nearest iteration as closest_logCPI().
  median_threshold <- if (length(median_reads) == 1L && is.finite(median_reads)) {
    df$Iteration[which.min(abs(df$Iteration - median_reads))]
  } else {
    numeric()
  }

  max_iter <- max(df$Iteration, na.rm = TRUE)

  step <- if (max_iter <= 20) 1 else if (max_iter <= 100) 10 else if (max_iter <= 500) 25 else 50
  ticks <- unique(c(min_fetal_reads,
                    seq(min_fetal_reads, max_iter, by=step), max_iter))

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

  ggplot(df, aes(x = Iteration)) +
    annotate("rect", xmin = -Inf, xmax = Inf,
             ymin = -Inf, ymax = -4, fill = "red", alpha = 0.05) +
    annotate("rect", xmin = -Inf, xmax = Inf,
             ymin = -4, ymax = 4, fill = "grey", alpha = 0.05) +
    annotate("rect", xmin = -Inf, xmax = Inf,
             ymin = 4, ymax = Inf, fill = "green", alpha = 0.05) +

    geom_vline(xintercept = median_threshold, colour = "red",
               linetype = "dashed", linewidth = 0.6,
               show.legend = FALSE) +
    geom_line(aes(y = log_CPI), colour = "black") +
    geom_point(aes(y = log_CPI), colour = "black", size = 1.3) +
    geom_line(aes(y = NotMismatch), colour = "green") +
    geom_line(aes(y = Mismatch), colour = "orange",
              linetype = "dashed") +

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
      sec.axis = sec_axis(~ ., name = "Matching / mismatching sites"),
      expand = expansion(mult = c(0.02, 0.14))
    ) +

    scale_x_continuous(
      name = "minimum number of fetal reads considered",
      breaks = ticks,
      limits = c(min_fetal_reads, max(min_fetal_reads + 1, max_iter)),
      expand = expansion(mult = c(0.02, 0.02))
    ) +

    labs(title = pair_name) +

    theme_bw(base_size = 9) +
    theme(
      plot.title = element_text(size = 9, hjust = 0),
      axis.title = element_text(size = 8),
      axis.text.x = element_text(angle = 45, hjust = 1, size = 7),
      panel.border = element_rect(
        colour = "black", fill = NA, linewidth = 0.6
      ),
      plot.margin = margin(8, 12, 8, 8)
    )
}

# Each pair is read, filtered and analysed once.
fetal_fraction_summary <- data.frame()
all_combined_plots <- list()

for (i in seq_len(nrow(coppie))) {
  mamma_id <- coppie$mamma[i]
  papa_id  <- coppie$papa[i]
  pair_name <- paste0("Mother", mamma_id, "-Father", papa_id, "_", marker, "s")

  mother_path <- file.path(args$pileup_dir, paste0(args$mother_prefix, mamma_id, ".txt"))
  father_path <- file.path(args$pileup_dir, paste0(args$father_prefix, papa_id, ".txt"))

  madre <- read_calls(mother_path)
  padre <- read_calls(father_path)
  check_pair(madre, padre)

  madre$chr <- as.character(madre$chr)
  padre$chr <- as.character(padre$chr)

  madre <- madre %>%
    dplyr::transmute(
      dplyr::across(dplyr::all_of(site_columns)), REF, ALT,
      Ref_mother = N_REF,
      Alt_mother = N_ALT,
      Error_mother = N_Other,
      ratio_Ref_mother = N_REF / (N_REF + N_ALT),
      total_count = total_count
    )

  padre <- padre %>%
    dplyr::transmute(
      dplyr::across(dplyr::all_of(site_columns)), REF, ALT,
      Ref_father = N_REF,
      Alt_father = N_ALT,
      Error_father = N_Other,
      ratio_Ref_father = N_REF / (N_REF + N_ALT),
      total_count = total_count
    )

  madre <- madre %>% dplyr::filter(Error_mother/total_count <= 0.10)
  padre <- padre %>%
    dplyr::mutate(
      Ref_father = ifelse(ratio_Ref_father < 0.1, 0, Ref_father),
      Alt_father = ifelse(ratio_Ref_father > 0.9, 0, Alt_father)
    ) %>% dplyr::filter(Error_father/total_count <= 0.10)


  out <- run_CPI_iteration(madre, padre, err_const)
  res <- out$results
  info <- out$madre_info
  target_i <- round(stats::median(info$fetal_reads, na.rm=TRUE))
  cpi_at_med <- closest_logCPI(res, target_i)
  median_fetal_fraction <- stats::median(
    2 * info$fetal_reads / (info$Ref_mother + info$Alt_mother),
    na.rm=TRUE
  )

  # Count paternal sites using the same rule as the previous summary.
  shared <- dplyr::inner_join(info, padre, by=site_columns)
  n_sites_father <- sum(
    (shared$ratio_Ref_mother >= 0.9 & shared$Alt_father >= 0) |
    (shared$ratio_Ref_mother <= 0.1 & shared$Ref_father >= 0)
  )

  values <- if (nrow(res)) res$log_CPI[!is.na(res$log_CPI)] else numeric()
  fetal_fraction_summary <- rbind(fetal_fraction_summary, data.frame(
    Pair = pair_name,
    N_sites_mother = nrow(info),
    N_sites_father = n_sites_father,
    Median_fetal_fraction_raw = round(median_fetal_fraction, 4),
    Median_fetal_fraction_percent = round(100 * median_fetal_fraction, 2),
    Max_logCPI = if (length(values)) round(max(values), 3) else NA_real_,
    Min_logCPI = if (length(values)) round(min(values), 3) else NA_real_,
    Median_logCPI = if (length(values)) round(stats::median(values), 3) else NA_real_,
    Mean_logCPI = if (length(values)) round(mean(values), 3) else NA_real_,
    CPI_medianFF = round(cpi_at_med, 3),
    Error_constant = err_const
  ))

  plot <- plot_CPI(res, pair_name,
                   cfDNA_percent=100 * median_fetal_fraction,
                   cpi_medff=cpi_at_med,
                   median_reads=target_i)
  ggsave(file.path(plots_dir, paste0(pair_name, "_CPIplot.pdf")),
         plot=plot, width=12, height=4)
  all_combined_plots[[pair_name]] <- plot
}

if (length(all_combined_plots)) {
  final_plot <- patchwork::wrap_plots(all_combined_plots, ncol=1)
  ggsave(file.path(plots_dir, "All_CPIplots.pdf"), plot=final_plot,
         width=12, height=4 * length(all_combined_plots), limitsize=FALSE)
}

write.csv(fetal_fraction_summary,
          file.path(args$out_dir, "Summary_FetalFraction_CPI.csv"),
          row.names=FALSE)
message("done: all summaries and plots saved.")

