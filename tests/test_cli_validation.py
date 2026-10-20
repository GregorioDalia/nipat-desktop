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
from nipat.validation.self_test import compare_snp_outputs, run_self_tests
from nipat.wizard import run_wizard


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/workspace')
        self.layout = ProjectLayout(
            self.root / 'repo', self.root, self.root / 'data',
            self.root / 'runs', self.root / 'repo' / 'compose.yaml',
        )
        self.workflows = Mock()
        for name in ('dnp_call', 'snp_call', 'contamination', 'cpi'):
            getattr(self.workflows, name).return_value = self.root / 'runs' / 'test'

    def invoke(self, answers, **kwargs):
        messages = []
        result = run_wizard(
            self.workflows, self.layout, err_const=DEFAULT_ERR_CONST,
            read=Mock(side_effect=answers), write=messages.append, **kwargs,
        )
        return result, '\n'.join(messages)

    def test_dnp_uses_paths_with_spaces_and_runs_serially(self):
        result, messages = self.invoke([
            '1', '1', '"/external/sample one.bam"', '', '/external/ref.fa',
            '/external/DNP.txt', '1', 'my-run', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.dnp_call.assert_called_once_with(
            bams=[Path('/external/sample one.bam')], bamlist=None,
            reference=Path('/external/ref.fa'), panel=Path('/external/DNP.txt'),
            parallel=False, run_name='my-run',
        )
        self.assertIn('Esecuzione completata', messages)

    def test_snp_preserves_separate_panel_and_automatic_name(self):
        result, _ = self.invoke([
            '2', '1', '/workspace/data/input.bam', '/workspace/data/ref.fa',
            '/workspace/data/SNP.txt', '', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.snp_call.assert_called_once_with(
            bam=Path('/workspace/data/input.bam'), pileup=None,
            reference=Path('/workspace/data/ref.fa'),
            panel=Path('/workspace/data/SNP.txt'), run_name=None,
        )

    def test_contamination_collects_multiple_inputs(self):
        result, _ = self.invoke([
            '3', '1', '/workspace/data/A.txt', '/workspace/data/B.tsv', '',
            '/workspace/data/DNP.txt', 'contam', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.contamination.assert_called_once_with(
            inputs=[Path('/workspace/data/A.txt'), Path('/workspace/data/B.tsv')],
            input_dir=None, panel=Path('/workspace/data/DNP.txt'), run_name='contam',
        )

    def test_cpi_maps_pairs_prefixes_and_optional_panel(self):
        result, _ = self.invoke([
            '4', '/workspace/data/cpi', 'M1:F1', 'Plasma_', 'Father_',
            '/workspace/data/pop.tsv', '0', '', '', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.cpi.assert_called_once_with(
            input_dir=Path('/workspace/data/cpi'), pairs='M1:F1',
            mother_prefix='Plasma_', father_prefix='Father_',
            popfreq=Path('/workspace/data/pop.tsv'), panel=None,
            cutoffs=None, cutoff_map=None, err_const=DEFAULT_ERR_CONST, run_name=None,
        )

    def test_cancel_returns_to_menu_without_workflow(self):
        result, messages = self.invoke(['1', ':annulla', '0'])
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.mock_calls, [])
        self.assertIn('annullata prima', messages)

    def test_eof_and_interrupt_exit_without_traceback(self):
        for exception in (EOFError(), KeyboardInterrupt()):
            with self.subTest(exception=type(exception).__name__):
                result, messages = self.invoke([exception])
                self.assertEqual(result, 130)
                self.assertIn('Sessione interrotta', messages)

    def test_failure_is_reported_and_menu_stays_available(self):
        self.workflows.snp_call.side_effect = ValidationError('Pannello non valido')
        result, messages = self.invoke(['2', '1', 'a', 'b', 'c', '', '0'])
        self.assertEqual(result, 2)
        self.assertIn('Operazione non riuscita: Pannello non valido', messages)
        self.assertNotIn('Esecuzione completata', messages)

    def test_dry_run_does_not_claim_execution(self):
        result, messages = self.invoke(['2', '1', 'a', 'b', 'c', '', '0'], dry_run=True)
        self.assertEqual(result, 0)
        self.assertIn('Esecuzione pianificata', messages)
        self.assertNotIn('Esecuzione completata', messages)

    def test_multiple_analyses_are_available_in_one_session(self):
        self.invoke(['2', '1', 'a', 'b', 'c', 'one', '2', '1', 'd', 'e', 'f', 'two', '0'])
        self.assertEqual(self.workflows.snp_call.call_count, 2)

    def test_dnp_bamlist_and_parallel_mode(self):
        result, _ = self.invoke(['1', '2', '../bams.txt', 'ref.fa', 'panel.txt', '2', '', '0'])
        self.assertEqual(result, 0)
        self.workflows.dnp_call.assert_called_once_with(
            bams=None, bamlist=Path('../bams.txt'), reference=Path('ref.fa'),
            panel=Path('panel.txt'), parallel=True, run_name=None,
        )

    def test_dnp_multiple_bams(self):
        result, _ = self.invoke([
            '1', '1', 'mother.bam', 'father.bam', '', 'ref.fa', 'panel.txt', '1', '', '0',
        ])
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.dnp_call.call_args.kwargs['bams'],
                         [Path('mother.bam'), Path('father.bam')])

    def test_snp_pileup_mode_does_not_ask_for_reference(self):
        result, _ = self.invoke(['2', '2', '/external/pileup.txt', 'snps.txt', '', '0'])
        self.assertEqual(result, 0)
        self.workflows.snp_call.assert_called_once_with(
            bam=None, pileup=Path('/external/pileup.txt'), reference=None,
            panel=Path('snps.txt'), run_name=None,
        )

    def test_contamination_directory_mode(self):
        result, _ = self.invoke(['3', '2', '/external/samples', 'panel.txt', '', '0'])
        self.assertEqual(result, 0)
        self.workflows.contamination.assert_called_once_with(
            inputs=None, input_dir=Path('/external/samples'),
            panel=Path('panel.txt'), run_name=None,
        )

    def test_cpi_repeated_cutoffs_and_editable_error_constant(self):
        result, messages = self.invoke([
            '4', 'samples', 'A:B', '', '', 'pop.tsv', '2',
            '0.3', 'one.tsv', '0.5', '../two.txt', '',
            'not-a-number', 'nan', 'inf', '-1', '0.0001', '', '0',
        ])
        self.assertEqual(result, 0)
        kwargs = self.workflows.cpi.call_args.kwargs
        self.assertEqual(kwargs['cutoffs'], [('0.3', Path('one.tsv')),
                                            ('0.5', Path('../two.txt'))])
        self.assertEqual(kwargs['err_const'], 0.0001)
        self.assertIsNone(kwargs['panel'])
        self.assertIsNone(kwargs['cutoff_map'])
        self.assertEqual(messages.count('numero finito maggiore o uguale a zero'), 4)

    def test_cpi_accepts_zero_error_constant(self):
        result, _ = self.invoke([
            '4', 'samples', 'A:B', '', '', 'pop.tsv', '0', '0', '', '0',
        ])
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.cpi.call_args.kwargs['err_const'], 0.0)

    def test_cpi_native_map_mode(self):
        result, _ = self.invoke([
            '4', 'samples', 'A:B', '', '', 'pop.tsv', '3',
            '0.3=D:\\panels\\one.tsv,0.5=two.txt', '', '', '0',
        ])
        self.assertEqual(result, 0)
        self.assertEqual(self.workflows.cpi.call_args.kwargs['cutoff_map'],
                         '0.3=D:\\panels\\one.tsv,0.5=two.txt')

    def test_output_directory_choice_updates_workflow_and_runner(self):
        for relative in (False, True):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                layout = ProjectLayout(root / 'repo', root, root / 'data',
                                       root / 'runs', root / 'repo' / 'compose.yaml')
                runner = Mock()
                runner.layout = layout
                workflows = Workflows(layout, runner)
                target = root / 'separate results'
                selected = target.relative_to(root) if relative else target
                messages = []
                # Temp and checkout may be on different Windows drives. Exercise
                # relative input from its own directory; keep the caller's cwd
                # unchanged for absolute input, which also supports other drives.
                with chdir(root) if relative else nullcontext():
                    result = run_wizard(
                        workflows, layout, err_const=DEFAULT_ERR_CONST,
                        read=Mock(side_effect=['5', f'"{selected}"', '5', '', '0']),
                        write=messages.append,
                    )
                self.assertEqual(result, 0)
                self.assertTrue(target.is_dir())
                self.assertEqual(workflows.layout.runs_dir, target.resolve())
                self.assertIs(workflows.layout, runner.layout)
                self.assertEqual(layout.runs_dir, root / 'runs')
                self.assertEqual(sum(str(target.resolve()) in line for line in messages), 2)

    def test_invalid_output_directory_does_not_replace_current_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = ProjectLayout(root / 'repo', root, root / 'data',
                                   root / 'runs', root / 'repo' / 'compose.yaml')
            runner = Mock()
            runner.layout = layout
            workflows = Workflows(layout, runner)
            messages = []
            result = run_wizard(
                workflows, layout, err_const=DEFAULT_ERR_CONST,
                read=Mock(side_effect=['5', str(layout.data_dir / 'results'), '0']),
                write=messages.append,
            )
            self.assertEqual(result, 2)
            self.assertIs(workflows.layout, layout)
            self.assertIs(runner.layout, layout)
            self.assertFalse((layout.data_dir / 'results').exists())
            self.assertIn('Operazione non riuscita:', '\n'.join(messages))


class CliRoutingTests(unittest.TestCase):
    def setUp(self):
        self.layout = Mock()
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
