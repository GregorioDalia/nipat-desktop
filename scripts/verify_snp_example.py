"""Execute SNPcall on its bundled pileup and compare every field to its reference."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nipat.errors import NipatError, ValidationError
from nipat.paths import ProjectLayout
from nipat.validation.self_test import run_snp_example


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", help="nome opzionale di una nuova esecuzione")
    args = parser.parse_args()
    layout = ProjectLayout.discover()
    try:
        if layout.project_dir != Path(__file__).resolve().parents[1]:
            raise ValidationError("Usare il Python del progetto e verificare NIPAT_PROJECT_DIR.")
        run_snp_example(layout, args.run_name)
    except (NipatError, OSError) as exc:
        print(f"Verifica SNPcall fallita: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Verifica SNPcall interrotta.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
