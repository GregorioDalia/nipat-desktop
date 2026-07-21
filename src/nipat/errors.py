class NipatError(Exception):
    """Base exception for errors that should be shown directly to the user."""


class ValidationError(NipatError):
    """Raised when an input is missing or incompatible with a workflow."""


class RuntimeExecutionError(NipatError):
    """Raised when Docker or a scientific command fails."""
