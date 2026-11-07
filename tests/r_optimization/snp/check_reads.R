#!/usr/bin/env Rscript
# Compare pileup parsing and read aggregation with the frozen 0.8.5 source.
suppressPackageStartupMessages({library(dplyr); library(tidyr); library(stringr)})
arguments <- commandArgs(trailingOnly=TRUE)
if (length(arguments) != 1L) stop("Expected one repository root argument")
repository <- normalizePath(arguments[[1]], mustWork=TRUE)
relative <- "scientific/vendor/NEWPAT/SNPcall/SNPcall.R"
paths <- c(reference=file.path(repository, "tests/reference_r/0.8.5", relative),
           candidate=file.path(repository, relative))
extract <- function(path) {
  lines <- readLines(path, warn=FALSE)
  start <- which(trimws(lines) == 'cat(">> reading pileup...\\n")')
  end <- which(trimws(lines) == "# extract the text between pipes and remove the first and last pipe")
  stopifnot(length(start) == 1L, length(end) == 1L, start < end)
  parse(text=lines[seq.int(start, end-1L)])
}
blocks <- lapply(paths, extract)
source(Sys.getenv("NIPAT_PARALLEL_HELPER",
                  unset=file.path(repository, "src/nipat_scientific/parallel.R")))
candidate_expressions <- parse(file=paths[["candidate"]])
group_definition <- Filter(function(expression) {
  is.call(expression) && identical(expression[[1L]], as.name("<-")) &&
    identical(expression[[2L]], as.name("nipat_snp_group_reads"))
}, candidate_expressions)
stopifnot(length(group_definition) == 1L)
eval(group_definition[[1L]], globalenv())

row <- function(position, bases, names, chromosome="chr1", extra=NULL) {
  paste(c(chromosome, position, "A", nchar(bases), bases,
          paste(rep("I", nchar(bases)), collapse=""), names, extra), collapse="\t")
}
ordinary <- vapply(49:51, function(position) row(position, ".,gT", "a,B,r@skip,shared"), "")
cases <- list(
  ordinary=ordinary,
  shared_across_windows=c(ordinary, vapply(119:121, function(position)
    row(position, ".,gT", "z,Z,r-1,shared"), "")),
  extra_columns=vapply(49:51, function(position)
    row(position, ".,gT", "a,B,r@skip,shared", extra=c("unused text", 123, "NA")), ""),
  numeric_names=vapply(49:51, function(position) row(position, ".", "100", "1"), ""),
  short_and_flank_indels=c(
    row(49, ".,.*.", "all,reverse,left,flank,single"),
    row(50, "GT...", "all,reverse,left,flank,right"),
    row(51, ".,...", "all,reverse,flank,right,other-single")
  ),
  coordinate_at=vapply(49:51, function(position) row(position, ".,", "a,b", "chr@1"), ""),
  empty_name=vapply(49:51, function(position) row(position, ".,G", "a,,b"), ""),
  missing_name=vapply(49:51, function(position) row(position, ".", "NA"), ""),
  whitespace_name=vapply(49:51, function(position) row(position, ".,", "read name,b"), ""),
  mismatched_lengths=vapply(49:51, function(position) row(position, ".,", "a,b,c"), ""),
  unicode_names=vapply(49:51, function(position) row(position, ".,", "\u00e9,Z"), "")
)
# Interleaved reads shared across many windows must retain their complete
# coordinate paths; partitioning by locus would change the scientific result.
cases$interleaved_global_names <- unlist(lapply(c(50L, 120L, 180L), function(center) {
  qnames <- sprintf("read_%02d", c(seq(1L, 63L, 2L), seq(2L, 64L, 2L)))
  vapply((center-1L):(center+1L), function(position) row(
    position, paste(rep(c(".", ",", "G", "t"), 16L), collapse=""),
    paste(qnames, collapse=",")), "")
}), use.names=FALSE)
original_locale <- Sys.getlocale("LC_COLLATE")
comparisons <- 0L
configurations <- list(
  serial=list(mode="serial", workers="4"),
  two=list(mode="auto", workers="2"),
  four=list(mode="auto", workers="4"),
  four_repeat=list(mode="auto", workers="4")
)
for (locale in unique(c(original_locale, "C", "C.UTF-8", "en_US.UTF-8"))) {
  selected <- suppressWarnings(Sys.setlocale("LC_COLLATE", locale))
  if (!nzchar(selected)) next
  for (name in names(cases)) {
    path <- tempfile(fileext=".pileup")
    writeLines(cases[[name]], path, useBytes=TRUE)
    evaluate <- function(block) {
      environment <- new.env(parent=globalenv())
      environment$pileup_file <- path
      tryCatch({
        invisible(capture.output(suppressMessages(suppressWarnings(eval(block, environment)))))
        list(ok=TRUE, result=environment$df_count2)
      }, error=function(error) list(ok=FALSE, class=class(error), message=conditionMessage(error)))
    }
    reference <- evaluate(blocks$reference)
    for (configuration in names(configurations)) {
      settings <- configurations[[configuration]]
      Sys.setenv(NIPAT_EXECUTION_MODE=settings$mode, NIPAT_MAX_WORKERS=settings$workers)
      candidate <- evaluate(blocks$candidate)
      if (!identical(reference, candidate)) {
        print(list(reference=reference, candidate=candidate))
        stop("SNP pileup mismatch: ", locale, " / ", name, " / ", configuration)
      }
      comparisons <- comparisons + 1L
    }
    unlink(path)
    if (!reference$ok && !name %in% c("whitespace_name", "mismatched_lengths")) {
      stop("Unexpected failure in SNP reference: ", name, ": ", reference$message)
    }
  }
}
Sys.setlocale("LC_COLLATE", original_locale)
cat("PASS SNP pileup transformations:", comparisons, "strict comparisons\n")
