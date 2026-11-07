# One bounded process budget shared by every scientific R workflow.
# Memory estimates guide scheduling; only the container's RAM limit is a hard limit.

nipat_parallel_positive <- function(text, name, default = NULL, whole = TRUE) {
  if (!nzchar(text)) return(default)
  value <- suppressWarnings(as.numeric(text))
  if (length(value) != 1L || !is.finite(value) || value <= 0 ||
      (whole && value != floor(value))) stop(name, " must be a positive number")
  value
}

nipat_parallel_lines <- function(path) {
  tryCatch(readLines(path, warn = FALSE), error = function(e) character(),
           warning = function(w) character())
}

nipat_parallel_number <- function(path) {
  value <- suppressWarnings(as.numeric(nipat_parallel_lines(path)[1L]))
  if (length(value) && is.finite(value) && value >= 0) value else Inf
}

nipat_parallel_cgroups <- function() {
  root <- "/sys/fs/cgroup"
  paths <- root
  line <- grep("^0::", nipat_parallel_lines("/proc/self/cgroup"), value = TRUE)
  if (length(line)) {
    relative <- sub("^0::/?", "", line[[1L]])
    # Container namespaces commonly expose the current cgroup directly at root.
    if (nzchar(relative) && !any(strsplit(relative, "/", fixed = TRUE)[[1L]] == "..")) {
      path <- file.path(root, relative)
      while (startsWith(path, paste0(root, "/"))) {
        paths <- c(paths, path)
        path <- dirname(path)
      }
    }
  }
  unique(paths)
}

