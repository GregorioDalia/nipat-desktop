#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(argparse)
  library(dplyr)
  library(ggplot2)
})

parser <- ArgumentParser(description="Postnatal CPI from SNPcall or DNPcall trio outputs")
parser$add_argument("--pileup_dir", required=TRUE)
parser$add_argument("--out_dir", required=TRUE)
parser$add_argument("--trios", required=TRUE,
                    help="mother:father:child identifiers, separated by commas")
parser$add_argument("--mother_prefix", default="full_output_")
parser$add_argument("--father_prefix", default="full_output_")
parser$add_argument("--child_prefix", default="full_output_")
parser$add_argument("--popfreq", required=TRUE)
parser$add_argument("--markers", required=FALSE)
parser$add_argument("--min_child_reads", type="double", default=2,
                    help="Minimum child reads supporting each called allele [default: 2]")
parser$add_argument("--err_const_snp", default="0.001")
parser$add_argument("--err_const_dnp", default="0.0000892303778101497")
parser$add_argument("--site_selection", choices=c("other_allele", "all", "both"),
                    default="both",
                    help="other_allele: heterozygous children; all: all compatible children; both: compare both [default: both]")
args <- parser$parse_args()
analyses <- switch(args$site_selection,
  other_allele="heterozygous_child_sites",
  all="all_compatible_sites",
  both=c("heterozygous_child_sites", "all_compatible_sites"))
message("Site selection: ", args$site_selection)

if (!is.finite(args$min_child_reads) || args$min_child_reads < 1 ||
    args$min_child_reads != floor(args$min_child_reads) ||
    args$min_child_reads >= .Machine$integer.max) {
  stop("--min_child_reads must be a positive integer below the R integer limit")
}
min_child_reads <- as.integer(args$min_child_reads)
if (dir.exists(args$out_dir) && length(list.files(args$out_dir, all.files=TRUE,
                                                no..=TRUE))) {
  stop("Output directory is not empty; choose a new --out_dir")
}
dir.create(args$out_dir, recursive=TRUE, showWarnings=FALSE)

trio_parts <- strsplit(args$trios, ",", fixed=TRUE)[[1]]
trios <- lapply(trio_parts, function(z) trimws(strsplit(z, ":", fixed=TRUE)[[1]]))
if (!length(trios) || any(lengths(trios) != 3L) ||
    any(!nzchar(unlist(trios))) || anyDuplicated(trio_parts)) {
  stop("--trios must be mother:father:child entries separated by commas")
}
if (any(!grepl("^[A-Za-z0-9_.-]+$", unlist(trios)))) {
  stop("Identifiers may contain letters, digits, underscores, dots and hyphens")
}
if (any(vapply(trios, function(z) anyDuplicated(z) > 0, logical(1)))) {
  stop("Mother, father and child identifiers must be distinct in each trio")
}

## Read coordinates from the frequency table and use them in every join.
if (!file.exists(args$popfreq)) stop("popfreq file not found")
population <- read.table(args$popfreq, header=TRUE, sep="\t",
                         stringsAsFactors=FALSE, check.names=FALSE,
                         quote="", comment.char="")

marker_type <- function(x, label) {
  has_snp <- "pos" %in% names(x)
  has_dnp <- all(c("pos1", "pos2") %in% names(x))
  if (has_snp == has_dnp) {
    stop(label, ": use either pos for SNPs or pos1 and pos2 for DNPs")
  }
  if (has_snp) "SNP" else "DNP"
}

has_markers <- !is.null(args$markers) && nzchar(trimws(args$markers))
marker_list <- NULL
marker <- marker_type(population, "population frequencies")
if (has_markers) {
  # DNPcall lists have five columns without a header; SNPcall lists have four.
  # A header is also accepted, with lower- or upper-case allele column names.
  marker_list <- read.table(args$markers, header=FALSE, sep="", quote="",
                            comment.char="", colClasses="character",
                            stringsAsFactors=FALSE, check.names=FALSE)
  marker_columns <- switch(as.character(ncol(marker_list)),
    "4" = c("chr", "pos", "REF", "ALT"),
    "5" = c("chr", "pos1", "pos2", "REF", "ALT"),
    stop("Marker list must contain four SNP columns or five DNP columns")
  )
  first_row <- unlist(marker_list[1, ], use.names=FALSE)
  if (identical(tolower(first_row), tolower(marker_columns))) {
    marker_list <- marker_list[-1, , drop=FALSE]
  }
  names(marker_list) <- marker_columns
  if (!nrow(marker_list)) stop("Marker list is empty")
  marker <- marker_type(marker_list, "marker list")
  if (marker_type(population, "population frequencies") != marker) {
    stop("Population frequency coordinates do not match the marker list format")
  }
}
message("Panel: ", if (has_markers) args$markers else "all calling-output sites")
site_columns <- if (marker == "SNP") c("chr", "pos") else c("chr", "pos1", "pos2")
message("Marker type: ", marker)

