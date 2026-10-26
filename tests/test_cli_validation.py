import csv
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir, nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from nipat.cli import DEFAULT_ERR_CONST, build_parser, main
from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.preferences import PreferencesStore
from nipat.validation.self_test import compare_snp_outputs, run_self_tests
from nipat.wizard import run_wizard


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'repo'
        self.project.mkdir()
        self.layout = ProjectLayout(self.project, self.root, self.root / 'data',
                                    self.root / 'runs', self.project / 'compose.yaml')
        self.bam = self.file('sample one.bam', '')
        self.other_bam = self.file('sample two.bam', '')
        self.reference = self.file('ref.fa', '>chr1\nACGT\n')
        self.file('ref.fa.fai', 'chr1\t4\t6\t4\t5\n')
        self.panel = self.file('DNP.txt', 'chr1\t1\t2\tAC\tGT\n')
        self.snp_panel = self.file('SNP.txt', 'pos\tref\talt\nchr1:2\tC\tG\n')
        self.pileup = self.file('pileup.txt', 'chr1\t2\tC\t1\t.\tI\tread1\n')
        self.table = self.file('counts.tsv', 'chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\nchr1\t1\t2\t5\t0\t0\n')
        self.samples = self.root / 'samples'
        self.samples.mkdir()
        self.popfreq = self.file('pop.tsv', 'chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t1\t2\t0.5\t0.5\n')
        self.run = self.layout.runs_dir / 'test'
        (self.run / 'output').mkdir(parents=True)
        (self.run / 'run.json').write_text(
            '{"schema_version": 1, "workflow": "fixture", "status": "succeeded"}',
            encoding='utf-8',
        )
        self.workflows = Mock()
        for name in ('dnp_call', 'snp_call', 'contamination', 'cpi'):
            getattr(self.workflows, name).return_value = self.run

    def file(self, name, content):
        path = self.root / name
        path.write_text(content, encoding='utf-8')
        return path

    def invoke(self, answers, **kwargs):
        messages = []
        reader = Mock(side_effect=[str(answer) if isinstance(answer, Path) else answer for answer in answers])
        result = run_wizard(self.workflows, self.layout, err_const=DEFAULT_ERR_CONST,
                            read=reader, write=messages.append, **kwargs)
        return result, '\n'.join(messages)

    def snp_answers(self, name=''):
        return ['2', '1', self.bam, self.reference, self.snp_panel, name]

    def cpi_answers(self):
        return ['4', self.samples, 'A:B', '', '', self.popfreq]

    def test_dnp_uses_paths_with_spaces_and_explicit_confirmation(self):
        result, messages = self.invoke(['1', '1', f'"{self.bam}"', '', self.reference,
                                        self.panel, '1', 'my-run', '1', '0', '0'])
        self.assertEqual(result, 0)
        self.workflows.dnp_call.assert_called_once_with(
            bams=[self.bam], bamlist=None, reference=self.reference, panel=self.panel,
            parallel=False, run_name='my-run')
        self.assertIn('Riepilogo prima', messages)
        self.assertIn('Esecuzione completata', messages)

    def test_review_cancel_never_invokes_workflow(self):
        result, messages = self.invoke(self.snp_answers() + ['0', '0'])
        self.assertEqual(result, 0)
        self.workflows.snp_call.assert_not_called()
        self.assertIn('annullata prima', messages)

    def test_back_retains_prior_field_and_allows_replacement(self):
        self.invoke(['2', '1', self.bam, ':indietro', self.other_bam,
                     self.reference, self.snp_panel, '', '1', '0', '0'])
        self.assertEqual(self.workflows.snp_call.call_args.kwargs['bam'], self.other_bam)

    def test_invalid_file_is_corrected_without_restarting_form(self):
        result, messages = self.invoke(['2', '1', self.root / 'missing.bam', self.bam,
                                        self.reference, self.snp_panel, '', '1', '0', '0'])
        self.assertEqual(result, 0)
        self.assertIn('BAM non trovato', messages)
        self.assertEqual(self.workflows.snp_call.call_count, 1)

    def test_malformed_tsv_can_be_replaced_without_traceback(self):
        oversized = self.file('oversized.tsv', 'pos\tref\talt\nchr1:2\t' + 'A' * 140000 + '\tG\n')
        result, messages = self.invoke(['2', '2', self.pileup, oversized, self.snp_panel,
                                        '', '1', '0', '0'])
        self.assertEqual(result, 0)
        self.assertIn('field larger', messages)
        self.assertEqual(self.workflows.snp_call.call_args.kwargs['panel'], self.snp_panel)

    def test_edit_mode_discards_hidden_arguments_and_collects_new_input(self):
        self.invoke(self.snp_answers('edit') + ['2', '1', '2', self.pileup, '1', '0', '0'])
        self.workflows.snp_call.assert_called_once_with(
            bam=None, pileup=self.pileup, reference=None, panel=self.snp_panel, run_name='edit')

    def test_edit_run_name_preserves_remaining_values(self):
        self.invoke(self.snp_answers('before') + ['2', '5', 'after', '1', '0', '0'])
        self.assertEqual(self.workflows.snp_call.call_args.kwargs['run_name'], 'after')
        self.assertEqual(self.workflows.snp_call.call_args.kwargs['bam'], self.bam)

    def test_invalid_field_number_returns_to_review_without_execution(self):
        result, messages = self.invoke(self.snp_answers() + ['2', '\u00b2', '0', '0'])
        self.assertEqual(result, 0)
        self.assertIn('Campo non valido', messages)
        self.workflows.snp_call.assert_not_called()

    def test_snp_pileup_mode_does_not_ask_for_reference(self):
        result, _ = self.invoke(['2', '2', self.pileup, self.snp_panel, '', '1', '0', '0'])
        self.assertEqual(result, 0)
        self.workflows.snp_call.assert_called_once_with(
            bam=None, pileup=self.pileup, reference=None, panel=self.snp_panel, run_name=None)

    def test_contamination_collects_multiple_inputs(self):
        second = self.file('second.txt', self.table.read_text())
        self.invoke(['3', '1', self.table, second, '', self.panel, 'contam', '1', '0', '0'])
        self.workflows.contamination.assert_called_once_with(
            inputs=[self.table, second], input_dir=None, panel=self.panel, run_name='contam')

    def test_contamination_directory_mode(self):
        self.invoke(['3', '2', self.samples, self.panel, '', '1', '0', '0'])
        self.workflows.contamination.assert_called_once_with(
            inputs=None, input_dir=self.samples, panel=self.panel, run_name=None)

    def test_cpi_all_sites_preserves_editable_prefixes(self):
        self.invoke(['4', self.samples, 'M1:F1', 'Plasma_', ':vuoto', self.popfreq,
                     '0', '', '', '1', '0', '0'])
        self.workflows.cpi.assert_called_once_with(
            input_dir=self.samples, pairs='M1:F1', mother_prefix='Plasma_', father_prefix='',
            popfreq=self.popfreq, panel=None, cutoffs=None, cutoff_map=None,
            err_const=DEFAULT_ERR_CONST, run_name=None)

    def test_cpi_repeated_cutoffs_and_numeric_validation(self):
        result, messages = self.invoke(self.cpi_answers() + [
            '2', '0.3', self.panel, '0.5', self.panel, '',
            'bad', 'nan', 'inf', '-1', '0', '', '1', '0', '0'])
        self.assertEqual(result, 0)
        args = self.workflows.cpi.call_args.kwargs
        self.assertEqual(args['cutoffs'], [('0.3', self.panel), ('0.5', self.panel)])
        self.assertEqual(args['err_const'], 0.0)
        self.assertIsNone(args['panel'])
        self.assertEqual(messages.count('numero finito maggiore o uguale a zero'), 4)

    def test_cpi_native_map_and_single_panel_modes(self):
        native = f'0.3={self.panel}'
        for answers, expected in ((['3', native], {'cutoff_map': native, 'panel': None}),
                                  (['1', self.panel], {'cutoff_map': None, 'panel': self.panel})):
            with self.subTest(answers=answers):
                self.invoke(self.cpi_answers() + answers + ['', '', '1', '0', '0'])
                for key, value in expected.items():
                    self.assertEqual(self.workflows.cpi.call_args.kwargs[key], value)

    def test_dnp_bamlist_relative_entries_and_parallel(self):
        bamlist = self.file('bams.txt', '"sample one.bam"\nsample two.bam\n')
        self.invoke(['1', '2', bamlist, self.reference, self.panel, '2', '', '1', '0', '0'])
        self.workflows.dnp_call.assert_called_once_with(
            bams=None, bamlist=bamlist, reference=self.reference, panel=self.panel,
            parallel=True, run_name=None)

    def test_dnp_multiple_bams_and_duplicate_retry(self):
        result, messages = self.invoke(['1', '1', self.bam, self.bam, self.other_bam, '',
                                        self.reference, self.panel, '1', '', '1', '0', '0'])
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.dnp_call.call_args.kwargs['bams'], [self.bam, self.other_bam])
        self.assertIn("gia' presente nella lista", messages)

    def test_cancel_and_eof_do_not_execute(self):
        for answers, expected in ((['1', ':annulla', '0'], 0), ([EOFError()], 130),
                                  ([KeyboardInterrupt(), '0'], 0)):
            result, _ = self.invoke(answers)
            self.assertEqual(result, expected)
        self.workflows.dnp_call.assert_not_called()

    def test_cancel_returns_directly_to_main_from_every_form_and_nested_screen(self):
        paths = [
            ['1', '1', self.bam], ['2', '1'], ['3', '1'], ['4', self.samples],
            self.snp_answers(), self.snp_answers() + ['2'],
            self.snp_answers() + ['2', '5'],
            ['W'], ['W', '1', '1'], ['W', '2', 'Pair1'],
            ['W', '3', 'Pair1', self.bam], ['W', '4', '1'],
            ['7'], ['7', '6'], ['7', '6', '1'],
            ['5'], ['5', '1', '2'], ['5', '8', '1'], ['5', '7'],
        ]
        for path in paths:
            for cancel in (':AnNuLlA', KeyboardInterrupt()):
                with self.subTest(path=path, cancel=cancel):
                    result, messages = self.invoke(path + [cancel, '0'])
                    self.assertEqual(result, 0)
                    self.assertEqual(messages.count('Menu principale\n'), 2)
                    self.assertIn('Ritorno al menu principale', messages)
        for method in ('dnp_call', 'snp_call', 'contamination', 'cpi',
                       'dnp_contamination', 'dnp_cpi', 'snp_batch'):
            getattr(self.workflows, method).assert_not_called()

    def test_main_cancel_and_escape_do_not_close_session(self):
        result, messages = self.invoke([':annulla', KeyboardInterrupt(), ':indietro', '0'])
        self.assertEqual(result, 0)
        self.assertEqual(messages.count('Menu principale\n'), 4)

    def test_cancel_after_saved_settings_keeps_saved_layout_and_discards_pending_edit(self):
        target = self.root / 'saved results'
        discarded = self.root / 'unsaved results'
        store = PreferencesStore(self.root / 'preferences.json')
        result, _ = self.invoke([
            '5', '1', '2', target, '9', '1', '2', discarded, ':annulla', '0',
        ], preferences_store=store)
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.layout.runs_dir, target)
        self.assertIs(self.workflows.layout, self.workflows.runner.layout)
        self.assertFalse(discarded.exists())
        self.assertEqual(store.load().runs_dir, target)

    def test_environment_interrupt_returns_to_menu_and_can_retry(self):
        self.workflows.runner.doctor.side_effect = [KeyboardInterrupt(), None]
        result, messages = self.invoke(['8', '8', '0'])
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.runner.doctor.call_count, 2)
        self.assertEqual(messages.count('Controllo completato:'), 1)
        self.assertIn('Ritorno al menu principale', messages)

    def test_interrupted_run_remains_accessible_and_another_analysis_can_start(self):
        interrupted = self.layout.new_run_dir('snp-call', 'interrupted')
        (interrupted / 'run.json').write_text(
            '{"schema_version": 1, "workflow": "snp-call", "status": "interrupted"}',
            encoding='utf-8',
        )
        (interrupted / 'execution.log').write_text('partial log\n', encoding='utf-8')
        self.workflows.runner.last_run_dir = None
        def cancel(**_kwargs):
            self.workflows.runner.last_run_dir = interrupted
            raise KeyboardInterrupt
        self.workflows.snp_call.side_effect = cancel
        self.workflows.contamination.return_value = self.run
        result, messages = self.invoke(self.snp_answers('cancelled') + [
            '1', '6', '0', '3', '1', self.table, '', self.panel, 'new-analysis', '1', '0', '0',
        ])
        self.assertEqual(result, 0)
        self.assertIn('Esecuzione interrotta:', messages)
        self.assertIn(str(interrupted), messages)
        self.assertIn('Esecuzione completata', messages)
        self.assertEqual((interrupted / 'execution.log').read_text(), 'partial log\n')
        self.workflows.snp_call.assert_called_once()
        self.workflows.contamination.assert_called_once()

    def test_cancellation_before_run_creation_does_not_adopt_stale_runner_directory(self):
        self.workflows.runner.last_run_dir = self.run
        self.workflows.snp_call.side_effect = KeyboardInterrupt()
        result, messages = self.invoke(self.snp_answers() + ['1', '6', '0'])
        self.assertEqual(result, 0)
        self.assertIn('Nessuna esecuzione', messages)
        self.assertNotIn('Esecuzione interrotta:', messages)

    def test_cancel_from_results_keeps_the_completed_run(self):
        for cancel in (':annulla', KeyboardInterrupt()):
            with self.subTest(cancel=cancel):
                result, messages = self.invoke(self.snp_answers() + ['1', cancel, '6', '0', '0'])
                self.assertEqual(result, 0)
                self.assertEqual(messages.count('Esecuzione completata'), 2)

    def test_update_interrupt_keeps_session_open(self):
        with patch('nipat.wizard.run_updates', side_effect=KeyboardInterrupt()):
            result, messages = self.invoke(['9', '7', '0', '0'])
        self.assertEqual(result, 0)
        self.assertIn('Guida e informazioni', messages)

    def test_workflow_failure_retains_form_for_corrected_retry(self):
        self.workflows.snp_call.side_effect = [ValidationError('Pannello non valido'), self.run]
        result, messages = self.invoke(self.snp_answers('first') + [
            '1', '2', '5', 'retry', '1', '0', '0'])
        self.assertEqual(result, 2)  # Existing session-level failure exit semantics.
        self.assertEqual(self.workflows.snp_call.call_count, 2)
        self.assertEqual(self.workflows.snp_call.call_args.kwargs['run_name'], 'retry')
        self.assertIn('Operazione non riuscita: Pannello non valido', messages)
        self.assertIn('Esecuzione completata', messages)

    def test_dry_run_does_not_claim_execution(self):
        result, messages = self.invoke(self.snp_answers() + ['1', '0', '0'], dry_run=True)
        self.assertEqual(result, 0)
        self.assertIn('Esecuzione pianificata', messages)
        self.assertNotIn('Esecuzione completata', messages)

    def test_multiple_analyses_and_last_result_in_one_session(self):
        self.invoke(self.snp_answers('one') + ['1', '0'] + self.snp_answers('two') +
                    ['1', '0', '6', '0', '0'])
        self.assertEqual(self.workflows.snp_call.call_count, 2)

    def test_output_directory_choice_updates_both_layouts(self):
        target = self.root / 'separate results'
        with chdir(self.root):
            result, _ = self.invoke(['5', '1', '2', '"separate results"', '9', '0', '0'],
                                    preferences_store=PreferencesStore(self.root / 'preferences.json'))
        self.assertEqual(result, 0)
        self.assertTrue(target.is_dir())
        self.assertEqual(self.workflows.layout.runs_dir, target)
        self.assertIs(self.workflows.layout, self.workflows.runner.layout)
        self.assertEqual(self.layout.runs_dir, self.root / 'runs')

    def test_invalid_output_directory_can_be_corrected_or_cancelled(self):
        result, messages = self.invoke(['5', '1', '2', str(self.layout.data_dir / 'results'), '9', '0', '0', '0'])
        self.assertEqual(result, 0)
        self.assertFalse((self.layout.data_dir / 'results').exists())
        self.assertIn('senza sovrapporsi', messages)

    def test_existing_run_name_is_rejected_before_workflow(self):
        self.invoke(self.snp_answers('test') + ['new-run', '1', '0', '0'])
        self.assertEqual(self.workflows.snp_call.call_args.kwargs['run_name'], 'new-run')

    def test_runtime_is_checked_only_on_explicit_request(self):
        result, messages = self.invoke(['7', '1', '0', '8', '0'])
        self.assertEqual(result, 0)
        self.workflows.runner.doctor.assert_called_once_with(True)
        self.assertNotIn('da verificare', messages)
        self.assertIn('Controllo completato: ambiente di analisi, R e samtools disponibili.', messages)

    def test_help_instructions_do_not_start_runtime_or_analyses(self):
        result, messages = self.invoke(['7', '1', '4', '0', '0'])
        self.assertEqual(result, 0)
        self.workflows.runner.doctor.assert_not_called()
        for name in ('dnp_call', 'snp_call', 'contamination', 'cpi'):
            getattr(self.workflows, name).assert_not_called()
        self.assertIn('dopo almeno un file, Invio conclude la lista', messages)
        self.assertIn('campo obbligatorio senza valore iniziale richiede una risposta', messages)
        self.assertIn('work i file intermedi', messages)
        self.assertIn('senza eseguire l\'analisi o produrre risultati scientifici', messages)
        self.assertNotIn('Controllo completato:', messages)

    def test_help_dry_run_explains_verification_without_running_it(self):
        result, messages = self.invoke(['8', '0'], dry_run=True)
        self.assertEqual(result, 0)
        self.workflows.runner.doctor.assert_not_called()
        self.assertIn('la verifica degli strumenti non viene eseguita', messages)
        self.assertIn('avviare NIPAT senza --dry-run', messages)
        self.assertNotIn('Controllo completato:', messages)

    def test_help_unknown_choice_and_navigation_stay_local(self):
        result, messages = self.invoke(['7', 'invalid', '1', ':indietro', '0'])
        self.assertEqual(result, 0)
        self.workflows.runner.doctor.assert_not_called()
        self.assertIn('Scegliere un argomento', messages)
        self.assertIn('Come usare NIPAT', messages)

    def test_failed_tool_verification_never_claims_availability(self):
        self.workflows.runner.doctor.side_effect = RuntimeExecutionError('Strumenti non disponibili')
        result, messages = self.invoke(['8', '0'])
        self.assertEqual(result, 2)
        self.assertIn('Strumenti non disponibili', messages)
        self.assertNotIn('Controllo completato:', messages)

    def test_portable_python_can_import_ui_without_site_packages(self):
        project = Path(__file__).resolve().parents[1]
        script = 'import sys; sys.path.insert(0, sys.argv[1]); import nipat.wizard; import nipat.terminal; import nipat.results'
        result = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(project / 'src')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


