#!/usr/bin/env Rscript
# The configurable Other threshold changes GT only, including its exact boundary.
root <- normalizePath(commandArgs(TRUE)[[1]], mustWork=TRUE)
Sys.setenv(NIPAT_PARALLEL_HELPER=file.path(root, "src/nipat_scientific/parallel.R"),
           NIPAT_SETTINGS_HELPER=file.path(root, "src/nipat_scientific/settings.R"),
           NIPAT_SETTINGS_REGISTRY=file.path(root, "src/nipat_scientific/settings_data.json"),
           NIPAT_EXECUTION_MODE="serial")
Sys.unsetenv("NIPAT_SCIENTIFIC_SETTINGS")
source(Sys.getenv("NIPAT_SETTINGS_HELPER"))
suppressPackageStartupMessages(library(tidyverse))
check_threshold <- function(environment, run) {
  environment$nipat_cfg$other_fraction_max <- 0.1
  boundary <- suppressMessages(run())
  environment$nipat_cfg$other_fraction_max <- 0.11
  relaxed <- suppressMessages(run())
  stopifnot(nrow(boundary) == 1L, is.na(boundary$GT), !is.na(relaxed$GT),
            boundary$N_REF == 8L, boundary$N_ALT == 1L, boundary$N_Other == 1L,
            identical(boundary[, setdiff(names(boundary), "GT")],
                      relaxed[, setdiff(names(relaxed), "GT")]))
  environment$nipat_cfg$other_fraction_max <- 0.09
  stopifnot(identical(suppressMessages(run()), boundary))
}

snp <- new.env(parent=globalenv())
sys.source(file.path(root, "scientific/vendor/NEWPAT/SNPcall/SNPcall.R"), snp)
folder <- tempfile("settings-callers-")
dir.create(folder)
qnames <- paste0("read", 1:10, collapse=",")
row <- function(position, bases) paste("chr1", position, "A", 10L, bases,
                                      strrep("I", 10), qnames, sep="\t")
pileup <- file.path(folder, "reads.pileup")
writeLines(c(row(49, strrep("A", 10)), row(50, paste0(strrep("A", 8), "GT")),
             row(51, strrep("A", 10))), pileup)
panel <- file.path(folder, "panel.tsv")
writeLines(c("chr\tpos\tref\talt", "chr1\t50\tA\tG"), panel)
check_threshold(snp, function() snp$call_sample(pileup, panel))

dnp <- new.env(parent=globalenv())
expressions <- parse(file.path(root, "scientific/vendor/DNPcall/DNPcall.R"))
selected <- Filter(function(x) is.call(x) && identical(x[[1]], as.name("<-")) &&
                     identical(x[[2]], as.name("prepare_individual")), expressions)
stopifnot(length(selected) == 1L)
eval(selected[[1]], dnp)
dnp$get_memory_usage_mb <- function() 0
dnp$nipat_progress <- function(...) invisible(NULL)
dnp$samplelist <- "sample"
dnp$common_columns <- 3L
dnp$nipat_cfg <- nipat_settings("dnp-call")
processor <- dnp$prepare_individual("sample")
raw <- data.frame(V1="chr1", V2=49:52, V3="A", V4=10L,
                  V5=c(strrep("A", 10), paste0(strrep("A", 8), "GA"),
                       paste0(strrep("C", 8), "TT"), strrep("A", 10)),
                  V6=strrep("I", 10), V7=qnames)
labels <- data.frame(df.chr=paste0("chr1:", 49:52), uniq=1L)
alleles <- data.frame(POS="chr1:50|chr1:51", ref="A|C", alt="G|T")
check_threshold(dnp, function() processor$compute(raw, labels, alleles)$final)
unlink(folder, recursive=TRUE)
cat("PASS SNP/DNP configurable Other threshold: exact boundary and unaffected scientific columns\n")
