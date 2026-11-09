#!/usr/bin/env Rscript
# Isolate cutoff/summary assembly with the same precomputed core result.
# No speed threshold; equality gates all measurements. Excludes file I/O,
# package loading, CPI core computation and plotting.
# Usage: Rscript benchmark_summary.R REPOSITORY PREVIOUS_CPI_SCRIPT OUTPUT_DIR
# Export PREVIOUS_CPI_SCRIPT with:
# git show d607f81850834b6fefad9fbd4f3543c27d8a57f9:scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R > /tmp/cpi-0.8.13.R
# This optional benchmark is not discovered by the check_*.R CI test glob.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) == 3L)
repository <- normalizePath(args[[1L]])
previous <- normalizePath(args[[2L]])
output <- args[[3L]]
if (dir.exists(output)) stop("Output directory already exists: ", output)
dir.create(output, recursive=TRUE)
output <- normalizePath(output)
if (!nzchar(Sys.which("sha256sum"))) stop("sha256sum is required for the input/output manifest")
suppressPackageStartupMessages({library(dplyr); library(tidyr)})
source(file.path(repository, "src/nipat_scientific/parallel.R"))
Sys.setenv(NIPAT_EXECUTION_MODE="serial", OPENBLAS_NUM_THREADS="1")
relative <- "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R"
paths <- c(`0.8.5`=file.path(repository, "tests/reference_r/0.8.5", relative),
           `0.8.13`=previous, candidate=file.path(repository, relative))
assigned <- function(x, name) is.call(x) && identical(x[[1L]], as.name("<-")) &&
  identical(x[[2L]], as.name(name))
loop <- function(x, variable) is.call(x) && identical(x[[1L]], as.name("for")) &&
  identical(x[[2L]], as.name(variable))
