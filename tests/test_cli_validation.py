import csv
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from nipat.cli import DEFAULT_ERR_CONST, main
from nipat.errors import RuntimeExecutionError, ValidationError
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
            '1', '"/workspace/data/sample one.bam"', '/workspace/data/ref.fa',
            '/workspace/data/DNP.txt', 'my-run', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.dnp_call.assert_called_once_with(
            bam=Path('/workspace/data/sample one.bam'),
            reference=Path('/workspace/data/ref.fa'), panel=Path('/workspace/data/DNP.txt'),
            parallel=False, run_name='my-run',
        )
        self.assertIn('Esecuzione completata', messages)

    def test_snp_preserves_separate_panel_and_automatic_name(self):
        result, _ = self.invoke([
            '2', '/workspace/data/input.bam', '/workspace/data/ref.fa',
            '/workspace/data/SNP.txt', '', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.snp_call.assert_called_once_with(
            bam=Path('/workspace/data/input.bam'), reference=Path('/workspace/data/ref.fa'),
            panel=Path('/workspace/data/SNP.txt'), run_name=None,
        )

    def test_contamination_collects_multiple_inputs(self):
        result, _ = self.invoke([
            '3', '/workspace/data/A.txt', '/workspace/data/B.tsv', '',
            '/workspace/data/DNP.txt', 'contam', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.contamination.assert_called_once_with(
            inputs=[Path('/workspace/data/A.txt'), Path('/workspace/data/B.tsv')],
            panel=Path('/workspace/data/DNP.txt'), run_name='contam',
        )

    def test_cpi_maps_pairs_prefixes_and_optional_panel(self):
        result, _ = self.invoke([
            '4', '/workspace/data/cpi', 'M1:F1', 'Plasma_', 'Father_',
            '/workspace/data/pop.tsv', '', '', '0',
        ])
        self.assertEqual(result, 0)
        self.workflows.cpi.assert_called_once_with(
            input_dir=Path('/workspace/data/cpi'), pairs='M1:F1',
            mother_prefix='Plasma_', father_prefix='Father_',
            popfreq=Path('/workspace/data/pop.tsv'), panel=None,
            err_const=DEFAULT_ERR_CONST, run_name=None,
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
        result, messages = self.invoke(['2', 'a', 'b', 'c', '', '0'])
        self.assertEqual(result, 2)
        self.assertIn('Operazione non riuscita: Pannello non valido', messages)
        self.assertNotIn('Esecuzione completata', messages)

    def test_dry_run_does_not_claim_execution(self):
        result, messages = self.invoke(['2', 'a', 'b', 'c', '', '0'], dry_run=True)
        self.assertEqual(result, 0)
        self.assertIn('Esecuzione pianificata', messages)
        self.assertNotIn('Esecuzione completata', messages)

    def test_multiple_analyses_are_available_in_one_session(self):
        self.invoke(['2', 'a', 'b', 'c', 'one', '2', 'd', 'e', 'f', 'two', '0'])
        self.assertEqual(self.workflows.snp_call.call_count, 2)


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
    def test_runs_distributed_checks_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            scripts = project / 'scripts'
            scripts.mkdir(parents=True)
            for name in ('verify_snp_example.py', 'verify_cpi_update.py',
                         'verify_contamination_update.py'):
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

    def test_cli_rejects_dry_self_test(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(['--dry-run', 'self-test'])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
