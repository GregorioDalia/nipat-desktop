# Presentation regression: bin membership, missing data, pagination and rendering.
# The runner passes the read-only repository mount; cwd holds result artifacts.
arguments <- commandArgs(trailingOnly = TRUE)
if (length(arguments) != 1L) stop("Expected one repository root argument")
repository <- normalizePath(arguments[[1L]], mustWork = TRUE)
source(file.path(repository, "src/nipat_scientific/plots.R"))
suppressPackageStartupMessages(library(ggplot2))
suppressPackageStartupMessages(library(ComplexUpset))
stopifnot(all(c(0, 1) %in% nipat_integer_breaks(c(-0.05, 1.05))))
classes <- nipat_count_classes(c(0, 1, 5, 6, 10, 11, NA))
stopifnot(identical(as.character(classes$class), c("0", "1-5", "6-10", "11-15", "Missing (NA)")),
          identical(classes$Freq, c(1L, 2L, 2L, 1L, 1L)), sum(classes$Freq) == 7L)
for (values in list(numeric(), c(0, 0), c(NA_real_, NA_real_), c(0, NA_real_))) {
  counted <- nipat_count_classes(values)
  expected_labels <- c("0", if (anyNA(values)) "Missing (NA)")
  stopifnot(sum(counted$Freq) == length(values), identical(as.character(counted$class), expected_labels))
  built <- ggplot2::ggplot_build(nipat_read_count_plot(values, "Synthetic", "steelblue", "SNP"))
  stopifnot(sum(built$data[[1]]$y) == length(values))
}
large <- nipat_count_classes(c(0, 1, 5, 6, 1000000))
stopifnot(nrow(large) <= 81L, sum(large$Freq) == 5L, attr(large, "bin_width") > 5)
for (invalid in list(c(-1, 0), c(1.5), c(Inf), c(-Inf))) {
  stopifnot(inherits(try(nipat_count_classes(invalid), silent = TRUE), "try-error"))
}
final <- data.frame(chr = "chrSynthetic", pos = seq_len(73), REF = "A", ALT = "C",
                    N_REF = rep(c(0L, 1L, 5L, 6L, 10L, 11L), length.out = 73),
                    N_ALT = 0L, N_Other = 0L,
                    GT = rep(c("0/0", "0/1", "1/1", NA_character_), length.out = 73))
merged <- final[, c("chr", "pos", "REF", "ALT", "GT")]
names(merged)[[5]] <- "GT_sample_0001"
merged$GT_sample_0002 <- rev(final$GT)
original <- serialize(merged, NULL)
pages <- nipat_unassigned_pages(merged)
stopifnot(length(pages) == 3L, identical(vapply(pages, function(x) nrow(x$data), 1L), c(35L, 35L, 3L)),
          sum(vapply(pages, function(x) sum(x$data$count), 1.0)) == sum(is.na(merged[, 5:6])))
directory <- Sys.getenv("NIPAT_PLOT_TEST_OUTPUT", unset = tempfile("nipat-plots-"))
dir.create(directory, recursive = TRUE, showWarnings = FALSE)
nipat_sample_plots(final, file.path(directory, "sample"), "sample_0001")
nipat_genotype_summary(merged, file.path(directory, "summary"))
stopifnot(identical(serialize(merged, NULL), original))
files <- c(file.path(directory, "sample", paste0("sample_0001_",
             c("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"), ".pdf")),
           file.path(directory, "summary", c("Unassigned_genotypes.pdf", "SNPs_covered_UpSet_plot.pdf")))
stopifnot(length(files) == 6L, all(file.exists(files)))
for (path in files) {
  con <- file(path, "rb")
  signature <- readChar(con, 5L, useBytes = TRUE)
  close(con)
  stopifnot(signature == "%PDF-", file.info(path)$size > 1000)
}
# Multi-page CPI layout keeps all panels and never creates one unbounded page.
cpi <- nipat_cpi_pages(rep(list(pages[[1]]), 9L))
stopifnot(length(cpi) == 3L)
ggsave(file.path(directory, "CPI_pages.pdf"), cpi, width = 12, height = 10)
cat("PASS: exact zero/edge bins; missing/empty/high-depth counts; complete bounded pagination; six SNP PDFs and CPI pages.\n")
cat("Plot regression artifacts:", directory, "\n")
