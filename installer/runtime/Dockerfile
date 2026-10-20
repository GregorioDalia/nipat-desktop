# This filesystem is imported into NIPAT's dedicated WSL distribution.
# CI resolves the base tag to a digest before building the release assets.
ARG DEBIAN_BASE=debian:bookworm-slim
FROM ${DEBIAN_BASE}

ARG DEBIAN_BASE
ARG SOURCE_COMMIT
ENV DEBIAN_FRONTEND=noninteractive

RUN test -n "$SOURCE_COMMIT" \
    && rm -f /etc/dpkg/dpkg.cfg.d/docker \
    && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod 0755 /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl iptables python3 util-linux \
    && install -m 0755 -d /etc/apt/keyrings /usr/share/nipat \
    && curl --proto '=https' --tlsv1.2 -fsSL \
        https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod 0644 /etc/apt/keyrings/docker.asc \
    && printf '%s\n' \
        'Types: deb' \
        'URIs: https://download.docker.com/linux/debian' \
        'Suites: bookworm' \
        'Components: stable' \
        'Architectures: amd64' \
        'Signed-By: /etc/apt/keyrings/docker.asc' \
        > /etc/apt/sources.list.d/docker.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    && dpkg-query -W -f='${Package}\t${Version}\n' \
        > /usr/share/nipat/apt-versions.tsv \
    && apt-cache show docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin \
        > /usr/share/nipat/docker-package-metadata.txt \
    && docker --version \
    && docker compose version \
    && rm -f /usr/sbin/policy-rc.d \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/lib/docker /var/lib/containerd

COPY installer/runtime/nipat-engine /usr/local/bin/nipat-engine
COPY installer/runtime/wsl.conf /etc/wsl.conf
COPY installer/runtime/write-provenance.py /usr/local/lib/nipat/write-provenance.py
RUN chmod 0755 /usr/local/bin/nipat-engine \
    && printf 'nipat-runtime-v1\n' > /etc/nipat-runtime-id \
    && python3 /usr/local/lib/nipat/write-provenance.py "$SOURCE_COMMIT" "$DEBIAN_BASE" \
    && bash -n /usr/local/bin/nipat-engine \
    && test -f /usr/share/doc/docker-ce/copyright \
    && install -d -m 0700 /var/lib/nipat

CMD ["/bin/bash"]
