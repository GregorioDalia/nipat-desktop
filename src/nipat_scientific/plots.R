# NIPAT 0.8.30: shared, presentation-only plots. Scientific tables are never
# changed. Counts include zero, missing values are explicit, and PDF pages have
# bounded dimensions rather than growing by one inch per locus/sample.

nipat_count_classes <- function(values, max_bins = 80L) {
  if (!is.numeric(values) || any(!is.na(values) &
      (!is.finite(values) | values < 0 | values != floor(values)))) {
    stop("Read counts must be non-negative whole numbers or NA")
  }
  if (length(max_bins) != 1L || is.na(max_bins) || max_bins < 1L) {
    stop("max_bins must be positive")
  }
  maximum <- if (any(!is.na(values))) max(values, na.rm = TRUE) else 0
  # Keep five-read classes for ordinary data. At high depth, widen classes
  # explicitly instead of allocating millions of bars or hiding an overflow bin.
  width <- max(5, ceiling(maximum / (5 * max_bins)) * 5)
  bins <- if (maximum > 0) ceiling(maximum / width) else 0
  starts <- if (bins) seq_len(bins) * width - width + 1 else numeric()
  positive_labels <- if (bins > 0) {
    paste0(format(starts, scientific = FALSE, trim = TRUE), "-",
           format(starts + width - 1, scientific = FALSE, trim = TRUE))
  } else character()
  labels <- c("0", positive_labels)
  indices <- ifelse(is.na(values), NA_real_, ifelse(values == 0, 1, ceiling(values / width) + 1))
  frequencies <- tabulate(as.numeric(indices), nbins = length(labels))
  if (anyNA(values)) {
    labels <- c(labels, "Missing (NA)")
    frequencies <- c(frequencies, sum(is.na(values)))
  }
  result <- data.frame(class = factor(labels, levels = labels, ordered = TRUE),
                       Freq = as.integer(frequencies))
  attr(result, "bin_width") <- width
  result
}

nipat_integer_breaks <- function(limits) {
  values <- pretty(limits)
  unique(round(values[is.finite(values) & values >= 0 & abs(values - round(values)) < 1e-8]))
}

nipat_plot_pages <- function(pages) {
  if (!length(pages)) stop("A plot document requires at least one page")
  structure(pages, class = c("nipat_plot_pages", "list"))
}

grid.draw.nipat_plot_pages <- function(x, recording = TRUE) {
  for (number in seq_along(x)) {
    if (number > 1L) grid::grid.newpage()
    page <- x[[number]]
    if (inherits(page, "patchwork")) page <- patchwork::patchworkGrob(page)
    else if (inherits(page, "ggplot")) page <- ggplot2::ggplotGrob(page)
    grid::grid.draw(page, recording = recording)
  }
  invisible(x)
}

nipat_read_count_plot <- function(values, title, colour, locus_kind) {
  counts <- nipat_count_classes(values)
  width <- attr(counts, "bin_width")
  ticks <- unique(c(1L, if (nrow(counts) > 1L) seq.int(2L, nrow(counts), by = max(1L, ceiling(nrow(counts) / 20L))), nrow(counts)))
  ticks <- ticks[ticks <= nrow(counts)]
  ggplot2::ggplot(counts, ggplot2::aes(x = class, y = Freq)) +
    ggplot2::geom_col(fill = colour, colour = "black", linewidth = 0.2, width = 0.9) +
    ggplot2::labs(title = title, x = "Reads per locus (inclusive intervals)",
      y = paste0("Number of ", locus_kind, " loci"),
      caption = paste0("Zero counts are shown separately; positive class width: ",
                       format(width, scientific = FALSE, trim = TRUE), " reads. Missing counts, if any, have a separate bar.")) +
    ggplot2::scale_x_discrete(breaks = as.character(counts$class[ticks]), drop = FALSE) +
    ggplot2::scale_y_continuous(breaks = nipat_integer_breaks, expand = ggplot2::expansion(mult = c(0, 0.08))) +
    ggplot2::theme_minimal(base_size = 11) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 60, hjust = 1, size = 8),
                   plot.caption = ggplot2::element_text(hjust = 0, size = 8))
}

nipat_sample_plots <- function(final, directory, sample, locus_kind = "SNP") {
  stopifnot(all(c("GT", "N_REF", "N_ALT", "N_Other") %in% names(final)))
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  observed <- as.character(final$GT)
  observed[is.na(observed)] <- "Unassigned (NA)"
  levels <- unique(c("0/0", "0/1", "1/1", "Unassigned (NA)", observed))
  counts <- as.data.frame(table(factor(observed, levels = levels)), stringsAsFactors = FALSE)
  names(counts) <- c("Genotype", "Loci")
  plot <- ggplot2::ggplot(counts, ggplot2::aes(x = Genotype, y = Loci)) +
    ggplot2::geom_col(fill = "steelblue", width = 0.75) +
    ggplot2::scale_x_discrete(drop = FALSE) +
    ggplot2::scale_y_continuous(breaks = nipat_integer_breaks, expand = ggplot2::expansion(mult = c(0, 0.08))) +
    ggplot2::labs(title = "Genotype assignments", x = "Genotype", y = paste0("Number of ", locus_kind, " loci"),
      caption = "Unassigned (NA) includes loci without sufficient usable evidence and calls excluded by the scientific model.") +
    ggplot2::theme_minimal(base_size = 11) +
    ggplot2::theme(plot.caption = ggplot2::element_text(hjust = 0, size = 8))
  ggsave(file.path(directory, paste0(sample, "_N_genotypes.pdf")), plot = plot, width = 11, height = 5, device = grDevices::cairo_pdf)
  specifications <- list(
    list("N_REF", "Reference read counts", "green3", "Ref_read_count"),
    list("N_ALT", "Alternative read counts", "red3", "Alt_read_count"),
    list("N_Other", "Other read counts", "steelblue", "Other_read_count"))
  for (specification in specifications) {
    plot <- nipat_read_count_plot(final[[specification[[1]]]], specification[[2]], specification[[3]], locus_kind)
    ggsave(file.path(directory, paste0(sample, "_", specification[[4]], ".pdf")), plot = plot, width = 11, height = 5, device = grDevices::cairo_pdf)
  }
  invisible(NULL)
}

