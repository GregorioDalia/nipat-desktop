#!/usr/bin/env Rscript
# Full-table differential tests against the byte-identical SNPcall 2.0 core.
arguments <- commandArgs(trailingOnly = TRUE)
if (length(arguments) != 1L) stop("Expected one repository root argument")
repository <- normalizePath(arguments[[1L]], mustWork = TRUE)
Sys.setenv(NIPAT_PARALLEL_HELPER = file.path(repository, "src/nipat_scientific/parallel.R"))
load_core <- function(path, upstream = FALSE) {
  environment <- new.env(parent = globalenv())
  expressions <- parse(file = path)
  if (upstream) expressions <- Filter(function(x) !identical(x, quote(main())), expressions)
  for (expression in expressions) eval(expression, environment)
  environment
}
reference <- load_core(file.path(repository, "tests/reference_r/2.0/SNPcall.R"), TRUE)
candidate <- load_core(file.path(repository, "scientific/vendor/NEWPAT/SNPcall/SNPcall.R"))
root <- tempfile("snp2-regression-")
dir.create(root)
row <- function(position, bases, names, qualities = NULL, chromosome = "chr1", extra = NULL) {
  count <- length(strsplit(names, ",", fixed = TRUE)[[1L]])
  if (is.null(qualities)) qualities <- paste(rep("I", count), collapse = "")
  paste(c(chromosome, position, "A", count, bases, qualities, names, extra), collapse = "\t")
}
window <- function(center, center_bases, names, qualities = NULL, chromosome = "chr1") {
  count <- length(strsplit(names, ",", fixed = TRUE)[[1L]])
  flank <- paste(rep(".", count), collapse = "")
  c(row(center - 1L, flank, names, chromosome = chromosome),
    row(center, center_bases, names, qualities, chromosome),
    row(center + 1L, flank, names, chromosome = chromosome))
}
panel <- function(positions = 50L, chromosome = "chr1") {
  data.frame(chr = chromosome, pos = positions, ref = "A", alt = "G")
}
names_100 <- paste(sprintf("read_%03d", seq_len(100L)), collapse = ",")
base_cases <- list(
  ordinary = list(panel(), window(50L, ".,gT", "a,B,r@skip,shared")),
  shared_distant_windows = list(panel(c(50L, 120L)), c(
    window(50L, "..GG", "a,b,c,shared"), window(120L, "GG..", "a,b,c,shared"))),
  shared_overlapping_windows = list(panel(c(50L, 51L)),
    vapply(49:52, function(p) row(p, ".G", "shared1,shared2"), "")),
  mixed_qualities = list(panel(), window(50L, "....GG", "a,b,c,d,e,f", "!#5I?~")),
  other_below_threshold = list(panel(), window(50L,
    paste0(strrep("A", 81L), strrep("G", 10L), strrep("T", 9L)), names_100)),
  other_at_threshold = list(panel(), window(50L,
    paste0(strrep("A", 80L), strrep("G", 10L), strrep("T", 10L)), names_100)),
  reference_only = list(panel(), window(50L, "....", "a,b,c,d")),
  alternative_only = list(panel(), window(50L, "GGGG", "a,b,c,d")),
  other_only = list(panel(), window(50L, "TTTT", "a,b,c,d")),
  center_and_flank_indels = list(panel(), c(
    row(49L, "..*..", "a,b,c,d,e"), row(50L, "AG.A+1A-2", "a,b,c,d,e"),
    row(51L, ".....", "a,b,c,d,e"))),
  incomplete_reads = list(panel(), c(
    row(49L, "...", "complete,left,single"), row(50L, "GG.", "complete,left,right"),
    row(51L, ".G", "complete,right"))),
  absent_panel_locus = list(panel(c(50L, 120L)), window(50L, "..GG", "a,b,c,d")),
  off_panel_observations = list(panel(), c(window(50L, "..GG", "a,b,c,d"),
    window(120L, "TTTT", "a,b,c,d"))),
  optional_columns = list(panel(), vapply(49:51, function(p)
    row(p, "..GG", "a,b,c,d", extra = c("unused text", 123, "NA")), "")),
  numeric_qnames = list(panel(chromosome = "1"),
    window(50L, "..G", "100,101,102", chromosome = "1")),
  coordinate_at = list(panel(chromosome = "chr@1"),
    window(50L, ".G", "a,b", chromosome = "chr@1")),
  empty_qname = list(panel(), window(50L, ".G.", "a,,b")),
  missing_qname = list(panel(), window(50L, ".", "NA")),
  whitespace_qname = list(panel(), window(50L, ".G", "read name,b")),
  unicode_qnames = list(panel(), window(50L, ".G", "\u00e9,Z")),
  invalid_quality_length = list(panel(), window(50L, "..G", "a,b,c", "II")),
  duplicate_read_observations = list(panel(), window(50L, "..G", "a,a,b")),
  interleaved_groups = list(panel(c(50L, 51L, 120L)), c(
    vapply(49:52, function(p) row(p, strrep(".G", 50L), names_100), ""),
    window(120L, strrep("G.", 50L), names_100)))
)
configurations <- list(serial = c("serial", "4"), auto2 = c("auto", "2"),
                       auto4 = c("auto", "4"), repeat4 = c("auto", "4"))
