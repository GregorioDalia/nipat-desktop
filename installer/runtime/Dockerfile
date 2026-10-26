# This filesystem is imported into NIPAT's dedicated WSL distribution.
# Use the base and engine versions from the verified 0.4.1 build (run 39686775980).
ARG DEBIAN_BASE=debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8
FROM ${DEBIAN_BASE}

ARG DEBIAN_BASE
ARG DOCKER_ENGINE_VERSION=5:29.9.2-1~debian.12~bookworm
ARG CONTAINERD_VERSION=2.4.2-3~debian.12~bookworm
ARG BUILDX_VERSION=0.38.1-1~debian.12~bookworm
ARG COMPOSE_VERSION=5.6.1-1~debian.12~bookworm
ENV DEBIAN_FRONTEND=noninteractive

RUN rm -f /etc/dpkg/dpkg.cfg.d/docker \
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
        "docker-ce=${DOCKER_ENGINE_VERSION}" "docker-ce-cli=${DOCKER_ENGINE_VERSION}" \
        "containerd.io=${CONTAINERD_VERSION}" "docker-buildx-plugin=${BUILDX_VERSION}" \
        "docker-compose-plugin=${COMPOSE_VERSION}" \
    && dpkg-query -W -f='${Package}\t${Version}\n' \
        > /usr/share/nipat/apt-versions.tsv \
    && apt-cache show "docker-ce=${DOCKER_ENGINE_VERSION}" "docker-ce-cli=${DOCKER_ENGINE_VERSION}" \
        "containerd.io=${CONTAINERD_VERSION}" "docker-buildx-plugin=${BUILDX_VERSION}" \
        "docker-compose-plugin=${COMPOSE_VERSION}" \
        > /usr/share/nipat/docker-package-metadata.txt \
    && docker --version \
    && docker compose version \
    && rm -f /usr/sbin/policy-rc.d \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/lib/docker /var/lib/containerd

COPY installer/runtime/nipat-engine /usr/local/bin/nipat-engine
COPY installer/runtime/wsl.conf /etc/wsl.conf
COPY installer/runtime/write-provenance.py /usr/local/lib/nipat/write-provenance.py
COPY installer/runtime/component.py /usr/local/lib/nipat/component.py
COPY installer/runtime/Dockerfile installer/runtime/component.py installer/runtime/nipat-engine installer/runtime/write-provenance.py installer/runtime/wsl.conf /usr/share/nipat/runtime-sources/
# Bind this component to its own sources and resolved packages, not to a CLI commit.
RUN chmod 0755 /usr/local/bin/nipat-engine \
    && printf 'nipat-runtime-v1\n' > /etc/nipat-runtime-id \
    && python3 /usr/local/lib/nipat/write-provenance.py "$DEBIAN_BASE" /usr/share/nipat/runtime-sources \
    && bash -n /usr/local/bin/nipat-engine \
    && test -s /usr/share/doc/docker-ce/README.md \
    && test -s /usr/share/doc/docker-ce/upstream-LICENSE \
    && test -s /usr/share/doc/docker-ce/upstream-NOTICE \
    && install -d -m 0700 /var/lib/nipat

CMD ["/bin/bash"]
