#!/usr/bin/env Rscript
# Compare bounded parsing and planning with base R's original whole-file import.
root <- normalizePath(commandArgs(trailingOnly = TRUE)[[1L]], mustWork = TRUE)
source(file.path(root, "src/nipat_scientific/dnp_blocks.R"))
checks <- 0L
compare_reader <- function(lines) {
  path <- tempfile(fileext = ".pileup")
  on.exit(unlink(path))
  writeLines(lines, path, useBytes = TRUE)
  reference <- read.csv(path, quote = "", row.names = NULL, stringsAsFactors = FALSE,
                        header = FALSE, sep = "\t")
  index <- nipat_dnp_index(path)
  con <- file(path, "rb")
  on.exit(close(con), add = TRUE)
  for (rows in list(seq_len(nrow(reference)), rev(seq_len(nrow(reference))), 1L, nrow(reference))) {
    actual <- nipat_dnp_read(index, rows, con)
    expected <- reference[rows, , drop = FALSE]
    rownames(expected) <- NULL
    stopifnot(identical(actual, expected))
    checks <<- checks + 1L
  }
  invisible(index)
}
# Numeric-looking names/qualities in early rows must not establish chunk-local
# types; the later text determines the complete column's storage semantics.
compare_reader(c("01\t10\tA\t1\tA\t5\t001", "1\t11\tC\t1\tC\tI\tname", "X\t12\tG\t0\t*\t*\t*"))
# All-numeric columns retain the old conversion (including leading zero loss).
compare_reader(c("01\t10\tA\t1\tA\t5\t001", "1\t11\tC\t1\tC\t6\t002"))
# Type transitions including numeric NaN, overflow, complex and logical unions.
lexemes <- c("NA", "TRUE", "T", "FALSE", "1", "001", "1.0", "1e3", "2147483648",
             "NaN", "Inf", "1+0i", "1+2i", "name")
for (a in lexemes) for (b in lexemes) {
  lines <- c(paste("chr1", 10, "A", 1, "A", "I", a, sep = "\t"),
             paste("chr1", 11, "C", 1, "C", "I", b, sep = "\t"))
  compare_reader(lines)
}
# Large round coordinates must retain integer formatting in lookup keys.
large <- compare_reader(paste("chr1", 99999:100002, "A", 1, "A", "I", "read", sep = "\t"))
stopifnot(is.integer(large$positions))
large_labels <- data.frame(df.chr = paste0("chr1:", 99999:100002), uniq = 1L)
large_plan <- nipat_dnp_plan(large, large_labels,
                           data.frame(POS = "chr1:100000|chr1:100001"))
stopifnot(identical(large_plan$blocks[[1L]]$row_ids, 1:4))
checks <- checks + 1L

# Complete-window groups remain indivisible; overlapping rows are read once in
# a block and repeated only where another block independently requires them.
index <- list(chromosomes = "chr1", chromosome = rep(1L, 6), positions = 9:14,
              lengths = rep(100, 6))
labels <- data.frame(df.chr = paste0("chr1:", c(9:12, 11:14, 9:12)),
                     uniq = rep(1:3, each = 4))
refs <- data.frame(POS = c("chr1:10|chr1:11", "chr1:12|chr1:13", "chr1:10|chr1:11"))
plan <- nipat_dnp_plan(index, labels, refs, max_loci = 1, max_bytes = 1)
stopifnot(length(plan$blocks) == 2L,
          identical(plan$blocks[[1L]]$locus_ids, c(1L, 3L)),
          identical(plan$blocks[[1L]]$row_ids, 1:4),
          identical(plan$blocks[[2L]]$row_ids, 3:6),
          plan$blocks[[1L]]$raw_bytes == 400)
checks <- checks + 1L
# Compatibility guards retain every raw row and global ID when the legacy
# grouping has cross-window dependencies. Ordinary planning above still split.
index$repeated_qname_rows <- 1L
compat <- nipat_dnp_plan(index, labels, refs, max_loci = 1, max_bytes = 1)
stopifnot(length(compat$blocks) == 1L,
          identical(compat$blocks[[1L]]$row_ids, 1:6),
          identical(compat$blocks[[1L]]$locus_ids, 1:3),
          "legacy-repeated-qname-within-position" %in% compat$compatibility_reasons)
index$repeated_qname_rows <- 0L
index$positions[[1L]] <- 1000L
compat <- nipat_dnp_plan(index, labels, refs, max_loci = 1, max_bytes = 1)
stopifnot(length(compat$blocks) == 1L, compat$unmatched_rows == 1L,
          "legacy-unmatched-coordinate-groups" %in% compat$compatibility_reasons)
# Combining must sort by the original merge keys rather than doubles printed
# in scientific notation (100000 becomes 1e+05).
parts <- list(list(final = data.frame(pos1 = 100001), sort_keys = "chr1:100001|chr1:100002"),
              list(final = data.frame(pos1 = 100000), sort_keys = "chr1:100000|chr1:100001"))
stopifnot(identical(nipat_dnp_combine(parts)$pos1, c(100000, 100001)))
checks <- checks + 3L
cat("DNP bounded reader/planner:", checks, "strict checks passed.\n")
