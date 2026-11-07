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

nipat_dnp_type <- function(current, token) {
  # read.csv/type.convert treats NA and whitespace-only fields as missing.
  # NaN is different: it establishes double storage even though is.na is TRUE.
  if (identical(current, "character") || is.na(token) ||
      token == "NA" || !nzchar(trimws(token))) return(current)
  observed <- typeof(type.convert(token, as.is = TRUE))
  if (is.null(current)) return(observed)
  witnesses <- c(logical = "TRUE", integer = "1", double = "1.5",
                 complex = "1+1i", character = "nipat-character-witness")
  typeof(type.convert(unname(witnesses[c(current, observed)]), as.is = TRUE))
}

nipat_dnp_index <- function(path) {
  started <- proc.time()[["elapsed"]]
  con <- file(path, open = "rb")
  on.exit(close(con))
  capacity <- 4096L
  offsets <- lengths <- positions <- numeric(capacity)
  chromosome <- integer(capacity)
  dictionary <- character()
  schema <- NULL
  count <- 0L
  repeated_qname_rows <- 0L
  repeat {
    offset <- seek(con)
    line <- readLines(con, n = 1L, warn = FALSE)
    if (!length(line)) break
    fields <- strsplit(line, "\t", fixed = TRUE)[[1L]]
    if (is.null(schema)) schema <- vector("list", length(fields))
    if (length(fields) != length(schema) || length(fields) < 7L ||
        (length(fields) - 3L) %% 4L != 0L) stop("Invalid DNP pileup columns")
    # Duplicate QNAMEs at one position can make legacy grouping infer a
    # middle pair belonging to another window. Preserve its global behavior;
    # ordinary reuse across different loci does not trigger this condition.
    if (any(vapply(seq.int(7L, length(fields), by = 4L), function(column) {
      anyDuplicated(strsplit(fields[[column]], ",", fixed = TRUE)[[1L]]) > 0L
    }, logical(1)))) repeated_qname_rows <- repeated_qname_rows + 1L
    for (column in seq_along(fields)) {
      schema[column] <- list(nipat_dnp_type(schema[[column]], fields[[column]]))
    }
    count <- count + 1L
    if (count > capacity) {
      capacity <- capacity * 2L
      length(offsets) <- length(lengths) <- length(positions) <- capacity
      length(chromosome) <- capacity
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
  }
  if (!count) stop("DNP pileup contains no rows")
  rows <- seq_len(count)
  classes <- vapply(schema, function(value) {
    value <- if (is.null(value)) "logical" else value
    if (value == "double") "numeric" else value
  }, character(1))
  # The dictionary contains every chromosome lexeme; its conversion therefore
  # agrees with the original whole-column read.csv, including 01/1 and NA.
  dictionary <- type.convert(dictionary, as.is = TRUE)
  # paste() formats doubles such as 100000 as 1e+05, whereas the legacy
  # integer V2 column uses 100000. Retain its globally inferred storage type.
  positions <- positions[rows]
  if (identical(classes[[2L]], "integer")) positions <- as.integer(positions)
  list(path = normalizePath(path, mustWork = TRUE), offsets = offsets[rows],
       lengths = lengths[rows], chromosome = chromosome[rows],
       chromosomes = dictionary, positions = positions, classes = classes,
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
  # Different original chromosome lexemes may collapse under read.table's
  # inference. Equal effective POS must stay together to preserve all merges.
  effective <- unique(ref_alt$POS)
  groups <- lapply(effective, function(key) which(ref_alt$POS == key))
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
  for (ids in groups) {
    coordinates <- unique(labels$df.chr[labels$uniq %in% ids])
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

nipat_dnp_read <- function(index, rows, connection) {
  if (!length(rows)) {
    empty <- lapply(index$classes, function(kind) switch(kind,
      logical = logical(), integer = integer(), numeric = numeric(),
      complex = complex(), character = character()))
    names(empty) <- paste0("V", seq_along(empty))
    return(as.data.frame(empty, stringsAsFactors = FALSE))
  }
  lines <- vapply(rows, function(row) {
    seek(connection, where = index$offsets[[row]], origin = "start")
    readChar(connection, nchars = index$lengths[[row]], useBytes = TRUE)
  }, character(1), USE.NAMES = FALSE)
  read.csv(text = paste0(lines, collapse = ""), quote = "", row.names = NULL,
           stringsAsFactors = FALSE, header = FALSE, sep = "\t",
           colClasses = index$classes)
}

# Scheduling estimate, not an allocation limit: expanded observations, joins
# and R's own heap are larger than the raw pileup. Account for indivisible
# oversize/compatibility blocks instead of assuming the configured target held.
nipat_dnp_worker_memory_mib <- function(plan) {
  largest <- max(c(0, vapply(plan$blocks, function(block) block$raw_bytes, numeric(1))))
  ceiling(512 + 48 * largest / 1024^2)
}

nipat_dnp_process_blocks <- function(index, plan, labels, ref_alt, compute,
                                     progress = function(...) invisible(NULL),
                                     workers = NULL) {
  started <- proc.time()[["elapsed"]]
  run_block <- function(number) {
    block <- plan$blocks[[number]]
    block_started <- proc.time()[["elapsed"]]
    # Open after the fork. Children must never share an inherited descriptor:
    # nipat_dnp_read seeks independently for every block's original row order.
    connection <- file(index$path, open = "rb")
    on.exit(close(connection), add = TRUE)
    pileup <- nipat_dnp_read(index, block$row_ids, connection)
    result <- compute(pileup, labels[labels$uniq %in% block$locus_ids, , drop = FALSE],
                      ref_alt[block$locus_ids, , drop = FALSE])
    rm(pileup)
    metric <- list(loci = length(block$locus_ids), raw_rows = length(block$row_ids),
                   raw_bytes = block$raw_bytes,
                   elapsed_seconds = unname(proc.time()[["elapsed"]] - block_started))
    gc(verbose = FALSE)
    list(result = result, metric = metric)
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