# Select the constant for the detected marker type.
read_error_constant <- function(value, option) {
  if (is.null(value)) return(NULL)
  number <- suppressWarnings(as.numeric(value))
  if (length(number) != 1L || !is.finite(number) || number <= 0 || number > 1) {
    stop(option, " must be a finite number in (0, 1], for example 1e-04")
  }
  number
}

error_constants <- list(
  SNP = read_error_constant(args$err_const_snp, "--err_const_snp"),
  DNP = read_error_constant(args$err_const_dnp, "--err_const_dnp")
)
err_const <- error_constants[[marker]]
message("Mismatch constant used for ", marker, ": ", sprintf("%.17g", err_const))

site_key <- function(x) {
  do.call(paste, c(unname(as.list(x[site_columns])), sep="\t"))
}

check_sites <- function(x, required, label) {
  missing <- setdiff(required, names(x))
  if (length(missing)) stop(label, ": missing columns ", paste(missing, collapse=", "))
  if (anyNA(x[site_columns]) || anyDuplicated(site_key(x))) {
    stop(label, ": missing or duplicate coordinates")
  }
}

if (has_markers) {
  check_sites(marker_list, marker_columns, "marker list")
  for (column in setdiff(site_columns, "chr")) {
    position <- suppressWarnings(as.numeric(marker_list[[column]]))
    if (any(!is.finite(position) | position < 1 | position != floor(position))) {
      stop("Marker list positions must be positive integers")
    }
    marker_list[[column]] <- position
  }
  marker_list$REF <- toupper(marker_list$REF)
  marker_list$ALT <- toupper(marker_list$ALT)
  allele_pattern <- if (marker == "SNP") "^[ACGT]$" else "^[ACGT]{2}$"
  if (anyNA(marker_list[c("REF", "ALT")]) ||
      any(!grepl(allele_pattern, marker_list$REF) |
          !grepl(allele_pattern, marker_list$ALT) |
          marker_list$REF == marker_list$ALT)) {
    stop("Marker list must contain distinct REF and ALT alleles for the selected marker type")
  }
  # Check again after converting positions, so equivalent coordinates cannot repeat.
  check_sites(marker_list, marker_columns, "marker list")
  
}

check_sites(population, c(site_columns, "Ref_f.pop", "Alt_f.pop"),
            "population frequencies")
population$chr <- as.character(population$chr)
if (has_markers) {
  frequency_index <- match(site_key(marker_list), site_key(population))
  if (anyNA(frequency_index)) {
    missing_sites <- site_key(marker_list)[is.na(frequency_index)]
    stop("Missing population frequencies for marker-list sites: ",
         paste(head(missing_sites, 5), collapse=", "))
  }
  population <- population[frequency_index, , drop=FALSE]
  if (all(c("REF", "ALT") %in% names(population))) {
    if (anyNA(population[c("REF", "ALT")]) ||
        any(toupper(population$REF) != marker_list$REF |
            toupper(population$ALT) != marker_list$ALT)) {
      stop("Population frequency alleles differ from the marker list")
    }
  }
}
population$Ref_f.pop <- as.numeric(gsub(",", ".", population$Ref_f.pop))
population$Alt_f.pop <- as.numeric(gsub(",", ".", population$Alt_f.pop))
if (any(!is.finite(population$Ref_f.pop) | !is.finite(population$Alt_f.pop) |
        population$Ref_f.pop <= 0 | population$Ref_f.pop > 1 |
        population$Alt_f.pop <= 0 | population$Alt_f.pop > 1)) {
  stop("Population frequencies must be finite and in (0, 1]")
}

# Keep allele columns outside the join to avoid REF and ALT suffix conflicts.
population_for_join <- population[, c(site_columns, "Ref_f.pop", "Alt_f.pop"), drop=FALSE]

