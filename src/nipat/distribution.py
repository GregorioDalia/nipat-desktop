"""Installation identity for the isolated portability experiment."""

import re

CHANNEL = "experimental08"
WINDOWS_DIRECTORY = "NIPAT-Experimental08"
UNIX_DIRECTORY = "nipat-experimental08"
EXPERIMENT_URL = "https://github.com/GregorioDalia/nipat-desktop/releases"


def is_experimental_version(version: str) -> bool:
    """These builds must never consume the stable desktop update feed."""
    return bool(re.fullmatch(r"0\.8\.\d+(?:a|b|rc)\d+", version))
