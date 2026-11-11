"""Quality reporting must not reward a method for accepting no work."""
import unittest

import numpy as np
import pandas as pd

from scripts.rank_results import position, rankable_results, rank_label, rank_means


class ReportingTests(unittest.TestCase):
    def test_empty_service_cannot_win_shortest_route_or_revenue_cost(self):
        raw = pd.DataFrame({
            'Algorithm': ['RejectEverything', 'AdmitFeasible'],
            'Accepted': [0, 1], 'Cost': [0., 10.], 'ServedCost': [0., 20.],
            'MeanHops': [0., 3.], 'R_C': [0., .8], 'Served_R_C': [0., .7]})
        saved = raw.copy(deep=True)
        view = rankable_results(raw).set_index('Algorithm')
        ranks = rank_means(view.MeanHops, ascending=True)
        self.assertEqual(ranks.Algorithm.tolist(), ['AdmitFeasible'])
        self.assertEqual(ranks.Rank.tolist(), [1])
        self.assertTrue(np.isnan(view.loc['RejectEverything', 'R_C']))
        self.assertTrue(np.isnan(view.loc['RejectEverything', 'Served_R_C']))
        pd.testing.assert_frame_equal(raw, saved)

    def test_all_undefined_quality_has_no_winner_and_formats_safely(self):
        ranks = rank_means(pd.Series({'NoServiceA': np.nan, 'NoServiceB': np.nan}), True)
        self.assertTrue(ranks.empty)
        ours = position(ranks, 'NoServiceA')
        self.assertEqual(rank_label(ours.Rank), 'undefined')


if __name__ == '__main__':
    unittest.main()
