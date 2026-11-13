#!/usr/bin/env Rscript
# Compare indexed planning to the former complete-panel scan (b7ffbd6).
# Optional second argument is a benchmark locus count; timings never gate CI.
arguments <- commandArgs(trailingOnly=TRUE)
root <- normalizePath(arguments[[1L]], mustWork=TRUE)
source(file.path(root, "src/nipat_scientific/dnp_blocks.R"))

reference_plan <- function(index, labels, ref_alt, max_loci=64, max_bytes=32*1024^2) {
  keys <- paste(index$chromosomes[index$chromosome], index$positions, sep=":")
  by_coordinate <- split(seq_along(keys), keys)
  effective <- unique(ref_alt$POS)
  groups <- lapply(effective, function(key) which(ref_alt$POS == key))
  blocks <- list()
  active_ids <- active_rows <- integer()
  append_block <- function() {
    if (length(active_ids)) blocks[[length(blocks)+1L]] <<- list(
      locus_ids=active_ids, row_ids=sort(active_rows), raw_bytes=sum(index$lengths[active_rows]))
  }
  for (ids in groups) {
    coordinates <- unique(labels$df.chr[labels$uniq %in% ids])
    rows <- unique(unlist(by_coordinate[coordinates], use.names=FALSE))
    if (is.null(rows)) rows <- integer()
    combined <- union(active_rows, rows)
    if (length(active_ids) && (length(active_ids)+length(ids) > max_loci ||
                              sum(index$lengths[combined]) > max_bytes)) {
      append_block()
      active_ids <- active_rows <- integer()
      combined <- rows
    }
    active_ids <- c(active_ids, ids)
    active_rows <- combined
  }
  append_block()
  list(blocks=blocks, max_loci=max_loci, max_bytes=max_bytes,
       compatibility_reasons=character(), unmatched_rows=0L)
}

fixture <- function(count) {
  p <- 10L * seq_len(count)
  list(index=list(chromosomes="chr1", chromosome=rep(1L,4L*count),
    positions=c(p-1L,p,p+1L,p+2L), lengths=rep(100,4L*count), repeated_qname_rows=0L),
    labels=data.frame(df.chr=paste0("chr1:",c(p-1L,p,p+1L,p+2L)), uniq=rep(seq_len(count),4L)),
    ref_alt=data.frame(POS=paste0("chr1:",p,"|chr1:",p+1L)))
}

check <- function(data, loci, bytes) {
  expected <- do.call(reference_plan,c(data,list(max_loci=loci,max_bytes=bytes)))
  actual <- do.call(nipat_dnp_plan,c(data,list(max_loci=loci,max_bytes=bytes)))
  stopifnot(identical(actual,expected))
}

data <- fixture(64L)
for (loci in c(1,3,64)) for (bytes in c(1,800,100000)) check(data,loci,bytes)
# Duplicated effective locus IDs remain indivisible; sparse/overlapping windows
# and labels in non-locus order retain the original raw row and locus order.
data$ref_alt$POS[c(13,22)] <- data$ref_alt$POS[2]
data$labels$df.chr[data$labels$uniq == 13] <- data$labels$df.chr[data$labels$uniq == 2]
data$labels$df.chr[data$labels$uniq == 22] <- data$labels$df.chr[data$labels$uniq == 2]
available <- which(paste0("chr1:",data$index$positions) %in% data$labels$df.chr)[seq_len(40)]
for (field in c("chromosome","positions","lengths")) data$index[[field]] <- data$index[[field]][available]
data$labels <- data$labels[rev(seq_len(nrow(data$labels))),]
for (loci in c(1,7,64)) for (bytes in c(1,800,100000)) check(data,loci,bytes)
cat("PASS: 18 exact DNP block-planning comparisons.\n")

if (length(arguments) > 1L) {
  count <- as.integer(arguments[[2L]])
  stopifnot(!is.na(count), count > 0)
  data <- fixture(count)
  timings <- data.frame(iteration=integer(), reference_seconds=numeric(), indexed_seconds=numeric())
  for (iteration in seq_len(3L)) {
    order <- if (iteration %% 2L) c("reference","indexed") else c("indexed","reference")
    elapsed <- numeric(); results <- list()
    for (name in order) {
      fun <- if (name == "reference") reference_plan else nipat_dnp_plan
      elapsed[name] <- unname(system.time(results[[name]] <- do.call(fun,data))["elapsed"])
    }
    stopifnot(identical(results$reference,results$indexed))
    timings <- rbind(timings,data.frame(iteration=iteration,
      reference_seconds=elapsed[["reference"]],indexed_seconds=elapsed[["indexed"]]))
  }
  print(timings,row.names=FALSE)
  cat("Loci:",count,"; identical plans in all three alternating benchmark repetitions.\n")
}