nipat_unassigned_pages <- function(merged, locus_kind = "SNP", per_page = 35L) {
  gt_columns <- grep("^GT_", names(merged), value = TRUE)
  if (!length(gt_columns)) stop("Genotype summary requires GT_<sample> columns")
  labels <- if (identical(locus_kind, "DNP")) {
    paste0(merged$chr, ":", merged$pos1, "-", merged$pos2)
  } else paste(merged$chr, merged$pos, sep = ":")
  counts <- rowSums(is.na(merged[, gt_columns, drop = FALSE]))
  groups <- split(seq_len(nrow(merged)), ceiling(seq_len(nrow(merged)) / per_page))
  if (!length(groups)) groups <- list(integer())
  pages <- lapply(seq_along(groups), function(number) {
    selected <- groups[[number]]
    frame <- data.frame(locus = factor(labels[selected], levels = unique(labels[selected])), count = counts[selected])
    ggplot2::ggplot(frame, ggplot2::aes(x = locus, y = count)) +
      ggplot2::geom_col(fill = "steelblue2", width = 0.8) +
      ggplot2::scale_y_continuous(limits = c(0, max(1L, length(gt_columns))), breaks = nipat_integer_breaks) +
      ggplot2::labs(title = "Unassigned genotypes", x = paste0(locus_kind, " locus"), y = "Samples with unassigned genotype (NA)",
        subtitle = paste0("Page ", number, " of ", length(groups), " | ", length(gt_columns), " sample(s)")) +
      ggplot2::theme_minimal(base_size = 11) +
      ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 60, hjust = 1, size = 8))
  })
  nipat_plot_pages(pages)
}

nipat_genotype_summary <- function(merged, directory, locus_kind = "SNP") {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  ggsave(file.path(directory, "Unassigned_genotypes.pdf"),
         plot = nipat_unassigned_pages(merged, locus_kind), width = 12, height = 6, device = grDevices::cairo_pdf)
  gt_columns <- grep("^GT_", names(merged), value = TRUE)
  if (length(gt_columns) >= 2L) {
    binary <- as.data.frame(lapply(merged[, gt_columns, drop = FALSE], function(x) !is.na(x)))
    names(binary) <- sub("^GT_", "", gt_columns)
    plot <- ComplexUpset::upset(binary, intersect = names(binary), min_size = 0,
      name = paste0(locus_kind, "s with assigned GT"),
      base_annotations = list("Intersection size" = ComplexUpset::intersection_size() +
        ggplot2::scale_y_continuous(breaks = nipat_integer_breaks)),
      set_sizes = ComplexUpset::upset_set_size() + ggplot2::scale_y_continuous(
        breaks = function(limits) {
          values <- pretty(limits)
          unique(round(values[is.finite(values) & abs(values - round(values)) < 1e-8]))
        }, labels = function(values) abs(values))) +
      patchwork::plot_annotation(caption = paste(
        "Intersections count loci with the indicated assigned genotypes.",
        "An empty intersection means no sample has an assigned genotype.", sep = "\n"))
    ggsave(file.path(directory, paste0(locus_kind, "s_covered_UpSet_plot.pdf")),
           plot = plot, width = min(20, max(12, 8 + length(gt_columns) * 0.6)),
           height = min(20, max(6, 4 + length(gt_columns) * 0.3)), device = grDevices::cairo_pdf)
  }
  invisible(NULL)
}

nipat_cpi_pages <- function(plots, per_page = 4L) {
  groups <- split(seq_along(plots), ceiling(seq_along(plots) / per_page))
  nipat_plot_pages(lapply(groups, function(indices) {
    patchwork::wrap_plots(plots[indices], ncol = min(2L, length(indices)))
  }))
}

# Standalone batch renderer. Sourcing this helper does not execute the CLI.
if (sys.nframe() == 0L) {
  suppressPackageStartupMessages(library(ggplot2))
  args <- commandArgs(trailingOnly = TRUE)
  option <- function(name, required = TRUE) {
    index <- match(name, args)
    if (is.na(index) || index == length(args)) {
      if (required) stop(paste("Missing argument", name))
      return(NULL)
    }
    args[[index + 1L]]
  }
  table <- read.delim(option("--table"), quote = "", comment.char = "", check.names = FALSE,
                      stringsAsFactors = FALSE, colClasses = "character", na.strings = "NA")
  labels_path <- option("--labels", FALSE)
  if (!is.null(labels_path)) {
    labels <- read.delim(labels_path, quote = "\"", comment.char = "", check.names = FALSE,
                        stringsAsFactors = FALSE, colClasses = "character", na.strings = character())
    if (!all(c("internal_id", "display_name") %in% names(labels)) || anyDuplicated(labels$internal_id)) stop("Invalid sample labels")
    old <- paste0("GT_", labels$internal_id)
    names(table)[match(old, names(table), nomatch = 0L)] <- paste0("GT_", labels$display_name)[old %in% names(table)]
  }
  nipat_genotype_summary(table, option("--out"), "SNP")
}
