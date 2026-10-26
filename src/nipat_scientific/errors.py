class NipatError(Exception):
    """Base exception for errors that should be shown directly to the user."""


class ValidationError(NipatError):
    """Raised when an input is missing or incompatible with a workflow."""


class PlanExecutionError(ValidationError):
    """An execution/preflight failure with a stable language-independent code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")
