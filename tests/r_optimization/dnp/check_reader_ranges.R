#!/usr/bin/env Rscript
# Compare byte-range reads with the 0.8.13 per-row reader, including inputs
# for which base R warns or fails. The whole-column type/index policy is shared.
root <- normalizePath(commandArgs(trailingOnly = TRUE)[[1L]], mustWork = TRUE)
source(file.path(root, "src/nipat_scientific/dnp_blocks.R"))

# Frozen low-level read algorithm from d607f818 (0.8.13); no scientific formula
# is copied or replaced. Full pipeline checks still use the immutable 0.8.5.
old_read <- function(index, rows, connection) {
  lines <- vapply(rows, function(row) {
    seek(connection, where = index$offsets[[row]], origin = "start")
    readChar(connection, nchars = index$lengths[[row]], useBytes = TRUE)
  }, character(1), USE.NAMES = FALSE)
  read.csv(text = paste0(lines, collapse = ""), quote = "", row.names = NULL,
           stringsAsFactors = FALSE, header = FALSE, sep = "\t",
           colClasses = index$classes, na.strings = NULL)
}

checks <- 0L
capture <- function(reader, index, rows) {
  connection <- file(index$path, "rb")
  on.exit(close(connection))
  warnings <- character()
  result <- tryCatch(withCallingHandlers(
    list(ok = TRUE, value = reader(index, rows, connection)),
    warning = function(warning) {
      warnings <<- c(warnings, conditionMessage(warning))
      invokeRestart("muffleWarning")
    }), error = function(error) list(ok = FALSE, class = class(error),
                                    message = conditionMessage(error)))
  list(result = result, warnings = warnings)
}

check_bytes <- function(bytes, expected_rows) {
  path <- tempfile(fileext = ".pileup")
  on.exit(unlink(path))
  writeBin(bytes, path)
  index <- suppressWarnings(nipat_dnp_index(path))
  stopifnot(index$rows == expected_rows)
  requests <- list(seq_len(expected_rows), rev(seq_len(expected_rows)),
                   c(1L, expected_rows), c(2L, 2L, 3L, 1L),
                   c(1L, 2L, expected_rows), expected_rows)
  for (rows in requests) {
    stopifnot(identical(capture(old_read, index, rows),
                        capture(nipat_dnp_read, index, rows)))
    checks <<- checks + 1L
  }
  # The optimized reader's empty-frame types are unchanged.
  connection <- file(path, "rb")
  on.exit(close(connection), add = TRUE)
  empty <- nipat_dnp_read(index, integer(), connection)
  stopifnot(nrow(empty) == 0L, ncol(empty) == length(index$classes))
  # A small target exercises range boundaries without a large test allocation.
  rows <- c(1L, 2L, 2L, 3L, expected_rows, 1L)
  ranges <- nipat_dnp_read_ranges(index, rows, max_bytes = 64)
  reconstructed <- integer()
  for (number in seq_along(ranges$offsets)) {
    selected <- rows[seq.int(ranges$first[[number]], ranges$last[[number]])]
    reconstructed <- c(reconstructed, selected)
    stopifnot(ranges$offsets[[number]] == index$offsets[[selected[[1L]]]],
              ranges$lengths[[number]] == sum(index$lengths[selected]),
              length(selected) == 1L || ranges$lengths[[number]] <= 64)
  }
  stopifnot(identical(reconstructed, rows))
  checks <<- checks + 2L
}

lines <- paste("chr1", 100001:100008, c("A", "C"), 1,
               c("A", "C"), c("5", "I"),
               c("001", "name", "r\u00e9ad", "same", "same", "NaN", "x", "z"), sep = "\t")
for (endings in list(rep("\n", 8), rep("\r\n", 8),
                     rep(c("\n", "\r\n", "\r", "\n"), 2),
                     c(rep("\n", 7), ""))) {
  check_bytes(charToRaw(paste0(lines, endings, collapse = "")), 8L)
}

# Exercise indivisible lines with the small target checked by check_bytes.
# Boundaries at the production 8 MiB target are checked below without making
# base R repeatedly parse a multi-megabyte field in every focused test run.
large <- paste0("read_", strrep("x", 8192L))
jumbo <- c(lines[[1L]], paste("chr1", 100002, "A", 1, "A", "I", large, sep = "\t"),
           lines[[3L]])
check_bytes(charToRaw(paste0(jumbo, "\n", collapse = "")), 3L)
rm(large, jumbo)

# NUL truncation used to occur independently for each requested line. A range
# read must replay the old path rather than discard the later lines silently.
nul <- c(charToRaw(paste0(lines[[1L]], "\n", lines[[2L]])), as.raw(0L),
         charToRaw(paste0("ignored\n", lines[[3L]], "\n")))
check_bytes(nul, 3L)
# A changed/truncated file must still fail through the original per-row path,
# including readChar's character(0) when a coalesced request starts past EOF.
truncated <- tempfile(fileext = ".pileup")
writeLines(lines, truncated, useBytes = TRUE)
truncated_index <- nipat_dnp_index(truncated)
for (bytes in list(charToRaw(paste0(lines[[1L]], "\n")), raw())) {
  writeBin(bytes, truncated)
  stopifnot(identical(capture(old_read, truncated_index, 1:8),
                      capture(nipat_dnp_read, truncated_index, 1:8)))
  checks <- checks + 1L
}
unlink(truncated)
oversize <- list(offsets = c(0, 1, 8 * 1024^2 + 2),
                 lengths = c(1, 8 * 1024^2 + 1, 1))
oversize_ranges <- nipat_dnp_read_ranges(oversize, 1:3)
stopifnot(identical(oversize_ranges$first, 1:3),
          identical(oversize_ranges$last, 1:3),
          identical(oversize_ranges$lengths, oversize$lengths))
checks <- checks + 1L
# The helper must not join two valid large rows into an invalid nchars value,
# even if a caller supplies an unbounded target. No multi-GB allocation needed.
huge <- list(offsets = c(0, 2^30, 2^31), lengths = rep(2^30, 3))
huge_ranges <- nipat_dnp_read_ranges(huge, 1:3, max_bytes = Inf)
stopifnot(identical(huge_ranges$first, 1:3),
          identical(huge_ranges$last, 1:3),
          all(huge_ranges$lengths < .Machine$integer.max))
checks <- checks + 1L
cat("DNP byte-range reader:", checks,
    "strict checks passed (order, repeats, gaps, EOL, large rows and NUL warnings/errors).\n")
