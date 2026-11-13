"""Failure and lifecycle contracts around real pipes with a fake samtools."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from nipat_scientific import dnp_pileup
from nipat_scientific.settings import settings_context


FAKE_SAMTOOLS = r'''
import json, os, pathlib, signal, sys, time
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
args = sys.argv[1:]
stage = args[0]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({'stage': stage, 'args': args, 'pid': os.getpid()}) + '\n')
if stage == 'view':
    if os.environ.get('VIEW_FAIL'):
        raise SystemExit(13)
    if '-H' in args:
        header = pathlib.Path(args[-1] + '.header')
        sys.stdout.write(header.read_text() if header.exists() else
            '@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr2\tLN:1000\n'
            '@SQ\tSN:chr1\tLN:1000\n@SQ\tSN:chr10\tLN:1000\n@SQ\tSN:chr3\tLN:1000\n')
        raise SystemExit(0)
    if os.environ.get('VIEW_CONTINUOUS'):
        while True:
            os.write(1, b'x' * 65536)
    sys.stdout.buffer.write(pathlib.Path(args[-1]).read_bytes())
elif stage == 'mpileup':
    if os.environ.get('MPILEUP_FAIL'):
        raise SystemExit(17)
    if os.environ.get('MPILEUP_SLEEP'):
        time.sleep(60)
    contig = args[args.index('-r') + 1] if '-r' in args else None
    if contig == os.environ.get('MPILEUP_FAIL_CONTIG', ''):
        raise SystemExit(19)
    if contig:
        time.sleep(json.loads(os.environ.get('MPILEUP_DELAYS', '{}')).get(contig, 0.1))
    names = pathlib.Path(args[args.index('-b')+1]).read_text().splitlines() if '-b' in args else ['-']
    data = []
    for name in names:
        data.append(sys.stdin.buffer.read() if name == '-' else pathlib.Path(name).read_bytes())
    sys.stdout.buffer.write((contig.encode() + b':' + b'|'.join(data) + b'\n') if contig else
                            (b'pileup\n' + b'|'.join(data)))
else:
    raise SystemExit(99)
'''


@unittest.skipUnless(os.name == 'posix', 'The scientific helper runs in the Linux engine')
class DnpPileupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.samtools = self.bin / 'samtools'
        self.samtools.write_text('#!' + sys.executable + '\n' + FAKE_SAMTOOLS)
        self.samtools.chmod(0o755)
        self.log = self.root / 'commands.jsonl'
        self.bed = self.root / 'same.bed'
        self.bed.write_text('chr1\t0\t10\n')
        self.reference = self.root / 'ref.fa'
        self.reference.write_text('>chr1\nAAAA\n')
        self.bamlist = self.root / 'bamlist.txt'
        self.output = self.scratch / 'pileup.txt'
        self.metadata = self.root / 'dnp-pileup.json'
        self.enterContext(patch.dict(os.environ, {'FAKE_LOG': str(self.log),
                           'PATH': str(self.bin) + os.pathsep + os.environ.get('PATH', '')}, clear=False))
        for key in ('VIEW_FAIL', 'VIEW_CONTINUOUS', 'MPILEUP_FAIL', 'MPILEUP_SLEEP',
                    'MPILEUP_FAIL_CONTIG', 'MPILEUP_DELAYS'):
            os.environ.pop(key, None)

    def samples(self, indexed):
        paths = []
        for i, has_index in enumerate(indexed):
            directory = self.root / str(i)
            directory.mkdir()
            # Repeated basenames must remain distinct inputs in the list.
            bam = directory / 'sample.bam'
            bam.write_bytes(f'reads-{i}'.encode())
            if has_index:
                Path(str(bam) + '.bai').write_bytes(b'index')
            paths.append(bam)
        self.bamlist.write_text(''.join(str(path) + '\n' for path in paths))
        return paths

    def generate(self, budget=None):
        return dnp_pileup.generate_pileup(self.bamlist, self.bed, self.reference,
                                        self.output, self.scratch, self.metadata,
                                        samtools=str(self.samtools), budget=budget)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_no_intermediates(self):
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_single_index_streams_and_preserves_scientific_options(self):
        bams = self.samples([True])
        result = self.generate()
        self.assertEqual(result['strategy'], 'indexed-pipe')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0')
        commands = {x['stage']: x['args'] for x in self.commands()}
        self.assertEqual(commands['view'], ['view', '--no-PG', '-u', '-M', '-L', str(self.bed), str(bams[0])])
        self.assertEqual(commands['mpileup'], ['mpileup', '-l', str(self.bed), '-f', str(self.reference),
                                             *dnp_pileup.MPILEUP_OPTIONS, '-'])
        self.assertEqual([x['returncode'] for x in result['processes']], [0, 0])
        self.assertIsNone(result['samples'][0]['selected_bytes'])
        self.assertEqual(result['staged_bytes'], 0)
        self.assertEqual(list(self.scratch.iterdir()), [self.output])
        self.assertEqual(json.loads(self.metadata.read_text()), result)

    def test_custom_acquisition_settings_apply_with_and_without_budget(self):
        self.samples([True, True])
        settings = {"min_base_quality": 21, "min_mapping_quality": 17, "max_depth": 500,
                    "baq": False, "count_overlaps": True, "include_orphans": True}
        for budget in (None, {"schema_version": 1, "interface": "nipat-parallel-v1",
                             "mode": "serial", "workers": 1}):
            with self.subTest(budget=budget), settings_context("dnp-call", settings, self.root / "settings"):
                result = self.generate(budget)
                command = [entry["args"] for entry in self.commands() if entry["stage"] == "mpileup"][-1]
                for flag, expected in (("-Q", "21"), ("-q", "17"), ("-d", "500")):
                    self.assertEqual(command[command.index(flag) + 1], expected)
                for flag in ("-B", "-x", "-A"):
                    self.assertIn(flag, command)
                    self.assertIn(flag, result["mpileup_options"])
                self.assertEqual(result["scientific_settings"]["min_base_quality"], 21)
            self.output.unlink()
            self.metadata.unlink()

    def test_multiple_inputs_keep_order_duplicate_names_and_staging_cost(self):
        self.samples([True, False, True])
        result = self.generate()
        self.assertEqual(result['strategy'], 'indexed-disk')
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0|reads-1|reads-2')
        self.assertEqual([x['staged_bytes'] for x in result['samples']], [7, 0, 7])
        self.assertEqual(result['staged_bytes'], 14)
        self.assertEqual([x['strategy'] for x in result['samples']],
                         ['indexed-disk', 'sequential-no-index', 'indexed-disk'])
        self.assertEqual([x['stage'] for x in self.commands()], ['view', 'view', 'mpileup'])
        self.assertEqual(list(self.scratch.iterdir()), [self.output])

    def test_missing_index_scans_originals_without_view(self):
        self.samples([False])
        result = self.generate()
        self.assertEqual(result['strategy'], 'sequential')
        self.assertEqual([x['stage'] for x in self.commands()], ['mpileup'])
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0')

    def test_failed_indexed_producer_cannot_report_success_or_retain_output(self):
        self.samples([True])
        os.environ['VIEW_FAIL'] = '1'
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate()
        self.assertEqual(json.loads(self.metadata.read_text())['status'], 'failed')
        self.assert_no_intermediates()

    def test_early_consumer_failure_reaps_blocked_producer(self):
        self.samples([True])
        os.environ.update(VIEW_CONTINUOUS='1', MPILEUP_FAIL='1')
        started = time.monotonic()
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate()
        self.assertLess(time.monotonic() - started, 4)
        self.assert_no_intermediates()
        for command in self.commands():
            with self.assertRaises(ProcessLookupError):
                os.kill(command['pid'], 0)

    def test_group_cancellation_reaps_children_and_removes_owned_partials(self):
        self.samples([True])
        os.environ.update(VIEW_CONTINUOUS='1', MPILEUP_SLEEP='1')
        arguments = [sys.executable, str(Path(dnp_pileup.__file__)), '--bamlist', str(self.bamlist),
                     '--bed', str(self.bed), '--reference', str(self.reference), '--output', str(self.output),
                     '--scratch-dir', str(self.scratch), '--metadata', str(self.metadata)]
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.log.exists() and len(self.commands()) == 2:
                    break
                time.sleep(0.02)
            else:
                self.fail('Both pipe children did not start')
            os.killpg(process.pid, signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr.decode())
            self.assertEqual(json.loads(self.metadata.read_text())['status'], 'cancelled')
            self.assert_no_intermediates()
            for command in self.commands():
                with self.assertRaises(ProcessLookupError):
                    os.kill(command['pid'], 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_existing_output_and_outside_scratch_are_never_overwritten(self):
        self.samples([False])
        self.output.write_bytes(b'preserve')
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate()
        self.assertEqual(self.output.read_bytes(), b'preserve')
        self.output = self.root / 'outside.txt'
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.metadata.exists())

    def test_budgeted_chromosomes_preserve_order_and_bound_actual_processes(self):
        self.samples([True, True])
        self.bed.write_text('chr3\t0\t10\nchr10\t0\t10\nchr1\t0\t10\nchr2\t0\t10\n')
        os.environ['MPILEUP_DELAYS'] = json.dumps({'chr2': 0.3, 'chr1': 0.05})
        result = self.generate({'mode': 'auto', 'workers': 8, 'max_workers': 2})
        self.assertEqual(result['strategy'], 'indexed-chromosomes')
        self.assertEqual(result['parallel']['workers'], 2)
        self.assertEqual(result['parallel']['observed_max_processes'], 2)
        tasks = [item for item in result['processes'] if item['stage'] == 'mpileup-chromosome']
        self.assertEqual([item['contig'] for item in tasks], ['chr2', 'chr1', 'chr10', 'chr3'])
        self.assertEqual([item['task_index'] for item in tasks], [1, 2, 3, 4])
        self.assertEqual(self.output.read_bytes(), b''.join(
            name + b':reads-0|reads-1\n' for name in (b'chr2', b'chr1', b'chr10', b'chr3')))
        self.assertLess(tasks[1]['finished_at_unix'], tasks[0]['finished_at_unix'])
        events = [(item['started_at_unix'], 1) for item in tasks]
        events += [(item['finished_at_unix'], -1) for item in tasks]
        active, maximum = 0, 0
        for _, change in sorted(events):
            active += change
            maximum = max(maximum, active)
        self.assertEqual(maximum, 2)
        self.assertTrue(all(item['outcome'] == 'succeeded' and item['returncode'] == 0 for item in tasks))
        self.assertEqual(list(self.scratch.iterdir()), [self.output])
        self.assertEqual(json.loads(self.metadata.read_text()), result)
        for item in self.commands():
            if item['stage'] == 'mpileup':
                for option in dnp_pileup.MPILEUP_OPTIONS:
                    self.assertIn(option, item['args'])
                self.assertNotIn('-B', item['args'])
                self.assertNotIn('-@', item['args'])

    def test_serial_budget_uses_one_process_and_preserves_dictionary_order(self):
        self.samples([True])
        self.bed.write_text('chr1\t0\t10\nchr2\t0\t10\n')
        result = self.generate({'mode': 'serial', 'workers': 4})
        self.assertEqual(result['parallel']['workers'], 1)
        self.assertEqual(result['parallel']['observed_max_processes'], 1)
        tasks = [item for item in result['processes'] if item['stage'] == 'mpileup-chromosome']
        self.assertLessEqual(tasks[0]['finished_at_unix'], tasks[1]['started_at_unix'])
        self.assertEqual(self.output.read_bytes(), b'chr2:reads-0\nchr1:reads-0\n')

    def test_mixed_indices_preserve_index_validation_with_sequential_staging(self):
        self.samples([True, False])
        result = self.generate({'mode': 'auto', 'workers': 4})
        self.assertEqual(result['strategy'], 'sequential-budgeted')
        self.assertEqual(result['parallel']['reason'], 'missing-index')
        self.assertEqual(result['parallel']['workers'], 1)
        self.assertEqual(result['parallel']['observed_max_processes'], 1)
        self.assertEqual([item['stage'] for item in self.commands()], ['view', 'mpileup'])
        self.assertEqual(result['staged_bytes'], 7)
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0|reads-1')

    def test_incompatible_dictionaries_fall_back_without_reordering_samples(self):
        bams = self.samples([True, True])
        Path(str(bams[1]) + '.header').write_text('@HD\tSO:coordinate\n@SQ\tSN:chr1\tLN:1001\n')
        result = self.generate({'mode': 'auto', 'workers': 4})
        self.assertEqual(result['parallel']['reason'], 'incompatible-dictionaries')
        self.assertEqual(result['strategy'], 'sequential-budgeted')
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0|reads-1')

    def test_region_ambiguous_contig_uses_original_stream(self):
        bams = self.samples([True])
        Path(str(bams[0]) + '.header').write_text('@HD\tSO:coordinate\n@SQ\tSN:chr1:2\tLN:1000\n')
        self.bed.write_text('chr1:2\t0\t10\n')
        result = self.generate({'mode': 'auto', 'workers': 4})
        self.assertEqual(result['parallel']['reason'], 'ambiguous-contig')
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0')

    def test_dot_contig_is_not_interpreted_as_samtools_special_region(self):
        bams = self.samples([True])
        Path(str(bams[0]) + '.header').write_text('@HD\tSO:coordinate\n@SQ\tSN:.\tLN:1000\n')
        self.bed.write_text('.\t0\t10\n')
        result = self.generate({'mode': 'auto', 'workers': 4})
        self.assertEqual(result['parallel']['reason'], 'ambiguous-contig')
        self.assertEqual(self.output.read_bytes(), b'pileup\nreads-0')
        self.assertTrue(all('-r' not in item['args'] for item in self.commands()))

    def test_budget_validation_rejects_invalid_values_before_claiming_outputs(self):
        for budget in ({'mode': 'invalid', 'workers': 1}, {'mode': 'auto', 'workers': True},
                       {'mode': 'auto', 'workers': 0}, {'mode': 'auto', 'workers': 1.5},
                       {'mode': 'auto', 'workers': 2, 'max_workers': -1},
                       {'mode': 'auto', 'workers': 2, 'cpu_limit': float('nan')}):
            with self.subTest(budget=budget), self.assertRaises(dnp_pileup.PileupError):
                self.generate(budget)
        self.assertFalse(self.metadata.exists())
        limited = dnp_pileup._budget({'mode': 'auto', 'workers': 10, 'cpu_limit': 2.9,
                                     'max_workers': 4, 'memory_worker_limit': 3})
        self.assertEqual(limited['workers'], 2)

    def test_header_failure_is_not_silently_replaced_by_sequential_execution(self):
        self.samples([True])
        os.environ['VIEW_FAIL'] = '1'
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate({'mode': 'auto', 'workers': 2})
        self.assertEqual([item['stage'] for item in self.commands()], ['view'])
        self.assertEqual(json.loads(self.metadata.read_text())['status'], 'failed')
        self.assert_no_intermediates()

    def test_present_index_failure_remains_fatal_when_another_index_is_missing(self):
        self.samples([True, False])
        os.environ['VIEW_FAIL'] = '1'
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate({'mode': 'auto', 'workers': 4})
        result = json.loads(self.metadata.read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['parallel']['reason'], 'missing-index')
        self.assertEqual([item['stage'] for item in self.commands()], ['view'])
        self.assert_no_intermediates()

    def test_parallel_task_failure_reaps_siblings_and_never_commits_output(self):
        self.samples([True])
        self.bed.write_text('chr1\t0\t10\nchr2\t0\t10\n')
        os.environ.update(MPILEUP_FAIL_CONTIG='chr2', MPILEUP_DELAYS=json.dumps({'chr1': 60}))
        started = time.monotonic()
        with self.assertRaises(dnp_pileup.PileupError):
            self.generate({'mode': 'auto', 'workers': 2})
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(json.loads(self.metadata.read_text())['status'], 'failed')
        self.assert_no_intermediates()
        for item in self.commands():
            with self.assertRaises(ProcessLookupError):
                os.kill(item['pid'], 0)

    def test_parallel_cancellation_reaps_all_children_and_records_partial_evidence(self):
        self.samples([True])
        self.bed.write_text('chr1\t0\t10\nchr2\t0\t10\n')
        os.environ['MPILEUP_SLEEP'] = '1'
        budget = self.root / 'budget.json'
        budget.write_text(json.dumps({'mode': 'auto', 'workers': 2}))
        arguments = [sys.executable, str(Path(dnp_pileup.__file__)), '--bamlist', str(self.bamlist),
                     '--bed', str(self.bed), '--reference', str(self.reference), '--output', str(self.output),
                     '--scratch-dir', str(self.scratch), '--metadata', str(self.metadata), '--budget', str(budget)]
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.log.exists() and sum(item['stage'] == 'mpileup' for item in self.commands()) == 2:
                    break
                time.sleep(0.02)
            else:
                self.fail('Parallel children did not start')
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr.decode())
            result = json.loads(self.metadata.read_text())
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(result['parallel']['observed_max_processes'], 2)
            tasks = [item for item in result['processes'] if item['stage'] == 'mpileup-chromosome']
            self.assertTrue(all(item['outcome'] == 'cancelled' for item in tasks))
            self.assert_no_intermediates()
            for item in self.commands():
                with self.assertRaises(ProcessLookupError):
                    os.kill(item['pid'], 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main()
