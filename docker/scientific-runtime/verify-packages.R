# Expected direct runtime versions from the successful NIPAT 0.4.1 build.
# The dated CRAN repository also constrains transitive dependency resolution.
expected <- read.delim(
  "/usr/share/nipat/r-packages.tsv",
  colClasses = "character",
  check.names = FALSE
)
stopifnot(
  identical(names(expected), c("Package", "Version")),
  nrow(expected) > 0L,
  !anyDuplicated(expected$Package),
  all(nzchar(expected$Package)),
  all(nzchar(expected$Version))
)

for (i in seq_len(nrow(expected))) {
  package <- expected$Package[[i]]
  if (!requireNamespace(package, quietly = TRUE)) {
    stop("Required runtime package cannot be loaded: ", package)
  }
  actual <- as.character(packageVersion(package))
  if (!identical(actual, expected$Version[[i]])) {
    stop("Runtime package version mismatch: ", package,
         "; expected ", expected$Version[[i]], "; found ", actual)
  }
}

# Retain all installed packages, including dependencies and R's base packages.
inventory <- installed.packages()[, c("Package", "Version", "Built"), drop = FALSE]
inventory <- inventory[order(inventory[, "Package"], inventory[, "Version"]), , drop = FALSE]
write.table(inventory, "/usr/share/nipat/r-versions.tsv",
            sep = "\t", quote = FALSE, row.names = FALSE)
message("Verified ", nrow(expected), " pinned NIPAT R packages.")