nipat_parallel_budget <- function(tasks, memory_mib = NULL, workers = NULL) {
  mode <- Sys.getenv("NIPAT_EXECUTION_MODE", "auto")
  if (!mode %in% c("auto", "serial")) stop("Invalid NIPAT_EXECUTION_MODE")
  maximum <- nipat_parallel_positive(Sys.getenv("NIPAT_MAX_WORKERS"), "NIPAT_MAX_WORKERS", Inf)
  if (!is.null(workers)) {
    requested <- nipat_parallel_positive(as.character(workers), "workers")
    maximum <- min(maximum, requested)
  }
  if (length(tasks) != 1L || !is.finite(tasks) || tasks < 0 || tasks != floor(tasks)) {
    stop("tasks must be a nonnegative whole number")
  }
  cpu <- tryCatch(length(parallel::mcaffinity()), error = function(e) 0L)
  if (!cpu) cpu <- parallel::detectCores(logical = TRUE)
  if (!length(cpu) || is.na(cpu) || cpu < 1) cpu <- 1L
  cpu <- min(cpu, nipat_parallel_positive(Sys.getenv("NIPAT_CPU_LIMIT"),
                                         "NIPAT_CPU_LIMIT", Inf, whole = FALSE))
  cgroups <- nipat_parallel_cgroups()
  for (path in cgroups) {
    text <- nipat_parallel_lines(file.path(path, "cpu.max"))
    if (length(text)) {
      fields <- strsplit(trimws(text[[1L]]), "[[:space:]]+")[[1L]]
      numbers <- suppressWarnings(as.numeric(fields))
      if (length(numbers) == 2L && all(is.finite(numbers)) && all(numbers > 0)) {
        cpu <- min(cpu, numbers[[1L]] / numbers[[2L]])
      }
    }
  }
  quota <- nipat_parallel_number("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
  period <- nipat_parallel_number("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
  if (is.finite(quota) && is.finite(period) && quota > 0 && period > 0) cpu <- min(cpu, quota / period)
  cpu <- max(1L, floor(cpu))

  meminfo <- nipat_parallel_lines("/proc/meminfo")
  available <- grep("^MemAvailable:", meminfo, value = TRUE)
  memory <- if (length(available)) as.numeric(strsplit(trimws(available[[1L]]), "[[:space:]]+")[[1L]][2L]) / 1024 else NA_real_
  cgroup_used <- 0
  cgroup_used_depth <- -1L
  for (path in cgroups) {
    limit <- nipat_parallel_number(file.path(path, "memory.max"))
    used <- nipat_parallel_number(file.path(path, "memory.current"))
    if (is.finite(used) && nchar(path) > cgroup_used_depth) {
      cgroup_used <- used / 1024^2
      cgroup_used_depth <- nchar(path)
    }
    if (is.finite(limit) && is.finite(used)) memory <- min(memory, max(0, limit - used) / 1024^2, na.rm = TRUE)
  }
  limit <- nipat_parallel_number("/sys/fs/cgroup/memory/memory.limit_in_bytes")
  used <- nipat_parallel_number("/sys/fs/cgroup/memory/memory.usage_in_bytes")
  if (is.finite(limit) && is.finite(used)) {
    memory <- min(memory, max(0, limit - used) / 1024^2, na.rm = TRUE)
    if (cgroup_used_depth < 0L) cgroup_used <- used / 1024^2
  }
  explicit_memory <- nipat_parallel_positive(Sys.getenv("NIPAT_MEMORY_LIMIT_MIB"),
                                              "NIPAT_MEMORY_LIMIT_MIB", Inf)
  if (is.finite(explicit_memory)) memory <- min(memory, max(0, explicit_memory - cgroup_used), na.rm = TRUE)
  estimate <- 2048
  if (!is.null(memory_mib)) estimate <- max(estimate, nipat_parallel_positive(as.character(memory_mib), "memory_mib", whole = FALSE))
  # MemAvailable and memory.current already account for the loaded parent.
  # Reserve 20% for coordination, other VM work and estimation uncertainty.
  memory_workers <- if (is.finite(memory)) max(1L, floor(0.8 * memory / estimate)) else 1L
  process_workers <- Inf
  for (path in cgroups) {
    limit <- nipat_parallel_number(file.path(path, "pids.max"))
    used <- nipat_parallel_number(file.path(path, "pids.current"))
    if (is.finite(limit) && is.finite(used)) process_workers <- min(process_workers, max(1, limit - used - 4))
  }
  nested <- identical(Sys.getenv("NIPAT_PARALLEL_CHILD"), "1")
  reason <- if (mode == "serial") "requested-serial" else if (nested) "shared-budget-child" else if (.Platform$OS.type == "windows") "fork-unavailable" else if (!is.finite(memory)) "memory-unavailable" else "cpu-memory-task-budget"
  selected <- max(1L, min(max(1L, tasks), cpu, memory_workers, process_workers, maximum))
  if (mode == "serial" || nested || .Platform$OS.type == "windows") selected <- 1L
  list(mode = mode, max_workers = if (is.finite(maximum)) maximum else NULL,
       workers = as.integer(selected), tasks = tasks, cpu_limit = cpu,
       memory_available_mib = if (is.finite(memory)) memory else NULL,
       memory_per_worker_mib = estimate, memory_worker_limit = memory_workers,
       reason = reason)
}

nipat_parallel_workers <- function(tasks, memory_mib = NULL) {
  nipat_parallel_budget(tasks, memory_mib)$workers
}

nipat_parallel_record <- function(event, label, coordinator_pid, budget, task_index = NULL, outcome = NULL) {
  directory <- Sys.getenv("NIPAT_PARALLEL_LOG_DIR")
  if (!nzchar(directory)) return(invisible(NULL))
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  if (!dir.exists(directory)) stop("Cannot create parallel diagnostics directory")
  target <- file.path(directory, paste0("worker-", Sys.getpid(), ".jsonl"))
  link <- Sys.readlink(target)
  if (!is.na(link) && nzchar(link)) stop("Parallel diagnostics cannot use a symbolic link")
  document <- c(list(schema_version = 1L, interface = "nipat-parallel-v1", event = event,
                     label = label, coordinator_pid = coordinator_pid, pid = Sys.getpid(),
                     task_index = task_index, outcome = outcome,
                     observed_at_unix = as.numeric(Sys.time()),
                     elapsed_seconds = unname(proc.time()[["elapsed"]])), budget)
  cat(jsonlite::toJSON(document, auto_unbox = TRUE, null = "null", digits = NA), "\n",
      file = target, append = TRUE, sep = "")
  invisible(NULL)
}

nipat_parallel_lapply <- function(X, FUN, ..., label = "scientific", workers = NULL,
                                  memory_mib = NULL, on_result = NULL) {
  budget <- nipat_parallel_budget(length(X), memory_mib, workers)
  coordinator <- Sys.getpid()
  nipat_parallel_record("plan", label, coordinator, budget)
  result <- vector("list", length(X))
  names(result) <- names(X)
  arguments <- list(...)
  execute <- function(index) {
    nipat_parallel_record("task-start", label, coordinator, budget, index)
    value <- tryCatch(list(ok = TRUE, value = do.call(FUN, c(list(X[[index]]), arguments))),
                      error = function(error) list(ok = FALSE, message = conditionMessage(error)))
    nipat_parallel_record("task-end", label, coordinator, budget, index,
                          if (isTRUE(value$ok)) "succeeded" else "failed")
    value
  }
  accept <- function(index, value) {
    if (!is.list(value) || !isTRUE(value$ok)) {
      detail <- if (is.list(value) && !is.null(value$message)) value$message else "worker exited without a result"
      stop(label, " task ", index, " failed: ", detail, call. = FALSE)
    }
    result[index] <<- list(value$value)
    if (!is.null(on_result)) on_result(index, value$value)
  }
  if (budget$workers == 1L || !length(X)) {
    for (index in seq_along(X)) accept(index, execute(index))
  } else {
    active <- list()
    indices <- list()
    cleanup <- function() {
      if (!length(active)) return(invisible(NULL))
      for (job in active) try(tools::pskill(job$pid, tools::SIGTERM), silent = TRUE)
      deadline <- proc.time()[["elapsed"]] + 2
      while (length(active) && proc.time()[["elapsed"]] < deadline) {
        finished <- suppressWarnings(parallel::mccollect(active, wait = FALSE, timeout = 0.05))
        for (pid in names(finished)) active[[pid]] <<- NULL
      }
      for (job in active) try(tools::pskill(job$pid, tools::SIGKILL), silent = TRUE)
      if (length(active)) suppressWarnings(parallel::mccollect(active, wait = TRUE))
      invisible(NULL)
    }
    on.exit(cleanup(), add = TRUE)
    next_index <- 1L
    while (next_index <= length(X) || length(active)) {
      while (next_index <= length(X) && length(active) < budget$workers) {
        index <- next_index
        job <- parallel::mcparallel({
          Sys.setenv(NIPAT_PARALLEL_CHILD = "1")
          execute(index)
        }, mc.set.seed = FALSE, silent = FALSE)
        pid <- as.character(job$pid)
        active[[pid]] <- job
        indices[[pid]] <- index
        next_index <- next_index + 1L
      }
      finished <- suppressWarnings(parallel::mccollect(active, wait = FALSE, timeout = 0.05))
      # Remove every collected job before callbacks/errors: collected PIDs may be reused.
      for (pid in names(finished)) active[[pid]] <- NULL
      for (pid in names(finished)) {
        accept(indices[[pid]], finished[[pid]])
        indices[[pid]] <- NULL
      }
    }
  }
  attr(result, "workers") <- budget$workers
  result
}
