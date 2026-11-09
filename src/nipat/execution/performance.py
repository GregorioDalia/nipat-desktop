"""Opt-in, bounded Docker observations collected outside the analysis container.

Docker CLI values are rounded presentation values. Linux memory from ``stats``
subtracts inactive file cache: it is NOT raw cgroup memory, R RSS, or a kernel
peak. The image-owned monitor records those different measurements separately.
Only the main thread integrates this observer's summary into a run record.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import threading
import time
from types import SimpleNamespace

from nipat.execution.diagnostics import inspect_container
from nipat.execution.transport import cleanup_process_options


_STATS_FORMAT = (
    '{"id":"{{.ID}}","cpu_percent":"{{.CPUPerc}}",'
    '"memory":"{{.MemUsage}}","block_io":"{{.BlockIO}}","pids":"{{.PIDs}}"}'
)
_SIZE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\Z")
_FACTORS = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2, "GB": 1000**3,
            "TB": 1000**4, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
_MAX_RESPONSE = 16 * 1024
_MAX_LOG_BYTES = 32 * 1024 * 1024
_QUERY_TIMEOUT = 5
# A pending stats query may be followed by a bounded 15-second inspection to
# distinguish container shutdown from a collection error.
_JOIN_TIMEOUT = _QUERY_TIMEOUT + 17
_STARTUP_POLL_INTERVAL = 0.25


class _StatsError(ValueError):
    """A fixed diagnostic code, never arbitrary Docker output or input paths."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bytes(value: str) -> int:
    match = _SIZE.fullmatch(value.strip())
    if match is None:
        raise ValueError("unrecognized Docker size")
    number = float(match[1]) * _FACTORS[match[2]]
    if not math.isfinite(number) or number > 2**63 - 1:
        raise ValueError("invalid Docker size")
    return round(number)