load_variant <- function(path, legacy=FALSE) {
  expressions <- parse(path)
  environment <- new.env(parent=globalenv())
  for (expression in expressions) {
    if (any(vapply(c("compute_madre_info", "run_CPI_iteration", "closest_logCPI"),
                   function(name) assigned(expression, name), logical(1)))) {
      eval(expression, environment)
    }
  }
  if (legacy) {
    outer <- Filter(function(x) loop(x, "i"), expressions)
    environment$loops <- lapply(outer, function(x) {
      found <- Filter(function(y) loop(y, "k"), as.list(x[[4L]]))
      stopifnot(length(found) == 1L)
      found[[1L]]
    })
    stopifnot(length(environment$loops) == 2L)
  } else {
    pair <- Filter(function(x) assigned(x, "process_pair"), expressions)[[1L]]
    cutoff <- Filter(function(x) assigned(x, "cutoff_results"), as.list(pair[[3L]][[3L]]))
    environment$task <- cutoff[[1L]][[3L]][[3L]]
  }
  environment
}
variants <- lapply(seq_along(paths), function(i) load_variant(paths[[i]], i == 1L))
names(variants) <- names(paths)
observations <- list()
for (n in c(5000L, 50000L)) {
  coordinates <- data.frame(chr="chr1", pos1=seq_len(n)*10L, pos2=seq_len(n)*10L+1L)
  fetal <- rep(2:5, length.out=n)
  mother <- cbind(coordinates, data.frame(REF="AA", ALT="GG", Ref_mother=9*fetal,
    Alt_mother=fetal, Error_mother=0, ratio_Ref_mother=.9, total_count=10*fetal))
  father <- cbind(coordinates, data.frame(REF="AA", ALT="GG", Ref_father=50,
    Alt_father=50, Error_father=0, ratio_Ref_father=.5, total_count=100))
  population <- cbind(coordinates, data.frame(Ref_f.pop=.75, Alt_f.pop=.25))
  for (selection in c("ALL", "full", "tenth")) {
    panel <- switch(selection, ALL=NULL, full=coordinates,
                    tenth=coordinates[seq_len(n) %% 10L == 0L, , drop=FALSE])
    inputs <- list(mother=mother, father=father, population=population, panel=panel)
    case_name <- paste(n, selection, sep="-")
    saveRDS(inputs, file.path(output, paste0(case_name, "-input.rds")), compress=FALSE, version=3)
    reference <- variants[["0.8.5"]]
    reference$PopFreqDNPs <- population
    precomputed <- suppressWarnings(reference$run_CPI_iteration(mother, father, panel, selection, .0000892303778101497))
    functions <- lapply(names(variants), function(variant) {
      definition <- variants[[variant]]
      definition$PopFreqDNPs <- population
      actual <- suppressWarnings(definition$run_CPI_iteration(mother, father, panel, selection, .0000892303778101497))
      stopifnot(identical(precomputed, actual))
      force(definition); force(variant)
      function() {
        values <- new.env(parent=definition)
        values$madre <- mother; values$padre <- father
        values$cutoff_df <- data.frame(Cutoff=selection,
          Path=if (is.null(panel)) NA_character_ else "fixture")
        values$cutoff_panels <- list(panel)
        values$has_cutoffs <- selection != "ALL"
        values$pair_name <- "MotherFixture-FatherFixture_DNPs"
        values$err_const <- .0000892303778101497
        values$run_CPI_iteration <- function(...) precomputed
        if (variant == "0.8.5") {
          values$read.table <- function(...) panel
          values$plot_CPI <- function(...) NULL
          values$per_cutoff_results <- list(); values$per_cutoff_plots <- list()
          values$per_cutoff_CPI_medreads <- c(); values$fetal_fraction_summary <- data.frame()
          for (expression in definition$loops) eval(expression, values)
          list(label=selection, plot_data=values$res, summary=values$fetal_fraction_summary,
               cfDNA_percent=values$cfDNA_percent, cpi_at_med=values$cpi_at_med)
        } else eval(definition$task, values)(1L)
      }
    })
    names(functions) <- names(variants)
    expected <- suppressWarnings(functions[[1L]]())
    reference_tables <- list()
    for (variant in names(functions)) {
      actual <- suppressWarnings(functions[[variant]]())
      stopifnot(identical(expected, actual))
      saveRDS(actual, file.path(output, paste0(case_name, "-", variant, "-output.rds")),
              compress=FALSE, version=3)
      tables <- list(summary=actual$summary, plot_data=actual$plot_data,
        plot_labels=data.frame(label=actual$label, cfDNA_percent=actual$cfDNA_percent,
                               cpi_at_med=actual$cpi_at_med))
      for (field in names(tables)) {
        path <- file.path(output, paste0(case_name, "-", variant, "-", field, ".tsv"))
        write.table(tables[[field]], path, sep="\t", row.names=FALSE, quote=TRUE, na="NA")
        bytes <- readBin(path, "raw", n=file.info(path)$size)
        if (variant == "0.8.5") reference_tables[[field]] <- bytes
        else stopifnot(identical(reference_tables[[field]], bytes))
      }
    }
    stopifnot(identical(inputs, readRDS(file.path(output, paste0(case_name, "-input.rds")))))
    for (round in seq_len(5L)) {
      order <- if (round %% 2L) names(functions) else rev(names(functions))
      for (variant in order) {
        gc()
        timing <- system.time(suppressWarnings(invisible(functions[[variant]]())))
        observations[[length(observations)+1L]] <- data.frame(case=case_name,
          variant=variant, repetition=round, elapsed_seconds=unname(timing[["elapsed"]]))
      }
    }
    cat("PASS", case_name, "exact core and cutoff outputs across three versions\n")
  }
}
write.table(do.call(rbind, observations), file.path(output, "timings.tsv"),
  sep="\t", row.names=FALSE, quote=FALSE)
manifest_files <- c(paths, file.path(repository, "tests/r_optimization/cpi/benchmark_summary.R"),
                    list.files(output, full.names=TRUE))
status <- system2("sha256sum", shQuote(manifest_files),
                   stdout=file.path(output, "SHA256SUMS"))
stopifnot(status == 0L)
cat("Scope: cutoff/summary assembly from one precomputed CPI result; no whole-workflow speed claim.\n")
cat("RDS bytes can differ for legacy data.frame attribute ordering; R values and all exported tables must match.\n")
