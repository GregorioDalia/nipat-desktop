"""No network or installer side effects without the user's explicit choices."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from nipat.cli import DEFAULT_ERR_CONST
from nipat.errors import ValidationError
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, PreferencesStore
from nipat.terminal import Terminal
from nipat.update_ui import DownloadProgress, HANDOFF_EXIT_CODE, run_updates
from nipat.wizard import run_wizard


class UpdateUITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        app = self.root / "app"
        app.mkdir()
        self.layout = ProjectLayout(app, self.root, self.root / "data", self.root / "runs", app / "compose.yaml")
        self.offer = SimpleNamespace(
            version="0.6.1", channel="testing", release_tag="v0.6.1",
            release_notes_url="https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.6.1",
            asset=SimpleNamespace(platform="windows-x86_64", name="NIPAT-Setup.exe", size=1024,
                                  sha256="a" * 64, url="https://example.invalid/not-used"))
        self.client = Mock()
        self.client.check.return_value = SimpleNamespace(status="available", message="Disponibile", offer=self.offer)
        self.client.download.return_value = self.root / "updates" / "NIPAT-Setup.exe"
        self.handoff = Mock(return_value=True)
        self.messages = []

    def invoke(self, answers=(), **kwargs):
        ui = Terminal(read=Mock(side_effect=list(answers)), write=self.messages.append)
        return run_updates(ui, self.layout, Preferences(), client=self.client,
                           download_directory=self.root / "updates", handoff=self.handoff,
                           platform="windows-x86_64", **kwargs)

    def test_manual_check_offers_version_notes_size_but_enter_never_downloads(self):
        self.assertFalse(self.invoke([""]))
        self.client.check.assert_called_once()
        self.client.download.assert_not_called()
        self.handoff.assert_not_called()
        text = "\n".join(self.messages)
        self.assertIn("0.6.1", text)
        self.assertIn(self.offer.release_notes_url, text)
        self.assertIn("Dimensione:", text)

    def test_download_confirmation_does_not_authorize_installation(self):
        self.assertFalse(self.invoke(["1", ""]))
        self.client.download.assert_called_once()
        self.assertEqual(self.client.download.call_args.args[1], self.root / "updates" / "0.6.1")
        self.handoff.assert_not_called()
        self.assertIn("versione installata non e' stata modificata", "\n".join(self.messages))

    def test_install_requires_two_explicit_choices_and_handoff_success(self):
        self.assertTrue(self.invoke(["1", "1"]))
        self.handoff.assert_called_once_with(self.offer, self.client.download.return_value, self.layout.project_dir)
        self.assertIn("Chiusura della sessione", "\n".join(self.messages))

    def test_interrupted_final_message_still_closes_after_confirmed_handoff(self):
        def write(message):
            if "Chiusura della sessione" in message:
                raise KeyboardInterrupt
            self.messages.append(message)

        ui = Terminal(read=Mock(side_effect=["1", "1"]), write=write)
        started = run_updates(ui, self.layout, Preferences(), client=self.client,
                              download_directory=self.root / "updates", handoff=self.handoff,
                              platform="windows-x86_64")
        self.assertTrue(started)
        self.handoff.assert_called_once()
        self.assertNotIn("annullata", "\n".join(self.messages))

    def test_handoff_declined_keeps_the_session_open(self):
        self.handoff.return_value = False
        self.assertFalse(self.invoke(["1", "1"]))
        self.assertIn("Installazione non avviata", "\n".join(self.messages))

    def test_handoff_failure_is_local_and_keeps_downloaded_file_available(self):
        self.handoff.side_effect = ValidationError("Nessun terminale disponibile; usare apt install.")
        self.assertFalse(self.invoke(["1", "1"]))
        self.assertIn("La sessione resta aperta", "\n".join(self.messages))
        self.assertIn("apt install", "\n".join(self.messages))

    def test_bad_checksum_never_offers_installation(self):
        self.client.download.side_effect = ValidationError("SHA-256 non corrispondente")
        self.assertFalse(self.invoke(["1"]))
        self.handoff.assert_not_called()
        self.assertIn("SHA-256 non corrispondente", "\n".join(self.messages))
        self.assertNotIn("Installare l'aggiornamento?", "\n".join(self.messages))

    def test_cancel_during_download_keeps_application_usable(self):
        self.client.download.side_effect = KeyboardInterrupt
        self.assertFalse(self.invoke(["1"]))
        self.handoff.assert_not_called()
        self.assertIn("annullata", "\n".join(self.messages))

    def test_unknown_choice_does_not_grant_approval(self):
        self.assertFalse(self.invoke(["si", "invalid", "0"]))
        self.client.download.assert_not_called()
        self.handoff.assert_not_called()

    def test_startup_notification_never_prompts_downloads_or_installs(self):
        self.assertFalse(self.invoke(startup=True))
        self.client.check.assert_called_once()
        self.client.download.assert_not_called()
        self.handoff.assert_not_called()
        self.assertIn("9 - Verifica aggiornamenti", "\n".join(self.messages))

    def test_dry_run_never_contacts_network_or_invokes_installer(self):
        for startup in (False, True):
            self.assertFalse(self.invoke(dry_run=True, startup=startup))
        self.client.check.assert_not_called()
        self.client.download.assert_not_called()
        self.handoff.assert_not_called()

    def test_offline_rate_limit_and_no_release_are_clear_and_nonfatal(self):
        for status, message in (("offline", "Connessione non disponibile"),
                                ("rate_limited", "Limite GitHub raggiunto"),
                                ("no_eligible_release", "Nessuna release disponibile nel canale"),
                                ("up_to_date", "Versione aggiornata"),
                                ("invalid_metadata", "Manifest non valido")):
            with self.subTest(status=status):
                self.client.check.return_value = SimpleNamespace(status=status, message=message, offer=None)
                self.assertFalse(self.invoke())
                self.assertIn(message, "\n".join(self.messages))
        self.client.download.assert_not_called()
        self.handoff.assert_not_called()

    def test_progress_is_throttled_and_completion_is_displayed(self):
        ui = Terminal(read=Mock(), write=self.messages.append)
        clock = Mock(side_effect=[0, 0.1, 0.2, 1.2, 1.3, 1.4])
        progress = DownloadProgress(ui, clock=clock)
        for amount in (0, 1, 2, 3, 10, 10):
            progress(amount, 10)
        self.assertEqual(len(self.messages), 3)
        self.assertIn("0%", self.messages[0])
        self.assertIn("30%", self.messages[1])
        self.assertIn("100%", self.messages[2])

    def wizard(self, answers, prefs=None, **kwargs):
        store = PreferencesStore(self.root / "preferences.json")
        if prefs is not None:
            store.save(prefs)
        workflows = Mock()
        status = run_wizard(workflows, self.layout, err_const=DEFAULT_ERR_CONST,
                            preferences_store=store, read=Mock(side_effect=answers),
                            write=self.messages.append, **kwargs)
        return status, store, workflows

    def test_wizard_default_startup_does_not_check_and_menu_handoff_returns_exit85(self):
        with patch("nipat.wizard.run_updates", return_value=True) as updater:
            status, _, _ = self.wizard(["0"])
            self.assertEqual(status, 0)
            updater.assert_not_called()
            status, _, _ = self.wizard(["9"])
            self.assertEqual(status, HANDOFF_EXIT_CODE)
            self.assertEqual(status, 85)
            updater.assert_called_once()

    def test_enabled_startup_check_is_notification_only(self):
        with patch("nipat.wizard.run_updates", return_value=False) as updater:
            status, _, workflows = self.wizard(["0"], Preferences(check_updates_on_startup=True))
        self.assertEqual(status, 0)
        updater.assert_called_once()
        self.assertTrue(updater.call_args.kwargs["startup"])
        workflows.dnp_call.assert_not_called()

    def test_failed_update_check_does_not_change_wizard_exit_status(self):
        with patch("nipat.wizard.run_updates", return_value=False):
            status, _, _ = self.wizard(["9", "0"])
        self.assertEqual(status, 0)

    def test_update_settings_save_explicitly_and_cancel_discards_edits(self):
        with patch("nipat.wizard.run_updates") as updater:
            status, store, _ = self.wizard(["5", "8", "1", "2", "2", "1", "9", "0", "0"])
        self.assertEqual(status, 0)
        prefs = store.load()
        self.assertEqual(prefs.update_channel, "stable")
        self.assertTrue(prefs.check_updates_on_startup)
        updater.assert_not_called()  # Changing a setting does not trigger a check immediately.
        with patch("nipat.wizard.run_updates", return_value=False):
            self.wizard(["5", "8", "1", "1", "2", "2", "0", "0", "0"])
        self.assertEqual(store.load(), prefs)


if __name__ == "__main__":
    unittest.main()