read_calls <- function(path) {
  x <- read.table(path, header=TRUE, check.names=FALSE, stringsAsFactors=FALSE)
  if (marker_type(x, path) != marker) stop(path, ": format differs from population frequencies")
  check_sites(x, c(site_columns, "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count"), path)
  x$chr <- as.character(x$chr)
  if (has_markers) {
    # Restrict all downstream calculations to the supplied marker list.
    x <- x[site_key(x) %in% site_key(marker_list), , drop=FALSE]
    j <- match(site_key(x), site_key(marker_list))
    if (anyNA(x[c("REF", "ALT")]) ||
        any(toupper(x$REF) != marker_list$REF[j] |
            toupper(x$ALT) != marker_list$ALT[j])) {
      stop(path, ": alleles differ from the marker list")
    }
  }
  expected_length <- if (marker == "SNP") 1L else 2L
  if (anyNA(x[c("REF", "ALT")]) ||
      any(nchar(x$REF) != expected_length | nchar(x$ALT) != expected_length |
          toupper(x$REF) == toupper(x$ALT))) {
    stop(path, ": invalid REF or ALT alleles")
  }
  # Older DNP frequency tables have no REF or ALT columns.
  if (all(c("REF", "ALT") %in% names(population))) {
    j <- match(site_key(x), site_key(population))
    present <- which(!is.na(j))
    if (anyNA(population[j[present], c("REF", "ALT"), drop=FALSE])) {
      stop("Population frequencies contain missing alleles")
    }
    if (any(toupper(x$REF[present]) != toupper(population$REF[j[present]]) |
            toupper(x$ALT[present]) != toupper(population$ALT[j[present]]))) {
      stop(path, ": alleles differ from population frequencies")
    }
  }
  x
}

# Genotype intervals follow the cfDNA script. Intermediate ratios are unassigned.
classify_genotype <- function(ratio) {
  gt <- rep(NA_character_, length(ratio))
  gt[is.finite(ratio) & ratio >= 0.9] <- "0/0"
  gt[is.finite(ratio) & ratio <= 0.1] <- "1/1"
  gt[is.finite(ratio) & ratio >= 0.4 & ratio <= 0.6] <- "0/1"
  gt
}

# Apply the same Other/total filter separately to every sample.
passes_quality <- function(ref, alt, other, total) {
  ratio <- other / total
  total > 0 & (ref + alt) > 0 & is.finite(ratio) & ratio <= 0.10
}
stopifnot(identical(passes_quality(c(90,89,0), c(0,0,0), c(10,11,0),
                                  c(100,100,0)), c(TRUE,FALSE,FALSE)))

select_sites <- function(x, analysis) {
  x$Status == "eligible" &
    (analysis == "all_compatible_sites" | x$GT_child %in% "0/1")
}
selection_test <- data.frame(Status=c("eligible", "eligible", "quality_filter"),
                             GT_child=c("0/1", "0/0", "0/1"))
stopifnot(identical(select_sites(selection_test, "heterozygous_child_sites"),
                    c(TRUE,FALSE,FALSE)),
          identical(select_sites(selection_test, "all_compatible_sites"),
                    c(TRUE,TRUE,FALSE)))

