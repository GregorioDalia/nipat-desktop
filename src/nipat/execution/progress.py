"""Bounded progress reader and presentation snapshots for CLI and future GUIs."""
from __future__ import annotations

from dataclasses import dataclass
import json
from itertools import islice
from pathlib import Path
import threading
import time
from typing import Callable

from nipat_scientific.progress import MAX_FILE_BYTES, MAX_LINE_BYTES, validate_event

MAX_FILES = 256
MAX_TOTAL_BYTES = 32 * 1024 * 1024
READ_CHUNK = 256 * 1024


@dataclass(frozen=True)
class ProgressSnapshot:
    status: str
    elapsed_seconds: float
    phase: str | None
    sample_ids: tuple[str, ...]
    completed: int | None = None
    total: int | None = None
    unit: str | None = None
    last_event_age_seconds: float | None = None
    phase_finished: bool = False
    workflow: str | None = None
    step_id: str | None = None


class ProgressObserver:
    """Poll bounded files independently of stdout; callbacks must return promptly."""
    def __init__(self, directory: Path, callback: Callable[[ProgressSnapshot], None], *,
                 interval: float = 1.0, clock=time.monotonic):
        self.directory, self.callback, self.interval, self.clock = Path(directory), callback, interval, clock
        self.started = clock()
        self.last_event_at = None
        self.latest = None
        self.active = {}
        self.sequences = {}
        self.readers = {}
        self.bytes_read = 0
        self.status = "running"
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()

    def _consume(self, value):
        if not validate_event(value):
            return
        source = value["source_id"]
        if source not in self.sequences and len(self.sequences) >= MAX_FILES:
            return
        if value["sequence"] <= self.sequences.get(source, 0):
            return
        key = (source, value["phase"], tuple(value["sample_ids"]))
        previous = self.active.get(key)
        if (value["event"] == "progress" and previous is not None and "completed" in previous
                and "completed" in value and (value["completed"] < previous["completed"]
                or value["total"] != previous["total"] or value["unit"] != previous["unit"])):
            return
        self.sequences[source] = value["sequence"]
        self.last_event_at = self.clock()
        self.latest = value
        if value["event"] == "end":
            self.active.pop(key, None)
        else:
            # Reinsertion tracks the most recently observed active operation.
            self.active.pop(key, None)
            self.active[key] = value

    def poll(self):
        """One bounded read; tolerate truncated final lines, hostile files and I/O errors."""
        with self._lock:
            try:
                if self.directory.is_symlink() or not self.directory.is_dir():
                    return
                paths = list(islice(self.directory.glob("*.jsonl"), MAX_FILES))
                for path in paths:
                    if path.is_symlink() or not path.is_file():
                        continue
                    if path not in self.readers and len(self.readers) >= MAX_FILES:
                        continue
                    state = self.readers.setdefault(path, [0, b"", False])
                    allowance = min(READ_CHUNK, MAX_FILE_BYTES - state[0], MAX_TOTAL_BYTES - self.bytes_read)
                    if allowance <= 0:
                        continue
                    try:
                        with path.open("rb") as stream:
                            stream.seek(state[0])
                            chunk = stream.read(allowance)
                    except OSError:
                        continue
                    state[0] += len(chunk)
                    self.bytes_read += len(chunk)
                    if not chunk:
                        continue
                    pending = state[1] + chunk
                    lines = pending.split(b"\n")
                    state[1] = lines.pop()
                    for index, line in enumerate(lines):
                        if state[2] and index == 0:
                            state[2] = False
                            continue
                        if len(line) > MAX_LINE_BYTES:
                            continue
                        try:
                            self._consume(json.loads(line))
                        except (ValueError, UnicodeError, TypeError, KeyError):
                            continue
                    if len(state[1]) > MAX_LINE_BYTES:
                        state[1] = b""
                        state[2] = True
            except OSError:
                return

    def snapshot(self):
        with self._lock:
            event = next(reversed(self.active.values()), None) if self.active else self.latest
            now = self.clock()
            return ProgressSnapshot(
                status=self.status, elapsed_seconds=max(0.0, now - self.started),
                phase=event["phase"] if event else None,
                sample_ids=tuple(event["sample_ids"]) if event else (),
                completed=event.get("completed") if event else None,
                total=event.get("total") if event else None,
                unit=event.get("unit") if event else None,
                last_event_age_seconds=None if self.last_event_at is None else max(0.0, now - self.last_event_at),
                phase_finished=bool(event and event["event"] == "end"),
                workflow=event["workflow"] if event else None,
                step_id=event["step_id"] if event else None,
            )

    def _notify(self):
        try:
            self.callback(self.snapshot())
        except Exception:
            # A terminal or GUI failure cannot replace the scientific outcome.
            pass

    def _observe(self):
        while not self._stop.is_set():
            self.poll()
            self._notify()
            self._stop.wait(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._observe, name="nipat-progress", daemon=True)
        self._thread.start()

    def stop(self, outcome="succeeded"):
        self._stop.set()
        if self._thread is not None:
            # The callback contract is nonblocking; join before final delivery so
            # no heartbeat can arrive after cancellation or terminal teardown.
            self._thread.join()
        self.poll()
        with self._lock:
            self.status = outcome
        self._notify()


