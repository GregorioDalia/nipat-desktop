# Execute the complete CLI script unchanged, retaining unrounded scientific data.
# Paths come from the environment so commandArgs() remains the native interface.
.nipat_eq_records <- list()
.nipat_eq_capture_dir <- "/results/cpi-capture"
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
for (.nipat_eq_expression in parse(.nipat_eq_script, keep.source = TRUE)) {
  eval(.nipat_eq_expression, envir = .GlobalEnv)
  if (.nipat_eq_workflow == "cpi" && is.call(.nipat_eq_expression) &&
      identical(.nipat_eq_expression[[1]], as.name("<-")) &&
      identical(.nipat_eq_expression[[2]], as.name("run_CPI_iteration"))) {
    run_CPI_iteration <- .nipat_eq_wrap_cpi(run_CPI_iteration)
  }
}

.nipat_eq_value <- switch(.nipat_eq_workflow,
  "dnp-call" = list(samples = lapply(results, function(result) {
    list(final = result$final, genotypes = result$indiv_final)
  }), summary = final_merged_data),
  "snp-call" = dataframe_final,
  "contamination" = contamination_summary,
  "cpi" = .nipat_eq_cpi_records(),
  stop("Unknown workflow"))
saveRDS(.nipat_eq_value, "/results/scientific-values.rds", compress = FALSE, version = 3)
