"""Execution policy shared by the CLI and guided client."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from nipat.errors import ValidationError


@dataclass(frozen=True)
class ExecutionOptions:
    input_hashes: str = "auto"
    cpus: float | None = None
    memory_mb: int | None = None
    pids_limit: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_hashes, str) or self.input_hashes not in {"auto", "full"}:
            raise ValidationError("La provenienza degli input deve essere auto oppure full.")
        if self.cpus is not None and (
            type(self.cpus) not in (int, float) or not 0 < self.cpus <= 1024
            or not math.isfinite(self.cpus)
        ):
            raise ValidationError("Il limite CPU deve essere un numero finito maggiore di 0 e fino a 1024.")
        if self.memory_mb is not None and (
            type(self.memory_mb) is not int or not 128 <= self.memory_mb <= 1_048_576
        ):
            raise ValidationError("Il limite memoria deve essere un intero fra 128 e 1048576 MiB.")
        if self.pids_limit is not None and (
            type(self.pids_limit) is not int or not 16 <= self.pids_limit <= 1_048_576
        ):
            raise ValidationError("Il limite processi deve essere un intero fra 16 e 1048576.")

    def as_dict(self) -> dict:
        return asdict(self)

    def compose_limits(self) -> dict:
        limits = {}
        if self.cpus is not None:
            limits["cpus"] = self.cpus
        if self.memory_mb is not None:
            limits["mem_limit"] = self.memory_mb * 1024 * 1024
            # Avoid an implicit additional swap allowance beyond the selected budget.
            limits["memswap_limit"] = limits["mem_limit"]
        if self.pids_limit is not None:
            limits["pids_limit"] = self.pids_limit
        return limits
