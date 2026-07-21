FROM rocker/r-ver:4.4.2

ARG SAMTOOLS_VERSION=1.21

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libbz2-dev \
        libcairo2-dev \
        libcurl4-openssl-dev \
        libfontconfig1-dev \
        libfreetype6-dev \
        libfribidi-dev \
        libharfbuzz-dev \
        libicu-dev \
        libjpeg-dev \
        liblzma-dev \
        libncurses-dev \
        libpng-dev \
        libssl-dev \
        libtiff-dev \
        libxml2-dev \
        python3 \
        zlib1g-dev \
    && curl -fsSL \
        "https://github.com/samtools/samtools/releases/download/${SAMTOOLS_VERSION}/samtools-${SAMTOOLS_VERSION}.tar.bz2" \
        -o /tmp/samtools.tar.bz2 \
    && mkdir -p /tmp/samtools-src \
    && tar -xjf /tmp/samtools.tar.bz2 -C /tmp/samtools-src --strip-components=1 \
    && cd /tmp/samtools-src \
    && ./configure --prefix=/usr/local \
    && make -j"$(nproc)" \
    && make install \
    && rm -rf /tmp/samtools-src /tmp/samtools.tar.bz2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN install2.r --error --skipinstalled --ncpus -1 \
      argparse \
      ComplexUpset \
      openxlsx \
      optparse \
      patchwork \
      readxl \
      tidyverse

RUN Rscript -e 'required <- c("argparse", "ComplexUpset", "dplyr", "ggplot2", "openxlsx", "optparse", "patchwork", "purrr", "readr", "readxl", "stringr", "tidyr", "tidyverse"); stopifnot(all(vapply(required, requireNamespace, logical(1), quietly=TRUE)))' \
    && samtools --version | head -n 1 \
    && R --version | head -n 1

WORKDIR /workspace/nipat-desktop
