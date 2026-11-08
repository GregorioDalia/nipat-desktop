#!/usr/bin/env Rscript
# NIPAT 0.8.9 modification, 2026-11-07: reuse invariant CPI calculations and
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

## cli parser
parser <- ArgumentParser()

parser$add_argument("--pileup_dir",    required=TRUE)
parser$add_argument("--out_dir",       required=TRUE)
parser$add_argument("--pairs",         required=TRUE)
parser$add_argument("--mother_prefix", required=TRUE)
parser$add_argument("--father_prefix", required=TRUE)
parser$add_argument("--popfreq",       required=TRUE)

## optional cutoff and err_const
parser$add_argument("--cutoff_map",    required=FALSE,
                    help='optional mapping "0.3=/abs/fileA.xlsx,0.5=/abs/fileB.xlsx". if missing use ALL sites')
parser$add_argument("--err_const",     default="0.0000892303778101497")

args <- parser$parse_args()
err_const <- as.numeric(args$err_const)

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

## parse cutoff map OR set to ALL mode
if (!is.null(args$cutoff_map) && nzchar(args$cutoff_map)) {

  items <- strsplit(args$cutoff_map, ",")[[1]] |> trimws()

  cutoff_list <- lapply(items, function(x){
    if (grepl("=", x)) {
      ## case: label=path
      kv <- strsplit(x, "=", fixed=TRUE)[[1]] |> trimws()
      if (length(kv) != 2) stop(paste0("invalid cutoff_map entry: ", x))
      list(Cutoff = kv[1], Path = kv[2])
    } else {
      ## case: only filename provided → use filename as label too
      list(Cutoff = x, Path = x)
    }
  })

  cutoff_df <- do.call(rbind, lapply(cutoff_list, as.data.frame))
  has_cutoffs <- TRUE

} else {
  cutoff_df <- data.frame(Cutoff="ALL", Path=NA_character_)
  has_cutoffs <- FALSE
}


## Panels are invariant across pairs and shared by plots and summaries.
cutoff_panels <- lapply(cutoff_df$Path, function(path) {
  if (is.na(path)) return(NULL)
  read.table(path, header=TRUE, sep="\t", stringsAsFactors=FALSE)
})

## check popfreq
if (!file.exists(args$popfreq)) stop("popfreq file not found")
PopFreqDNPs <- read.table(args$popfreq, header=TRUE, sep="\t", stringsAsFactors=FALSE)

# converto virgole in punti nelle due colonne di frequenza
PopFreqDNPs$Ref_f.pop <- as.numeric(gsub(",", ".", PopFreqDNPs$Ref_f.pop))
PopFreqDNPs$Alt_f.pop <- as.numeric(gsub(",", ".", PopFreqDNPs$Alt_f.pop))

## helper: compute fetal_reads on mother dataframe
## note: this mirrors the logic used in cpi iteration
compute_madre_info <- function(madre_df) {
  madre_df %>%
    dplyr::filter(
      (ratio_Ref_mother >= 0.9 & Alt_mother >= 2) |
        (ratio_Ref_mother <= 0.1 & Ref_mother >= 2)
    ) %>%
    dplyr::mutate(
      fetal_reads = ifelse(ratio_Ref_mother >= 0.9, Alt_mother, Ref_mother)
    )
}

