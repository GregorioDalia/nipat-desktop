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
    if os.environ.get('VIEW_CONTINUOUS'):
        while True:
            os.write(1, b'x' * 65536)
    sys.stdout.buffer.write(pathlib.Path(args[-1]).read_bytes())
elif stage == 'mpileup':
    if os.environ.get('MPILEUP_FAIL'):
        raise SystemExit(17)
    if os.environ.get('MPILEUP_SLEEP'):
        time.sleep(60)
    names = pathlib.Path(args[args.index('-b')+1]).read_text().splitlines() if '-b' in args else ['-']
    data = []
    for name in names:
        data.append(sys.stdin.buffer.read() if name == '-' else pathlib.Path(name).read_bytes())
    sys.stdout.buffer.write(b'pileup\n' + b'|'.join(data))
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
        for key in ('VIEW_FAIL', 'VIEW_CONTINUOUS', 'MPILEUP_FAIL', 'MPILEUP_SLEEP'):
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

    def generate(self):
        return dnp_pileup.generate_pileup(self.bamlist, self.bed, self.reference,
                                        self.output, self.scratch, self.metadata,
                                        samtools=str(self.samtools))

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


if __name__ == '__main__':
    unittest.main()
