"""The maintained reports must expose undefined and adverse outcomes honestly."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

import vne
from scripts.analyze_full_results import verify_statistics, verify_summary
from scripts.rank_results import METRICS


def observations():
    rows = []
    for seed in (1, 2, 3, 4):
        for method in ('ProposedAdaptive', 'GRC', 'NodeRank'):
            rows.append(dict(Lambda=6., Algorithm=method, Seed=seed,
                Accepted=1, Cost=1., ServedCost=1.,
                **{metric: 1. for metric, *_ in METRICS}))
    return pd.DataFrame(rows)


def reports(frame):
    with tempfile.TemporaryDirectory() as directory:
        summary = vne.write_summary(frame, Path(directory) / 'summary.csv')
        statistical = vne.write_statistics(frame, Path(directory) / 'statistics.csv')
        verify_summary(frame, summary)
        verify_statistics(frame, statistical)
        return summary, statistical


class GreenReportingTests(unittest.TestCase):
    def test_no_service_does_not_become_a_quality_comparison_win(self):
        frame = observations()
        no_service = frame.Algorithm.eq('GRC')
        frame.loc[no_service, ['Accepted', 'Cost', 'ServedCost', 'MeanHops', 'R_C', 'Served_R_C']] = 0.
        raw_before = frame.copy(deep=True)
        summary, statistical = reports(frame)
        report = statistical.set_index(['Baseline', 'Metric'])
        for metric in ('R_C', 'Served_R_C'):
            row = report.loc[('GRC', metric)]
            self.assertEqual(row.n, 0)
            self.assertEqual(row.status, 'insufficient_pairs')
            self.assertTrue(np.isnan(row.p_value))
            self.assertTrue(np.isnan(row.q_value))
        quality = summary[summary.Algorithm.eq('GRC') & summary.Metric.isin(['MeanHops', 'R_C', 'Served_R_C'])]
        self.assertTrue(quality.n.eq(0).all())
        self.assertTrue(quality['mean'].isna().all())
        pd.testing.assert_frame_equal(frame, raw_before)
        invalid = statistical.copy()
        invalid.loc[invalid.Baseline.eq('GRC') & invalid.Metric.eq('R_C'), 'p_value'] = .01
        with self.assertRaisesRegex(ValueError, 'insufficient comparison'):
            verify_statistics(frame, invalid)

    def test_higher_energy_is_adverse_and_utilization_is_contextual(self):
        frame = observations()
        frame.loc[frame.Algorithm.eq('ProposedAdaptive'), ['Energy_Wh', 'NodeUtil']] = 2.
        _, statistical = reports(frame)
        report = statistical.set_index(['Baseline', 'Metric'])
        self.assertEqual(report.loc[('GRC', 'Energy_Wh'), 'preferred_direction'], 'lower')
        self.assertEqual(report.loc[('GRC', 'Energy_Wh'), 'mean_paired_difference'], 1.)
        self.assertEqual(report.loc[('GRC', 'NodeUtil'), 'preferred_direction'], 'context_dependent')

    def test_bh_excludes_undefined_tests_and_matches_independent_adjustment(self):
        frame = observations()
        frame.loc[frame.Algorithm.eq('NodeRank'), 'Cost'] = 0.
        frame.loc[frame.Algorithm.eq('ProposedAdaptive'), 'MeanEmbeddingTime'] = .5
        _, report = reports(frame)
        valid = report.p_value.dropna().sort_values()
        expected = np.minimum.accumulate((valid.to_numpy() * len(valid)
                    / np.arange(1, len(valid) + 1))[::-1])[::-1].clip(0, 1)
        np.testing.assert_allclose(report.loc[valid.index, 'q_value'], expected)
        self.assertEqual(len(valid), len(report) - 1)


if __name__ == '__main__':
    unittest.main()
