#!/usr/bin/env Rscript
# Exercise the production DNP R -> Python acquisition handoff independently of
# scientific calculation. The Python fixture validates the real JSON/CLI
# boundary; full samtools and 0.8.5 equivalence are qualified separately.
root <- normalizePath(commandArgs(trailingOnly = TRUE)[[1L]], mustWork = TRUE)

main <- function() {
  variables <- c("NIPAT_EXECUTION_MODE", "NIPAT_MAX_WORKERS", "NIPAT_PARALLEL_CHILD",
                 "NIPAT_TEST_FAIL_ACQUISITION")
  previous <- Sys.getenv(variables, unset = NA_character_)
  on.exit(for (name in names(previous)) {
    if (is.na(previous[[name]])) Sys.unsetenv(name) else
      do.call(Sys.setenv, setNames(list(previous[[name]]), name))
  }, add = TRUE)
  Sys.unsetenv(variables)
  old_directory <- getwd()
  directory <- tempfile("acquisition budget ")
  dir.create(directory)
  on.exit(setwd(old_directory), add = TRUE)
  on.exit(unlink(directory, recursive = TRUE), add = TRUE)

  helper <- file.path(directory, "capture acquisition.py")
  writeLines(c(
    "import argparse, json, os, pathlib, sys",
    "parser = argparse.ArgumentParser()",
    "for name in ('bamlist', 'bed', 'reference', 'output', 'scratch-dir', 'metadata', 'budget'):",
    "    parser.add_argument('--' + name, required=True)",
    "args = parser.parse_args()",
    "budget = json.loads(pathlib.Path(args.budget).read_text())",
    "assert budget['schema_version'] == 1 and budget['interface'] == 'nipat-parallel-v1'",
    "assert type(budget['workers']) is int and budget['workers'] >= 1",
    "assert budget['workers'] <= budget['cpu_limit']",
    "assert budget['workers'] <= budget['memory_worker_limit']",
    "assert budget['mode'] in ('serial', 'auto')",
    "if budget['mode'] == 'serial': assert budget['workers'] == 1",
    "if budget['max_workers'] is not None: assert budget['workers'] <= budget['max_workers']",
    "assert pathlib.Path(args.bamlist).read_text() == 'mounted-sample.bam\\n'",
    "assert pathlib.Path(args.reference).read_text() == '>chr1\\nACGT\\n'",
    "if os.environ.get('NIPAT_TEST_FAIL_ACQUISITION') == '1': sys.exit(23)",
    "pathlib.Path(args.output).write_text('fixture-pileup\\n')",
    "pathlib.Path(args.metadata).write_text(json.dumps({'budget': budget}))"
  ), helper)

  # Evaluate the actual acquisition statements from DNPcall, without copying
  # their JSON serializer, quoting, command construction or status handling.
  expressions <- parse(file.path(root, "scientific/vendor/DNPcall/DNPcall.R"))
  assignment <- function(expression, name) {
    is.call(expression) && identical(expression[[1L]], as.name("<-")) &&
      identical(expression[[2L]], as.name(name))
  }
  first <- which(vapply(expressions, assignment, logical(1), name = "acquisition_budget"))
  last <- which(vapply(expressions, assignment, logical(1), name = "acquisition_seconds"))
  stopifnot(length(first) == 1L, length(last) == 1L, first < last)
  handoff <- expressions[first:last]

  configurations <- list(
    list(name = "serial", mode = "serial", maximum = "2"),
    list(name = "maximum-one", mode = "auto", maximum = "1"),
    list(name = "maximum-two", mode = "auto", maximum = "2"),
    list(name = "failure", mode = "auto", maximum = "2")
  )
  for (configuration in configurations) {
    work <- file.path(directory, configuration$name)
    dir.create(work)
    setwd(work)
    Sys.setenv(NIPAT_EXECUTION_MODE = configuration$mode,
               NIPAT_MAX_WORKERS = configuration$maximum)
    if (configuration$name == "failure") Sys.setenv(NIPAT_TEST_FAIL_ACQUISITION = "1")
    environment <- new.env(parent = globalenv())
    sys.source(file.path(root, "src/nipat_scientific/parallel.R"), environment)
    environment$pileup_helper <- helper
    environment$bamlist <- file.path(work, "input list.txt")
    environment$reference <- file.path(work, "reference genome.fa")
    environment$dnp_scratch <- file.path(work, "scratch space")
    dir.create(environment$dnp_scratch)
    environment$pileup_path <- file.path(environment$dnp_scratch, "mpileup.txt")
    writeLines("mounted-sample.bam", environment$bamlist)
    writeLines(c(">chr1", "ACGT"), environment$reference)
    writeLines("chr1\t0\t4", "bedfile_for_mpileup.bed")

    error <- tryCatch({
      suppressWarnings(for (statement in handoff) eval(statement, environment))
      NULL
    }, error = identity)
    stopifnot(file.exists("work/dnp-acquisition-budget.json"))
    if (configuration$name == "failure") {
      stopifnot(inherits(error, "error"),
                grepl("DNP pileup acquisition failed", conditionMessage(error)),
                !file.exists(environment$pileup_path))
    } else {
      if (!is.null(error)) stop(error)
      evidence <- jsonlite::fromJSON("work/dnp-pileup.json")
      stopifnot(identical(evidence$budget$mode, configuration$mode),
                evidence$budget$max_workers == as.integer(configuration$maximum),
                evidence$budget$workers <= as.integer(configuration$maximum),
                is.finite(environment$acquisition_seconds),
                identical(readLines(environment$pileup_path), "fixture-pileup"))
      if (configuration$mode == "serial" || configuration$maximum == "1") {
        stopifnot(evidence$budget$workers == 1L)
      }
    }
  }
  cat("DNP acquisition budget: serial, maximum 1/2, quoted paths and subprocess failure passed.\n")
}
main()
