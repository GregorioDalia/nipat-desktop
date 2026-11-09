#!/usr/bin/env Rscript
# Resource-policy checks use explicit read-only /proc and cgroup fixtures.
# Scheduler checks below use the production helper, real resource discovery,
# real forked R processes, and actual child cleanup.
root <- normalizePath(commandArgs(trailingOnly = TRUE)[[1L]], mustWork = TRUE)
helper <- file.path(root, "src/nipat_scientific/parallel.R")

main <- function() {
  variables <- c("NIPAT_EXECUTION_MODE", "NIPAT_MAX_WORKERS", "NIPAT_CPU_LIMIT",
                 "NIPAT_MEMORY_LIMIT_MIB", "NIPAT_DNP_BLOCK_BYTES",
                 "NIPAT_PARALLEL_CHILD", "NIPAT_PARALLEL_LOG_DIR")
  previous <- Sys.getenv(variables, unset = NA_character_)
  on.exit(for (name in names(previous)) {
    if (is.na(previous[[name]])) Sys.unsetenv(name) else
      do.call(Sys.setenv, setNames(list(previous[[name]]), name))
  }, add = TRUE)
  Sys.unsetenv(variables)
  checked <- 0L
  check <- function(condition) {
    stopifnot(isTRUE(condition))
    checked <<- checked + 1L
  }
  fresh <- function(files = NULL) {
    environment <- new.env(parent = globalenv())
    sys.source(helper, environment)
    if (!is.null(files)) environment$nipat_parallel_lines <- function(path) {
      value <- files[[path]]
      if (is.null(value)) character() else as.character(value)
    }
    environment
  }
  expect_error <- function(expression, pattern) {
    error <- tryCatch({ force(expression); NULL }, error = identity)
    check(inherits(error, "error") && grepl(pattern, conditionMessage(error)))
  }
  MiB <- 1024^2

  # V2 quotas constrain affinity; available memory subtracts current use before
  # reserving coordination space. No writes to the real control group occur.
  v2 <- fresh(list(
    "/proc/self/cgroup" = "0::/",
    "/proc/meminfo" = "MemAvailable: 33554432 kB",
    "/sys/fs/cgroup/cpu.max" = "250000 100000",
    "/sys/fs/cgroup/memory.max" = 10 * 1024 * MiB,
    "/sys/fs/cgroup/memory.current" = 2 * 1024 * MiB))
  budget <- v2$nipat_parallel_budget(20)
  check(budget$cpu_limit <= 2L)
  check(budget$memory_available_mib == 8192)
  check(budget$memory_worker_limit == 3L)
  check(budget$workers <= 2L)
  check(v2$nipat_parallel_budget(1)$workers == 1L)
  # A DNP-specific block preference must not change the generic SNP/CPI/
  # contamination budget; DNP supplies its actual block estimate explicitly.
  Sys.setenv(NIPAT_DNP_BLOCK_BYTES = as.character(128 * MiB))
  check(v2$nipat_parallel_budget(20)$memory_per_worker_mib == 2048)
  check(v2$nipat_parallel_budget(20, memory_mib = 6144)$memory_per_worker_mib == 6144)
  Sys.unsetenv("NIPAT_DNP_BLOCK_BYTES")
  Sys.setenv(NIPAT_MAX_WORKERS = "1")
  check(v2$nipat_parallel_budget(20)$workers == 1L)
  Sys.unsetenv("NIPAT_MAX_WORKERS")
  Sys.setenv(NIPAT_EXECUTION_MODE = "serial")
  check(v2$nipat_parallel_budget(20)$reason == "requested-serial")
  check(v2$nipat_parallel_budget(20)$workers == 1L)
  Sys.setenv(NIPAT_EXECUTION_MODE = "auto", NIPAT_PARALLEL_CHILD = "1")
  check(v2$nipat_parallel_budget(20)$reason == "shared-budget-child")
  check(v2$nipat_parallel_budget(20)$workers == 1L)
  Sys.unsetenv("NIPAT_PARALLEL_CHILD")

  # A parent cgroup can include unrelated jobs. The explicit limit belongs to
  # this container and must not subtract an ancestor's total current memory.
  nested <- fresh(list(
    "/proc/self/cgroup" = "0::/parent/child",
    "/proc/meminfo" = "MemAvailable: 33554432 kB",
    "/sys/fs/cgroup/memory.max" = 32 * 1024 * MiB,
    "/sys/fs/cgroup/memory.current" = 16 * 1024 * MiB,
    "/sys/fs/cgroup/parent/child/memory.max" = 8 * 1024 * MiB,
    "/sys/fs/cgroup/parent/child/memory.current" = 512 * MiB))
  Sys.setenv(NIPAT_MEMORY_LIMIT_MIB = "8192")
  check(nested$nipat_parallel_budget(20)$memory_available_mib == 7680)
  check(nested$nipat_parallel_budget(20)$memory_worker_limit == 3L)
  Sys.unsetenv("NIPAT_MEMORY_LIMIT_MIB")

  v1 <- fresh(list(
    "/proc/meminfo" = "MemAvailable: 33554432 kB",
    "/sys/fs/cgroup/cpu/cpu.cfs_quota_us" = "150000",
    "/sys/fs/cgroup/cpu/cpu.cfs_period_us" = "100000",
    "/sys/fs/cgroup/memory/memory.limit_in_bytes" = 6 * 1024 * MiB,
    "/sys/fs/cgroup/memory/memory.usage_in_bytes" = 1024 * MiB))
  check(v1$nipat_parallel_budget(20)$cpu_limit == 1L)
  check(v1$nipat_parallel_budget(20)$memory_available_mib == 5120)
  check(v1$nipat_parallel_budget(20)$memory_worker_limit == 2L)
  unknown <- fresh(list())
  check(unknown$nipat_parallel_budget(20)$workers == 1L)
  check(unknown$nipat_parallel_budget(20)$reason == "memory-unavailable")
  Sys.setenv(NIPAT_MAX_WORKERS = "0")
  expect_error(v2$nipat_parallel_budget(20), "NIPAT_MAX_WORKERS")
  Sys.setenv(NIPAT_MAX_WORKERS = "1.5")
  expect_error(v2$nipat_parallel_budget(20), "NIPAT_MAX_WORKERS")
  Sys.unsetenv("NIPAT_MAX_WORKERS")
  expect_error(v2$nipat_parallel_budget(-1), "tasks")
  expect_error(v2$nipat_parallel_budget(2, memory_mib = 0), "memory_mib")

  # Production scheduler: real resource discovery, without a synthetic budget.
  real <- fresh()
  Sys.setenv(NIPAT_MAX_WORKERS = "2")
  if (real$nipat_parallel_workers(4) < 2L) {
    stop("Parallel scheduler qualification requires two effective workers; CPU/RAM budget is insufficient")
  }
  directory <- tempfile("parallel-budget-")
  dir.create(directory)
  on.exit(unlink(directory, recursive = TRUE), add = TRUE)
  Sys.setenv(NIPAT_PARALLEL_LOG_DIR = file.path(directory, "events"))
  coordinator <- Sys.getpid()
  callback_order <- integer()
  release_first <- file.path(directory, "release-first-task")
  callback <- function(index, value) {
    check(Sys.getpid() == coordinator)
    callback_order <<- c(callback_order, index)
    if (index == 2L) writeLines("release", release_first)
  }
  values <- real$nipat_parallel_lapply(setNames(1:4, letters[1:4]), function(index) {
    if (index == 1L) {
      deadline <- proc.time()[["elapsed"]] + 3
      while (!file.exists(release_first) && proc.time()[["elapsed"]] < deadline) Sys.sleep(0.01)
      stopifnot(file.exists(release_first))
    }
    list(index = index, pid = Sys.getpid())
  }, on_result = callback, label = "budget-order")
  check(identical(names(values), letters[1:4]))
  check(identical(unname(vapply(values, function(value) value$index, integer(1))), 1:4))
  check(callback_order[[1L]] != 1L)
  check(all(vapply(values, function(value) value$pid != coordinator, logical(1))))
  check(attr(values, "workers") == 2L)
  nulls <- real$nipat_parallel_lapply(1:3, function(index) NULL)
  check(length(nulls) == 3L && all(vapply(nulls, is.null, logical(1))))
  nested_values <- real$nipat_parallel_lapply(1:2, function(index) {
    own_pid <- Sys.getpid()
    inner <- real$nipat_parallel_lapply(1:3, function(j) Sys.getpid())
    list(own_pid = own_pid, inner = inner)
  })
  check(all(vapply(nested_values, function(value) {
    attr(value$inner, "workers") == 1L && all(unlist(value$inner) == value$own_pid)
  }, logical(1))))
  Sys.setenv(NIPAT_EXECUTION_MODE = "serial")
  serial <- real$nipat_parallel_lapply(1:3, function(index) Sys.getpid())
  check(all(unlist(serial) == coordinator) && attr(serial, "workers") == 1L)
  Sys.setenv(NIPAT_EXECUTION_MODE = "auto")

  # The first worker stays busy while the second raises. Error propagation must
  # terminate and collect the outstanding worker instead of abandoning it.
  marker <- file.path(directory, "busy-pid.txt")
  before <- proc.time()[["elapsed"]]
  expect_error(real$nipat_parallel_lapply(1:2, function(index) {
    if (index == 1L) {
      writeLines(as.character(Sys.getpid()), marker)
      Sys.sleep(10)
      return(TRUE)
    }
    deadline <- proc.time()[["elapsed"]] + 3
    while (!file.exists(marker) && proc.time()[["elapsed"]] < deadline) Sys.sleep(0.01)
    stop("deliberate worker failure")
  }), "deliberate worker failure")
  check(proc.time()[["elapsed"]] - before < 5)
  busy_pid <- as.integer(readLines(marker))
  check(!tools::pskill(busy_pid, signal = 0L))
  check(length(parallel::mccollect(wait = FALSE)) == 0L)

  events <- unlist(lapply(list.files(file.path(directory, "events"), full.names = TRUE),
                          readLines), use.names = FALSE)
  events <- lapply(events, jsonlite::fromJSON)
  check(any(vapply(events, function(event) event$event == "task-start" &&
                   event$pid != event$coordinator_pid, logical(1))))
  check(all(vapply(events, function(event) is.finite(event$observed_at_unix), logical(1))))
  cat("Parallel budget and scheduler:", checked,
      "checks passed (resource fixtures and real ordered forks, callbacks, nested budget, errors, cleanup).\n")
}
main()
