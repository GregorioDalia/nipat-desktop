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
original_locale <- Sys.getlocale("LC_COLLATE")
comparisons <- 0L
for (locale in unique(c(original_locale, "C", "C.UTF-8", "en_US.UTF-8"))) {
  selected <- suppressWarnings(Sys.setlocale("LC_COLLATE", locale))
  if (!nzchar(selected)) next
  for (name in names(cases)) {
    path <- tempfile(fileext=".pileup")
    writeLines(cases[[name]], path, useBytes=TRUE)
    values <- lapply(blocks, function(block) {
      environment <- new.env(parent=globalenv())
      environment$pileup_file <- path
      tryCatch({
        invisible(capture.output(suppressMessages(suppressWarnings(eval(block, environment)))))
        list(ok=TRUE, result=environment$df_count2)
      }, error=function(error) list(ok=FALSE, class=class(error), message=conditionMessage(error)))
    })
    unlink(path)
    if (!identical(values$reference, values$candidate)) {
      print(values)
      stop("SNP pileup mismatch: ", locale, " / ", name)
    }
    if (!values$reference$ok && !name %in% c("whitespace_name", "mismatched_lengths")) {
      stop("Unexpected failure in SNP reference: ", name, ": ", values$reference$message)
    }
    comparisons <- comparisons + 1L
  }
}
Sys.setlocale("LC_COLLATE", original_locale)
cat("PASS SNP pileup transformations:", comparisons, "strict comparisons\n")
