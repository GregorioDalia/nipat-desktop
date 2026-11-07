"""Own disk-backed temporary files for one scientific invocation.

The desktop supplies an anonymous Docker volume at NIPAT_SCRATCH_ROOT. Native
source-tree execution uses the explicitly supplied writable work directory;
large intermediates never use Python's default temporary directory or /tmp.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Iterator

from nipat_scientific.errors import ValidationError


@contextmanager
def dnp_environment(workflow: str, work_dir: Path) -> Iterator[Path | None]:
    """Provide a fresh scratch directory and verified sibling helper to DNP R.

    Engine plans run steps sequentially in one process. Environment values are
    scoped to this invocation and restored on success, failure or cancellation.
    Docker removes the enclosing anonymous volume after retaining diagnostics.
    """
    if workflow != "dnp-call":
        yield None
        return
    configured = os.environ.get("NIPAT_SCRATCH_ROOT")
    root = Path(configured) if configured else Path(work_dir)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValidationError("DNP scratch requires an existing absolute writable disk directory.")
    root = root.resolve()
    # No RAM-backed fallback: failure to create scratch is an execution error.
    with tempfile.TemporaryDirectory(prefix="nipat-dnp-", dir=root, ignore_cleanup_errors=True) as temporary:
        directory = Path(temporary)
        values = {
            "NIPAT_DNP_SCRATCH": str(directory),
            "NIPAT_DNP_PILEUP_HELPER": str(Path(__file__).resolve().with_name("dnp_pileup.py")),
        }
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
