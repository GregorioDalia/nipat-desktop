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
Selecting an external input does not mount its parent directory. The base
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