_WORKFLOW_LABELS = {"dnp-call": "DNPcall", "snp-call": "SNPcall",
                    "contamination": "Contamination", "cpi": "CPI"}


_PHASE_LABELS = {
    "preparation": "Preparazione degli input", "plan-preflight": "Verifica del workflow",
    "presentation-preparation": "Preparazione dei risultati leggibili",
    "r-execution": "Calcolo R", "output-validation": "Controllo dei risultati",
    "presentation-finalization": "Esportazione dei risultati",
    "plan-presentation": "Riepilogo del workflow", "pileup": "Preparazione pileup",
    "pileup-index": "Indicizzazione del pileup", "pileup-reading": "Lettura pileup",
    "dnp-processing": "Calcolo DNP", "plots": "Creazione grafici",
    "dnp-indexed-selection": "Selezione indicizzata delle letture",
    "dnp-indexed-pileup": "Pileup dalle regioni indicizzate", "dnp-pileup": "Preparazione pileup DNP",
}


def _safe(value):
    return "".join(char if ord(char) >= 32 and not 127 <= ord(char) <= 159 else "?" for char in str(value))[:160]


class ProgressRenderer:
    """Readable, throttled lines: no ANSI control sequences in logs or redirected output."""
    def __init__(self, write, *, sample_names=None, is_tty=False, clock=time.monotonic):
        self.write, self.sample_names, self.clock = write, sample_names or {}, clock
        self.interval = 2.0 if is_tty else 15.0
        self.last_at = float("-inf")
        self.last_key = None
        self.tick = 0

    def __call__(self, state):
        key = (state.status, state.workflow, state.step_id, state.phase,
               state.sample_ids, state.phase_finished)
        now = self.clock()
        if key == self.last_key and now - self.last_at < self.interval:
            return
        self.last_at, self.last_key = now, key
        self.tick += 1
        elapsed = int(state.elapsed_seconds)
        duration = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        phase = _PHASE_LABELS.get(state.phase, _safe(state.phase) if state.phase else "Avvio del motore")
        if state.status != "running":
            status = {"succeeded": "completato", "failed": "non riuscito", "cancelled": "annullato",
                      "interrupted": "annullato"}.get(state.status, _safe(state.status))
            self.write(f"Motore {status} | trascorso {duration}\n")
            return
        workflow = _WORKFLOW_LABELS.get(state.workflow)
        if workflow:
            phase = f"{workflow}: {phase}"
        names = [_safe(self.sample_names.get(x, x)) for x in state.sample_ids]
        sample = " | campione: " + ", ".join(names[:3]) if names else ""
        if len(names) > 3:
            sample += f" (+{len(names)-3})"
        counter = ""
        if state.completed is not None and state.total is not None:
            counter = f" | {state.completed}/{state.total} {_safe(state.unit)}"
        qualifier = "fase conclusa" if state.phase_finished else "in esecuzione" + "." * (1 + self.tick % 3)
        self.write(f"{phase}{sample}{counter} | trascorso {duration} | {qualifier}\n")
