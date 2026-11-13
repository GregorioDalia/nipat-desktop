#!/usr/bin/env Rscript
# Presentation-only adapter. The reviewed scientific R file is sourced unchanged.
# Original plots are saved normally; additional copies replace text grob labels.
# No expressions, counts, likelihoods, data columns, or plotting coordinates change.

local({
config_path <- if (file.exists("presentation-config.json")) {
  "presentation-config.json"
} else {
  file.path("work", "presentation-config.json")
}
if (!file.exists(config_path)) stop("NIPAT presentation configuration is missing")
config <- jsonlite::fromJSON(config_path, simplifyVector = FALSE)
if (!identical(config$schema_version, 1L)) stop("Invalid NIPAT presentation schema")

replacements <- unlist(config$replacements, use.names = TRUE)
tokens <- names(replacements)
# A single pass prevents labels containing another internal ID being rewritten.
tokens <- tokens[order(nchar(tokens), decreasing = TRUE)]
escape_regex <- function(x) {
  chars <- strsplit(x, "", fixed = TRUE)[[1]]
  special <- c("\\", ".", "^", "$", "|", "(", ")", "[", "]", "{", "}", "*", "+", "?")
  paste0(ifelse(chars %in% special, paste0("\\", chars), chars), collapse = "")
}
pattern <- paste0("(?<![[:alnum:]_])(?:", paste(vapply(tokens, escape_regex, ""), collapse = "|"), ")(?![[:alnum:]_])")
replace_label <- function(values) {
  if (!is.character(values) || !length(tokens)) return(values)
  vapply(values, function(value) {
    if (is.na(value)) return(value)
    matches <- gregexpr(pattern, value, perl = TRUE)[[1]]
    if (matches[1] < 0) return(value)
    lengths <- attr(matches, "match.length")
    pieces <- character()
    cursor <- 1L
    for (index in seq_along(matches)) {
      start <- matches[index]
      finish <- start + lengths[index] - 1L
      if (start > cursor) pieces <- c(pieces, substr(value, cursor, start - 1L))
      pieces <- c(pieces, replacements[[substr(value, start, finish)]])
      cursor <- finish + 1L
    }
    if (cursor <= nchar(value)) pieces <- c(pieces, substr(value, cursor, nchar(value)))
    paste0(pieces, collapse = "")
  }, "", USE.NAMES = FALSE)
}
wrap_label <- function(label, width) {
  # strwrap alone does not split long, unspaced instrument-generated filenames.
  vapply(label, function(value) {
    if (is.na(value)) return(value)
    lines <- character()
    while (nchar(value) > width) {
      lines <- c(lines, substr(value, 1L, width))
      value <- substring(value, width + 1L)
    }
    paste(c(lines, value), collapse = "\n")
  }, "", USE.NAMES = FALSE)
}
present_plot <- function(plot) {
  maximum_lines <- 1L
  text <- function(label) {
    if (!is.character(label)) return(label)
    presented <- replace_label(label)
    if (!identical(presented, label) && config$workflow %in% c("cpi", "cpin")) {
      # Full names remain in sample-map.tsv and readable tables. Very long
      # custom pair labels get an explicit display-only ellipsis, preventing
      # a title alone from exceeding a readable PDF page.
      presented <- ifelse(nchar(presented) > 800L,
                          paste0(substr(presented, 1L, 797L), "..."), presented)
      presented <- wrap_label(presented, 50L)
      maximum_lines <<- max(maximum_lines, vapply(strsplit(presented, "\n", fixed = TRUE), length, 1L))
    }
    presented
  }
  walk <- function(value) {
    # Labels alone are copied. Data, layers, scales, statistics and coordinates
    # remain the original objects. Rebuilding the grob recomputes title heights.
    for (name in c("title", "subtitle", "caption")) value$labels[[name]] <- text(value$labels[[name]])
    if (inherits(value, "patchwork")) {
      value$patches$plots <- lapply(value$patches$plots, walk)
      for (name in c("title", "subtitle", "caption")) {
        value$patches$annotation[[name]] <- text(value$patches$annotation[[name]])
      }
    }
    value
  }
  result <- walk(plot)
  list(plot = result, maximum_lines = maximum_lines)
}
replace_grob <- function(grob, skip_label = FALSE) {
  if (!skip_label && !is.null(grob$label) && is.character(grob$label)) grob$label <- replace_label(grob$label)
  if (!is.null(grob$grobs)) {
    grob$grobs <- lapply(seq_along(grob$grobs), function(index) {
      # Titles were processed before layout. Never rewrite their new names a
      # second time if an original filename itself contains an internal alias.
      title <- !is.null(grob$layout) && grepl("^(title|subtitle|caption)(-|$)", grob$layout$name[index])
      replace_grob(grob$grobs[[index]], skip_label || title)
    })
  }
  if (!is.null(grob$children)) {
    children <- lapply(grob$children, replace_grob, skip_label = skip_label)
    grob$children <- do.call(grid::gList, children)
    names(grob$children) <- names(children)
  }
  grob
}

display_ggsave <- function(filename, plot = ggplot2::last_plot(), ...) {
  # Keep the native artifact exactly as requested by the scientific script.
  result <- ggplot2::ggsave(filename = filename, plot = plot, ...)
  native <- normalizePath(filename, mustWork = TRUE)
  prefix <- paste0(normalizePath(config$output, mustWork = TRUE), "/")
  if (!startsWith(native, prefix)) stop("Scientific plot escaped its output directory")
  relative <- substring(native, nchar(prefix) + 1L)
  item <- config$plots[[relative]]
  if (is.null(item)) stop(paste("No display mapping for scientific plot", relative))
  page_sources <- if (inherits(plot, "nipat_plot_pages")) unclass(plot) else list(plot)
  presented <- lapply(page_sources, present_plot)
  grobs <- lapply(presented, function(page) {
    grob <- if (inherits(page$plot, "patchwork")) {
      patchwork::patchworkGrob(page$plot)
    } else {
      ggplot2::ggplotGrob(page$plot)
    }
    replace_grob(grob)
  })
  extra_height <- 0
  if (config$workflow %in% c("cpi", "cpin")) {
    # Four cutoff panels per page, at most two rows. The number of pairs no
    # longer makes a PDF page arbitrarily tall.
    maximum_lines <- max(vapply(presented, function(page) page$maximum_lines, 1L))
    extra_height <- max(0, maximum_lines - 1L) * 0.18 * 2L
  }
  if (!is.null(item$sample)) {
    label <- wrap_label(config$samples[[item$sample]], 110L)
    caption <- grid::textGrob(label, gp = grid::gpar(fontsize = 10))
    extra_height <- length(strsplit(label, "\n", fixed = TRUE)[[1]]) * 0.18 + 0.1
    grobs <- lapply(grobs, function(grob) {
      grob <- gtable::gtable_add_rows(grob, grid::unit(extra_height, "in"), pos = 0)
      gtable::gtable_add_grob(grob, caption, t = 1, l = 1, r = ncol(grob), clip = "off")
    })
  }
  options <- list(...)
  options$device <- NULL
  if (extra_height > 0) {
    if (!is.null(options$units) && !identical(options$units, "in")) stop("Unexpected scientific plot units")
    if (!is.numeric(options$height)) stop("Scientific plot height is required")
    options$height <- options$height + extra_height
  }
  displayed <- if (inherits(plot, "nipat_plot_pages")) nipat_plot_pages(grobs) else grobs[[1]]
  do.call(ggplot2::ggsave, c(list(filename = file.path(config$directory, item$target),
                                 plot = displayed, device = grDevices::cairo_pdf), options))
  invisible(result)
}
# Preserve the native global execution environment (DNPcall explicitly updates
# .GlobalEnv for memory accounting); keep adapter state private in this closure.
assign("ggsave", display_ggsave, envir = globalenv())
sys.source(config$script, envir = globalenv(), keep.source = FALSE)
# SNPcall 2.0 exposes a sourcable core for differential tests; its standalone
# guard deliberately does not execute when loaded through this adapter.
if (identical(config$workflow, "snp-call")) {
  get("nipat_snp_main", envir = globalenv(), inherits = FALSE)()
}
})