prepare_sample <- function(id, prefix, role) {
  path <- file.path(args$pileup_dir, paste0(prefix, id, ".txt"))
  x <- read_calls(path)
  pattern <- if (marker == "SNP") "^[ACGT]$" else "^[ACGT]{2}$"
  if (any(!grepl(pattern, toupper(x$REF)) | !grepl(pattern, toupper(x$ALT)))) {
    stop(path, ": alleles must contain only A, C, G and T")
  }
  count_columns <- c("N_REF", "N_ALT", "N_Other", "total_count")
  if (any(!vapply(x[count_columns], is.numeric, logical(1)))) {
    stop(path, ": read counts must be numeric")
  }
  # DNPcall can report NA total_count at sites with no reads.
  # Correct this representation in memory and retain an internal flag.
  x$Missing_total_at_zero_coverage <- is.na(x$total_count) &
    !is.na(x$N_REF) & !is.na(x$N_ALT) & !is.na(x$N_Other) &
    x$N_REF == 0 & x$N_ALT == 0 & x$N_Other == 0
  if (any(x$Missing_total_at_zero_coverage)) {
    message(path, ": ", sum(x$Missing_total_at_zero_coverage),
            " zero-coverage site(s) with missing total_count; treated as zero coverage")
    x$total_count[x$Missing_total_at_zero_coverage] <- 0
  }
  counts <- as.matrix(x[count_columns])
  if (anyNA(counts) || any(!is.finite(counts) | counts < 0 | counts != floor(counts))) {
    stop(path, ": counts must be nonnegative finite integers")
  }
  if (any(x$total_count != x$N_REF + x$N_ALT + x$N_Other)) {
    stop(path, ": total_count differs from REF + ALT + Other")
  }
  x$ratio <- x$N_REF / (x$N_REF + x$N_ALT)
  x$GT <- classify_genotype(x$ratio)
  x$Other_ratio <- x$N_Other / x$total_count
  x$Quality_pass <- passes_quality(x$N_REF, x$N_ALT, x$N_Other, x$total_count)
  x$Present <- TRUE
  x <- x[c(site_columns, "REF", "ALT", count_columns, "ratio", "GT",
           "Other_ratio", "Quality_pass", "Present", "Missing_total_at_zero_coverage")]
  names(x)[!names(x) %in% site_columns] <- paste0(
    names(x)[!names(x) %in% site_columns], "_", role)
  x
}

# With a homozygous mother, the compatible child's genotype identifies one
# obligatory paternal allele, even when mother and child are both homozygous.
site_pi <- function(required, father_gt, ref_frequency, alt_frequency, epsilon) {
  frequency <- ifelse(required == "REF", ref_frequency, alt_frequency)
  transmission <- ifelse(father_gt == "0/1", 0.5,
    ifelse((required == "REF" & father_gt == "0/0") |
           (required == "ALT" & father_gt == "1/1"), 1, 0))
  mismatch <- transmission == 0
  weight <- ifelse(mismatch, epsilon, transmission)
  list(PI=weight / frequency, Mismatch=mismatch,
       Frequency=frequency, Transmission=transmission)
}

# Basic genotype and formula checks.
stopifnot(identical(classify_genotype(c(1, 0.9, 0.6, 0.5, 0.4, 0.1, 0, 0.3, NaN)),
                    c("0/0", "0/0", "0/1", "0/1", "0/1", "1/1", "1/1", NA_character_, NA_character_)))
# Include homozygous children and paternal mismatches.
test <- site_pi(c("ALT", "ALT", "REF", "REF"),
                c("1/1", "0/1", "0/0", "1/1"),
                rep(0.6, 4), rep(0.4, 4), 0.001)
stopifnot(isTRUE(all.equal(test$PI, c(2.5, 1.25, 1/0.6, 0.001/0.6))),
          identical(test$Mismatch, c(FALSE, FALSE, FALSE, TRUE)))

