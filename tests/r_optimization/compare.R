# Strict R-value comparison: numeric values, types, attributes and row order.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
reference <- readRDS(args[1])
candidate <- readRDS(args[2])
if (!identical(reference, candidate)) {
  print(all.equal(reference, candidate, tolerance = 0, check.attributes = TRUE))
  stop("Unrounded scientific R values differ from NIPAT 0.8.5")
}
cat("PASS: exact unrounded R values, types, attributes and ordering.\n")
