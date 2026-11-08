#!/usr/bin/env Rscript
# Optional synthetic I/O microbenchmark; intentionally outside check_*.R.
# Usage: Rscript benchmark_reader.R REPOSITORY OLD_DNP_BLOCKS_R OUTPUT_DIR
# OLD_DNP_BLOCKS_R should be exported from immutable 0.8.13 d607f818.
# Add --keep-fixtures to retain the deep fixture/index for separate-process RSS
# measurements; use the same three arguments plus rss-old or rss-new to read it.
# Timing/allocations are isolated reader costs, never end-to-end BAM timings.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3L) stop("Expected repository, old dnp_blocks.R, output directory")
root <- normalizePath(args[[1L]], mustWork = TRUE)
reference <- normalizePath(args[[2L]], mustWork = TRUE)
out <- args[[3L]]
dir.create(out, recursive = TRUE, showWarnings = FALSE)
out <- normalizePath(out, mustWork = TRUE)
mode <- if (length(args) >= 4L) args[[4L]] else "benchmark"
old <- new.env(parent = globalenv())
new <- new.env(parent = globalenv())
sys.source(reference, envir = old)
sys.source(file.path(root, "src/nipat_scientific/dnp_blocks.R"), envir = new)

make_file <- function(count, depth, path = tempfile(fileext = ".pileup")) {
  names <- paste(sprintf("read%06d", seq_len(depth)), collapse = ",")
  bases <- strrep("A", depth)
  quality <- strrep("I", depth)
  con <- file(path, "wb")
  on.exit(close(con))
  for (row in seq_len(count)) {
    writeLines(paste("chr1", 100000L + row, "A", depth, bases, quality, names,
                     sep = "\t"), con, useBytes = TRUE)
  }
  path
}
read_with <- function(fun, index, rows) {
  con <- file(index$path, "rb")
  on.exit(close(con))
  fun(index, rows, con)
}
profile_alloc <- function(fun, index, rows) {
  path <- tempfile()
  Rprofmem(path)
  value <- read_with(fun, index, rows)
  Rprofmem(NULL)
  entries <- readLines(path, warn = FALSE)
  unlink(path)
  bytes <- suppressWarnings(as.numeric(sub(" .*", "", entries)))
  c(allocation_mib = sum(bytes, na.rm = TRUE) / 1024^2,
    allocation_count = sum(!is.na(bytes)))
}
allocations <- ranges <- list()
bench <- function(label, index, rows) {
  a <- read_with(old$nipat_dnp_read, index, rows)
  b <- read_with(new$nipat_dnp_read, index, rows)
  stopifnot(identical(a, b))
  rm(a, b)
  methods <- list(old = old$nipat_dnp_read, new = new$nipat_dnp_read)
  results <- list()
  for (round in 1:5) {
    for (method in if (round %% 2L) c("old", "new") else c("new", "old")) {
      gc()
      elapsed <- system.time(value <- read_with(methods[[method]], index, rows))[["elapsed"]]
      results[[length(results) + 1L]] <- data.frame(case = label, round = round,
        method = method, elapsed_seconds = unname(elapsed))
      rm(value)
    }
  }
  for (method in names(methods)) {
    allocation <- profile_alloc(methods[[method]], index, rows)
    allocations[[length(allocations) + 1L]] <<- data.frame(case = label, method = method,
      allocation_mib = unname(allocation[["allocation_mib"]]),
      allocation_count = unname(allocation[["allocation_count"]]))
    cat("ALLOC", label, method, paste(names(allocation), allocation, collapse = " "), "\n")
  }
  ranges[[length(ranges) + 1L]] <<- data.frame(case = label, rows = length(rows),
    spans = length(new$nipat_dnp_read_ranges(index, rows)$offsets),
    raw_mib = sum(index$lengths[rows]) / 1024^2)
  cat("RANGES", label, "rows", length(rows), "spans",
      length(new$nipat_dnp_read_ranges(index, rows)$offsets), "raw_mib",
      sum(index$lengths[rows]) / 1024^2, "\n")
  do.call(rbind, results)
}

if (mode %in% c("rss-old", "rss-new")) {
  index <- readRDS(file.path(out, "reader-benchmark-deep-index.rds"))
  reader <- if (mode == "rss-old") old$nipat_dnp_read else new$nipat_dnp_read
  value <- read_with(reader, index, seq_len(index$rows))
  stopifnot(nrow(value) == 512L)
  # Linux exposes this process's actual high-water RSS; on other platforms use
  # the operating system's process resource meter around this isolated run.
  if (file.exists("/proc/self/status")) {
    cat(grep("^VmHWM:", readLines("/proc/self/status"), value = TRUE), "\n")
  }
  quit(status = 0L)
}
writeLines(c(R.version.string, capture.output(sessionInfo()),
  paste("reference", reference, unname(tools::md5sum(reference))),
  paste("candidate", unname(tools::md5sum(file.path(root,
    "src/nipat_scientific/dnp_blocks.R"))))), file.path(out, "reader-environment.txt"))
deep_path <- make_file(512L, 6000L, file.path(out, "reader-benchmark-deep.pileup"))
short_path <- make_file(20000L, 4L)
cat("Generated fixtures", deep_path, short_path, "\n")
Rprof(file.path(out, "index-deep-profile.out"), interval = 0.01)
deep <- old$nipat_dnp_index(deep_path)
Rprof(NULL)
saveRDS(deep, file.path(out, "reader-benchmark-deep-index.rds"))
profile <- summaryRprof(file.path(out, "index-deep-profile.out"))
cat("INDEX_DEEP", deep$bytes / 1024^2, "MiB", deep$elapsed_seconds, "s\n")
write.csv(profile$by.self, file.path(out, "index-profile-self.csv"))
print(head(profile$by.self, 18))
write.csv(profile$by.total, file.path(out, "index-profile-total.csv"))
print(head(profile$by.total, 18))
short <- old$nipat_dnp_index(short_path)
cat("INDEX_SHORT", short$bytes / 1024^2, "MiB", short$elapsed_seconds, "s\n")
results <- rbind(bench("deep_contiguous", deep, seq_len(deep$rows)),
                 bench("short_contiguous", short, seq_len(short$rows)),
                 bench("short_gapped", short, seq(1L, short$rows, by = 2L)))
write.csv(results, file.path(out, "reader-range-benchmark.csv"), row.names = FALSE)
write.csv(do.call(rbind, allocations), file.path(out, "reader-allocations.csv"), row.names = FALSE)
write.csv(do.call(rbind, ranges), file.path(out, "reader-ranges.csv"), row.names = FALSE)
print(aggregate(elapsed_seconds ~ case + method, results, median))
unlink(short_path)
if (mode != "--keep-fixtures") {
  unlink(c(deep_path, file.path(out, "reader-benchmark-deep-index.rds")))
}