class CliRoutingTests(unittest.TestCase):
    def setUp(self):
        self.layout = Mock()
        self.layout.project_dir = Path(__file__).resolve().parents[1]
        self.runner = Mock()
        self.workflows = Mock()

    def invoke(self, arguments):
        with patch('nipat.cli.ProjectLayout.discover', return_value=self.layout) as discover:
            with patch('nipat.cli.DockerComposeRunner', return_value=self.runner):
                with patch('nipat.cli.Workflows', return_value=self.workflows):
                    with redirect_stdout(io.StringIO()):
                        code = main(arguments)
        self.assertEqual(code, 0)
        return discover

    def test_data_and_run_roots_are_passed_to_discovery(self):
        discover = self.invoke(['--data-dir', '/external/data', '--runs-dir', '/results', 'doctor'])
        discover.assert_called_once_with(data_dir=Path('/external/data'), runs_dir=Path('/results'))

    def test_layout_validation_errors_are_reported_without_traceback(self):
        stderr = io.StringIO()
        with patch('nipat.cli.ProjectLayout.discover',
                   side_effect=ValidationError('Percorsi errati')):
            with redirect_stderr(stderr):
                self.assertEqual(main(['doctor']), 2)
        self.assertIn('Percorsi errati', stderr.getvalue())

    def test_installer_lease_prevents_cli_runtime_or_analysis_start(self):
        stderr = io.StringIO()
        with patch('nipat.cli.ProjectLayout.discover', return_value=self.layout), \
                patch('nipat.cli.activity_session', side_effect=ValidationError('Aggiornamento in corso')), \
                patch('nipat.cli.DockerComposeRunner') as runner, redirect_stderr(stderr):
            self.assertEqual(main(['doctor', '--runtime']), 2)
        runner.assert_not_called()
        self.assertIn('Aggiornamento in corso', stderr.getvalue())

    def test_repeated_dnp_bams_are_routed(self):
        self.invoke(['dnp-call', '--bam', 'one.bam', '--bam', 'two.bam',
                     '--reference', 'ref.fa', '--panel', 'panel.txt', '--parallel'])
        self.workflows.dnp_call.assert_called_once_with(
            bams=[Path('one.bam'), Path('two.bam')], bamlist=None,
            reference=Path('ref.fa'), panel=Path('panel.txt'), parallel=True, run_name=None,
        )

    def test_dnp_bamlist_is_routed(self):
        self.invoke(['dnp-call', '--bamlist', 'files.txt', '--reference', 'ref.fa',
                     '--panel', 'panel.txt'])
        self.assertEqual(self.workflows.dnp_call.call_args.kwargs['bamlist'], Path('files.txt'))
        self.assertIsNone(self.workflows.dnp_call.call_args.kwargs['bams'])

    def test_snp_pileup_does_not_require_a_reference_at_parser_level(self):
        self.invoke(['snp-call', '--pileup', 'pileup.txt', '--panel', 'snps.txt'])
        self.workflows.snp_call.assert_called_once_with(
            bam=None, pileup=Path('pileup.txt'), reference=None,
            panel=Path('snps.txt'), run_name=None,
        )

    def test_contamination_directory_is_routed(self):
        self.invoke(['contamination', '--input-dir', 'samples', '--panel', 'panel.txt'])
        self.workflows.contamination.assert_called_once_with(
            inputs=None, input_dir=Path('samples'), panel=Path('panel.txt'), run_name=None,
        )

    def test_repeated_cpi_cutoffs_are_routed_with_paths(self):
        self.invoke(['cpi', '--input-dir', 'samples', '--pairs', 'A:B', '--popfreq', 'pop.txt',
                     '--cutoff', '0.3', 'one.tsv', '--cutoff', '0.5', '../two.txt',
                     '--err-const', '0.0001'])
        kwargs = self.workflows.cpi.call_args.kwargs
        self.assertEqual(kwargs['cutoffs'], [('0.3', Path('one.tsv')),
                                            ('0.5', Path('../two.txt'))])
        self.assertEqual(kwargs['err_const'], 0.0001)
        self.assertIsNone(kwargs['cutoff_map'])

    def test_native_cpi_cutoff_map_alias_is_preserved(self):
        native = '0.3=D:\\panels\\one.tsv,0.5=two.txt'
        self.invoke(['cpi', '--input-dir', 'samples', '--pairs', 'A:B', '--popfreq', 'pop.txt',
                     '--cutoff_map', native])
        self.assertEqual(self.workflows.cpi.call_args.kwargs['cutoff_map'], native)

    def test_conflicting_input_modes_are_rejected(self):
        cpi = ['cpi', '--input-dir', 'samples', '--pairs', 'A:B', '--popfreq', 'pop.txt']
        commands = [
            ['dnp-call', '--bam', 'one.bam', '--bamlist', 'list.txt',
             '--reference', 'ref.fa', '--panel', 'panel.txt'],
            ['snp-call', '--bam', 'one.bam', '--pileup', 'pileup.txt', '--panel', 'panel.txt'],
            ['contamination', '--input', 'one.txt', '--input-dir', 'samples',
             '--panel', 'panel.txt'],
            cpi + ['--panel', 'panel.txt', '--cutoff', '0.3', 'one.tsv'],
            cpi + ['--cutoff', '0.3', 'one.tsv', '--cutoff-map', '0.5=two.txt'],
        ]
        for command in commands:
            with self.subTest(command=command), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    build_parser().parse_args(command)
                self.assertEqual(error.exception.code, 2)


class SnpReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.expected = Path(self.temp.name) / 'expected.txt'
        self.actual = Path(self.temp.name) / 'actual.txt'
        self.columns = ['chr', 'pos', 'Reference', 'Alternative', 'N_Reference',
                        'N_Alternative', 'N_Altro', 'total_count', 'ratio']
        self.rows = [
            ['chr1', '100', 'A', 'C', '95', '5', '1', '101', '0.95'],
            ['chr1', '200', 'T', 'G', '80', '20', '0', '100', '0.8'],
        ]
        self.write(self.expected, self.rows)

    def write(self, path, rows):
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle, delimiter='\t')
            writer.writerow(self.columns)
            writer.writerows(rows)

    def test_comparison_is_numeric_and_independent_of_row_order(self):
        actual = [row[:] for row in reversed(self.rows)]
        actual[0][-1] = '0.80000000000000004'
        self.write(self.actual, actual)
        self.assertEqual(compare_snp_outputs(self.expected, self.actual), 2)

    def test_detects_wrong_counts(self):
        actual = [row[:] for row in self.rows]
        actual[0][4] = '96'
        self.write(self.actual, actual)
        with self.assertRaisesRegex(ValidationError, 'N_Reference'):
            compare_snp_outputs(self.expected, self.actual)

    def test_detects_duplicate_or_missing_sites(self):
        for rows in ([self.rows[0], self.rows[0]], [self.rows[0]]):
            self.write(self.actual, rows)
            with self.assertRaises(ValidationError):
                compare_snp_outputs(self.expected, self.actual)

    def test_detects_non_finite_ratio(self):
        actual = [row[:] for row in self.rows]
        actual[0][-1] = 'nan'
        self.write(self.actual, actual)
        with self.assertRaisesRegex(ValidationError, 'ratio'):
            compare_snp_outputs(self.expected, self.actual)


