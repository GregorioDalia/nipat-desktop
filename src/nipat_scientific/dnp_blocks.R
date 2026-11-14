# Bounded DNP input handling. Scientific transformations remain in DNPcall.R.
# Byte limits describe raw input, not a guarantee about R's resident memory.

nipat_dnp_number <- function(name, default) {
  text <- Sys.getenv(name, unset = as.character(default))
  value <- suppressWarnings(as.numeric(text))
  if (length(value) != 1L || !is.finite(value) || value < 1 || value != floor(value)) {
    stop(name, " must be a positive whole number")
  }
  value
}

nipat_dnp_index <- function(path, empty_samples = NULL) {
  started <- proc.time()[["elapsed"]]
  con <- file(path, open = "rb")
  on.exit(close(con))
  capacity <- 4096L
  offsets <- lengths <- positions <- numeric(capacity)
  chromosome <- integer(capacity)
  reference <- character(capacity)
  dictionary <- character()
  classes <- NULL
  if (!is.null(empty_samples)) {
    classes <- c("character", "integer", "character",
                 rep(c("integer", "character", "character", "character"), empty_samples))
  }
  count <- 0L
  repeated_qname_rows <- 0L
  repeat {
    offset <- seek(con)
    line <- readLines(con, n = 1L, warn = FALSE)
    if (!length(line)) break
    fields <- strsplit(line, "\t", fixed = TRUE)[[1L]]
    if (length(fields) < 7L || (length(fields) - 3L) %% 4L != 0L ||
        (!is.null(classes) && length(fields) != length(classes))) stop("Invalid DNP pileup columns")
    if (is.null(classes)) {
      classes <- c("character", "integer", "character",
                   rep(c("integer", "character", "character", "character"), (length(fields) - 3L) / 4L))
    }
    # Duplicate QNAMEs at one position can make legacy grouping infer a
    # middle pair belonging to another window. Preserve its global behavior;
    # ordinary reuse across different loci does not trigger this condition.
    if (any(vapply(seq.int(7L, length(fields), by = 4L), function(column) {
      anyDuplicated(strsplit(fields[[column]], ",", fixed = TRUE)[[1L]]) > 0L
    }, logical(1)))) repeated_qname_rows <- repeated_qname_rows + 1L
    count <- count + 1L
    if (count > capacity) {
      capacity <- capacity * 2L
      length(offsets) <- length(lengths) <- length(positions) <- capacity
      length(chromosome) <- length(reference) <- capacity
    }
    offsets[[count]] <- offset
    lengths[[count]] <- seek(con) - offset
    code <- match(fields[[1L]], dictionary)
    if (is.na(code)) {
      dictionary <- c(dictionary, fields[[1L]])
      code <- length(dictionary)
    }
    chromosome[[count]] <- code
    positions[[count]] <- as.numeric(fields[[2L]])
    reference[[count]] <- fields[[3L]]
  }
  if (!count && is.null(classes)) stop("DNP pileup contains no rows")
  rows <- seq_len(count)
  positions <- positions[rows]
  if (any(!is.finite(positions) | positions < 1 | positions > .Machine$integer.max |
          positions != floor(positions))) stop("Invalid DNP pileup position")
  list(path = normalizePath(path, mustWork = TRUE), offsets = offsets[rows],
       lengths = lengths[rows], chromosome = chromosome[rows],
       chromosomes = dictionary, positions = as.integer(positions),
       reference = reference[rows], classes = classes,
       rows = count, bytes = sum(lengths[rows]), repeated_qname_rows = repeated_qname_rows,
       elapsed_seconds = unname(proc.time()[["elapsed"]] - started))
}