## core: compute cpi for one list (or all sites if dnp_list is NULL)
run_CPI_iteration <- function(madre_df, padre_df, dnp_list, cutoff_label, err_const) {
  if (!is.null(dnp_list)) {
    madre <- madre_df %>% dplyr::semi_join(dnp_list, by=c("chr","pos1","pos2"))
    padre <- padre_df %>% dplyr::semi_join(dnp_list, by=c("chr","pos1","pos2"))
  } else {
    madre <- madre_df
    padre <- padre_df
  }

  madre_info <- compute_madre_info(madre)
  max_fetal <- suppressWarnings(max(madre_info$fetal_reads, na.rm=TRUE))
  if (!is.finite(max_fetal) || max_fetal < 2)
    return(list(results=data.frame(), madre_info=madre_info))

  ## Carry the maternal row identity through joins rather than relying on the
  ## joined fetal_reads name, which population metadata may also contain.
  row_id <- ".nipat_cpi_maternal_row"
  input_names <- c(names(madre_info), names(padre), names(PopFreqDNPs))
  while (row_id %in% input_names) row_id <- paste0(row_id, "_")
  madre_indexed <- madre_info
  madre_indexed[[row_id]] <- seq_len(nrow(madre_indexed))

  df_merged <- dplyr::inner_join(madre_indexed, padre, by=c("chr","pos1","pos2")) %>%
    dplyr::mutate(threshold = dplyr::case_when(
      ratio_Ref_mother >= 0.9 & Alt_father >= 0 ~ "informative",
      ratio_Ref_mother <= 0.1 & Ref_father >= 0 ~ "informative",
      TRUE ~ "non informative"
    )) %>%
    dplyr::inner_join(PopFreqDNPs, by=c("chr","pos1","pos2")) %>%
    dplyr::mutate(dplyr::across(c(Ref_f.pop,Alt_f.pop), as.numeric))

  informative_all <- df_merged %>% dplyr::filter(threshold=="informative")
  PI_all <- informative_all %>%
    dplyr::mutate(Paternity_Index = dplyr::case_when(
      ratio_Ref_mother >= 0.9 & ratio_Ref_father <= 0.1 ~ 1/Alt_f.pop,
      ratio_Ref_mother >= 0.9 & between(ratio_Ref_father,0.4,0.6) ~ 0.5/Alt_f.pop,
      ratio_Ref_mother >= 0.9 & ratio_Ref_father >= 0.9 ~ err_const/Alt_f.pop,
      ratio_Ref_mother <= 0.1 & ratio_Ref_father <= 0.1 ~ err_const/Ref_f.pop,
      ratio_Ref_mother <= 0.1 & between(ratio_Ref_father,0.4,0.6) ~ 0.5/Ref_f.pop,
      ratio_Ref_mother <= 0.1 & ratio_Ref_father >= 0.9 ~ 1/Ref_f.pop,
      TRUE ~ NA_real_
    )) %>% tidyr::drop_na()

  ## drop_na still covers all original columns, including population metadata.
  ## The added row identity is always present and has no missing values.
  pi_fetal_reads <- madre_info$fetal_reads[PI_all[[row_id]]]
  informative_fetal_reads <- madre_info$fetal_reads[informative_all[[row_id]]]
  mismatch <- (informative_all$ratio_Ref_mother >= 0.9 &
                 informative_all$ratio_Ref_father >= 0.9) |
    (informative_all$ratio_Ref_mother <= 0.1 &
       informative_all$ratio_Ref_father <= 0.1)

  iterations <- 2:max_fetal
  ## A locus with f fetal reads disappears at threshold floor(f) + 1.
  ## Since iteration 1 corresponds to threshold 2, that change has index
  ## floor(f). All joined rows originate from these maternal loci, so their
  ## PI and mismatch selections are constant between the same boundaries.
  ## Keep every threshold in the final table: its repetitions affect the
  ## summary statistics, median-threshold lookup and plots.
  interval_starts <- sort(unique(c(1L, floor(madre_info$fetal_reads))))
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
                     cpi_medff = NA_real_) {

  if (nrow(df) == 0) {
    return(
      ggplot() +
        theme_void() +
        labs(title = paste(pair_name, "-", cutoff_label, "(no data)"))
    )
  }

  max_iter <- max(df$Iteration, na.rm = TRUE)

  ticks <- if (max_iter <= 20) {
    2:max_iter
  } else if (max_iter <= 100) {
    unique(c(2, seq(10, max_iter, by = 10), max_iter))
  } else if (max_iter <= 500) {
    unique(c(2, seq(25, max_iter, by = 25), max_iter))
  } else {
    unique(c(2, seq(50, max_iter, by = 50), max_iter))
  }

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
      limits = c(2, max(3, max_iter)),
      expand = expansion(mult = c(0.02, 0.02))
    ) +

    labs(title = paste(pair_name, "-", cutoff_label)) +

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
  pair_name <- paste0("Mother", mamma_id, "-Father", papa_id, "_DNPs")

  mother_path <- file.path(args$pileup_dir, paste0(args$mother_prefix, mamma_id, ".txt"))
  father_path <- file.path(args$pileup_dir, paste0(args$father_prefix, papa_id, ".txt"))

  if (!identical(mother_path, pair_cache$mother_path)) {
    madre <- read.table(mother_path, header=TRUE, check.names=FALSE)
    madre$chr <- as.character(madre$chr)
    madre <- madre %>%
      dplyr::transmute(
        chr, pos1, pos2, REF, ALT,
        Ref_mother = N_REF,
        Alt_mother = N_ALT,
        Error_mother = N_Other,
        ratio_Ref_mother = N_REF / (N_REF + N_ALT),
        total_count = total_count
      ) %>% dplyr::filter(Error_mother/total_count <= 0.10)
    pair_cache$mother <- madre
    pair_cache$mother_path <- mother_path
  } else {
    madre <- pair_cache$mother
  }

  if (!identical(father_path, pair_cache$father_path)) {
    padre <- read.table(father_path, header=TRUE, check.names=FALSE)
    padre$chr <- as.character(padre$chr)
    padre <- padre %>%
      dplyr::transmute(
        chr, pos1, pos2, REF, ALT,
        Ref_father = N_REF,
        Alt_father = N_ALT,
        Error_father = N_Other,
        ratio_Ref_father = N_REF / (N_REF + N_ALT),
        total_count = total_count
      ) %>%
      dplyr::mutate(
        Ref_father = ifelse(ratio_Ref_father < 0.1, 0, Ref_father),
        Alt_father = ifelse(ratio_Ref_father > 0.9, 0, Alt_father)
      ) %>% dplyr::filter(Error_father/total_count <= 0.10)
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
          ratio_Ref_mother >= 0.9 ~ Alt_mother,
          ratio_Ref_mother <= 0.1 ~ Ref_mother,
          TRUE ~ NA_real_
        ),
        fetal_fraction_site = 2*fetal_reads/(Ref_mother+Alt_mother)
      ) %>% filter(!is.na(fetal_fraction_site), fetal_fraction_site > 0, fetal_reads >= 2)

    n_sites_mother <- nrow(madre_cutoff)

    ## Maternal keys are already limited to the panel. Joining the original
    ## father table therefore selects the same paternal rows (and duplicates)
    ## in the same order, without applying that panel a second time.
    df_merge_tmp <- inner_join(madre_cutoff, padre, by=c("chr","pos1","pos2")) %>%
      mutate(threshold = case_when(
        ratio_Ref_mother >= 0.9 & Alt_father >= 0 ~ "informative",
        ratio_Ref_mother <= 0.1 & Ref_father >= 0 ~ "informative",
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
        CPI_medianFF = round(cpi_at_med,3)
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
        CPI_medianFF = round(cpi_at_med,3)
      )
    }
    list(label = cutoff_label, plot_data = res, summary = summary_row,
         cfDNA_percent = cfDNA_percent, cpi_at_med = cpi_at_med)
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
      cpi_medff = cutoff_result$cpi_at_med)
    summary_index <- (i - 1L) * nrow(cutoff_df) + k
    fetal_fraction_rows[[summary_index]] <- cutoff_result$summary
  }

  ## save combined plots in plots_dir
  if (length(per_cutoff_plots)>0) {
    combined <- Reduce(`+`, per_cutoff_plots[names(per_cutoff_plots)]) +
      patchwork::plot_layout(ncol=length(per_cutoff_plots))
    ggsave(file.path(plots_dir, paste0(pair_name,"_CPIplot.pdf")),
           plot=combined, width=max(12,4*length(per_cutoff_plots)), height=4)
    all_combined_plots[[pair_name]] <- combined
  }

}

## save single big pdf with all pairs
if (length(all_combined_plots)>0) {
  final_plot <- wrap_plots(all_combined_plots, ncol=1)
  ggsave(file.path(plots_dir, "All_CPIplots.pdf"),
         plot=final_plot, width=12, height=4*length(all_combined_plots), limitsize=FALSE)
}

fetal_fraction_summary <- do.call(rbind, fetal_fraction_rows)
write.csv(
  fetal_fraction_summary,
  file.path(args$out_dir, "Summary_FetalFraction_CPI.csv"),
  row.names = FALSE
)

message("done: all summaries and plots saved.")