class SelfTestCommandTests(unittest.TestCase):
    def test_input_mode_check_starts_with_isolated_runtime_search_path(self):
        project = Path(__file__).resolve().parents[1]
        # Match portable Python: stdlib plus project/src, without automatic
        # script-directory injection, PYTHONPATH, site-packages or caller cwd.
        bootstrap = '''import runpy, sys
from pathlib import Path
project = Path(sys.argv[1])
sys.path[:0] = [str(project / "src"), str(project)]
script = project / "scripts" / "verify_input_modes.py"
sys.argv = [str(script), "--help"]
runpy.run_path(str(script), run_name="__main__")
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-I', '-S', '-c', bootstrap, str(project)],
                cwd=directory, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('--fixture-parent', result.stdout)

    def test_runs_distributed_checks_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            scripts = project / 'scripts'
            scripts.mkdir(parents=True)
            for name in ('verify_snp_example.py', 'verify_cpi_update.py',
                         'verify_contamination_update.py', 'verify_input_modes.py'):
                (scripts / name).touch()
            layout = ProjectLayout(project, project.parent, project.parent / 'data',
                                   project.parent / 'runs', project / 'compose.yaml')
            with patch('nipat.validation.self_test.subprocess.run') as run:
                run.side_effect = [None, subprocess.CalledProcessError(1, 'CPI')]
                with redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(RuntimeExecutionError, 'CPI'):
                        run_self_tests(layout)
                self.assertEqual(run.call_count, 2)
                self.assertEqual(Path(run.call_args_list[0].args[0][1]).name,
                                 'verify_snp_example.py')
                self.assertEqual(run.call_args_list[0].kwargs['env']['NIPAT_PROJECT_DIR'],
                                 str(project))
                self.assertEqual(run.call_args_list[0].kwargs['env']['NIPAT_DATA_DIR'],
                                 str(layout.data_dir))
                self.assertEqual(run.call_args_list[0].kwargs['env']['NIPAT_RUNS_DIR'],
                                 str(layout.runs_dir))

    def test_cli_rejects_dry_self_test(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(['--dry-run', 'self-test'])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
