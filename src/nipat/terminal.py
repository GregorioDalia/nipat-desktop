"""Small, dependency-free terminal presentation for the guided CLI.

The portable Windows Python distribution intentionally has no site-packages.
Menus use console keys only on a real terminal; scripts and redirected output
always retain ordinary line input and plain text.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from contextlib import contextmanager
from typing import Callable, Iterator


_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
_COLORS = {
    "info": "", "muted": "\x1b[90m", "success": "\x1b[32m",
    "warning": "\x1b[33m", "error": "\x1b[31m", "accent": "\x1b[36m",
}
_BANNER = (
    r" _   _ ___ ____   _  _____",
    r"| \ | |_ _|  _ \ / \|_   _|",
    r"|  \| || || |_) / _ \ | |",
    r"| |\  || ||  __/ ___ \| |",
    r"|_| \_|___|_| /_/   \_\_|",
)


def _clean(value: object, *, multiline: bool = False) -> str:
    """Remove terminal commands and control characters from displayed values."""
    text = _ANSI.sub("", str(value))
    return "".join(
        character if (ord(character) >= 32 and not 127 <= ord(character) <= 159)
        or (multiline and character == "\n") else " "
        for character in text
    )


def _decode_key(sequence: str) -> str:
    if sequence in ("\x1b[A", "\x1bOA", "\xe0H", "\x00H"):
        return "up"
    if sequence in ("\x1b[B", "\x1bOB", "\xe0P", "\x00P"):
        return "down"
    if sequence in ("\r", "\n"):
        return "enter"
    if sequence == "\x1b":
        return "escape"
    if sequence == "\x03":
        raise KeyboardInterrupt
    if sequence in ("", "\x04", "\x1a"):
        raise EOFError
    return sequence.casefold() if len(sequence) == 1 and sequence.isprintable() else "ignore"


def _clip(text: str, width: int) -> str:
    """Keep a row on one terminal line, including wide Unicode file names."""
    cells = 0
    for position, character in enumerate(text):
        size = 0 if unicodedata.combining(character) else (
            2 if unicodedata.east_asian_width(character) in ("W", "F") else 1
        )
        if cells + size > width - 4:
            return text[:position] + "..."
        cells += size
    return text


class _Unavailable(Exception):
    pass


class _WindowsConsole:
    """Enable VT on the actual output console and restore its original mode."""

    def __init__(self) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetConsoleMode.restype = wintypes.BOOL
        self.kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.SetConsoleMode.restype = wintypes.BOOL
        input_handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        self.output_handle = msvcrt.get_osfhandle(sys.stdout.fileno())
        input_mode, output_mode = wintypes.DWORD(), wintypes.DWORD()
        if not self.kernel.GetConsoleMode(input_handle, ctypes.byref(input_mode)):
            raise _Unavailable
        if not self.kernel.GetConsoleMode(self.output_handle, ctypes.byref(output_mode)):
            raise _Unavailable
        self.original_mode = output_mode.value
        if not self.kernel.SetConsoleMode(self.output_handle, self.original_mode | 0x0001 | 0x0004):
            raise _Unavailable
        self.closed = False

    def close(self) -> None:
        if not self.closed:
            self.kernel.SetConsoleMode(self.output_handle, self.original_mode)
            self.closed = True


def _windows_key() -> str:
    import msvcrt

    sequence = msvcrt.getwch()
    if sequence in ("\x00", "\xe0"):
        sequence += msvcrt.getwch()
    return _decode_key(sequence)


def _posix_key(fd: int) -> str:
    import select

    first = os.read(fd, 1)
    if not first:
        raise EOFError
    sequence = first
    if first == b"\x1b":
        # A standalone Escape is distinct from an arrow's short escape sequence.
        if not select.select([fd], [], [], 0.08)[0]:
            return "escape"
        sequence += os.read(fd, 1)
        if sequence[-1:] in (b"[", b"O"):
            for _ in range(8):
                if not select.select([fd], [], [], 0.02)[0]:
                    break
                part = os.read(fd, 1)
                sequence += part
                if not part or 64 <= part[0] <= 126:
                    break
    return _decode_key(sequence.decode("utf-8", errors="replace"))


@contextmanager
def _posix_reader(fd: int) -> Iterator[Callable[[], str]]:
    import termios
    import tty

    try:
        original = termios.tcgetattr(fd)
        tty.setcbreak(fd, termios.TCSANOW)
    except (OSError, termios.error) as exc:
        raise _Unavailable from exc
    try:
        yield lambda: _posix_key(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)


class Terminal:
    def __init__(
        self, read: Callable[[str], str] = input, write: Callable[[str], None] = print,
        *, cancel_to_menu: bool = False,
    ) -> None:
        self.read = read
        self.write = write
        self.cancel_to_menu = cancel_to_menu
        self._console: _WindowsConsole | None = None
        self._live = False
        self._color = False
        # Custom streams are used by tests and integrations; never emit cursor
        # sequences into them or bypass their supplied reader.
        if read is not input or write is not print or "NO_COLOR" in os.environ:
            return
        if os.environ.get("TERM", "").casefold() == "dumb":
            return
        try:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                return
            sys.stdin.fileno()
            sys.stdout.fileno()
            if os.name == "nt":
                self._console = _WindowsConsole()
            elif os.name == "posix" and os.environ.get("TERM"):
                import termios

                try:
                    termios.tcgetattr(sys.stdin.fileno())
                except termios.error:
                    return
            else:
                return
        except (OSError, ValueError, AttributeError, ImportError, _Unavailable):
            return
        self._live = self._color = True

    def __enter__(self) -> "Terminal":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._console is not None:
            self._console.close()
            self._console = None
        self._live = self._color = False

    def _emit(self, text: str) -> None:
        if self.write is not print:
            self.write(text)
            return
        try:
            sys.stdout.write(text + "\n")
        except UnicodeEncodeError:
            encoding = sys.stdout.encoding or "utf-8"
            sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding) + "\n")
        sys.stdout.flush()

    def _styled(self, text: str, kind: str) -> str:
        color = _COLORS.get(kind, "") if self._color else ""
        return f"{color}{text}\x1b[0m" if color else text

    def banner(self, version: str, dry_run: bool) -> None:
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
        if width >= 48:
            self._emit(self._styled("\n".join(_BANNER), "accent"))
        else:
            self._emit(self._styled("N I P A T", "accent"))
        self.message(f"NIPAT {_clean(version)} | CLI per la validazione", "muted")
        if dry_run:
            self.message("DRY-RUN: preparazione dei comandi, senza eseguire le analisi.", "warning")

    def heading(self, title: str) -> None:
        self._emit("\n" + self._styled(_clean(title), "accent"))

    def message(self, text: str, kind: str = "info") -> None:
        prefix = {"error": "[ERRORE] ", "warning": "[AVVISO] ", "success": "[OK] "}.get(kind, "")
        self._emit(self._styled(prefix + _clean(text, multiline=True), kind))

    def prompt(self, label: str, default: str = "", path: bool = False) -> str:
        # Native line editing remains available. Path completion is deliberately
        # not emulated differently on Windows and POSIX in this first revision.
        suffix = f" [{_clean(default)}]" if default else ""
        prompt = f"{_clean(label)}{suffix}: "
        if self.read is input:
            encoding = sys.stdout.encoding or "utf-8"
            prompt = prompt.encode(encoding, errors="replace").decode(encoding)
        if self.cancel_to_menu:
            self.message("Ctrl+C oppure :annulla e Invio: torna al menu principale.", "muted")
        answer = self.read(prompt)
        if self.cancel_to_menu and answer.strip().casefold() == ":annulla":
            from nipat.errors import Cancelled
            raise Cancelled
        return answer

    @contextmanager
    def _key_reader(self) -> Iterator[Callable[[], str]]:
        if os.name == "nt":
            yield _windows_key
        else:
            with _posix_reader(sys.stdin.fileno()) as read_key:
                yield read_key

    def _size(self) -> os.terminal_size | None:
        try:
            return os.get_terminal_size(sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            return None

    def _menu_lines(
        self, choices: list[tuple[str, str, str]], selected: int, width: int,
        groups: dict[str, str] | None = None,
    ) -> list[str]:
        lines = []
        for index, (key, label, description) in enumerate(choices):
            if groups and key.casefold() in groups:
                lines.append(self._styled(_clip(groups[key.casefold()], width), "muted"))
            text = f"{'>' if index == selected else ' '} {key}  {label}"
            if description:
                text += f"  - {description}"
            text = _clip(text, width)
            lines.append(self._styled(text, "accent") if index == selected else text)
        lines.append(self._styled(_clip(
            "Su/Giu e Invio | Esc: indietro | Numero/lettera: scelta", width,
        ), "muted"))
        if self.cancel_to_menu:
            lines.append(self._styled("Ctrl+C: annulla e torna al menu principale", "muted"))
        return lines

    def menu(
        self, title: str, choices: list[tuple[str, str, str]], default: str | None = None,
        *, groups: dict[str, str] | None = None,
    ) -> str:
        if not choices:
            raise ValueError("A menu must contain at least one choice.")
        clean = [tuple(_clean(part) for part in choice) for choice in choices]
        keys = [choice[0].casefold() for choice in clean]
        if len(set(keys)) != len(keys) or any(not key for key in keys):
            raise ValueError("Menu keys must be nonempty and unique.")
        group_names = {key.casefold(): _clean(label) for key, label in (groups or {}).items()}
        if not set(group_names).issubset(keys):
            raise ValueError("Menu group headings must refer to existing choices.")
        self.heading(title)
        size = self._size() if self._live else None
        minimum_rows = len(clean) + len(group_names) + 5 + int(self.cancel_to_menu)

        def fits(dimensions: os.terminal_size | None) -> bool:
            return bool(dimensions and dimensions.columns >= 52 and dimensions.lines >= minimum_rows)

        rendered = False
        if fits(size) and all(len(k) == 1 for k in keys):
            selected = keys.index(default.casefold()) if default and default.casefold() in keys else 0
            try:
                with self._key_reader() as read_key:
                    lines = self._menu_lines(clean, selected, size.columns, group_names)
                    self._emit("\n".join(lines))
                    rendered = True
                    while True:
                        key = read_key()
                        if key == "enter":
                            return clean[selected][0]
                        if key == "escape":
                            return ":indietro"
                        if key in keys:
                            return clean[keys.index(key)][0]
                        if key not in ("up", "down"):
                            continue
                        selected = (selected + (1 if key == "down" else -1)) % len(clean)
                        current_size = self._size()
                        if current_size != size:
                            # Reflow makes the old cursor offsets unreliable. A
                            # fresh, explicitly labelled rendering is safe and
                            # retains both selection and earlier log output.
                            if fits(current_size):
                                size = current_size
                                self.message("Finestra ridimensionata: menu aggiornato; le frecce restano attive.", "muted")
                                lines = self._menu_lines(clean, selected, size.columns, group_names)
                                self._emit("\n".join(lines))
                                continue
                            reason = ("dimensioni della console non disponibili" if current_size is None else
                                      "finestra troppo piccola dopo il ridimensionamento")
                            self.message(f"Menu testuale: {reason}. Digitare il numero o la lettera della voce e premere Invio. Le frecce saranno riprovate al prossimo menu.", "muted")
                            default = clean[selected][0]
                            break
                        # Only the menu is redrawn; previous analysis/log text stays
                        # available in terminal scrollback.
                        lines = self._menu_lines(clean, selected, size.columns, group_names)
                        self._emit(f"\x1b[{len(lines)}A" + "\n".join("\r\x1b[2K" + line for line in lines))
            except (_Unavailable, OSError, ValueError) as exc:
                self._live = False
                # Do not include exception messages: an OS error can contain
                # user paths. Type and numeric OS code are sufficient to
                # distinguish a read failure from a harmless resize.
                cause = exc.__cause__ if isinstance(exc, _Unavailable) and exc.__cause__ else exc
                diagnostic = type(cause).__name__
                error_code = getattr(cause, "winerror", None) or getattr(cause, "errno", None)
                if isinstance(error_code, int):
                    diagnostic += f", codice {error_code}"
                self.message(f"Navigazione a frecce non disponibile ({diagnostic}). Modalita' testuale per questa sessione: digitare il numero o la lettera della voce e premere Invio.", "muted")
                if rendered:
                    default = clean[selected][0]
        elif self._live and all(len(k) == 1 for k in keys):
            reason = "dimensioni della console non disponibili" if size is None else "finestra troppo piccola per le frecce"
            self.message(f"Menu testuale: {reason}. Digitare il numero o la lettera della voce e premere Invio.", "muted")
        # If the live list is already on screen, do not duplicate it solely
        # because input switches to line mode. Its keys remain valid.
        if not rendered:
            for key, label, description in clean:
                if key.casefold() in group_names:
                    self.message(group_names[key.casefold()], "muted")
                self.message(f"  {key}  {label}" + (f" - {description}" if description else ""))
        answer = self.prompt("Scelta", default=default or "").strip()
        if not answer and default is not None:
            return default
        return answer
