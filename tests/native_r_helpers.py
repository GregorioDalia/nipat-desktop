"""Host prerequisite probe; packaged-image CI separately forbids native skips."""

import shutil
import subprocess


def native_r_availability():
    executable = shutil.which("Rscript")
    if executable is None:
        return False, "R runtime is unavailable; native regressions run in scientific-image CI"
    packages = ("argparse", "dplyr", "ggplot2", "jsonlite", "readxl", "patchwork", "stringr", "tidyr")
    expression = ("packages <- c(" + ",".join(f'"{name}"' for name in packages) + "); "
                  "missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly=TRUE)]; "
                  "if (length(missing)) { cat(paste(missing, collapse=', ')); quit(status=1) }")
    try:
        result = subprocess.run([executable, "--vanilla", "-e", expression], capture_output=True,
                                text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"R prerequisite probe failed: {type(exc).__name__}; scientific-image CI is mandatory"
    if result.returncode:
        detail = result.stdout.strip() or "R package loading failed"
        return False, f"Host R lacks scientific prerequisites: {detail}; native regressions run in scientific-image CI"
    return True, "Complete native R prerequisites available"


NATIVE_R_AVAILABLE, NATIVE_R_REASON = native_r_availability()