def parse_stats(raw: str, identifier: str) -> dict:
    """Allowlist and normalize one CLI row without retaining arbitrary metadata."""
    if len(raw) > _MAX_RESPONSE:
        raise _StatsError("oversized_stats_response")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise _StatsError("invalid_stats_json") from None
    if not isinstance(value, dict) or value.get("id") != identifier:
        raise _StatsError("stats_identity_mismatch")
    result = {}
    cpu = value.get("cpu_percent")
    if isinstance(cpu, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?%", cpu):
        number = float(cpu[:-1])
        if math.isfinite(number) and number <= 1_000_000:
            result["cpu_percent"] = number
    for source, names in (("memory", ("memory_cache_adjusted_bytes", "memory_limit_bytes")),
                          ("block_io", ("block_io_read_bytes", "block_io_write_bytes"))):
        pair = value.get(source)
        if not isinstance(pair, str) or len(pair) > 128:
            continue
        parts = pair.split("/")
        if len(parts) != 2:
            continue
        try:
            parsed = [_bytes(part) for part in parts]
        except ValueError:
            continue
        result.update(zip(names, parsed))
    pids = value.get("pids")
    if isinstance(pids, str) and re.fullmatch(r"[0-9]{1,9}", pids):
        result["pids"] = int(pids)
    if not result:
        raise _StatsError("stats_metrics_unavailable")
    result["unavailable_metrics"] = sorted({
        "cpu_percent", "memory_cache_adjusted_bytes", "memory_limit_bytes",
        "block_io_read_bytes", "block_io_write_bytes", "pids",
    } - result.keys())
    return result


class ContainerPerformanceObserver:
    """Poll one owned immutable ID; never control or inspect unrelated containers.

    The observer survives an R/container OOM while the desktop and Docker daemon
    remain available. It cannot guarantee observations after a whole-VM/host crash.
    All its files are optional: collection failures do not fail scientific work.
    """

    def __init__(self, runner, name: str, labels: dict[str, str], directory: Path, *,
                 interval: float = 2.0, max_bytes: int = _MAX_LOG_BYTES):
        self.directory = directory
        self._transport = runner._transport
        self._environment = runner._environment().copy()
        # inspect_container needs only these immutable inputs. It must not access
        # the runner's live RunRecord or image state from a background thread.
        self._inspection = SimpleNamespace(
            _transport=self._transport, _environment=lambda: self._environment.copy(),
            _image_id=runner._image_id,
        )
        self._name, self._labels = name, labels.copy()
        self._interval, self._max_bytes = interval, max_bytes
        self._stop = threading.Event()
        self._thread = None
        self._started = time.monotonic()
        self._identifier = None
        self._failures = Counter()
        self._failure_reasons = Counter()
        self._count, self._bytes_written = 0, 0
        self._maxima = {}
        self._first, self._last = None, None
        self._reason = None
        self._summary = {
            "schema_version": 1, "enabled": True, "source": "docker-cli-stats",
            "status": "collecting", "started_at": _utc(),
            "requested_interval_seconds": interval, "query_timeout_seconds": _QUERY_TIMEOUT,
            "startup_poll_interval_seconds": min(interval, _STARTUP_POLL_INTERVAL),
            "max_output_bytes": max_bytes,
            "measurement_notes": [
                "Periodic samples; actual timestamps and query durations describe the observed interval.",
                "Docker CLI numbers are rounded. Memory excludes inactive file cache on Linux.",
                "Sampled maxima may miss spikes and are not kernel memory.peak or R RSS.",
                "CPU percent may exceed 100 when several CPU cores are used.",
                "Block I/O counters are accounted device I/O, not all filesystem traffic or disk speed.",
                "The observer runs outside the analysis container; VM or host failure may truncate evidence.",
            ],
        }

    def start(self) -> None:
        # The run directory is owned by this run. Still reject symlinks and
        # existing output files instead of overwriting user evidence.
        for path in (self.directory, *self.directory.parents):
            if path.is_symlink():
                raise ValueError("performance destination contains a symlink")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "container-samples.jsonl").open("x", encoding="utf-8"):
            pass
        with (self.directory / "summary.json").open("x", encoding="utf-8") as handle:
            json.dump(self._summary, handle, indent=2)
            handle.write("\n")
        self._thread = threading.Thread(target=self._collect, name="nipat-performance", daemon=True)
        self._thread.start()

    def _stats(self) -> dict:
        command = self._transport.command([
            "docker", "stats", "--no-stream", "--no-trunc", "--format", _STATS_FORMAT,
            self._identifier,
        ], self._environment)
        started = time.monotonic()
        result = subprocess.run(
            command, env=self._environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_QUERY_TIMEOUT, check=False,
            stdin=subprocess.DEVNULL, **cleanup_process_options(),
        )
        if result.returncode:
            raise _StatsError("stats_command_failed")
        sample = parse_stats(result.stdout.strip(), self._identifier)
        if sample.get("pids") == 0 and sample.get("memory_cache_adjusted_bytes") == 0:
            # Docker can return an all-zero row if the container stopped while
            # its sampling request was pending. That is not measured live RAM.
            raise _StatsError("container_not_running_during_sample")
        sample.update(observed_at=_utc(), elapsed_seconds=round(time.monotonic() - self._started, 6),
                      query_seconds=round(time.monotonic() - started, 6))
        return sample

    def _append(self, handle, sample: dict) -> bool:
        line = (json.dumps(sample, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        if self._bytes_written + len(line) > self._max_bytes:
            self._reason = "output_limit_reached"
            return False
        handle.write(line)
        handle.flush()
        self._bytes_written += len(line)
        self._count += 1
        self._first = self._first or sample["observed_at"]
        self._last = sample["observed_at"]
        for key in ("cpu_percent", "memory_cache_adjusted_bytes", "pids",
                    "block_io_read_bytes", "block_io_write_bytes"):
            if key in sample:
                self._maxima[key] = max(self._maxima.get(key, 0), sample[key])
        return True

    def _record_failure(self, exc: Exception, *, reason: str | None = None) -> None:
        # Retain the original exception-type counter for report compatibility,
        # adding fixed reason codes so future failures can actually be diagnosed.
        kind = "ValueError" if isinstance(exc, _StatsError) else type(exc).__name__
        self._failures[kind] += 1
        self._failure_reasons[reason or (exc.reason if isinstance(exc, _StatsError) else kind)] += 1

    def _handle_sample_failure(self, exc: Exception) -> bool:
        """Record a failed query or confirmed shutdown; return whether to stop."""
        if not isinstance(exc, _StatsError) or exc.reason != "container_not_running_during_sample":
            self._record_failure(exc)
            return False
        # An all-zero row alone is not evidence of an exit. Verify ownership,
        # immutable ID and terminal state before treating it as a normal end.
        observed = inspect_container(self._inspection, self._name, self._labels)
        if observed.get("availability") == "identity_mismatch" or (
            observed.get("owned") is True and observed.get("container_id") != self._identifier
        ):
            self._record_failure(exc, reason="ownership_not_verified")
            self._reason = "ownership_not_verified"
            return True
        if observed.get("owned") is True and observed.get("container_id") == self._identifier:
            state = observed.get("state", {}).get("status")
            if state in {"exited", "dead", "removing"}:
                self._reason = "container_stopped_during_sample"
                return True
            if state == "running":
                self._record_failure(exc, reason="zero_metrics_while_running")
                return False
        self._record_failure(exc, reason="terminal_state_not_confirmed")
        return False

    def _collect(self) -> None:
        try:
            deadline = time.monotonic() + 60
            while not self._stop.is_set():
                observed = inspect_container(self._inspection, self._name, self._labels)
                if observed.get("owned") is True:
                    identifier = observed["container_id"]
                    if self._identifier is not None and self._identifier != identifier:
                        self._reason = "ownership_not_verified"
                        return
                    self._identifier = identifier
                    state = observed.get("state", {}).get("status")
                    if state == "running":
                        break
                    if state in {"exited", "dead", "removing"}:
                        self._reason = "container_not_running_at_first_observation"
                        return
                    # Compose may still be creating the container. Keep its
                    # verified immutable ID while waiting for the process.
                elif observed.get("availability") == "identity_mismatch":
                    self._reason = "ownership_not_verified"
                    return
                if time.monotonic() >= deadline:
                    self._reason = "container_not_observed_before_deadline"
                    return
                # The first running observation must not wait a whole sampling
                # interval: a short scientific task may already have finished.
                if self._stop.wait(min(self._interval, _STARTUP_POLL_INTERVAL)):
                    return
            if self._stop.is_set():
                return
            consecutive = 0
            with (self.directory / "container-samples.jsonl").open("ab") as handle:
                while not self._stop.is_set():
                    try:
                        sample = self._stats()
                    except (OSError, subprocess.SubprocessError, ValueError, TypeError,
                            RecursionError) as exc:
                        if self._handle_sample_failure(exc):
                            return
                        consecutive += 1
                        if consecutive >= 3:
                            self._reason = "repeated_observation_failures"
                            return
                    else:
                        consecutive = 0
                        if not self._append(handle, sample):
                            return
                    if self._stop.wait(self._interval):
                        return
        except Exception as exc:
            # Diagnostic errors are reported by type, without leaking paths,
            # environment or arbitrary Docker stderr into a sharing report.
            self._record_failure(exc)
            self._reason = "observer_failed"

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_TIMEOUT)
            if self._thread.is_alive():
                # Bounded subprocesses normally prevent this. Never wait
                # indefinitely before stopping the scientific container.
                return {"schema_version": 1, "enabled": True, "status": "partial",
                        "reason": "observer_stop_not_confirmed", "summary": None}
        reason = self._reason or ("observation_finished" if self._count else "no_samples_collected")
        interrupted = self._reason not in {None, "container_stopped_during_sample"}
        status = "partial" if self._count and (interrupted or self._failures) else (
            "completed" if self._count else "unavailable")
        summary = {**self._summary, "status": status, "reason": reason,
                   "finished_at": _utc(), "elapsed_seconds": round(time.monotonic() - self._started, 6),
                   "container_id": self._identifier, "sample_count": self._count,
                   "sample_bytes": self._bytes_written, "first_sample_at": self._first,
                   "last_sample_at": self._last, "sampled_maxima": self._maxima,
                   "observation_failures": dict(self._failures),
                   "failure_reasons": dict(self._failure_reasons),
                   "files": {"samples": "container-samples.jsonl", "summary": "summary.json"}}
        temporary = self.directory / "summary.tmp"
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(self.directory / "summary.json")
        return summary
