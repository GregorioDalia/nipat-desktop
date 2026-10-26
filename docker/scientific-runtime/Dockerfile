# Scientific base and CRAN snapshot are pinned inputs. Changes require the
# scientific regression suite against the resulting image.
FROM rocker/r-ver:4.4.2@sha256:df26749182af64d5263bf64149d51a427b476ed28c4e046997143be3f97fdd7c

ARG SAMTOOLS_VERSION=1.21
ARG SAMTOOLS_SHA256=05724b083a6b6f0305fcae5243a056cc36cf826309c3cb9347a6b89ee3fc5ada
ENV NIPAT_CRAN_REPOSITORY=https://p3m.dev/cran/__linux__/noble/2025-02-27

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
    && printf '%s  %s\n' "$SAMTOOLS_SHA256" /tmp/samtools.tar.bz2 | sha256sum --check --strict - \
    && mkdir -p /tmp/samtools-src \
    && tar -xjf /tmp/samtools.tar.bz2 -C /tmp/samtools-src --strip-components=1 \
    && cd /tmp/samtools-src \
    && ./configure --prefix=/usr/local \
    && make -j"$(nproc)" \
    && make install \
    && install -D -m 0644 LICENSE /usr/share/doc/nipat-samtools/samtools/LICENSE \
    && install -D -m 0644 "htslib-${SAMTOOLS_VERSION}/LICENSE" \
        /usr/share/doc/nipat-samtools/htslib/LICENSE \
    && install -D -m 0644 "htslib-${SAMTOOLS_VERSION}/htscodecs/LICENSE.md" \
        /usr/share/doc/nipat-samtools/htscodecs/LICENSE.md \
    && install -D -m 0644 lz4/LICENSE /usr/share/doc/nipat-samtools/lz4/LICENSE \
    && rm -rf /tmp/samtools-src /tmp/samtools.tar.bz2 \
    && install -d /usr/share/nipat \
    && dpkg-query -W -f='${Package}\t${Version}\n' > /usr/share/nipat/apt-versions.tsv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN install2.r --error --skipinstalled --ncpus -1 --repos "$NIPAT_CRAN_REPOSITORY" \
      argparse \
      ComplexUpset \
      openxlsx \
      optparse \
      patchwork \
      readxl \
      tidyverse

COPY docker/scientific-runtime/r-packages.tsv /usr/share/nipat/r-packages.tsv
COPY docker/scientific-runtime/verify-packages.R /usr/local/lib/nipat/verify-packages.R
RUN Rscript /usr/local/lib/nipat/verify-packages.R \
    && samtools --version | head -n 1 \
    && R --version | head -n 1

# Bundle only reviewed code and notices. Do not copy arbitrary local files or
# mount the host project over this path in production.
COPY LICENSE THIRD_PARTY_NOTICES.md /opt/nipat/
COPY scientific/SHA256SUMS /opt/nipat/scientific/SHA256SUMS
COPY scientific/vendor/DNPcall/DNPcall.R scientific/vendor/DNPcall/LICENSE /opt/nipat/scientific/vendor/DNPcall/
COPY scientific/vendor/NEWPAT/LICENSE /opt/nipat/scientific/vendor/NEWPAT/LICENSE
COPY scientific/vendor/NEWPAT/SNPcall/SNPcall.R /opt/nipat/scientific/vendor/NEWPAT/SNPcall/SNPcall.R
COPY scientific/vendor/NEWPAT/contamination/detect_contamination.R /opt/nipat/scientific/vendor/NEWPAT/contamination/detect_contamination.R
COPY scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R /opt/nipat/scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R
COPY engine/main.py /opt/nipat/engine/main.py
COPY src/nipat_scientific/__init__.py src/nipat_scientific/errors.py src/nipat_scientific/panels.py src/nipat_scientific/files.py src/nipat_scientific/contamination.py src/nipat_scientific/snp.py src/nipat_scientific/dnp.py src/nipat_scientific/cpi.py src/nipat_scientific/catalog.py src/nipat_scientific/plan.py src/nipat_scientific/executor.py src/nipat_scientific/outputs.py /opt/nipat/lib/nipat_scientific/
COPY src/nipat_scientific/catalog_data/ /opt/nipat/lib/nipat_scientific/catalog_data/
RUN python3 /opt/nipat/engine/main.py verify \
    && python3 /opt/nipat/engine/main.py catalog --json > /tmp/nipat-catalog-check.json \
    && rm /tmp/nipat-catalog-check.json

# The client explicitly selects the bundled workflow or an isolated runtime probe.
WORKDIR /workspace/nipat-desktop
