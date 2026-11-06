# Execute the complete CLI script unchanged, retaining unrounded scientific data.
# Paths come from the environment so commandArgs() remains the native interface.
.nipat_eq_records <- list()
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
    }
    value
  }
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
  "cpi" = .nipat_eq_records,
  stop("Unknown workflow"))
saveRDS(.nipat_eq_value, "/results/scientific-values.rds", compress = FALSE, version = 3)
