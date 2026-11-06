#!/usr/bin/env Rscript
# Compare complete CPI threshold results with the frozen 0.8.5 implementation.
# Usage: Rscript tests/r_optimization/cpi/check_core.R /path/to/repository
suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
})

arguments <- commandArgs(trailingOnly=TRUE)
if (length(arguments) != 1L) stop("Expected one repository root argument")
repository <- normalizePath(arguments[[1]], mustWork=TRUE)
relative_script <- "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R"

load_core <- function(path) {
  environment <- new.env(parent=globalenv())
  wanted <- c("compute_madre_info", "run_CPI_iteration")
  found <- character()
  for (expression in parse(path)) {
    if (is.call(expression) && identical(expression[[1]], as.name("<-")) &&
        is.symbol(expression[[2]]) && as.character(expression[[2]]) %in% wanted) {
      eval(expression, envir=environment)
      found <- c(found, as.character(expression[[2]]))
    }
  }
  if (!setequal(found, wanted)) stop("CPI core definitions not found: ", path)
  environment
}

reference <- load_core(file.path(repository, "tests/reference_r/0.8.5", relative_script))
candidate <- load_core(file.path(repository, relative_script))

make_case <- function(fetal_reads=c(2, 3, 4, 7, 20, 2, 3, 4, 7, 20),
                      father_ratio=c(0, .1, .4, .5, .6, .9, 1, .2, .3, .5),
                      maternal_high=rep(c(TRUE, FALSE), length.out=length(fetal_reads))) {
  n <- length(fetal_reads)
  positions <- seq_len(n) * 10L
  coordinates <- data.frame(chr=rep("chr1", n), pos1=positions, pos2=positions+1L)
  ref <- ifelse(maternal_high, 9*fetal_reads, fetal_reads)
  alt <- ifelse(maternal_high, fetal_reads, 9*fetal_reads)
  mother <- cbind(coordinates, data.frame(
    REF=rep("AA", n), ALT=rep("GG", n), Ref_mother=ref, Alt_mother=alt,
    Error_mother=rep(0, n), ratio_Ref_mother=ref/(ref+alt), total_count=ref+alt
  ))
  ratios <- rep(father_ratio, length.out=n)
  father <- cbind(coordinates, data.frame(
    REF=rep("AA", n), ALT=rep("GG", n), Ref_father=100*ratios,
    Alt_father=100*(1-ratios), Error_father=rep(0, n),
    ratio_Ref_father=ratios, total_count=rep(100, n)
  ))
  population <- cbind(coordinates, data.frame(
    Ref_f.pop=rep(.75, n), Alt_f.pop=rep(.25, n)
  ))
  list(mother=mother, father=father, population=population,
       err_const=.0000892303778101497)
}

cases <- list(boundaries_and_unclassified=make_case())
cases$long_threshold_gaps <- make_case(
  fetal_reads=c(2, 7, 101), father_ratio=c(.5, .1, .9),
  maternal_high=c(TRUE, FALSE, TRUE)
)
cases$missing_population_sites <- make_case()
cases$missing_population_sites$population <- cases$missing_population_sites$population[-c(2, 6), ]
cases$population_metadata_na <- make_case()
cases$population_metadata_na$population$metadata <- c(NA, rep("present", 9))
cases$fetal_reads_column_collision <- make_case()
cases$fetal_reads_column_collision$population$fetal_reads <- c(NA, rep(1, 9))
cases$internal_column_collision <- make_case()
cases$internal_column_collision$population$.nipat_cpi_maternal_row <- seq_len(10)
cases$internal_column_collision$population$.nipat_cpi_maternal_row_ <- c(NA, rep(1, 9))
cases$zero_error_constant <- make_case()
cases$zero_error_constant$err_const <- 0
cases$missing_father_ratio <- make_case()
cases$missing_father_ratio$father$ratio_Ref_father[c(1, 4)] <- NA_real_
cases$missing_father_metadata <- make_case()
cases$missing_father_metadata$father$ALT[3] <- NA_character_
cases$missing_maternal_metadata <- make_case()
cases$missing_maternal_metadata$mother$REF[4] <- NA_character_
cases$no_informative_sites <- make_case()
cases$no_informative_sites$mother$ratio_Ref_mother <- rep(.5, 10)
cases$no_father_matches <- make_case()
cases$no_father_matches$father <- cases$no_father_matches$father[FALSE, ]
cases$no_population_matches <- make_case()
cases$no_population_matches$population <- cases$no_population_matches$population[FALSE, ]
cases$duplicate_rows_and_order <- make_case()
cases$duplicate_rows_and_order$mother <- cases$duplicate_rows_and_order$mother[c(6, 1, 1, 5, 2, 10), ]
cases$duplicate_rows_and_order$father <- cases$duplicate_rows_and_order$father[c(5, 1, 1, 6, 2, 10), ]
cases$duplicate_rows_and_order$population <- cases$duplicate_rows_and_order$population[c(6, 1, 5, 1, 2, 10), ]
cases$infinite_product <- make_case(rep(2, 1100), father_ratio=0,
                                   maternal_high=rep(TRUE, 1100))
cases$infinite_product$population$Alt_f.pop <- rep(.5, 1100)
cases$underflow_product <- make_case(rep(2, 1100), father_ratio=.5,
                                    maternal_high=rep(TRUE, 1100))
cases$underflow_product$population$Alt_f.pop <- rep(1, 1100)
cases$zero_and_infinite_product <- make_case(c(2, 2), father_ratio=c(1, 0),
                                           maternal_high=c(TRUE, TRUE))
cases$zero_and_infinite_product$population$Alt_f.pop <- c(.5, 0)
cases$zero_and_infinite_product$err_const <- 0
cases$all_missing_pi <- make_case(father_ratio=.2)

comparisons <- 0L
for (case_name in names(cases)) {
  case <- cases[[case_name]]
  reference$PopFreqDNPs <- case$population
  candidate$PopFreqDNPs <- case$population
  coordinates <- case$mother[, c("chr", "pos1", "pos2"), drop=FALSE]
  panels <- list(ALL=NULL, subset=coordinates[seq_len(nrow(coordinates)) %% 2L == 0L, , drop=FALSE],
                 empty=coordinates[FALSE, , drop=FALSE])
  for (panel_name in names(panels)) {
    parameters <- list(case$mother, case$father, panels[[panel_name]],
                       panel_name, case$err_const)
    expected <- suppressWarnings(do.call(reference$run_CPI_iteration, parameters))
    actual <- suppressWarnings(do.call(candidate$run_CPI_iteration, parameters))
    if (!identical(expected, actual)) {
      difference <- paste(capture.output(all.equal(expected, actual)), collapse="\n")
      stop("CPI core mismatch: ", case_name, " / ", panel_name, "\n", difference)
    }
    comparisons <- comparisons + 1L
  }
  cat("PASS CPI core:", case_name, "(ALL, subset, empty)\n")
}
cat("PASS CPI core:", comparisons, "strict comparisons including every threshold and madre_info\n")
