#!/usr/bin/env Rscript
# Exact legacy comparison for contiguous-row partitioning and filename collisions.
arguments <- commandArgs(trailingOnly = TRUE)
if (length(arguments) != 1L) stop("Expected one repository root argument")
repository <- normalizePath(arguments[[1L]], mustWork = TRUE)
relative <- "scientific/vendor/NEWPAT/contamination/detect_contamination.R"
Sys.setenv(NIPAT_PARALLEL_HELPER = file.path(repository, "src/nipat_scientific/parallel.R"),
           NIPAT_MAX_WORKERS = "2")
source(Sys.getenv("NIPAT_PARALLEL_HELPER"))
root <- tempfile("nipat-contamination-parallel-")
dir.create(root)

panel <- data.frame(chr = "chr1", pos1 = 10:19, pos2 = 11:20)
panel_path <- file.path(root, "panel.txt")
write.table(panel, panel_path, sep = "\t", row.names = FALSE, quote = FALSE)
template <- transform(panel,
  N_REF = c(90, 1, 50, 0, 99, 9, 10, 100, 4, NA),
  N_ALT = c(10, 9, 50, 0, 1, 1, 90, 0, 96, 2),
  N_Other = c(0, 0, 0, 0, 11, 1, 0, 0, 10, 0),
  extra = c("a", "b", "c", "d", "e", "f", "g", "h", "i", "j"))
large_path <- file.path(root, "large.txt")
write.table(template[rep(seq_len(nrow(template)), length.out = 120003L), ],
            large_path, sep = "\t", row.names = FALSE, quote = FALSE)
duplicate_dir <- file.path(root, "duplicate")
dir.create(duplicate_dir)
for (name in c("first", "last")) dir.create(file.path(duplicate_dir, name))
write.table(template[1:3, ], file.path(duplicate_dir, "first", "same.txt"),
            sep = "\t", row.names = FALSE, quote = FALSE)
write.table(template[6:9, ], file.path(duplicate_dir, "last", "same.txt"),
            sep = "\t", row.names = FALSE, quote = FALSE)

run_case <- function(name, input, source_root, mode) {
  output <- file.path(root, name)
  log_dir <- paste0(output, "-workers")
  Sys.setenv(NIPAT_EXECUTION_MODE = mode, NIPAT_PARALLEL_LOG_DIR = log_dir)
  values <- new.env(parent = globalenv())
  values$commandArgs <- function(trailingOnly = FALSE) c(panel_path, input, output)
  sys.source(file.path(source_root, relative), envir = values)
  list(output = output, summary = values$contamination_summary, logs = log_dir)
}
bytes <- function(path) readBin(path, "raw", n = file.info(path)$size)
compare <- function(expected, actual) {
  stopifnot(identical(expected$summary, actual$summary))
  files <- list.files(expected$output)
  stopifnot(identical(files, list.files(actual$output)))
  for (name in files) {
    if (!identical(bytes(file.path(expected$output, name)),
                   bytes(file.path(actual$output, name)))) stop("Output differs: ", name)
  }
}
for (case_name in c("large", "duplicate")) {
  input <- if (case_name == "large") large_path else duplicate_dir
  baseline <- run_case(paste0(case_name, "-reference"), input,
                       file.path(repository, "tests/reference_r/0.8.5"), "serial")
  serial <- run_case(paste0(case_name, "-serial"), input, repository, "serial")
  first <- run_case(paste0(case_name, "-parallel1"), input, repository, "auto")
  second <- run_case(paste0(case_name, "-parallel2"), input, repository, "auto")
  for (candidate in list(serial, first, second)) compare(baseline, candidate)
  plans <- unlist(lapply(list.files(first$logs, full.names = TRUE), readLines),
                  use.names = FALSE)
  plans <- lapply(plans, jsonlite::fromJSON)
  plans <- Filter(function(value) identical(value$event, "plan"), plans)
  if (case_name == "duplicate") {
    samples <- Filter(function(value) identical(value$label, "contamination-samples"), plans)
    stopifnot(length(samples) == 1L, samples[[1L]]$workers == 1L)
  } else {
    rows <- Filter(function(value) identical(value$label, "contamination-rows"), plans)
    if (length(rows)) {
      stopifnot(length(rows) == 1L, rows[[1L]]$tasks > 1L, rows[[1L]]$workers <= 2L)
      cat("Observed contamination row workers:", rows[[1L]]$workers, "\n")
    } else {
      cat("Contamination row fork unavailable under the current resource budget\n")
    }
  }
  cat("PASS contamination:", case_name,
      "legacy/serial/parallel/repeat exact tables and unrounded summary\n")
}
unlink(root, recursive = TRUE)