nipat_dnp_plan <- function(index, labels, ref_alt,
                           max_loci = nipat_dnp_number("NIPAT_DNP_BLOCK_LOCI", 64),
                           max_bytes = nipat_dnp_number("NIPAT_DNP_BLOCK_BYTES", 32 * 1024^2)) {
  keys <- paste(index$chromosomes[index$chromosome], index$positions, sep = ":")
  by_coordinate <- split(seq_along(keys), keys)
  unmatched <- sum(!keys %in% labels$df.chr)
  reasons <- character()
  if (unmatched) reasons <- c(reasons, "legacy-unmatched-coordinate-groups")
  if (!is.null(index$repeated_qname_rows) && index$repeated_qname_rows > 0L) {
    reasons <- c(reasons, "legacy-repeated-qname-within-position")
  }
  if (length(reasons)) {
    return(list(blocks = list(list(locus_ids = seq_len(nrow(ref_alt)),
      row_ids = seq_along(keys), raw_bytes = sum(index$lengths))),
      max_loci = max_loci, max_bytes = max_bytes,
      compatibility_reasons = reasons, unmatched_rows = unmatched))
  }
  # Equal effective POS must stay together to preserve all merges.
  effective <- unique(ref_alt$POS)
  group_ids <- match(ref_alt$POS, effective)
  groups <- split(seq_len(nrow(ref_alt)), factor(group_ids, levels = seq_along(effective)))
  # Index panel membership and raw coordinates once. Repeated which()/%in%
  # scans and named-list lookups otherwise make planning quadratic in the
  # number of panel loci, before any scientific computation begins.
  label_groups <- group_ids[match(labels$uniq, seq_len(nrow(ref_alt)))]
  coordinate_indices <- match(labels$df.chr, names(by_coordinate))
  group_coordinates <- split(coordinate_indices,
    factor(label_groups, levels = seq_along(effective)))
  blocks <- list()
  active_ids <- active_rows <- integer()
  append_block <- function() {
    if (length(active_ids)) {
      blocks[[length(blocks) + 1L]] <<- list(
        locus_ids = active_ids, row_ids = sort(active_rows),
        raw_bytes = sum(index$lengths[active_rows])
      )
    }
  }
  for (group_number in seq_along(groups)) {
    ids <- groups[[group_number]]
    coordinates <- unique(group_coordinates[[group_number]])
    rows <- unique(unlist(by_coordinate[coordinates], use.names = FALSE))
    if (is.null(rows)) rows <- integer()
    combined <- union(active_rows, rows)
    if (length(active_ids) && (length(active_ids) + length(ids) > max_loci ||
                              sum(index$lengths[combined]) > max_bytes)) {
      append_block()
      active_ids <- active_rows <- integer()
      combined <- rows
    }
    active_ids <- c(active_ids, ids)
    active_rows <- combined
  }
  append_block()
  list(blocks = blocks, max_loci = max_loci, max_bytes = max_bytes,
       compatibility_reasons = character(), unmatched_rows = 0L)
}

nipat_dnp_read_ranges <- function(index, rows, max_bytes = 8 * 1024^2) {
  # Merge only byte-adjacent rows in the REQUESTED order. Sorting or unique()
  # here would change callers that repeat or reverse rows. Keep each temporary
  # read bounded, except for an indivisible line already larger than the target.
  max_bytes <- min(max_bytes, .Machine$integer.max - 1)
  count <- length(rows)
  offsets <- lengths <- numeric(count)
  first <- last <- integer(count)
  ranges <- 0L
  for (number in seq_along(rows)) {
    row <- rows[[number]]
    offset <- index$offsets[[row]]
    size <- index$lengths[[row]]
    if (ranges > 0L && offset == offsets[[ranges]] + lengths[[ranges]] &&
        lengths[[ranges]] + size <= max_bytes) {
      lengths[[ranges]] <- lengths[[ranges]] + size
      last[[ranges]] <- number
    } else {
      ranges <- ranges + 1L
      offsets[[ranges]] <- offset
      lengths[[ranges]] <- size
      first[[ranges]] <- last[[ranges]] <- number
    }
  }
  selected <- seq_len(ranges)
  list(offsets = offsets[selected], lengths = lengths[selected],
       first = first[selected], last = last[selected])
}

