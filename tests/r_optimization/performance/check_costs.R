#!/usr/bin/env Rscript
# Controlled synthetic observations; equality is a gate, speed is descriptive.
suppressPackageStartupMessages({library(dplyr); library(tidyr); library(stringr)})
arguments <- commandArgs(trailingOnly=TRUE)
if (length(arguments) != 1L) stop("Expected one repository root argument")
repository <- normalizePath(arguments[[1]], mustWork=TRUE)
source(file.path(repository, "src/nipat_scientific/parallel.R"))
variants <- c(reference=file.path(repository, "tests/reference_r/0.8.5"),
              candidate=repository)

block_function <- function(path, start, end, inputs, output) {
  lines <- readLines(path, warn=FALSE)
  first <- which(trimws(lines) == start)
  last <- which(trimws(lines) == end)
  stopifnot(length(first) == 1L, length(last) == 1L, first < last)
  expressions <- parse(text=lines[seq.int(first, last-1L)])
  force(inputs); force(output)
  function() {
    environment <- list2env(inputs, parent=globalenv())
    environment$update_peak_ind <- function() invisible(NULL)
    suppressMessages(suppressWarnings(eval(expressions, environment)))
    get(output, environment, inherits=FALSE)
  }
}

observations <- list()
measure <- function(label, size, functions, repeats=3L) {
  expected <- functions$reference()
  actual <- functions$candidate()
  if (!identical(expected, actual)) stop("Benchmark output mismatch: ", label)
  rm(expected, actual)
  allocated <- setNames(rep(NA_real_, length(functions)), names(functions))
  if (isTRUE(capabilities("profmem"))) {
    for (variant in names(functions)) {
      profile <- tempfile()
      gc()
      Rprofmem(profile)
      tryCatch(invisible(functions[[variant]]()), finally=Rprofmem(NULL))
      events <- readLines(profile, warn=FALSE)
      unlink(profile)
      events <- events[grepl("^[0-9]+[[:space:]]", events)]
      allocated[[variant]] <- sum(as.numeric(sub("[[:space:]].*$", "", events)))
    }
  }
  # Alternate order to avoid always assigning one variant the first run.
  for (round in seq_len(repeats)) {
    order <- if (round %% 2L) names(functions) else rev(names(functions))
    for (variant in order) {
      gc()
      timing <- system.time(invisible(functions[[variant]]()))
      observations[[length(observations)+1L]] <<- data.frame(
        case=label, input_size=size, variant=variant, repetition=round,
        elapsed_seconds=unname(timing[["elapsed"]]),
        allocated_bytes=allocated[[variant]],
        stringsAsFactors=FALSE
      )
      cat("OBSERVATION", label, variant, "repeat", round,
          "elapsed_seconds", unname(timing[["elapsed"]]),
          "allocated_bytes", allocated[[variant]], "\n")
    }
  }
}

dnp_path <- "scientific/vendor/DNPcall/DNPcall.R"
rows <- 2000L
depth <- 40L
reads <- paste0("read_", seq_len(depth), collapse=",")
token_input <- data.frame(
  df.chr=paste0("chr1:", seq_len(rows)),
  df.V5=rep(paste(rep(c("A", "C", "G", "T"), depth/4L), collapse=""), rows),
  df.V7=rep(reads, rows),
  df.qual=rep(paste(rep(c("I", "5", "~", "!"), depth/4L), collapse=""), rows),
  stringsAsFactors=FALSE
)
measure("dnp-tokenization", paste(rows, "rows x", depth, "observations"),
        lapply(variants, function(root) block_function(
          file.path(root, dnp_path), "# substitution of characters to modify the df",
          "# get unique label for each DNP", list(df2=token_input), "df4.1")))

qualities <- rep(rawToChar(as.raw(33:126), multiple=TRUE), length.out=200000L)
measure("dnp-quality-decoding", "200000 quality characters",
        lapply(variants, function(root) block_function(
          file.path(root, dnp_path), "# convert ASCII pred score to number",
          "# group by new read label", list(df6=data.frame(df.qual=qualities)), "df6")))

coordinates <- vapply(seq_len(200), function(index)
  paste0("chr1:", 4L*index+seq_len(4), collapse="|"), "")
quality_patterns <- vapply(13:28, function(score)
  paste(c(40L, score, score+1L, 40L), collapse="|"), "")
groups <- data.frame(
  ID_DNP=paste0("read_", seq_len(20000L)),
  chr=rep(coordinates, length.out=20000L), pos=rep("A|C|G|T", 20000L),
  qual=rep(quality_patterns, length.out=20000L), stringsAsFactors=FALSE
)
measure("dnp-central-extraction", "20000 reads / 200 coordinate and 16 quality patterns",
        lapply(variants, function(root) block_function(
          file.path(root, dnp_path), '# eliminate reads with "@", indicating reads with INDELs',
          "# for full* dataset final", list(DF=groups), "good_reads")))

# Updated CPI model has its own independent oracle/curve qualification.
result <- do.call(rbind, observations)
write.table(result, "performance-observations.tsv", sep="\t", row.names=FALSE, quote=FALSE, na="NA")
cat("PASS synthetic performance cases: strict equality before each measurement.\n")
cat("Allocation totals are Rprofmem events, not peak RAM. Timings exclude profiling,\n",
    "container startup and package loading; they are not whole-workflow speedups.\n", sep="")
