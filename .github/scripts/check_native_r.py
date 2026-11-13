"""Run mandatory native R regressions using only the installed scientific payload."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = Path("/opt/nipat")


def main():
    # Host R can be incomplete and native unit tests then explicitly skip.
    # The packaged-image gate must instead fail missing tools/dependencies.
    from nipat_scientific.settings import REGISTRY
    if REGISTRY.resolve() != PAYLOAD / "lib/nipat_scientific/settings_data.json":
        raise RuntimeError("Native regressions must use the installed scientific settings")
    subprocess.run(["Rscript", "-e", 'stopifnot(requireNamespace("jsonlite", quietly=TRUE), '
                    'requireNamespace("data.table", quietly=TRUE), requireNamespace("ggplot2", quietly=TRUE))'],
                   check=True, timeout=60)
    os.environ["NIPAT_NATIVE_TEST_PAYLOAD_ROOT"] = str(PAYLOAD)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.discover(str(ROOT / "tests"), pattern=pattern)
                              for pattern in ("test_native_r_*.py", "test_scientific_settings.py"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for name, module in tuple(sys.modules.items()):
        if name == "nipat_scientific" or name.startswith("nipat_scientific."):
            source = getattr(module, "__file__", None)
            if source is not None and not Path(source).resolve().is_relative_to(PAYLOAD / "lib/nipat_scientific"):
                raise RuntimeError(f"Native regressions imported a checkout replacement: {name}")
    if not result.wasSuccessful() or not result.testsRun or result.skipped:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
