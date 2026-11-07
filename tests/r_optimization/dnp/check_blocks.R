#!/usr/bin/env Rscript
# Compare optimized DNPcall transformations against the frozen 0.8.5 source.
# Usage: Rscript tests/r_optimization/dnp/check_blocks.R /path/to/repository
# The complete scripts are parsed, but only the relevant transformations are
# evaluated here. End-to-end tests separately exercise BAM reading and plots.

suppressPackageStartupMessages(library(dplyr))
suppressPackageStartupMessages(library(tidyr))
suppressPackageStartupMessages(library(stringr))

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 1L) stop("Expected the repository root as the only argument")
  root <- normalizePath(args[[1]], mustWork = TRUE)
  relative_path <- file.path("scientific", "vendor", "DNPcall", "DNPcall.R")
  source_paths <- c(
    reference = file.path(root, "tests", "reference_r", "0.8.5", relative_path),
    candidate = file.path(root, relative_path)
  )
  sources <- lapply(source_paths, function(path) {
    parse(file = path, encoding = "UTF-8")
    readLines(path, encoding = "UTF-8", warn = FALSE)
  })
  checks <- 0L

  block <- function(lines, start, end) {
    start_index <- which(trimws(lines) == start)
    end_index <- which(trimws(lines) == end)
    if (length(start_index) != 1L || length(end_index) != 1L ||
        start_index >= end_index) {
      stop("Source anchors must identify one nonempty block: ", start)
    }
    parse(text = lines[seq.int(start_index, end_index - 1L)])
  }

  compare_block <- function(label, start, end, inputs, outputs,
                            allow_reference_error = FALSE) {
    actual <- lapply(sources, function(lines) {
      env <- list2env(inputs, parent = globalenv())
      env$update_peak_ind <- function() invisible(NULL)
      tryCatch({
        suppressMessages(suppressWarnings(eval(block(lines, start, end), env)))
        list(ok = TRUE, values = lapply(outputs, get, envir = env, inherits = FALSE))
      }, error = function(error) {
        list(ok = FALSE, error_class = class(error), message = conditionMessage(error))
      })
    })
    if (!actual$reference$ok && !allow_reference_error) {
      stop(label, ": reference failed: ", actual$reference$message)
    }
    if (!identical(actual$reference, actual$candidate)) {
      print(actual)
      stop(label, ": reference and candidate differ")
    }
    checks <<- checks + 1L
    invisible(actual$reference)
  }

  # Compare the whole cleaning/tokenization boundary, including fallback
  # inputs: equal scientific values alone would miss changed row attributes
  # or accidental pairing of a quality with a different read.
  preprocessing_case <- function(bases, reads, qualities) {
    data.frame(df.chr=rep("chr1:50", length(bases)), df.V5=bases,
               df.V7=reads, df.qual=qualities, stringsAsFactors=FALSE)
  }
  preprocessing <- list(
    ordinary=preprocessing_case(c("ACGT", "TGCA"), c("a,B,z,Z", "a,B,z,Z"),
                               c("!5I~", "~I5!")),
    indels=preprocessing_case(c("A*", "C+1G", "g-1a"),
                             c("a,b", "c,d", "e,f"), c("5I", "II", "I5")),
    special_names=preprocessing_case(c("AC", "TG"),
                                    c("r@skip,r|pipe", "\u00e9,z"), c("I5", "5I")),
    empty_name=preprocessing_case("ACG", "a,,b", "III"),
    missing_name=preprocessing_case("A", NA_character_, "I"),
    whitespace_name=preprocessing_case("AC", "read name,b", "II"),
    missing_bases=preprocessing_case(NA_character_, "a", "I"),
    missing_quality=preprocessing_case("A", "a", NA_character_),
    mismatched_lengths=preprocessing_case("AC", "a,b,c", "II"),
    empty=preprocessing_case(character(), character(), character())
  )
  for (name in names(preprocessing)) {
    compare_block(
      paste("paired base/name/quality tokenization", name),
      "# substitution of characters to modify the df",
      "# get unique label for each DNP", list(df2=preprocessing[[name]]), "df4.1",
      allow_reference_error=TRUE
    )
  }

  quality_cases <- list(
    printable_ascii=rawToChar(as.raw(33:126), multiple=TRUE),
    repeated=c("I", "5", "I", "!", "~", "5", "|", "\\", "\""),
    empty=character(),
    missing=c("I", NA_character_, "5"),
    empty_element=c("I", "", "5"),
    outside_printable=c("I", " ", "\u00e9", "5"),
    multiple_bytes=c("II", "55")
  )
  for (name in names(quality_cases)) {
    qualities <- quality_cases[[name]]
    compare_block(
      paste("ASCII quality decoding", name),
      "# convert ASCII pred score to number", "# group by new read label",
      list(df6=data.frame(df.qual=qualities, row=seq_along(qualities),
                         stringsAsFactors=FALSE)), "df6",
      allow_reference_error=TRUE
    )
  }

  group_start <- "# group by new read label"
  group_end <- paste("# substitute characters strand specific characters",
                     "(unecessary) with only uppercase letters")
  make_rows <- function(keys) {
    data.frame(
      readUniq = keys,
      df.chr = rep(c("chr2:103", "chr1:21", "chr1:20"), length.out = length(keys)),
      df.V5 = rep(c("g", ".", "T", ","), length.out = length(keys)),
      df.qual = rep(c(40L, 0L, NA_integer_, 21L), length.out = length(keys)),
      stringsAsFactors = FALSE
    )
  }
  set.seed(892026L)
  groups <- list(
    empty = make_rows(character()),
    singleton = make_rows("read_1"),
    interleaved = make_rows(c("z", "A", "a", "z", "a_10", "a_2", "A", NA, NA)),
    unicode = make_rows(c("\u00e9", "Z", "e", "\u00c9", "\u00e9", "z")),
    random = make_rows(sample(c(paste0("read_", 1:24), NA_character_), 800, replace = TRUE))
  )
  original_locale <- Sys.getlocale("LC_COLLATE")
  on.exit(Sys.setlocale("LC_COLLATE", original_locale), add = TRUE)
  # base::merge in the reference sorts using LC_COLLATE. Test the candidate's
  # explicit sorting under each available locale, not only dplyr's group order.
  for (locale in unique(c(original_locale, "C", "C.UTF-8", "en_US.UTF-8"))) {
    selected <- suppressWarnings(Sys.setlocale("LC_COLLATE", locale))
    if (!nzchar(selected)) next
    for (name in names(groups)) {
      compare_block(paste("group", locale, name), group_start, group_end,
                    list(df6 = groups[[name]]), "DF")
    }
  }
  Sys.setlocale("LC_COLLATE", original_locale)

  compare_block(
    "strand character mapping", group_end,
    "# count INDEL reads and their ratio over total reads per DNP",
    list(DF = data.frame(
      pos = c("", NA_character_, "gact,", "GACT.", "NnRrYy", "@+-12^$*", "\u00e9,g\u03bb"),
      untouched = 1:7,
      stringsAsFactors = FALSE
    )), "DF"
  )

  make_df <- function(positions, coordinates = NULL) {
    if (is.null(coordinates)) {
      coordinates <- rep("chr1:19|chr1:20|chr1:21|chr1:22", length(positions))
    }
    data.frame(
      ID_DNP = paste0("read_", seq_along(positions)),
      chr = coordinates,
      pos = positions,
      qual = rep("40|20|30|40", length(positions)),
      stringsAsFactors = FALSE
    )
  }
  read_fixtures <- list(
    mixed = make_df(c("A|T|A|G", "C|@|G|T", "A|T|A|G", "G|T|G|A", "A|C")),
    no_indels = make_df(c("A|T|A|G", "C|C|G|T")),
    multiple_loci = make_df(
      c("A|T|A|G", "C|@|G|T", "A|T|A|G"),
      c("chr2:9|chr2:10|chr2:11|chr2:12", "chr1:9|chr1:10|chr1:11|chr1:12",
        "chr2:9|chr2:10|chr2:11|chr2:12")
    )
  )
  read_fixtures$quality_boundaries <- make_df(rep("A|T|A|G", 8))
  read_fixtures$quality_boundaries$qual <- c(
    "0|0|0|0", "93|92|93|93", "40|0|93|40", "20|13|14|20",
    "40|NA|30|40", "40|20|30", "40|20", "40|20|30|40"
  )
  read_fixtures$coordinate_boundaries <- make_df(
    rep("A|T|A|G", 4),
    c("chr1:1|chr1:2|chr1:3|chr1:4", "chr2:1|chr2:2|chr2:3",
      "chr3:1|chr3:2", "chr4:1|chr4:2|chr4:3|chr4:4")
  )
  for (name in names(read_fixtures)) {
    compare_block(
      paste("indel summary", name),
      "# count INDEL reads and their ratio over total reads per DNP",
      '# eliminate reads with "@", indicating reads with INDELs',
      list(DF = read_fixtures[[name]]), "dfIND_summary"
    )
    compare_block(
      paste("microhaplotype extraction", name),
      '# eliminate reads with "@", indicating reads with INDELs',
      "# for full* dataset final", list(DF = read_fixtures[[name]]), "good_reads"
    )
  }

  good_reads <- data.frame(
    chr1 = c("chr2:1|chr2:2", "chr1:1|chr1:2", "chr1:1|chr1:2", "chr1:1|chr1:2"),
    pos2 = c("A|T", "G|A", "T|C", "G|A"),
    qual1 = c("30|40", "20|30", "10|20", "20|20"),
    mean_quality = c(35, 25, 15, 20), stringsAsFactors = FALSE
  )
  ref_alt <- data.frame(
    POS = c("chr1:1|chr1:2", "chr2:1|chr2:2"),
    ref = c("A|A", "A|T"), alt = c("T|C", "G|C"), stringsAsFactors = FALSE
  )
  for (name in c("mixed", "no_other", "empty")) {
    indices <- switch(name, mixed = seq_len(nrow(good_reads)), no_other = c(1L, 3L), empty = integer())
    compare_block(
      paste("other allele aggregation", name), "# merge with ref alt data",
      "# create df only for alleles ref or alt",
      list(good_reads = good_reads[indices, , drop = FALSE], RefAltDNP = ref_alt),
      c("data_info", "altro_dt3")
    )
  }

  make_gl_reads <- function(keys) {
    n <- length(keys)
    data.frame(
      chr1 = keys,
      pos2 = rep(c("A|G", "T|C", "A|G"), length.out = n),
      mean_quality = rep(c(30, 0, 13.5, 50), length.out = n),
      ref = rep("A|G", n), alt = rep("T|C", n), stringsAsFactors = FALSE
    )
  }
  gl_fixtures <- list(
    empty = make_gl_reads(character()),
    singleton = make_gl_reads("chr1:2|chr1:3"),
    interleaved = make_gl_reads(c("z", "A", "z", "a", "A", "z")),
    twelve_loci = make_gl_reads(rep(paste0("locus_", 1:12), 3)),
    randomized = make_gl_reads(sample(paste0("locus_", 1:24), 800, replace = TRUE)),
    missing_key = make_gl_reads(c("locus_1", NA_character_, "locus_1"))
  )
  for (name in names(gl_fixtures)) {
    compare_block(
      paste("unrounded likelihoods", name), "# likelihood function",
      "# create df for reference alleles", list(ref_alt_dt = gl_fixtures[[name]]), "res",
      allow_reference_error = identical(name, "missing_key")
    )
  }

  cat(sprintf("DNPcall transformation equivalence: %d checks passed.\n", checks))
}

main()
