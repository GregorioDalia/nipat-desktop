"""Scope execution diagnostics and thread limits around one scientific R invocation."""

from contextlib import contextmanager
import os
from pathlib import Path


THREAD_LIMITS = {
    name: "1" for name in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
        "VROOM_THREADS",
    )
}


@contextmanager
def execution_environment(work_dir: Path | None = None):
    """Keep each step's effective worker decisions in its own writable directory.

    Workflow steps are sequential. R owns the single bounded process pool within
    each step; threaded numeric libraries must not multiply that process budget.
    """
    # Native R invocation has no managed work directory but must respect the
    # same thread budget as validated requests and workflow plans.
    directory = None
    values = THREAD_LIMITS.copy()
    if work_dir is not None:
        directory = Path(work_dir) / "parallel"
        if directory.is_symlink():
            raise ValueError("Parallel diagnostics directory cannot be a symbolic link")
        directory.mkdir(parents=True, exist_ok=True)
        values["NIPAT_PARALLEL_LOG_DIR"] = str(directory)
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield directory
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