evaluate <- function(environment, pileup, snplist) {
  tryCatch({
    invisible(capture.output(result <- suppressMessages(suppressWarnings(
      environment$call_sample(pileup, snplist)))))
    list(ok = TRUE, result = result)
  }, error = function(error) list(ok = FALSE, message = conditionMessage(error)))
}
original_locale <- Sys.getlocale("LC_COLLATE")
comparisons <- 0L
results <- list()
for (locale in unique(c(original_locale, "C", "C.UTF-8"))) {
  selected <- suppressWarnings(Sys.setlocale("LC_COLLATE", locale))
  if (!nzchar(selected)) next
  for (name in names(base_cases)) {
    case <- base_cases[[name]]
    snplist <- file.path(root, paste0(name, ".tsv"))
    pileup <- file.path(root, paste0(name, ".pileup"))
    write.table(case[[1L]], snplist, quote = FALSE, sep = "\t", row.names = FALSE)
    writeLines(case[[2L]], pileup, useBytes = TRUE)
    expected <- evaluate(reference, pileup, snplist)
    for (configuration in configurations) {
      Sys.setenv(NIPAT_EXECUTION_MODE = configuration[[1L]], NIPAT_MAX_WORKERS = configuration[[2L]])
      actual <- evaluate(candidate, pileup, snplist)
      if (expected$ok != actual$ok || (expected$ok && !identical(expected$result, actual$result))) {
        print(list(reference = expected, candidate = actual))
        stop("SNP 2.0 mismatch: ", name, " / ", locale, " / ", paste(configuration, collapse = ":"))
      }
      comparisons <- comparisons + 1L
    }
    if (!expected$ok && !name %in% c("whitespace_qname", "invalid_quality_length", "duplicate_read_observations"))
      stop("Unexpected oracle failure: ", name, ": ", expected$message)
    results[[name]] <- expected$result
  }
}
Sys.setlocale("LC_COLLATE", original_locale)
# Independent assertions prevent an accidentally empty oracle comparison.
stopifnot(results$shared_distant_windows$total_count == c(4L, 4L))
stopifnot(results$shared_overlapping_windows$total_count == c(2L, 2L))
stopifnot(results$other_below_threshold$GT == "0/1", is.na(results$other_at_threshold$GT))
stopifnot(results$reference_only$GT == "0/0", results$alternative_only$GT == "1/1")
stopifnot(is.na(results$other_only$GT), is.na(results$other_only$GL0))
stopifnot(results$center_and_flank_indels$N_REF == 1L,
          results$center_and_flank_indels$N_ALT == 1L,
          results$center_and_flank_indels$reads_discarded_for_indels == 2L,
          results$center_and_flank_indels$ratio_reads_discarded_for_indels == 2 / 5)
# Empty whole-sample input uses the upstream worker fallback, including NA
# indel statistics; the upstream call_sample itself never receives this input.
empty <- file.path(root, "empty.pileup")
file.create(empty)
snplist <- file.path(root, "empty.tsv")
write.table(panel(c(50L, 120L)), snplist, sep = "\t", quote = FALSE, row.names = FALSE)
zero <- candidate$call_sample(empty, snplist)
stopifnot(identical(zero$total_count, c(0L, 0L)), all(is.na(zero$GT)),
          all(is.na(zero$ratio)), all(is.na(zero$reads_discarded_for_indels)))
writeLines("chr1\t50\tA\t0\t*\t*\t*", empty)
stopifnot(identical(zero, candidate$call_sample(empty, snplist)))
legacy <- file.path(root, "legacy.tsv")
writeLines(c("pos\tref\talt", "chr1:50\tA\tG"), legacy)
ordinary <- file.path(root, "reference_only.pileup")
stopifnot(identical(results$reference_only, candidate$call_sample(ordinary, legacy)))
# readr's own thread pool must respect the same serial/resource budget.
settings <- options(readr.num_threads = 8L)
trace("read_tsv", where = asNamespace("readr"), print = FALSE,
      tracer = quote(stopifnot(identical(num_threads, 1L))))
invisible(candidate$call_sample(ordinary, legacy))
untrace("read_tsv", where = asNamespace("readr"))
options(settings)
unlink(root, recursive = TRUE)
cat("PASS SNP 2.0 tables:", comparisons, "strict oracle comparisons and edge assertions\n")
