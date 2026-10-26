import io
import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from nipat.terminal import Terminal, _clean, _clip, _decode_key, _posix_reader
from nipat.errors import Cancelled


CHOICES = [("1", "DNPcall", "BAM"), ("2", "SNPcall", "BAM o pileup"), ("0", "Esci", "")]


class TerminalTests(unittest.TestCase):
    def test_custom_io_stays_plain_and_preserves_invalid_answer(self):
        output = []
        read = Mock(return_value="invalid")
        terminal = Terminal(read=read, write=output.append)
        terminal.banner("0.3.0a1", dry_run=False)
        self.assertEqual(terminal.menu("Analisi", CHOICES), "invalid")
        self.assertIn("NIPAT 0.3.0a1", "\n".join(output))
        self.assertNotIn("\x1b", "\n".join(output))
        read.assert_called_once_with("Scelta: ")

    def test_plain_default_and_raw_prompt_are_distinct(self):
        terminal = Terminal(read=Mock(side_effect=["", "", '"a b.txt"']), write=lambda _: None)
        self.assertEqual(terminal.menu("Analisi", CHOICES, default="2"), "2")
        self.assertEqual(terminal.prompt("Nome", default="originale"), "")
        self.assertEqual(terminal.prompt("File", path=True), '"a b.txt"')

    def test_wizard_cancel_command_is_global_and_opt_in(self):
        output = []
        terminal = Terminal(read=Mock(return_value="  :AnNuLlA  "), write=output.append,
                            cancel_to_menu=True)
        with self.assertRaises(Cancelled):
            terminal.prompt("BAM", path=True)
        with self.assertRaises(Cancelled):
            terminal.menu("Catalogo", CHOICES, default="1")
        self.assertIn("Ctrl+C", "\n".join(output))
        terminal.cancel_to_menu = False
        self.assertEqual(terminal.prompt("Test"), "  :AnNuLlA  ")

    def test_live_cancel_guidance_and_keyboard_interrupt_leave_reader(self):
        terminal, output, _ = self.make_live([KeyboardInterrupt()])
        terminal.cancel_to_menu = True
        with self.assertRaises(KeyboardInterrupt):
            terminal.menu("Workflow", CHOICES)
        self.assertIn("Ctrl+C: annulla e torna al menu principale", "\n".join(output))

    def test_live_wizard_redraw_accounts_for_cancel_hint_and_accepts_letter(self):
        terminal, output, _ = self.make_live(["down", "w"])
        terminal.cancel_to_menu = True
        self.assertEqual(terminal.menu("Workflow", CHOICES + [("W", "Workflow", "")]), "W")
        self.assertIn("\x1b[6A", "\n".join(output))

    def test_displayed_input_cannot_emit_terminal_commands(self):
        output = []
        read = Mock(return_value="raw\x1b[31mvalue")
        terminal = Terminal(read=read, write=output.append)
        terminal.message("file\x1b[31m.txt\x07", "error")
        self.assertEqual(output[-1], "[ERRORE] file.txt ")
        self.assertEqual(terminal.prompt("name\nnext"), "raw\x1b[31mvalue")
        read.assert_called_once_with("name next: ")

    def test_redirected_standard_streams_never_enable_ansi(self):
        out = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stdin", io.StringIO()):
            with Terminal() as terminal:
                terminal.message("Completato", "success")
                self.assertFalse(terminal._live)
        self.assertEqual(out.getvalue(), "[OK] Completato\n")

    def test_no_color_and_dumb_terminal_do_not_touch_console_modes(self):
        for environment in ({"NO_COLOR": ""}, {"TERM": "dumb"}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment):
                with patch("nipat.terminal._WindowsConsole") as console:
                    terminal = Terminal()
                self.assertFalse(terminal._live)
                self.assertFalse(terminal._color)
                console.assert_not_called()

    def test_dry_run_is_explicit_in_banner(self):
        output = []
        terminal = Terminal(write=output.append)
        terminal.banner("test", dry_run=True)
        self.assertIn("DRY-RUN", "\n".join(output))
        self.assertNotIn("pronto", "\n".join(output))

    def make_live(self, sequence, *, size=(80, 24)):
        output = []
        terminal = Terminal(read=Mock(), write=output.append)
        terminal._live = True
        terminal._color = True
        terminal._size = Mock(return_value=os.terminal_size(size))
        read_key = Mock(side_effect=sequence)

        @contextmanager
        def keys():
            yield read_key

        terminal._key_reader = keys
        return terminal, output, read_key

    def test_arrows_select_wrap_and_enter_default(self):
        terminal, output, _ = self.make_live(["up", "enter"])
        self.assertEqual(terminal.menu("Analisi", CHOICES), "0")
        self.assertIn("\x1b[4A", "\n".join(output))
        terminal, _, _ = self.make_live(["enter"])
        self.assertEqual(terminal.menu("Analisi", CHOICES, default="2"), "2")

    def test_direct_number_and_escape_work_in_live_menu(self):
        for sequence, answer in ((["2"], "2"), (["escape"], ":indietro")):
            terminal, _, _ = self.make_live(sequence)
            self.assertEqual(terminal.menu("Analisi", CHOICES), answer)

    def test_narrow_terminal_uses_line_reader(self):
        terminal, output, read_key = self.make_live([], size=(40, 12))
        terminal.read.return_value = "2"
        self.assertEqual(terminal.menu("Analisi", CHOICES), "2")
        read_key.assert_not_called()
        self.assertNotIn("\x1b[4A", "\n".join(output))

    def test_resize_falls_back_without_cursor_redraw(self):
        terminal, output, _ = self.make_live(["down"])
        terminal._size.side_effect = [os.terminal_size((80, 24)), os.terminal_size((30, 10))]
        terminal.read.return_value = "2"
        self.assertEqual(terminal.menu("Analisi", CHOICES), "2")
        self.assertFalse(terminal._live)
        self.assertNotIn("\x1b[4A", "\n".join(output))

    def test_wide_labels_are_clipped_before_the_terminal_edge(self):
        self.assertEqual(_clip("abcdef", 20), "abcdef")
        self.assertEqual(_clip("試験試験試験", 12), "試験試験...")

    def test_keyboard_interrupt_and_eof_propagate(self):
        for error in (KeyboardInterrupt(), EOFError()):
            terminal, _, _ = self.make_live([error])
            with self.assertRaises(type(error)):
                terminal.menu("Analisi", CHOICES)

    def test_context_restores_console_even_on_exception(self):
        terminal = Terminal(read=Mock(), write=Mock())
        console = Mock()
        terminal._console = console
        with self.assertRaises(KeyboardInterrupt):
            with terminal:
                raise KeyboardInterrupt
        terminal.close()
        console.close.assert_called_once_with()
        self.assertFalse(terminal._live)

    def test_keys_decode_for_windows_and_posix(self):
        for sequence in ("\xe0H", "\x00H", "\x1b[A", "\x1bOA"):
            self.assertEqual(_decode_key(sequence), "up")
        for sequence in ("\xe0P", "\x00P", "\x1b[B", "\x1bOB"):
            self.assertEqual(_decode_key(sequence), "down")
        self.assertEqual(_decode_key("\x1b"), "escape")
        self.assertEqual(_decode_key("\x1b[C"), "ignore")
        with self.assertRaises(KeyboardInterrupt):
            _decode_key("\x03")
        with self.assertRaises(EOFError):
            _decode_key("")

    @unittest.skipUnless(os.name == "posix", "POSIX console restoration")
    def test_posix_mode_restored_after_interrupt(self):
        import pty
        import termios

        master, slave = pty.openpty()
        try:
            original = termios.tcgetattr(slave)
            with self.assertRaises(KeyboardInterrupt):
                with _posix_reader(slave):
                    self.assertNotEqual(termios.tcgetattr(slave), original)
                    raise KeyboardInterrupt
            self.assertEqual(termios.tcgetattr(slave), original)
        finally:
            os.close(master)
            os.close(slave)

    def test_no_escape_survives_cleaning_osc_or_csi(self):
        self.assertEqual(_clean("a\x1b]0;title\x07b\x1b[2Jc\x00"), "abc ")


if __name__ == "__main__":
    unittest.main()
