# Architecture

NIPAT is a local layered modular monolith. The CLI and text wizard call the
`Workflows` application service, which validates inputs, adapts file interfaces,
creates runs and delegates execution to the Docker Compose runner. The scientific
algorithms remain in the R scripts, executed with samtools inside the selected
Linux runtime. No web server, REST API or cloud analysis component is present.

Input locations are independent of the project and output locations. Global
CLI options or `NIPAT_DATA_DIR` / `NIPAT_RUNS_DIR` select the default data folder
and results root; absent overrides, these are beside the project. Relative
arguments use the caller's current directory. Relative BAM-list entries use
the list's parent directory. Wizard option 5 validates and creates a new
results root before updating the active layout in the runner and workflow
service for subsequent runs in that session; it does not persist an application setting.

Each workflow registers the files it needs as selective read-only bind mounts.
This includes required sidecars and avoids copying large BAM/FASTA inputs.
Selecting an external input does not mount its parent directory. The legacy base
Compose configuration also mounts the project and configured `data` directory
read-only. Mechanical adapters can create small
working tables inside the run. DNPcall receives safe numbered sample aliases
because the R script cannot safely use arbitrary original filenames; metadata
preserves the association with each original BAM. Its small DNP panel is
written to `work` with validated coordinates and uppercase REF/ALT alleles,
preserving the original file.

Every run receives a new directory under the chosen results root. `run.json`
records input evidence, parameters, source versions, the original-to-container
mapping and the resolved Docker image ID; `work/input-mounts.json` records the
input mounts. The project and selected inputs are read-only inside the
container; generated working files and outputs are written under the results
root. Existing runs are never overwritten by the application.

On Linux and macOS the container uses the invoking user's UID/GID. Docker
Desktop uses its normal default mapping on Windows. The future GUI must call
the same `Workflows` service, rather than invoke R or Docker directly.

## Incremental 0.5 engine migration

Contamination now uses a separate execution path. The client selects files,
performs early validation with the shared `nipat_scientific` library, maps the
original paths and writes a `contamination-v1` request. The bundled library
validates the request again, normalizes the panel and stages the tables before
executing the unchanged R script. There is one implementation of the panel and
table validators, included in both client and image; no host Python source is
mounted into the container.

The runner uses `work/engine-compose.json` as its only Compose file for this
workflow. It mounts individual selected inputs read-only and the current run
read-write; the application, default data folder and other runs are not mounted.
The image filesystem is read-only and the network is disabled. Staging remains
visible under `work/inputs` and `work/DNPpanel.txt`, with the original sample names.

The runner negotiates the image's workflow interface before analysis and records
the verified R manifest plus the actual engine/preparation Python hashes under
`runtime.engine`. The `source` evidence describes the client and is marked with
`role: client`. An older image without the requested interface fails explicitly;
there is no silent fallback to host R scripts. Dry-run records a request and the
planned command without claiming the image has been verified.

SNPcall, DNPcall and CPI still use the legacy client preparation and mounts during
this increment. Their R scripts are already bundled, but their complete workflow
migration is pending. Version 0.5 retains the guided CLI without a GUI. Installer
identity isolation and removal of the Windows Docker Desktop edition are later
increments; current review artifacts must not replace a 0.4.1 installation.

## Managed Windows runtime

The installer adds an explicit `NIPAT_BACKEND=wsl` transport. Windows Python
continues to validate user paths and retain original file evidence. Docker
commands run through `wsl.exe` in the dedicated `NIPAT-Runtime` distribution;
Compose paths and bind sources are translated for that environment. Argument
lists are passed directly, without constructing shell commands. Linux container
paths and scientific arguments are not rewritten.

The default transport still calls the host Docker CLI. The managed transport
starts its own Docker daemon through the distro helper, and uses that same
transport for probes, execution and cancellation. It does not change the
user’s Docker context or stop other WSL distributions. The source setup does
not automatically opt into WSL.

The installer runs per user. Only Windows prerequisite enablement is elevated;
distro import and configuration run under the original account. Runtime assets
are built in CI, hashed and declared in the manifest embedded in the installer.
Installation logs and state support retries and reboot continuation. Scientific
algorithms and their SHA256 manifest are unchanged in this revision.