summary_rows <- list()
all_plots <- list()
plots_dir <- file.path(args$out_dir, "plots")
dir.create(plots_dir, recursive=TRUE, showWarnings=FALSE)
for (ids in trios) {
  trio_name <- paste0("Mother", ids[1], "-Father", ids[2], "-Child", ids[3],
                      "_", marker, "s")
  message("Processing ", trio_name)
  mother <- prepare_sample(ids[1], args$mother_prefix, "mother")
  father <- prepare_sample(ids[2], args$father_prefix, "father")
  child <- prepare_sample(ids[3], args$child_prefix, "child")
  x <- full_join(full_join(mother, father, by=site_columns), child, by=site_columns)
  if (has_markers) {
    x <- full_join(marker_list[site_columns], x, by=site_columns)
  }

  # Check all shared allele definitions, including sites without frequencies.
  for (pair in list(c("mother", "father"), c("mother", "child"), c("father", "child"))) {
    for (allele in c("REF", "ALT")) {
      a <- x[[paste0(allele, "_", pair[1])]]
      b <- x[[paste0(allele, "_", pair[2])]]
      if (any(!is.na(a) & !is.na(b) & toupper(a) != toupper(b))) {
        stop(trio_name, ": inconsistent allele definitions between samples")
      }
    }
  }
  x <- left_join(x, population_for_join, by=site_columns)
  x$REF <- coalesce(x$REF_mother, x$REF_father, x$REF_child)
  x$ALT <- coalesce(x$ALT_mother, x$ALT_father, x$ALT_child)
  if (has_markers) {
    panel_index <- match(site_key(x), site_key(marker_list))
    x$REF <- coalesce(x$REF, marker_list$REF[panel_index])
    x$ALT <- coalesce(x$ALT, marker_list$ALT[panel_index])
  }
  m <- x$GT_mother
  cgt <- x$GT_child
  x$Mother_homozygous <- !is.na(m) & m %in% c("0/0", "1/1")
  x$Mother_child_incompatible <- x$Mother_homozygous & !is.na(cgt) &
    ((m == "0/0" & cgt == "1/1") | (m == "1/1" & cgt == "0/0"))
  x$Required_paternal_allele <- case_when(
    m == "0/0" & cgt == "0/1" ~ "ALT",
    m == "1/1" & cgt == "0/1" ~ "REF",
    m == "0/0" & cgt == "0/0" ~ "REF",
    m == "1/1" & cgt == "1/1" ~ "ALT",
    TRUE ~ NA_character_)
  x$Child_support <- ifelse(x$Required_paternal_allele == "REF",
                            x$N_REF_child, x$N_ALT_child)
  x$Child_called_alleles_supported <- case_when(
    cgt == "0/1" ~ x$N_REF_child >= min_child_reads & x$N_ALT_child >= min_child_reads,
    cgt == "0/0" ~ x$N_REF_child >= min_child_reads,
    cgt == "1/1" ~ x$N_ALT_child >= min_child_reads,
    TRUE ~ FALSE)
  x$Status <- case_when(
    is.na(x$Present_mother) | is.na(x$Present_father) | is.na(x$Present_child) ~ "missing_call",
    !x$Quality_pass_mother | !x$Quality_pass_father | !x$Quality_pass_child ~ "quality_filter",
    !x$Mother_homozygous ~ "mother_not_homozygous",
    is.na(cgt) ~ "child_unassigned",
    !x$Child_called_alleles_supported ~ "insufficient_child_support",
    x$Mother_child_incompatible ~ "mother_child_incompatible",
    is.na(x$GT_father) ~ "father_unassigned",
    is.na(x$Ref_f.pop) | is.na(x$Alt_f.pop) ~ "missing_population_frequency",
    TRUE ~ "eligible")

  eligible <- x$Status == "eligible"
  x$Paternity_Index <- NA_real_
  x$Mismatch <- NA
  x$Paternal_transmission <- NA_real_
  if (any(eligible)) {
    pi <- site_pi(x$Required_paternal_allele[eligible], x$GT_father[eligible],
                  x$Ref_f.pop[eligible], x$Alt_f.pop[eligible], err_const)
    x$Paternity_Index[eligible] <- pi$PI
    x$Mismatch[eligible] <- pi$Mismatch
    x$Paternal_transmission[eligible] <- pi$Transmission
  }
  for (analysis in analyses) {
    retained <- select_sites(x, analysis)
    sites <- x[retained, , drop=FALSE]

    # Sum logs directly to avoid numerical underflow of the product.
    log_cpi <- if (nrow(sites)) sum(log10(sites$Paternity_Index)) else NA_real_
    cpi <- if (is.na(log_cpi)) NA_real_ else 10^log_cpi
    summary_rows[[length(summary_rows) + 1L]] <- data.frame(
      Trio=trio_name, Marker_type=marker, Analysis=analysis,
      N_sites=nrow(sites),
      N_heterozygous_child_sites=sum(sites$GT_child == "0/1"),
      N_homozygous_child=sum(sites$GT_child %in% c("0/0", "1/1")),
      Matching_sites=sum(sites$Mismatch %in% FALSE),
      Mismatching_sites=sum(sites$Mismatch %in% TRUE),
      Log10_CPI=log_cpi, CPI=cpi, Error_constant=err_const,
      Min_child_reads=min_child_reads)

    if (nrow(sites)) {
      thresholds <- seq.int(min_child_reads, max(sites$Child_support))
      curve <- bind_rows(lapply(thresholds, function(t) {
        use <- sites$Child_support >= t
        data.frame(Min_child_reads=t, N_sites=sum(use),
                   Log10_CPI=sum(log10(sites$Paternity_Index[use])),
                   Matching_sites=sum(!sites$Mismatch[use]),
                   Mismatching_sites=sum(sites$Mismatch[use]))
      }))
      # Keep the left axis on the CPI scale. Map counts onto it for display
      # and recover their original values on the right axis.
      cpi_range <- range(c(curve$Log10_CPI, -4, 4), finite=TRUE)
      count_max <- max(c(curve$Matching_sites, curve$Mismatching_sites, 1))
      count_scale <- diff(cpi_range) / count_max
      count_offset <- cpi_range[1]
      plot_data <- curve
      plot_data$Plot_matching <- curve$Matching_sites * count_scale + count_offset
      plot_data$Plot_mismatching <- curve$Mismatching_sites * count_scale + count_offset
      count_axis <- local({
        scale <- count_scale
        offset <- count_offset
        function(y) (y - offset) / scale
      })
      x_ticks <- pretty(c(min_child_reads, max(thresholds)), n=6)
      x_ticks <- sort(unique(c(min_child_reads,
        x_ticks[x_ticks >= min_child_reads & x_ticks <= max(thresholds)])))

      plot <- ggplot(plot_data, aes(x=Min_child_reads)) +
        annotate("rect", xmin=-Inf, xmax=Inf, ymin=-Inf, ymax=-4,
                 fill="red", alpha=0.08) +
        annotate("rect", xmin=-Inf, xmax=Inf, ymin=-4, ymax=4,
                 fill="grey85", alpha=1) +
        annotate("rect", xmin=-Inf, xmax=Inf, ymin=4, ymax=Inf,
                 fill="green", alpha=0.08) +
        geom_hline(yintercept=c(-4, 4), colour="grey50",
                   linetype="dotted", linewidth=0.4) +
        geom_line(aes(y=Log10_CPI), colour="black") +
        geom_point(aes(y=Log10_CPI), colour="black", size=1.3) +
        geom_line(aes(y=Plot_matching), colour="green") +
        geom_line(aes(y=Plot_mismatching),
                  colour="orange", linetype="dashed") +
        # Draw the test marker last so the black curve cannot cover it.
        geom_vline(xintercept=min_child_reads, colour="red",
                   linetype="dashed", linewidth=1) +
        annotate("point", x=min_child_reads, y=log_cpi,
                 shape=21, size=3, stroke=1, colour="red", fill="white") +
        annotate("label", x=Inf, y=Inf,
                 label=sprintf("Test log10(CPI): %.3f\nSites: %d; minimum reads: %d",
                               log_cpi, nrow(sites), min_child_reads),
                 hjust=1.05, vjust=1.10, size=3, fill="white", colour="black") +
        scale_y_continuous(name=expression(log[10](CPI)),
          sec.axis=sec_axis(count_axis,
                            name="Matching / mismatching sites"),
          expand=expansion(mult=c(0.02, 0.14))) +
        scale_x_continuous(
          name="Minimum child reads supporting the obligatory paternal allele",
          breaks=x_ticks,
          limits=c(min_child_reads, max(min_child_reads + 1, max(thresholds))),
          expand=expansion(mult=c(0.03, 0.02))) +
        labs(title=paste(trio_name, analysis, sep=" — ")) +
        theme_bw(base_size=9) +
        theme(plot.title=element_text(size=9, hjust=0),
              axis.title=element_text(size=8),
              axis.text.x=element_text(angle=45, hjust=1, size=7),
              panel.border=element_rect(colour="black", fill=NA, linewidth=0.6),
              plot.margin=margin(8,12,8,8))
    } else {
      curve <- data.frame(Min_child_reads=integer(), N_sites=integer(),
                          Log10_CPI=numeric(), Matching_sites=integer(),
                          Mismatching_sites=integer())
      plot <- ggplot() + theme_void() +
        labs(title=paste(trio_name, analysis, "— no eligible sites"))
    }
    ggsave(file.path(plots_dir, paste0(trio_name, "_", analysis, "_CPIplot.pdf")),
           plot, width=10, height=4)
    all_plots[[length(all_plots) + 1L]] <- plot
  }
}
summary <- bind_rows(summary_rows)
write.table(summary, file.path(args$out_dir, "Summary_Postnatal_CPI.txt"),
            sep="\t", quote=FALSE, row.names=FALSE, na="NA")

pdf(file.path(args$out_dir, "All_CPIplots.pdf"), width=10, height=4)
for (plot in all_plots) print(plot)
dev.off()
message("Done: tab-separated summary and PDF plots saved.")
