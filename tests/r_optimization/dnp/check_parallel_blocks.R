#!/usr/bin/env Rscript
# Focused dispatcher check: real forked R workers and pileup reads; synthetic
# scientific calculation. The complete scientific equations are qualified by
# check_blocks.R and the frozen 0.8.5 end-to-end comparisons.
root <- normalizePath(commandArgs(trailingOnly = TRUE)[[1L]], mustWork = TRUE)
source(file.path(root, "src/nipat_scientific/dnp_blocks.R"))

main <- function() {
  path <- tempfile(fileext = ".pileup")
  on.exit(unlink(path))
  writeLines(paste("chr1", 1:8, "A", 1, "A", "I", paste0("read", 1:8), sep = "\t"), path)
  index <- nipat_dnp_index(path)
  labels <- data.frame(df.chr = paste0("chr1:", 1:8), uniq = rep(1:4, each = 2L))
  refs <- data.frame(POS = c("d", "c", "b", "a"))
  plan <- nipat_dnp_plan(index, labels, refs, max_loci = 1L, max_bytes = 1024L)
  stopifnot(length(plan$blocks) == 4L)

  # Exercise the block dispatcher independently of the host's CPU/RAM quota.
  # The shared scheduler's resource caps are tested in its own focused checks.
  # Deliberately deliver callbacks in reverse order, but return values in input
  # order, matching the shared scheduler's completion/result-order contract.
  scheduler <- function(X, FUN, ..., label, workers = NULL, memory_mib = NULL,
                        on_result = NULL) {
    workers <- if (is.null(workers)) 2L else as.integer(workers)
    values <- if (workers > 1L) parallel::mclapply(X, FUN, ..., mc.cores = workers,
                                                 mc.preschedule = FALSE) else lapply(X, FUN, ...)
    failed <- which(vapply(values, inherits, logical(1), "try-error"))
    if (length(failed)) stop("worker failure: ", values[[failed[[1L]]]])
    for (number in rev(seq_along(values))) on_result(number, values[[number]])
    attr(values, "workers") <- workers
    values
  }
  assign("nipat_parallel_lapply", scheduler, envir = .GlobalEnv)
  on.exit(rm("nipat_parallel_lapply", envir = .GlobalEnv), add = TRUE)

  parent_pid <- Sys.getpid()
  own_connection <- function() {
    connections <- showConnections(all = TRUE)
    sum(connections[, "description"] == index$path)
  }
  compute <- function(pileup, block_labels, block_refs) {
    stopifnot(own_connection() == 1L,
              identical(paste0(pileup$V1, ":", pileup$V2), block_labels$df.chr))
    list(final = data.frame(locus = block_refs$POS,
                           reads = paste(pileup$V7, collapse = ",")),
         sort_keys = block_refs$POS, pid = Sys.getpid())
  }
  events <- list()
  progress <- function(completed, total) {
    stopifnot(Sys.getpid() == parent_pid, total == 4L)
    events[[length(events) + 1L]] <<- completed
  }
  stopifnot(own_connection() == 0L)
  serial <- nipat_dnp_process_blocks(index, plan, labels, refs, compute, progress, workers = 1L)
  stopifnot(own_connection() == 0L, identical(unlist(events), 1:4))
  events <- list()
  forked <- nipat_dnp_process_blocks(index, plan, labels, refs, compute, progress, workers = 2L)
  stopifnot(own_connection() == 0L, identical(unlist(events), 1:4),
            identical(nipat_dnp_combine(serial$results), nipat_dnp_combine(forked$results)),
            identical(forked$workers, 2L),
            all(vapply(serial$results, function(value) value$pid == parent_pid, logical(1))),
            all(vapply(forked$results, function(value) value$pid != parent_pid, logical(1))),
            length(unique(vapply(forked$results, function(value) value$pid, integer(1)))) >= 2L,
            identical(vapply(forked$results, function(value) value$final$reads, character(1)),
                      c("read1,read2", "read3,read4", "read5,read6", "read7,read8")))

  # Errors must propagate to the caller and leave no parent file handle or
  # misleading completed-locus events. They cannot become partial results.
  events <- list()
  failed <- tryCatch({
    suppressWarnings(nipat_dnp_process_blocks(index, plan, labels, refs,
      function(...) stop("deliberate scientific failure"), progress, workers = 2L))
    NULL
  }, error = identity)
  stopifnot(inherits(failed, "error"),
            grepl("deliberate scientific failure", conditionMessage(failed)),
            own_connection() == 0L, length(events) == 0L)

  # Integrate with the production scheduler as well. The host may legitimately
  # allow only one worker; when resources permit, this executes real child
  # processes and confirms the global outer/inner budget is never multiplied.
  source(file.path(root, "src/nipat_scientific/parallel.R"), local = .GlobalEnv)
  policy_names <- c("NIPAT_EXECUTION_MODE", "NIPAT_MAX_WORKERS", "NIPAT_PARALLEL_CHILD")
  policy <- Sys.getenv(policy_names, unset = NA_character_)
  on.exit(for (name in names(policy)) {
    if (is.na(policy[[name]])) Sys.unsetenv(name) else do.call(Sys.setenv, setNames(list(policy[[name]]), name))
  }, add = TRUE)
  Sys.setenv(NIPAT_EXECUTION_MODE = "auto", NIPAT_MAX_WORKERS = "2")
  Sys.unsetenv("NIPAT_PARALLEL_CHILD")
  events <- list()
  production <- nipat_dnp_process_blocks(index, plan, labels, refs, compute, progress)
  stopifnot(identical(nipat_dnp_combine(serial$results), nipat_dnp_combine(production$results)),
            identical(unlist(events), 1:4), own_connection() == 0L,
            production$workers %in% 1:2)
  if (production$workers > 1L) {
    stopifnot(all(vapply(production$results, function(value) value$pid != parent_pid, logical(1))),
              length(unique(vapply(production$results, function(value) value$pid, integer(1)))) >= 2L)
  }
  nested <- nipat_parallel_lapply(1:2, function(sample_number) {
    sample_pid <- Sys.getpid()
    inner <- nipat_dnp_process_blocks(index, plan, labels, refs, compute,
      progress = function(...) stopifnot(Sys.getpid() == sample_pid))
    list(workers = inner$workers, pid = sample_pid,
         task_pids = vapply(inner$results, function(value) value$pid, integer(1)),
         scientific = nipat_dnp_combine(inner$results))
  }, label = "dnp-test-samples", workers = 2L)
  for (sample in nested) {
    stopifnot(identical(sample$scientific, nipat_dnp_combine(serial$results)))
    if (attr(nested, "workers") > 1L) {
      stopifnot(sample$workers == 1L, all(sample$task_pids == sample$pid))
    }
  }
  Sys.setenv(NIPAT_EXECUTION_MODE = "serial")
  production_serial <- nipat_dnp_process_blocks(index, plan, labels, refs, compute, workers = 2L)
  stopifnot(production_serial$workers == 1L,
            all(vapply(production_serial$results, function(value) value$pid == parent_pid, logical(1))))
  Sys.setenv(NIPAT_EXECUTION_MODE = "auto")
  production_error <- tryCatch({
    nipat_dnp_process_blocks(index, plan, labels, refs,
      function(...) stop("production worker failure"), workers = 2L)
    NULL
  }, error = identity)
  stopifnot(inherits(production_error, "error"),
            grepl("production worker failure", conditionMessage(production_error)),
            own_connection() == 0L)
  cat("DNP production scheduler integration:", production$workers,
      "block worker(s),", attr(nested, "workers"), "sample worker(s); nested budget and serial override passed.\n")

  # The default changed, while indivisible groups remain safe and the memory
  # scheduling estimate uses their actual size, including compatibility mode.
  old <- Sys.getenv(c("NIPAT_DNP_BLOCK_BYTES", "NIPAT_DNP_BLOCK_LOCI"), unset = NA_character_)
  on.exit(for (name in names(old)) {
    if (is.na(old[[name]])) Sys.unsetenv(name) else do.call(Sys.setenv, setNames(list(old[[name]]), name))
  }, add = TRUE)
  Sys.unsetenv(names(old))
  defaults <- nipat_dnp_plan(index, labels, refs)
  stopifnot(defaults$max_bytes == 32 * 1024^2, defaults$max_loci == 64L)
  oversize <- plan
  oversize$blocks[[1L]]$raw_bytes <- 64 * 1024^2
  stopifnot(nipat_dnp_worker_memory_mib(oversize) == 512 + 48 * 64)
  cat("DNP parallel dispatcher: ordered fork results, isolated connections, parent progress, errors and limits passed.\n")
}
main()
