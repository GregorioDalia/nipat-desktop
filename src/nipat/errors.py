"""Client errors and compatibility imports for shared scientific validation."""

from nipat_scientific.errors import NipatError, ValidationError

__all__ = ["NipatError", "ValidationError", "RuntimeExecutionError"]


class RuntimeExecutionError(NipatError):
    """Raised when Docker or a scientific command fails."""