nipat_dnp_read <- function(index, rows, connection, columns = NULL) {
  classes <- index$classes
  column_names <- paste0("V", seq_along(classes))
  if (!is.null(columns)) {
    if (!length(columns) || anyNA(columns) || any(columns != as.integer(columns)) ||
        any(columns < 1L | columns > length(classes)) || anyDuplicated(columns)) {
      stop("Invalid DNP selected columns")
    }
    # Retain original pileup order and names, rather than renumbering a sample's
    # columns. Types still come from the complete global index, not this block.
    columns <- sort(as.integer(columns))
    classes[-columns] <- "NULL"
  }
  if (!length(rows)) {
    selected <- which(classes != "NULL")
    empty <- lapply(classes[selected], function(kind) switch(kind,
      logical = logical(), integer = integer(), numeric = numeric(),
      complex = complex(), character = character()))
    names(empty) <- column_names[selected]
    return(as.data.frame(empty, stringsAsFactors = FALSE))
  }
  read_row <- function(row) {
    seek(connection, where = index$offsets[[row]], origin = "start")
    readChar(connection, nchars = index$lengths[[row]], useBytes = TRUE)
  }
  offsets <- index$offsets[rows]
  adjacent <- length(rows) > 1L && any(
    head(offsets, -1L) + head(index$lengths[rows], -1L) == tail(offsets, -1L))
  if (!adjacent) {
    # Sparse/reversed requests cannot benefit from merging. Keep their old
    # direct path instead of allocating one range descriptor for every row.
    lines <- vapply(rows, read_row, character(1), USE.NAMES = FALSE)
  } else {
    ranges <- nipat_dnp_read_ranges(index, rows)
    lines <- vapply(seq_along(ranges$offsets), function(number) {
      first <- ranges$first[[number]]
      last <- ranges$last[[number]]
      if (first == last) return(read_row(rows[[first]]))
      seek(connection, where = ranges$offsets[[number]], origin = "start")
      warned <- FALSE
      value <- withCallingHandlers(
        readChar(connection, nchars = ranges$lengths[[number]], useBytes = TRUE),
        warning = function(warning) {
          warned <<- TRUE
          invokeRestart("muffleWarning")
        })
      # readChar can truncate at an embedded NUL. Preserve the former per-row
      # parsing and warnings on unusual bytes or a short read rather than losing
      # every following row in a combined interval. Normal samtools text is LF.
      if (warned || length(value) != 1L ||
          nchar(value, type = "bytes") != ranges$lengths[[number]]) {
        return(paste0(vapply(rows[seq.int(first, last)], read_row, character(1),
                            USE.NAMES = FALSE), collapse = ""))
      }
      value
    }, character(1), USE.NAMES = FALSE)
  }
  read.csv(text = paste0(lines, collapse = ""), quote = "", row.names = NULL,
           stringsAsFactors = FALSE, header = FALSE, sep = "\t",
           colClasses = classes, na.strings = NULL)
}

# Scheduling estimate, not an allocation limit: expanded observations, joins
# and R's own heap are larger than the raw pileup. Account for indivisible
# oversize/compatibility blocks instead of assuming the configured target held.
nipat_dnp_worker_memory_mib <- function(plan) {
  largest <- max(c(0, vapply(plan$blocks, function(block) block$raw_bytes, numeric(1))))
  ceiling(512 + 48 * largest / 1024^2)
}

nipat_dnp_run_block <- function(index, block, labels, ref_alt, compute, columns = NULL) {
    block_started <- proc.time()[["elapsed"]]
    started_at <- as.numeric(Sys.time())
    # Open after the fork. Children must never share an inherited descriptor:
    # nipat_dnp_read seeks independently for every block's original row order.
    connection <- file(index$path, open = "rb")
    on.exit(close(connection), add = TRUE)
    pileup <- nipat_dnp_read(index, block$row_ids, connection, columns)
    result <- compute(pileup, labels[labels$uniq %in% block$locus_ids, , drop = FALSE],
                      ref_alt[block$locus_ids, , drop = FALSE])
    rm(pileup)
    metric <- list(loci = length(block$locus_ids), raw_rows = length(block$row_ids),
                   raw_bytes = block$raw_bytes,
                   elapsed_seconds = unname(proc.time()[["elapsed"]] - block_started))
    gc(verbose = FALSE)
    list(result = result, metric = metric, started_at = started_at,
         finished_at = as.numeric(Sys.time()))
}

nipat_dnp_process_blocks <- function(index, plan, labels, ref_alt, compute,
                                     progress = function(...) invisible(NULL),
                                     workers = NULL) {
  started <- proc.time()[["elapsed"]]
  run_block <- function(number) {
    nipat_dnp_run_block(index, plan$blocks[[number]], labels, ref_alt, compute)
  }
  # Scientific values and metrics retain the plan's order regardless of which
  # worker completed first. Only this coordinating process publishes progress.
  completed <- 0L
  values <- nipat_parallel_lapply(seq_along(plan$blocks), run_block,
    label = "dnp-blocks", workers = workers,
    memory_mib = nipat_dnp_worker_memory_mib(plan),
    on_result = function(number, value) {
      completed <<- completed + value$metric$loci
      progress(completed, nrow(ref_alt))
    })
  list(results = lapply(values, function(value) value$result),
       metrics = lapply(values, function(value) value$metric),
       workers = attr(values, "workers"),
       elapsed_seconds = unname(proc.time()[["elapsed"]] - started))
}

