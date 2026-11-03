"""Limit the experimental installer job to its branch and explicit pre-release family."""

import json
import os
from pathlib import Path
import re
import tomllib

from verify_experimental_installers import PROFILE


def validate_dispatch(event, ref, version, profile):
    if event != "workflow_dispatch" or ref != "refs/heads/experiment/0.8-portability":
        raise ValueError("Experimental installers require a manual dispatch on experiment/0.8-portability")
    if not isinstance(version, str) or not re.fullmatch(r"0\.8\.[0-9]+(?:a|b|rc)[0-9]+", version):
        raise ValueError("Only 0.8 pre-releases may use the experimental build")
    if profile != PROFILE:
        raise ValueError("Experimental Windows installation must remain isolated")


def main():
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    profile = json.loads(Path("installer/windows/install-profile.json").read_text(encoding="utf-8"))
    validate_dispatch(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"], version, profile)
    print(f"Experimental build authorized for this checkout: {version}; no publication is performed.")


if __name__ == "__main__":
    main()
