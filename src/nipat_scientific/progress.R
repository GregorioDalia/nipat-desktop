# Optional presentation events. These functions never modify scientific objects.
nipat_progress <- local({
  sequences <- new.env(parent = emptyenv())
  written <- new.env(parent = emptyenv())
  function(event, phase, sample_ids = character(), completed = NULL, total = NULL,
           unit = NULL, outcome = NULL) {
    tryCatch({
      directory <- Sys.getenv("NIPAT_PROGRESS_DIR")
      if (!nzchar(directory) || !dir.exists(directory)) return(invisible(NULL))
      token <- Sys.getenv("NIPAT_PROGRESS_SOURCE")
      if (!grepl("^[a-f0-9]{32}$", token)) return(invisible(NULL))
      workflow <- Sys.getenv("NIPAT_PROGRESS_WORKFLOW", "dnp-call")
      step_id <- Sys.getenv("NIPAT_PROGRESS_STEP_ID")
      # Invocation nonce and PID distinguish parallel workers. The Python
      # coordinator provides a new nonce for each workflow step.
      source_id <- paste0(token, "-", Sys.getpid(), "-000000000000")
      sequence <- if (exists(source_id, sequences, inherits = FALSE)) sequences[[source_id]] + 1L else 1L
      sequences[[source_id]] <- sequence
      if (!length(sample_ids)) {
        sample_ids <- jsonlite::fromJSON(Sys.getenv("NIPAT_PROGRESS_SAMPLE_IDS", "[]"))
      }
      sample_map <- jsonlite::fromJSON(Sys.getenv("NIPAT_PROGRESS_SAMPLE_MAP", "{}"))
      sample_ids <- vapply(as.character(sample_ids), function(value) {
        mapped <- sample_map[[value]]
        if (is.null(mapped)) value else as.character(mapped)
      }, character(1))
      document <- list(schema_version = 1L, interface = "nipat-progress-v1",
                       source_id = source_id, sequence = sequence, event = event,
                       workflow = workflow, step_id = if (nzchar(step_id)) step_id else NULL,
                       phase = phase, sample_ids = as.list(as.character(sample_ids)))
      if (!is.null(completed) || !is.null(total) || !is.null(unit)) {
        if (is.null(completed) || is.null(total) || is.null(unit) ||
            length(completed) != 1L || length(total) != 1L ||
            !is.finite(completed) || !is.finite(total) ||
            completed < 0 || completed > total || completed != floor(completed) ||
            total != floor(total)) return(invisible(NULL))
        document$completed <- as.numeric(completed)
        document$total <- as.numeric(total)
        document$unit <- unit
      }
      if (!is.null(outcome)) document$outcome <- outcome
      encoded <- paste0(jsonlite::toJSON(document, auto_unbox = TRUE, null = "null", digits = NA), "\n")
      size <- nchar(encoded, type = "bytes")
      count <- if (exists(source_id, written, inherits = FALSE)) written[[source_id]] else 0
      if (size > 16384 || count + size > 4 * 1024 * 1024) return(invisible(NULL))
      target <- file.path(directory, paste0(source_id, ".jsonl"))
      if (file.exists(target) && nzchar(Sys.readlink(target))) return(invisible(NULL))
      cat(encoded, file = target, append = TRUE)
      written[[source_id]] <- count + size
    }, error = function(error) invisible(NULL))
    invisible(NULL)
  }
})
