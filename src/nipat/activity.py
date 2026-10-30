"""Process-lifetime coordination between installed clients and package updates."""

from __future__ import annotations

import contextlib
import ctypes
import os
from pathlib import Path
import re
import sys
from typing import Iterator

from .errors import NipatError
from .distribution import WINDOWS_DIRECTORY

_BUSY = "NIPAT e in aggiornamento. Attendere la fine dell'installazione prima di avviare una sessione."
_TOKEN = "NIPAT_SETUP_ACTIVITY_TOKEN"


def _safe_parent(path: Path) -> None:
    for entry in (path, *path.parents):
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
            raise NipatError("Il percorso di coordinamento NIPAT non puo attraversare collegamenti.")


def windows_activity_path() -> Path:
    base = os.environ.get("LOCALAPPDATA", "")
    if not base or not Path(base).is_absolute():
        raise NipatError("LOCALAPPDATA non disponibile per coordinare le sessioni NIPAT.")
    path = Path(base) / WINDOWS_DIRECTORY / "activity.lock"
    _safe_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_parent(path)
    return path


def _windows_kernel():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _windows_ancestors() -> set[int]:
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    kernel = _windows_kernel()
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return set()
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    ancestors: set[int] = set()
    current = os.getpid()
    for _ in range(128):
        current = parents.get(current, 0)
        if not current or current in ancestors:
            break
        ancestors.add(current)
    return ancestors


def _authorized_setup_child() -> bool:
    """Only descendants of the live setup lease may run installer diagnostics."""
    token = os.environ.get(_TOKEN, "")
    match = re.fullmatch(r"([1-9][0-9]{0,9}):([a-f0-9]{32})", token)
    if not match or int(match[1]) not in _windows_ancestors():
        return False
    from ctypes import wintypes

    kernel = _windows_kernel()
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    handle = kernel.OpenEventW(0x00100000, False, "Local\\" + WINDOWS_DIRECTORY + "-SetupLease-" + match[2])
    if not handle:
        return False
    kernel.CloseHandle(handle)
    return True


@contextlib.contextmanager
def activity_session(*, project_dir: Path) -> Iterator[None]:
    """Hold a shared lease for the whole CLI; never wait for or stop another process."""
    if sys.platform == "win32":
        if _authorized_setup_child():
            yield
            return
        kernel = _windows_kernel()
        handle = kernel.CreateFileW(str(windows_activity_path()), 0x80000000,
                                    0x00000001 | 0x00000002, None, 4,
                                    0x00000080 | 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            raise NipatError(_BUSY if error in (32, 33) else
                             f"Impossibile coordinare la sessione NIPAT (errore Windows {error}).")
        try:
            yield
        finally:
            kernel.CloseHandle(handle)
        return
    if Path(project_dir).resolve() != Path("/opt/nipat-desktop"):
        yield
        return
    import fcntl

    lock = Path("/var/lib/nipat-desktop/activity.lock")
    _safe_parent(lock)
    try:
        with lock.open("rb") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise NipatError(_BUSY) from exc
            try:
                if lock.with_name("update-in-progress").exists():
                    raise NipatError(_BUSY)
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
    except OSError as exc:
        raise NipatError("Coordinamento NIPAT non disponibile: completare o riparare l'installazione.") from exc
