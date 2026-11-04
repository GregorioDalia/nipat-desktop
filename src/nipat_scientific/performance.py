"""Opt-in, bounded performance evidence from the Linux scientific container.

This observer never changes scientific arguments or R sources. Its samples are
periodic, not continuous. Cgroup memory includes cache/kernel accounting and is
not comparable to a sum of per-process RSS or Docker CLI's adjusted memory.
The observer shares the analysis cgroup: a container-wide kill can leave only
the progressively flushed samples and the initial, incomplete summary.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from itertools import islice
import os
from pathlib import Path, PurePosixPath
import re
import sys
import threading
import time


INTERFACE = "performance-diagnostics-v1"
INTERVAL_SECONDS = 1.0
MAX_SAMPLE_BYTES = 32 * 1024 * 1024
MAX_PHASE_BYTES = 2 * 1024 * 1024
MAX_PROCESSES = 256
_ACTIVE = None
_PROCESS_NAMES = frozenset({"R", "Rscript", "samtools", "python", "python3", "python3.12"})
_CPU_KEYS = frozenset({"usage_usec", "user_usec", "system_usec", "nr_periods", "nr_throttled", "throttled_usec"})
_EVENT_KEYS = frozenset({"low", "high", "max", "oom", "oom_kill", "oom_group_kill"})
_IO_KEYS = frozenset({"rbytes", "wbytes", "rios", "wios", "dbytes", "dios"})


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn(message: str) -> None:
    try:
        print(message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def _read(path: Path) -> str:
    with path.open("r", encoding="ascii", errors="replace") as source:
        value = source.read(65537)
    if len(value) > 65536:
        raise ValueError("oversized metric")
    return value.strip()


def _number(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,30}", value):
        raise ValueError("invalid counter")
    return int(value)


def _key_values(value: str, allowed: frozenset[str]) -> dict[str, int]:
    output = {}
    for line in value.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].rstrip(":") in allowed:
            output[parts[0].rstrip(":")] = _number(parts[1])
    return output


def _controller_paths(root: Path, proc_root: Path) -> dict[str, Path]:
    """Resolve our membership against mounted controllers, including host cgroup namespaces.

    Reading a controller's mount root without resolving membership could report
    the whole VM on older Docker/cgroup setups. Unknown layouts are unavailable.
    """
    memberships = {}
    for line in _read(proc_root / "self/cgroup").splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            raise ValueError("invalid cgroup membership")
        for controller in parts[1].split(",") if parts[1] else ["unified"]:
            memberships[controller] = PurePosixPath(parts[2])
    resolved = {}
    for line in _read(proc_root / "self/mountinfo").splitlines():
        before, separator, after = line.partition(" - ")
        prefix, suffix = before.split(), after.split()
        if not separator or len(prefix) < 6 or len(suffix) < 3:
            continue
        if suffix[0] not in {"cgroup", "cgroup2"}:
            continue
        mount_root, mount = PurePosixPath(prefix[3]), PurePosixPath(prefix[4])
        if not mount.is_relative_to("/sys/fs/cgroup"):
            continue
        controllers = ["unified"] if suffix[0] == "cgroup2" else suffix[2].split(",")
        for controller in controllers:
            membership = memberships.get(controller)
            if membership is None or ".." in membership.parts or not membership.is_absolute():
                continue
            if not membership.is_relative_to(mount_root):
                continue
            local = root / mount.relative_to("/sys/fs/cgroup") / membership.relative_to(mount_root)
            if ".." not in local.parts and local.is_relative_to(root):
                resolved[controller] = local
    return resolved


def cgroup_sample(root: Path = Path("/sys/fs/cgroup"), proc_root: Path = Path("/proc")) -> dict:
    """Read fixed metric files; an absent or inaccessible metric remains unknown."""
    try:
        controllers = _controller_paths(root, proc_root)
    except (OSError, ValueError):
        return {"version": None, "available": False, "unavailable": ["cgroup_membership"]}
    if not controllers:
        return {"version": None, "available": False, "unavailable": ["cgroup_mount"]}
    version = 2 if "unified" in controllers else 1
    result = {"version": version, "available": False, "unavailable": []}

    def metric(name, relative, parser=_number, controller="unified"):
        try:
            if controller not in controllers:
                raise ValueError("controller unavailable")
            result[name] = parser(_read(controllers[controller] / relative))
            result["available"] = True
        except (OSError, ValueError):
            result[name] = None
            result["unavailable"].append(relative)

    if version == 2:
        metric("memory_current_bytes", "memory.current")
        metric("memory_peak_bytes", "memory.peak")
        metric("memory_limit", "memory.max", lambda value: "unlimited" if value == "max" else _number(value))
        metric("memory_events", "memory.events", lambda value: _key_values(value, _EVENT_KEYS))
        metric("cpu", "cpu.stat", lambda value: _key_values(value, _CPU_KEYS))
        metric("memory_stat", "memory.stat", lambda value: _key_values(
            value, frozenset({"anon", "file", "kernel", "kernel_stack", "pagetables", "sock", "shmem"})))

        def io_stat(value):
            devices = []
            for line in value.splitlines():
                parts = line.split()
                if not parts or not re.fullmatch(r"[0-9]+:[0-9]+", parts[0]):
                    raise ValueError("invalid device")
                item = {"device": parts[0]}
                for part in parts[1:]:
                    key, _, number = part.partition("=")
                    if key in _IO_KEYS:
                        item[key] = _number(number)
                devices.append(item)
            return devices

        metric("io_devices", "io.stat", io_stat)
    else:
        metric("memory_current_bytes", "memory.usage_in_bytes", controller="memory")
        metric("memory_peak_bytes", "memory.max_usage_in_bytes", controller="memory")
        metric("memory_limit", "memory.limit_in_bytes", controller="memory")
        metric("memory_failcnt", "memory.failcnt", controller="memory")
        metric("cpu_usage_ns", "cpuacct.usage", controller="cpuacct")
        metric("cpu", "cpu.stat", lambda value: _key_values(
            value, frozenset({"nr_periods", "nr_throttled", "throttled_time"})), controller="cpu")
        # v1 has multiple controller layouts. Do not invent zeros for controllers
        # or I/O accounting not exposed at these conventional mount locations.
        result["io_devices"] = None
        result["unavailable"].append("io.stat (requires cgroup v2)")
    return result


def process_sample(root: Path = Path("/proc")) -> dict:
    """Allowlisted process names/counters only; no commands, filenames or samples."""
    records = []
    unavailable = 0
    try:
        paths = sorted(islice((path for path in root.iterdir() if path.name.isdecimal()), 4097),
                       key=lambda path: int(path.name))
    except OSError:
        return {"available": False, "processes": [], "reason": "proc_unavailable"}
    scanned = 0
    for path in paths[:4096]:
        scanned += 1
        try:
            name = _read(path / "comm")
            if name not in _PROCESS_NAMES:
                continue
            fields = _read(path / "stat").rsplit(")", 1)[1].split()
            item = {"pid": int(path.name), "name": name,
                    "parent_pid": _number(fields[1]), "user_cpu_ticks": _number(fields[11]),
                    "system_cpu_ticks": _number(fields[12]), "start_time_ticks": _number(fields[19])}
            status = _read(path / "status")
            match = re.search(r"^VmRSS:\s+([0-9]+)\s+kB$", status, re.MULTILINE)
            item["rss_bytes"] = int(match[1]) * 1024 if match else None
            try:
                item["io"] = _key_values(_read(path / "io"), frozenset({"read_bytes", "write_bytes", "rchar", "wchar"}))
            except (OSError, ValueError):
                item["io"] = None
            records.append(item)
            if len(records) >= MAX_PROCESSES:
                break
        except (OSError, ValueError, IndexError):
            # Processes can exit between directory enumeration and a file read.
            unavailable += 1
    try:
        ticks = int(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, OSError, ValueError):
        ticks = None
    return {"available": True, "processes": records, "clock_ticks_per_second": ticks,
            "unreadable_or_exited": unavailable, "truncated": scanned < len(paths),
            "rss_semantics": "per-process resident memory; shared pages can overlap; do not sum"}


class PerformanceSession:
    """Best-effort recording with bounded files and no effect on scientific exit status."""

    def __init__(self, directory: Path, *, interval: float = INTERVAL_SECONDS,
                 max_sample_bytes: int = MAX_SAMPLE_BYTES, max_phase_bytes: int = MAX_PHASE_BYTES,
                 cgroup_root: Path = Path("/sys/fs/cgroup"), proc_root: Path = Path("/proc")):
        self.directory = directory
        self.interval = interval
        self.max_sample_bytes = max_sample_bytes
        self.max_phase_bytes = max_phase_bytes
        self.cgroup_root = cgroup_root
        self.proc_root = proc_root
        self.started = time.monotonic()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.handles = {}
        self.owns_directory = False
        self.written = {"samples": 0, "phases": 0}
        self.summary = {
            "schema_version": 1, "interface": INTERFACE, "status": "incomplete",
            "started_utc": _utc(), "finished_utc": None,
            "interval_seconds": interval, "samples": 0, "phase_events": 0,
            "cgroup_available_samples": 0, "proc_available_samples": 0,
            "sampled_memory_max_bytes": None, "observed_kernel_memory_peak_bytes": None,
            "truncated": [], "errors": [],
            "semantics": {
                "scope": "scientific container including this observer",
                "memory": "cgroup accounting, including cache/kernel; not process RSS or Docker CLI adjusted usage",
                "sampled_maximum": "maximum among collected samples; intervening peaks can be missed",
                "kernel_peak": "kernel high-water mark observed during sampling; availability depends on controller/kernel",
                "processes": "allowlisted R, samtools and Python process counters; RSS values overlap",
                "io": "per-device kernel accounting; cache hits and host filesystem work may not appear as block I/O",
                "phases": "engine boundaries; R execution includes R-internal preparation, computation and plots",
                "failure": "a container-wide kill can interrupt the observer; partial samples remain evidence",
            },
        }

    @classmethod
    def from_environment(cls):
        value = os.environ.get("NIPAT_PERFORMANCE_DIR")
        return cls(Path(value)) if value else None

    def _error(self, reason):
        if reason not in self.summary["errors"] and len(self.summary["errors"]) < 20:
            self.summary["errors"].append(reason)

    def _save_summary(self):
        temporary = self.directory / ".summary.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(self.summary, handle, ensure_ascii=True, allow_nan=False, indent=2)
                handle.write("\n")
                handle.flush()
            temporary.replace(self.directory / "summary.json")
        finally:
            temporary.unlink(missing_ok=True)

    def start(self):
        global _ACTIVE
        try:
            path = self.directory
            if (not path.is_absolute() or path.exists() or path.is_symlink()
                    or any(parent.is_symlink() for parent in path.parents)
                    or path.resolve() != path):
                raise ValueError("unsafe_or_existing_destination")
            path.mkdir(parents=True, exist_ok=False)
            self.owns_directory = True
            for kind in ("samples", "phases"):
                self.handles[kind] = (path / f"{kind}.jsonl").open("x", encoding="utf-8", newline="\n")
            self._save_summary()
            _ACTIVE = self
            self._sample()
            self.thread = threading.Thread(target=self._loop, name="nipat-engine-observer", daemon=True)
            self.thread.start()
        except Exception as exc:
            self._error(type(exc).__name__)
            self.summary["status"] = "unavailable"
            if self.owns_directory:
                try:
                    self._save_summary()
                except Exception:
                    pass
            for handle in self.handles.values():
                try:
                    handle.close()
                except OSError:
                    pass
            self.handles.clear()
            if _ACTIVE is self:
                _ACTIVE = None
            _warn("NIPAT performance diagnostics unavailable; scientific execution continues.")

    def _append(self, kind: str, value: dict) -> bool:
        if kind not in self.handles or kind in self.summary["truncated"]:
            return False
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"
        size = len(encoded.encode("utf-8"))
        limit = self.max_sample_bytes if kind == "samples" else self.max_phase_bytes
        with self.lock:
            if self.written[kind] + size > limit:
                if kind not in self.summary["truncated"]:
                    self.summary["truncated"].append(kind)
                return False
            self.handles[kind].write(encoded)
            self.handles[kind].flush()
            self.written[kind] += size
        return True

    def _sample(self):
        try:
            value = {"observed_utc": _utc(), "elapsed_seconds": time.monotonic() - self.started,
                     "cgroup": cgroup_sample(self.cgroup_root, self.proc_root), "proc": process_sample(self.proc_root)}
            if self._append("samples", value):
                self.summary["samples"] += 1
                self.summary["cgroup_available_samples"] += int(value["cgroup"]["available"])
                self.summary["proc_available_samples"] += int(value["proc"]["available"])
                for source, destination in (("memory_current_bytes", "sampled_memory_max_bytes"),
                                            ("memory_peak_bytes", "observed_kernel_memory_peak_bytes")):
                    number = value["cgroup"].get(source)
                    if type(number) is int:
                        self.summary[destination] = max(number, self.summary[destination] or 0)
        except Exception as exc:
            self._error(type(exc).__name__)

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            self._sample()
            if "samples" in self.summary["truncated"]:
                break

    def event(self, phase: str, event: str, *, workflow=None, step=None, duration=None, outcome=None):
        try:
            # Only application-owned identifiers belong in this evidence. Never
            # serialize requests, sample names, paths or arbitrary exception text.
            value = {"observed_utc": _utc(), "elapsed_seconds": time.monotonic() - self.started,
                     "phase": phase, "event": event}
            for key, item in (("workflow", workflow), ("step", step), ("outcome", outcome)):
                if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", item):
                    value[key] = item
            if duration is not None:
                value["duration_seconds"] = duration
            if self._append("phases", value):
                self.summary["phase_events"] += 1
        except Exception as exc:
            self._error(type(exc).__name__)

    def stop(self):
        global _ACTIVE
        if _ACTIVE is self:
            _ACTIVE = None
        self.stop_event.set()
        try:
            if self.thread is not None:
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    self._error("observer_join_timeout")
                    # A blocked kernel read must not block scientific completion;
                    # its daemon thread can finish/exit with the engine process.
                    return
            if self.handles:
                self._sample()
                self.summary["finished_utc"] = _utc()
                self.summary["duration_seconds"] = time.monotonic() - self.started
                partial = (self.summary["errors"] or self.summary["truncated"]
                           or not self.summary["cgroup_available_samples"]
                           or not self.summary["proc_available_samples"])
                self.summary["status"] = "partial" if partial else "complete"
                self._save_summary()
                for handle in self.handles.values():
                    handle.close()
                self.handles.clear()
        except Exception as exc:
            self._error(type(exc).__name__)
            _warn("NIPAT performance diagnostics incomplete; scientific results remain unchanged.")
        finally:
            if self.thread is None or not self.thread.is_alive():
                for handle in self.handles.values():
                    try:
                        handle.close()
                    except OSError:
                        pass
                self.handles.clear()


@contextmanager
def phase(name: str, *, workflow=None, step=None):
    """Time a Python-owned boundary without intercepting or modifying R code."""
    observer = _ACTIVE
    if observer is None:
        yield
        return
    started = time.monotonic()
    observer.event(name, "start", workflow=workflow, step=step)
    outcome = "returned"
    try:
        yield
    except BaseException:
        outcome = "raised"
        raise
    finally:
        observer.event(name, "end", workflow=workflow, step=step,
                       duration=time.monotonic() - started, outcome=outcome)
