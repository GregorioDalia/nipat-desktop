"""Client errors and compatibility imports for shared scientific validation."""

from nipat_scientific.errors import NipatError, ValidationError

__all__ = ["NipatError", "ValidationError", "RuntimeExecutionError", "Cancelled"]


class Cancelled(Exception):
    """Leave the current guided action and return to the main menu."""


class RuntimeExecutionError(NipatError):
    """Raised when Docker or a scientific command fails."""
