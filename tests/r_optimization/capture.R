# Execute the complete CLI script unchanged, retaining unrounded scientific data.
# Paths come from the environment so commandArgs() remains the native interface.
.nipat_eq_records <- list()
.nipat_eq_results <- Sys.getenv("NIPAT_EQ_RESULTS", unset = "/results")
.nipat_eq_capture_dir <- file.path(.nipat_eq_results, "cpi-capture")
dir.create(.nipat_eq_capture_dir, showWarnings = FALSE)
.nipat_eq_capture_counter <- 0L
# Retain the already computed pileup only for the differential audit. Intercept
# exactly the historical final cleanup command; all samtools execution and R
# computation still use the original source and arguments.
if (identical(Sys.getenv("NIPAT_EQ_KEEP_PILEUP"), "1")) {
  system <- function(command, ...) {
    if (identical(command, "rm mpileup.txt")) return(invisible(0L))
    base::system(command, ...)
  }
}
.nipat_eq_wrap_cpi <- function(original) {
  force(original)
  function(madre_df, padre_df, dnp_list, cutoff_label, err_const) {
    inputs <- list(madre_df, padre_df, dnp_list, cutoff_label, err_const)
    value <- original(madre_df, padre_df, dnp_list, cutoff_label, err_const)
    matches <- which(vapply(.nipat_eq_records,
      function(record) identical(record$inputs, inputs), logical(1)))
    if (length(matches)) {
      stopifnot(identical(.nipat_eq_records[[matches[1]]]$value, value))
    } else {
      .nipat_eq_records[[length(.nipat_eq_records) + 1L]] <<-
        list(inputs = inputs, value = value)
      # Forked workers inherit this wrapper but not subsequent parent memory.
      # Each process writes a distinct audit record after the real calculation;
      # scientific inputs, values and output files are never rewritten here.
      .nipat_eq_capture_counter <<- .nipat_eq_capture_counter + 1L
      saveRDS(list(inputs = inputs, value = value), file.path(
        .nipat_eq_capture_dir, paste0(Sys.getpid(), "-", .nipat_eq_capture_counter, ".rds")),
        compress = FALSE, version = 3)
    }
    value
  }
}

.nipat_eq_cpi_records <- function() {
  records <- lapply(sort(list.files(.nipat_eq_capture_dir, full.names = TRUE,
                                   pattern = "\\.rds$")), readRDS)
  unique_records <- list()
  for (record in records) {
    matches <- which(vapply(unique_records,
      function(previous) identical(previous$inputs, record$inputs), logical(1)))
    if (length(matches)) {
      stopifnot(identical(unique_records[[matches[1L]]]$value, record$value))
    } else {
      unique_records[[length(unique_records) + 1L]] <- record
    }
  }
  # Invocation completion order is not a scientific output. Canonicalize only
  # this audit record list by complete serialized inputs; all numeric values,
  # classes, attributes and ordering within each result remain untouched.
  keys <- vapply(unique_records, function(record) paste(sprintf("%02x",
    as.integer(serialize(record$inputs, NULL, version = 3))), collapse = ""), character(1))
  unique_records[order(keys, method = "radix")]
}

.nipat_eq_script <- Sys.getenv("NIPAT_EQ_SCRIPT")
.nipat_eq_workflow <- Sys.getenv("NIPAT_EQ_WORKFLOW")
stopifnot(nzchar(.nipat_eq_script), nzchar(.nipat_eq_workflow))
if (.nipat_eq_workflow == "snp-call") {
  # The frozen 2.0 file has an unconditional native BAM-list entry point.
  # Evaluate its definitions unchanged, excluding only that final invocation;
  # the candidate is safely sourceable and uses the same call_sample interface.
  expressions <- parse(.nipat_eq_script, keep.source = TRUE)
  for (expression in expressions) {
    if (identical(expression, quote(main()))) next
    if (is.call(expression) && identical(expression[[1]], as.name("if")) &&
        grepl("sys.nframe", paste(deparse(expression), collapse = " "), fixed = TRUE)) next
    eval(expression, envir = .GlobalEnv)
  }
  arguments <- commandArgs(trailingOnly = TRUE)
  value_for <- function(name) {
    index <- match(name, arguments)
    stopifnot(!is.na(index), index < length(arguments))
    arguments[index + 1L]
  }
  pileup <- value_for("--pileup")
  panel_path <- value_for("--snplist")
  if (file.info(pileup)$size > 0L) {
    dataframe_final <- call_sample(pileup, panel_path)
  } else if (grepl("tests/reference_r/2.0/", .nipat_eq_script, fixed = TRUE)) {
    # Literal fallback from the upstream BAM worker (lines507-514), which is
    # outside call_sample. No counts or estimates are inferred here.
    panel <- readr::read_tsv(panel_path, col_types=readr::cols(.default=readr::col_character()),
                             show_col_types=FALSE)
    dataframe_final <- data.frame(chr=panel$chr,pos=as.integer(panel$pos),
      REF=toupper(panel$ref),ALT=toupper(panel$alt),N_REF=0L,N_ALT=0L,
      N_Other=0L,total_count=0L,ratio=NA_real_,GL0=NA_real_,GL1=NA_real_,
      GL2=NA_real_,GT=NA_character_,reads_discarded_for_indels=NA_integer_,
      ratio_reads_discarded_for_indels=NA_real_,
      combined_bases=NA_character_,combined_counts=NA_character_)
  } else {
    dataframe_final <- call_sample(pileup, panel_path)
  }
  write.table(dataframe_final, value_for("--out"), sep="\t", quote=FALSE, row.names=FALSE)
} else {
for (.nipat_eq_expression in parse(.nipat_eq_script, keep.source = TRUE)) {
  eval(.nipat_eq_expression, envir = .GlobalEnv)
  if (.nipat_eq_workflow == "cpi" && is.call(.nipat_eq_expression) &&
      identical(.nipat_eq_expression[[1]], as.name("<-")) &&
      identical(.nipat_eq_expression[[2]], as.name("run_CPI_iteration"))) {
    run_CPI_iteration <- .nipat_eq_wrap_cpi(run_CPI_iteration)
  }
}

}

# The historical DNP plotting code mutates final_merged_data by appending
# NA_count/DNP_name after exporting the canonical genotype table. Revised
# plotting keeps those derived presentation fields separate. Exclude only these
# two known plot fields on both sides; all canonical values/types remain exact.
.nipat_eq_value <- switch(.nipat_eq_workflow,
  "dnp-call" = list(samples = lapply(results, function(result) {
    list(final = result$final, genotypes = result$indiv_final)
  }), summary = final_merged_data[, setdiff(names(final_merged_data),
      c("NA_count", "DNP_name")), drop = FALSE]),
  "snp-call" = dataframe_final,
  "contamination" = contamination_summary,
  "cpi" = .nipat_eq_cpi_records(),
  stop("Unknown workflow"))
saveRDS(.nipat_eq_value, file.path(.nipat_eq_results, "scientific-values.rds"), compress = FALSE, version = 3)