# One process pool spans every sample and block. A sample does not reserve one
# worker and serialize all of its blocks: available workers take the next task,
# including when the sample count is smaller or larger than the shared budget.
nipat_dnp_process_samples <- function(index, plan, labels, ref_alt, computations,
                                      progress = function(...) invisible(NULL),
                                      workers = NULL, columns = NULL) {
  started <- proc.time()[["elapsed"]]
  sample_count <- length(computations)
  block_count <- length(plan$blocks)
  if (!sample_count || !block_count ||
      !all(vapply(computations, is.function, logical(1)))) {
    stop("DNP processing requires samples, blocks and compute functions")
  }
  if (!is.null(columns) && length(columns) != sample_count) {
    stop("DNP column selections must match the sample count")
  }
  task_count <- sample_count * block_count
  completed <- integer(sample_count)
  # Block-major order interleaves samples without allocating a Cartesian list.
  # This prevents the first large sample from monopolizing the entire queue.
  run_task <- function(number) {
    sample_number <- as.integer((number - 1L) %% sample_count + 1L)
    block_number <- as.integer((number - 1L) %/% sample_count + 1L)
    value <- nipat_dnp_run_block(index, plan$blocks[[block_number]], labels, ref_alt,
      computations[[sample_number]], if (is.null(columns)) NULL else columns[[sample_number]])
    value$sample_number <- sample_number
    value$block_number <- block_number
    value
  }
  values <- nipat_parallel_lapply(seq_len(task_count), run_task,
    label = "dnp-sample-blocks", workers = workers,
    memory_mib = nipat_dnp_worker_memory_mib(plan),
    on_result = function(number, value) {
      sample_number <- value$sample_number
      completed[[sample_number]] <<- completed[[sample_number]] + value$metric$loci
      progress(sample_number, completed[[sample_number]], nrow(ref_alt))
    })
  # Count observed concurrency separately from the resource-policy upper bound.
  # End events precede start events at equal timestamps; empty intervals do not
  # imply overlap. These timestamps describe successful tasks, not predictions.
  starts <- vapply(values, function(value) value$started_at, numeric(1))
  ends <- vapply(values, function(value) value$finished_at, numeric(1))
  sample_numbers <- vapply(values, function(value) value$sample_number, integer(1))
  active <- peaks <- integer(sample_count)
  observed_workers <- observed_samples <- 0L
  times <- c(starts, ends)
  deltas <- c(rep(1L, task_count), rep(-1L, task_count))
  samples <- rep(sample_numbers, 2L)
  nonempty <- rep(ends > starts, 2L)
  events <- which(nonempty)
  events <- events[order(times[events], deltas[events])]
  for (event in events) {
    sample_number <- samples[[event]]
    active[[sample_number]] <- active[[sample_number]] + deltas[[event]]
    peaks[[sample_number]] <- max(peaks[[sample_number]], active[[sample_number]])
    observed_workers <- max(observed_workers, sum(active))
    observed_samples <- max(observed_samples, sum(active > 0L))
  }
  grouped <- lapply(seq_len(sample_count), function(sample_number) {
    selected <- values[sample_numbers == sample_number]
    selected <- selected[order(vapply(selected, function(value) value$block_number, integer(1)))]
    list(results = lapply(selected, function(value) value$result),
         metrics = lapply(selected, function(value) value$metric),
         workers = as.integer(min(block_count, attr(values, "workers"))),
         observed_workers = as.integer(peaks[[sample_number]]),
         elapsed_seconds = max(vapply(selected, function(value) value$finished_at, numeric(1))) -
                           min(vapply(selected, function(value) value$started_at, numeric(1))))
  })
  list(samples = grouped, workers = attr(values, "workers"), task_count = task_count,
       observed_workers = as.integer(observed_workers), observed_samples = as.integer(observed_samples),
       elapsed_seconds = unname(proc.time()[["elapsed"]] - started))
}

nipat_dnp_combine <- function(values) {
  final <- do.call(rbind, lapply(values, function(value) value$final))
  # Numeric final coordinates can use scientific notation. Retain the exact
  # original DNPs strings used by the legacy merge instead of recreating keys.
  keys <- unlist(lapply(values, function(value) value$sort_keys), use.names = FALSE)
  stopifnot(length(keys) == nrow(final))
  final <- final[order(keys), , drop = FALSE]
  rownames(final) <- NULL
  final
}

nipat_dnp_write_metrics <- function(path, value) {
  # Metrics do not participate in the calculation, and an unwritable diagnostic
  # destination must not discard otherwise valid scientific output.
  tryCatch({
    dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
    jsonlite::write_json(value, path, auto_unbox = TRUE, pretty = TRUE,
                         digits = NA, null = "null")
  }, error = function(error) warning("DNP execution metrics unavailable: ", conditionMessage(error)))
}
