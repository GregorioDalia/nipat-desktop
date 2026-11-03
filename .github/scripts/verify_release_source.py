"""Allow deliberate candidate builds on main or the matching release branch."""

import json
import os
from pathlib import Path
import re
import tomllib


PROFILE = {
    "schema_version": 1, "channel": "desktop", "display_name": "NIPAT Desktop",
    "app_dir_name": "NIPAT-Desktop", "data_dir_name": "NIPAT-Desktop",
    "distro_prefix": "NIPAT-Desktop-", "resume_key": "NIPAT-Desktop-ResumeSetup",
    "mutex_prefix": "Local\\NIPAT-Desktop-Setup-",
    "app_id": "6B1702B6-F75C-4F8C-956F-86626C60AF45",
}


def validate_dispatch(event, ref, version, profile):
    if event != "workflow_dispatch":
        raise ValueError("Installer candidates require a deliberate manual dispatch.")
    if not isinstance(version, str) or not re.fullmatch(r"0\.8\.[0-9]+", version) or int(version.split(".")[2]) < 2:
        raise ValueError("Official multi-platform installers require 0.8.2 or later.")
    if ref != "refs/heads/main" and not re.fullmatch(
            r"refs/heads/release/" + re.escape(version) + r"(?:-[a-z0-9-]+)?", ref):
        raise ValueError("Build main or a release branch matching the package version.")
    if profile != PROFILE:
        raise ValueError("The official build requires the Desktop installation identity.")


def main():
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    profile = json.loads(Path("installer/windows/install-profile.json").read_text(encoding="utf-8"))
    validate_dispatch(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"], version, profile)
    print(f"Candidate build authorized for this checkout: {version}; publication is a separate operation.")


if __name__ == "__main__":
    main()
