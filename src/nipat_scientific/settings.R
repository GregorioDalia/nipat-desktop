# Scientific configuration shared with the Python client and engine.
# The registry is the single source of defaults, constraints and documentation.
.nipat_settings_source <- tryCatch(sys.frame(1)$ofile, error=function(e) NULL)
.nipat_settings_helper <- Sys.getenv("NIPAT_SETTINGS_HELPER", unset="")
if (!nzchar(.nipat_settings_helper)) {
  .nipat_parallel_helper <- Sys.getenv("NIPAT_PARALLEL_HELPER", unset="")
  .nipat_settings_helper <- if (nzchar(.nipat_parallel_helper))
    file.path(dirname(.nipat_parallel_helper), "settings.R") else
      if (!is.null(.nipat_settings_source)) .nipat_settings_source else
        "/opt/nipat/lib/nipat_scientific/settings.R"
}
.nipat_settings_registry <- Sys.getenv("NIPAT_SETTINGS_REGISTRY",
  unset=file.path(dirname(.nipat_settings_helper), "settings_data.json"))

nipat_settings <- function(workflow) {
  registry <- jsonlite::fromJSON(.nipat_settings_registry, simplifyVector=FALSE)
  if (!identical(registry$schema_version, 1L) || is.null(registry$workflows[[workflow]]))
    stop("Unknown scientific settings workflow: ", workflow)
  definitions <- registry$workflows[[workflow]]$parameters
  values <- lapply(definitions, function(x) x$default)
  path <- Sys.getenv("NIPAT_SCIENTIFIC_SETTINGS", unset="")
  if (nzchar(path)) {
    supplied <- jsonlite::fromJSON(path, simplifyVector=FALSE)
    if (!identical(supplied$schema_version, 1L) || !identical(supplied$workflow, workflow) ||
        !is.list(supplied$parameters)) stop("Scientific settings identity mismatch")
    unknown <- setdiff(names(supplied$parameters), names(definitions))
    if (length(unknown)) stop("Unknown scientific parameter: ", paste(unknown, collapse=", "))
    for (name in names(supplied$parameters)) values[[name]] <- supplied$parameters[[name]]
  }
  nipat_validate_settings(workflow, values)
}

nipat_validate_settings <- function(workflow, values) {
  registry <- jsonlite::fromJSON(.nipat_settings_registry, simplifyVector=FALSE)
  if (!identical(registry$schema_version, 1L) || is.null(registry$workflows[[workflow]]))
    stop("Unknown scientific settings workflow: ", workflow)
  definitions <- registry$workflows[[workflow]]$parameters
  if (!is.list(values) || !setequal(names(values), names(definitions)))
    stop("Effective scientific parameters must include exactly the declared fields")
  for (name in names(definitions)) {
    spec <- definitions[[name]]
    value <- values[[name]]
    if (length(value) != 1L || is.na(value)) stop("Invalid scientific parameter: ", name)
    valid <- switch(spec$type, boolean=is.logical(value), string=is.character(value),
      integer=is.integer(value) && is.finite(value),
      number=is.numeric(value) && is.finite(value), FALSE)
    if (!valid) stop("Invalid scientific parameter type: ", name)
    if (!is.null(spec$minimum) && (value < spec$minimum ||
        (isTRUE(spec$exclusive_minimum) && value == spec$minimum)))
      stop("Scientific parameter below minimum: ", name)
    if (!is.null(spec$maximum) && value > spec$maximum)
      stop("Scientific parameter above maximum: ", name)
    if (!is.null(spec$choices) && !value %in% unlist(spec$choices))
      stop("Unknown scientific parameter choice: ", name)
  }
  if (!is.null(values$heterozygous_min)) {
    if (!(values$homozygous_alt_max < values$heterozygous_min &&
          values$heterozygous_min <= values$heterozygous_max &&
          values$heterozygous_max < values$homozygous_ref_min))
      stop("Overlapping genotype intervals")
  } else if (!is.null(values$homozygous_alt_max) &&
             values$homozygous_alt_max >= values$homozygous_ref_min) {
    stop("Overlapping homozygous intervals")
  }
  if (!is.null(values$log_cpi_lower) && values$log_cpi_lower >= values$log_cpi_upper)
    stop("Invalid logCPI plot guide order")
  if (isTRUE(values$redo_baq) && !isTRUE(values$baq)) stop("redo_baq requires baq=true")
  values
}

# Native R invocations may explicitly override values from the engine settings
# file. Write the final values after applying those arguments, before analysis.
nipat_write_settings <- function(workflow, values, out_dir) {
  values <- nipat_validate_settings(workflow, values)
  registry <- jsonlite::fromJSON(.nipat_settings_registry, simplifyVector=FALSE)
  document <- list(schema_version=1L, workflow=workflow, parameters=values,
                   constants=registry$workflows[[workflow]]$constants)
  dir.create(out_dir, recursive=TRUE, showWarnings=FALSE)
  if (!dir.exists(out_dir)) stop("Cannot create scientific settings output directory")
  target <- file.path(out_dir, "scientific-settings.json")
  link <- Sys.readlink(target)
  linked <- !is.na(link) && nzchar(link)
  if (file.exists(target) || linked) {
    if (linked) stop("Scientific settings output cannot be a symbolic link")
    existing <- jsonlite::fromJSON(target, simplifyVector=FALSE)
    if (!isTRUE(all.equal(existing, document)))
      stop("Different scientific settings already exist in output directory")
    return(invisible(target))
  }
  temporary <- tempfile(".scientific-settings-", tmpdir=out_dir)
  on.exit(unlink(temporary), add=TRUE)
  jsonlite::write_json(document, temporary, auto_unbox=TRUE, pretty=TRUE,
                      digits=NA, null="null", na="null")
  if (!file.link(temporary, target)) stop("Cannot claim scientific settings output file")
  invisible(target)
}
