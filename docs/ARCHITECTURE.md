# Architecture

NIPAT is a local layered modular monolith. The Python package owns validation,
run creation, file-interface adaptation and process orchestration. The scientific
algorithms remain in the original R scripts and run as separate processes inside
the pinned Linux runtime.

```text
CLI now / GUI later
        |
Python application layer
        |
Validation + mechanical adapters + run manager
        |
Docker Compose execution adapter
        |
R 4.4.2 + samtools 1.21 + canonical R scripts
```

No web server, REST API or cloud component is present. Every run receives its own
directory under the workspace-level `runs` folder. The repository and genomic
inputs are mounted read-only; only `runs` is writable inside the container.
On Linux and macOS the container uses the invoking user's UID/GID so generated
files are not left owned by root. Docker Desktop uses its normal default mapping
on Windows.

The future GUI must call the same `Workflows` application service used by the CLI.
It must not invoke R or Docker directly.
