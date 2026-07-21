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

  results <- data.frame()
  for (i in 2:max_fetal) {
    madre_filt <- madre_info %>% dplyr::filter(fetal_reads >= i)

    df_merged <- dplyr::inner_join(madre_filt, padre, by=c("chr","pos1","pos2")) %>%
      dplyr::mutate(threshold = dplyr::case_when(
        ratio_Ref_mother >= 0.9 & Alt_father >= 0 ~ "informative",
        ratio_Ref_mother <= 0.1 & Ref_father >= 0 ~ "informative",
        TRUE ~ "non informative"
      )) %>%
      dplyr::inner_join(PopFreqDNPs, by=c("chr","pos1","pos2")) %>%
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
      NotMismatch=mismatch_summary$NotMismatch,
      Cutoff=cutoff_label
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

plot_CPI <- function(df, cutoff_label, pair_name) {

  if (nrow(df)==0) {
    return(ggplot() + ggtitle(paste(pair_name,"-",cutoff_label,"(no data)")))
  }

  max_iter <- suppressWarnings(max(df$Iteration,na.rm=TRUE)); if(!is.finite(max_iter)) max_iter <- 2
  range_len <- max_iter - 2
  tick_step <- if (range_len <= 20) 1 else if (range_len <= 100) 20 else if (range_len <= 500) 50 else 100
  tick_vals <- sort(unique(c(2, seq(from=max(2,tick_step), to=max_iter, by=tick_step))))

  ggplot(df, aes(x=Iteration)) +
    annotate("rect", xmin=-Inf, xmax=Inf, ymin=-Inf, ymax=-4,
             fill="red", alpha=0.05) +
    annotate("rect", xmin=-Inf, xmax=Inf, ymin=-4, ymax=4,
             fill="grey", alpha=0.05) +
    annotate("rect", xmin=-Inf, xmax=Inf, ymin=4, ymax=Inf,
             fill="green", alpha=0.05) +

    geom_line(aes(y=log_CPI), color="black") +
    geom_point(aes(y=log_CPI), color="black", size=1.5) +
    geom_line(aes(y=NotMismatch), color="green") +
    geom_line(aes(y=Mismatch), color="orange", linetype="dashed") +

    scale_y_continuous(name="log10(CPI)",
                       sec.axis=sec_axis(~ ., name="match / mismatch sites")) +
    scale_x_continuous(name="minimum number of fetal reads considered",
                       limits=c(2,max_iter), breaks=tick_vals) +
    labs(title=paste(pair_name,"-",cutoff_label)) +
    theme_bw(base_size=9) +
    theme(plot.title=element_text(size=9),
          axis.title=element_text(size=8))
}


## main containers
summary_table <- data.frame()
all_combined_plots <- list()

for (i in 1:nrow(coppie)) {
  mamma_id <- coppie$mamma[i]
  papa_id  <- coppie$papa[i]
  pair_name <- paste0("Mother", mamma_id, "-Father", papa_id, "_DNPs")

  mother_path <- file.path(args$pileup_dir, paste0(args$mother_prefix, mamma_id, ".txt"))
  father_path <- file.path(args$pileup_dir, paste0(args$father_prefix, papa_id, ".txt"))

  madre <- read.table(mother_path, header=TRUE, check.names=FALSE)
  padre <- read.table(father_path, header=TRUE, check.names=FALSE)

  madre$chr <- as.character(madre$chr)
  padre$chr <- as.character(padre$chr)

  madre <- madre %>%
    dplyr::transmute(
      chr, pos1, pos2, REF, ALT,
      Ref_mother = N_REF,
      Alt_mother = N_ALT,
      Error_mother = N_Other,
      ratio_Ref_mother = N_REF / (N_REF + N_ALT),
      total_count = total_count
    )

  padre <- padre %>%
    dplyr::transmute(
      chr, pos1, pos2, REF, ALT,
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

  per_cutoff_results <- list()
  per_cutoff_plots   <- list()
  per_cutoff_CPI_medreads <- c()

  for (k in seq_len(nrow(cutoff_df))) {
    cutoff_label <- cutoff_df$Cutoff[k]
    dnp_list <- if (!is.na(cutoff_df$Path[k])) read.table(cutoff_df$Path[k], header=TRUE, sep="\t", stringsAsFactors=FALSE) else NULL

    out <- run_CPI_iteration(madre, padre, dnp_list, cutoff_label, err_const)
    res <- out$results
    per_cutoff_results[[cutoff_label]] <- res

    target_i <- out$madre_info %>% dplyr::pull(fetal_reads) %>%
      stats::median(na.rm=TRUE) %>% round()
    per_cutoff_CPI_medreads <- c(per_cutoff_CPI_medreads,
                                 closest_logCPI(res, target_i))

    per_cutoff_plots[[cutoff_label]] <- plot_CPI(res, cutoff_label, pair_name)
  }

  ## save combined plots in plots_dir
  if (length(per_cutoff_plots)>0) {
    combined <- Reduce(`+`, per_cutoff_plots[names(per_cutoff_plots)]) +
      patchwork::plot_layout(ncol=length(per_cutoff_plots))
    ggsave(file.path(plots_dir, paste0(pair_name,"_CPIplot.pdf")),
           plot=combined, width=max(12,4*length(per_cutoff_plots)), height=4)
    all_combined_plots[[pair_name]] <- combined
  }

  ## build first summary row
  all_res <- dplyr::bind_rows(per_cutoff_results)
  all_res$log_CPI <- as.numeric(all_res$log_CPI)

  summary_table <- rbind(summary_table, data.frame(
    Pair = pair_name,
    Mother_sites_max = suppressWarnings(max(all_res$InfSites_mother, na.rm=TRUE)),
    Father_sites_max = suppressWarnings(max(all_res$InfSites_father, na.rm=TRUE)),
    Max_logCPI = suppressWarnings(round(max(all_res$log_CPI, na.rm=TRUE),3)),
    Min_logCPI = suppressWarnings(round(min(all_res$log_CPI, na.rm=TRUE),3)),
    Median_logCPI = suppressWarnings(round(stats::median(all_res$log_CPI, na.rm=TRUE),3)),
    CPI_medianFF = suppressWarnings(round(stats::median(per_cutoff_CPI_medreads, na.rm=TRUE),3))
  ))

}

## save single big pdf with all pairs
if (length(all_combined_plots)>0) {
  final_plot <- wrap_plots(all_combined_plots, ncol=1)
  ggsave(file.path(plots_dir, "All_CPIplots.pdf"),
         plot=final_plot, width=12, height=4*length(all_combined_plots), limitsize=FALSE)
}


## fetal fraction + cpi summaries (cutoff or ALL)
fetal_fraction_summary <- data.frame()

for (i in 1:nrow(coppie)) {
  mamma_id <- coppie$mamma[i]
  papa_id  <- coppie$papa[i]
  pair_name <- paste0("Mother", mamma_id, "-Father", papa_id, "_DNPs")

  mother_path <- file.path(args$pileup_dir, paste0(args$mother_prefix, mamma_id, ".txt"))
  father_path <- file.path(args$pileup_dir, paste0(args$father_prefix, papa_id, ".txt"))

  madre <- read.table(mother_path, header=TRUE, check.names=FALSE)
  padre <- read.table(father_path, header=TRUE, check.names=FALSE)

madre$chr <- as.character(madre$chr)
padre$chr <- as.character(padre$chr)

madre <- madre %>%
  dplyr::transmute(
    chr, pos1, pos2, REF, ALT,
    Ref_mother = N_REF,
    Alt_mother = N_ALT,
    Error_mother = N_Other,
    ratio_Ref_mother = N_REF / (N_REF + N_ALT),
    total_count = total_count
  )

padre <- padre %>%
  dplyr::transmute(
    chr, pos1, pos2, REF, ALT,
    Ref_father = N_REF,
    Alt_father = N_ALT,
    Error_father = N_Other,
    ratio_Ref_father = N_REF / (N_REF + N_ALT),
    total_count = total_count
  )

  madre <- madre %>% filter(Error_mother/total_count <= 0.10)
  padre <- padre %>%
    mutate(
      Ref_father = ifelse(ratio_Ref_father < 0.1,0,Ref_father),
      Alt_father = ifelse(ratio_Ref_father > 0.9,0,Alt_father)
    ) %>% filter(Error_father/total_count <= 0.10)

  for (k in seq_len(nrow(cutoff_df))) {
    cutoff_label <- cutoff_df$Cutoff[k]
    dnp_list <- if (!is.na(cutoff_df$Path[k])) read.table(cutoff_df$Path[k], header=TRUE, sep="\t", stringsAsFactors=FALSE) else NULL

    madre_cutoff <- if (!is.null(dnp_list)) madre %>% semi_join(dnp_list, by=c("chr","pos1","pos2")) else madre
    padre_cutoff <- if (!is.null(dnp_list)) padre %>% semi_join(dnp_list, by=c("chr","pos1","pos2")) else padre

    madre_cutoff <- madre_cutoff %>%
      mutate(
        fetal_reads = case_when(
          ratio_Ref_mother >= 0.9 ~ Alt_mother,
          ratio_Ref_mother <= 0.1 ~ Ref_mother,
          TRUE ~ NA_real_
        ),
        fetal_fraction_site = 2*fetal_reads/(Ref_mother+Alt_mother)
      ) %>% filter(!is.na(fetal_fraction_site), fetal_fraction_site>0)

    n_sites_mother <- nrow(madre_cutoff)

    ## recalc father informative count after merge
    if (!is.null(dnp_list)) {
      padre_cut_tmp <- padre %>% semi_join(dnp_list, by=c("chr","pos1","pos2"))
    } else {
      padre_cut_tmp <- padre
    }

    df_merge_tmp <- inner_join(madre_cutoff, padre_cut_tmp, by=c("chr","pos1","pos2")) %>%
      mutate(threshold = case_when(
        ratio_Ref_mother >= 0.9 & Alt_father >= 0 ~ "informative",
        ratio_Ref_mother <= 0.1 & Ref_father >= 0 ~ "informative",
        TRUE ~ "non informative"
      ))

    n_sites_father <- sum(df_merge_tmp$threshold=="informative")


    median_fetal_fraction <- suppressWarnings(median(madre_cutoff$fetal_fraction_site, na.rm=TRUE))

    out <- run_CPI_iteration(madre, padre, dnp_list, cutoff_label, err_const)
    res <- out$results
    all_cpi_vals <- res$log_CPI[!is.na(res$log_CPI)]

    max_cpi <- ifelse(length(all_cpi_vals)==0, NA, max(all_cpi_vals))
    min_cpi <- ifelse(length(all_cpi_vals)==0, NA, min(all_cpi_vals))
    med_cpi <- ifelse(length(all_cpi_vals)==0, NA, median(all_cpi_vals))
    mean_cpi <- ifelse(length(all_cpi_vals)==0, NA, mean(all_cpi_vals))

    target_i <- out$madre_info %>% pull(fetal_reads) %>% median(na.rm=TRUE) %>% round()
    cpi_at_med <- closest_logCPI(res, target_i)

    if (has_cutoffs) {
      fetal_fraction_summary <- rbind(fetal_fraction_summary, data.frame(
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
      ))
    } else {
      fetal_fraction_summary <- rbind(fetal_fraction_summary, data.frame(
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
      ))
    }
  }
}

write.csv(
  fetal_fraction_summary,
  file.path(args$out_dir, "Summary_FetalFraction_CPI.csv"),
  row.names = FALSE
)

message("done: all summaries and plots saved.")
