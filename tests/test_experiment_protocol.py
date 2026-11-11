"""Checkpoint and analysis guards using tiny cases, without worker processes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys

import pandas as pd
import vne
from scripts.analyze_full_results import RAW_NAME, validate_raw, verify_statistics, verify_summary


class ExperimentProtocolTests(unittest.TestCase):
    @staticmethod
    def run_fixture(directory, loads=(2.,), seeds=(31,)):
        def worker(task):
            load, seed, duration, nodes, pso, ablations, scenario, references = task
            return vne.run_simulation(load, duration, nodes, seed, pso,
                include_ablations=ablations, scenario=scenario,
                include_reference_baselines=references)

        with patch.object(vne.experiments.mp, 'get_context') as context:
            pool = context.return_value.Pool.return_value.__enter__.return_value
            pool.imap_unordered.side_effect = lambda function, tasks, chunksize: map(worker, tasks)
            vne.run_full_evaluation(directory, loads, seeds, duration=40., num_nodes=8,
                workers=1, include_pso=True, include_ablations=True, include_reference_baselines=True)

    def test_programmatic_run_and_failed_invocation_keep_authoritative_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.run_fixture(directory)
            frame, spec, loads, seeds = validate_raw(path)
            self.assertEqual((loads, seeds, len(frame)), ([2.], [31], 32))
            self.assertEqual(spec['schema'], 14)
            self.assertFalse((path / 'invocations.jsonl').exists())
            (path / 'invocations.jsonl').write_text(json.dumps({'arguments': {
                'lambdas': '99', 'seeds': '888', 'workers': 4}}) + '\n', encoding='utf-8')
            self.assertEqual(validate_raw(path)[2:], ([2.], [31]))
            summary = pd.read_csv(path / 'summary_with_pso_ablations.csv', float_precision='round_trip')
            statistical = pd.read_csv(path / 'statistics_with_pso_ablations.csv', float_precision='round_trip')
            verify_summary(frame, summary)
            verify_statistics(frame, statistical)

    def test_compatible_extension_and_resume_preserve_raw_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.run_fixture(directory)
            before = (path / RAW_NAME).read_bytes()
            self.run_fixture(directory)
            self.assertEqual((path / RAW_NAME).read_bytes(), before)
            self.run_fixture(directory, seeds=(31, 32))
            frame, _, loads, seeds = validate_raw(path)
            self.assertEqual((loads, seeds, len(frame)), ([2.], [31, 32], 64))
            manifest = path / RAW_NAME.replace('.csv', '.config.json')
            saved = manifest.read_bytes()
            checkpoint = (path / RAW_NAME).read_bytes()
            with self.assertRaisesRegex(ValueError, 'omits checkpoint cases'):
                self.run_fixture(directory, seeds=(32,))
            self.assertEqual(manifest.read_bytes(), saved)
            self.assertEqual((path / RAW_NAME).read_bytes(), checkpoint)

    def test_incomplete_inputs_and_wrong_algorithm_parameters_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.run_fixture(directory)
            frame, _, _, _ = validate_raw(path)
            invalid_inputs = frame.copy()
            invalid_inputs.loc[0, 'TraceSHA256'] = '0' * 64
            invalid_parameters = frame.copy()
            invalid_parameters.loc[0, 'AlgorithmParameters'] = '{}'
            for invalid in (frame.iloc[:-1], invalid_inputs, invalid_parameters):
                invalid.to_csv(path / RAW_NAME, index=False)
                with self.assertRaises(ValueError):
                    validate_raw(path)

    def test_pinned_source_manifest_and_license_are_complete(self):
        import zipfile
        path = Path(__file__).resolve().parents[1] / 'third_party/virne'
        manifest = json.loads((path / 'SOURCE.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256((path / 'source.zip').read_bytes()).hexdigest(), manifest['archive_sha256'])
        with zipfile.ZipFile(path / 'source.zip') as archive:
            self.assertEqual(set(archive.namelist()), set(manifest['files']))
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            self.assertEqual((path / 'LICENSE').read_bytes(), archive.read('LICENSE'))

    def test_analysis_and_rank_cli_accept_a_complete_fixture_and_preserve_raw(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.run_fixture(directory, seeds=(31, 32))
            before = (path / RAW_NAME).read_bytes()
            for script in ('analyze_full_results.py', 'rank_results.py'):
                process = subprocess.run([sys.executable, '-B', str(root / 'scripts' / script), directory],
                    cwd=root, capture_output=True, text=True, timeout=90)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual((path / RAW_NAME).read_bytes(), before)
            self.assertTrue((path / 'analysis/primary_comparison.png').is_file())
            report = (path / 'rankings/REPORT.md').read_text(encoding='utf-8')
            self.assertIn('pinned Virne ports', report)


if __name__ == '__main__':
    unittest.main()
