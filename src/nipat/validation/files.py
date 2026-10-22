"""Compatibility exports for the shared scientific table validators."""

from nipat_scientific.files import (
    CONTAMINATION_COLUMNS, DNP_OUTPUT_COLUMNS, require_columns,
    require_contamination_input, require_directory, require_file, require_sidecar,
    require_snp_pileup, tabular_header,
)

__all__ = [
    "CONTAMINATION_COLUMNS", "DNP_OUTPUT_COLUMNS", "require_columns",
    "require_contamination_input", "require_directory", "require_file",
    "require_sidecar", "require_snp_pileup", "tabular_header",
]
