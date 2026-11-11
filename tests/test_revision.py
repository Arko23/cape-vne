"""Work-saving regressions and independently checked resource tradeoffs."""
import random
import unittest
from unittest.mock import patch

import vne
from tests.test_core import graph
from tests.helpers import regression_fixture, run_case, expected_outcomes


class RevisionTests(unittest.TestCase):
    def test_full_hop_footprint_avoids_a_powered_bandwidth_detour(self):
        sn = graph([100] * 3, [(0, 2, 100, 15), (0, 1, 100, 1), (1, 2, 100, 1)])
        sn.cpu_residual = {node: 90 for node in range(3)}
        current = vne.LegacyAdaptiveVNE(sn, hop_footprint=1.0)
        previous = vne.LegacyAdaptiveVNE(sn, hop_footprint=.25)
        self.assertEqual(previous.find_shortest_paths(0, 2, 10, 20, 3, sn.empty_state(), 1), [[0, 1, 2]])
        self.assertEqual(current.find_shortest_paths(0, 2, 10, 20, 3, sn.empty_state(), 1), [[0, 2]])
        self.assertEqual(sn.path_delay([0, 2]), 15)

    def test_successful_first_route_does_not_compute_unused_alternatives(self):
        sn = graph([100] * 4, [(0, 3, 100, 1), (0, 1, 100, 2),
                               (1, 3, 100, 2), (0, 2, 100, 3), (2, 3, 100, 3)])
        request = vne.VirtualNetworkRequest(1, 0, 10, {0: 10, 1: 10},
                                           [vne.VirtualEdge(0, 1, 10)])
        algorithm = vne.LegacyAdaptiveVNE(sn)
        state = sn.empty_state()
        algorithm.reserve_cpu(state, 0, 10)
        algorithm.reserve_cpu(state, 3, 10)
        with patch.object(algorithm, '_constrained_shortest_path',
                          wraps=algorithm._constrained_shortest_path) as searches:
            paths = algorithm.route_link_set(request, {0: 0, 1: 3}, state, k=3)
        self.assertEqual(paths, {(0, 1): [0, 3]})
        self.assertEqual(searches.call_count, 1)
        self.assertIsNotNone(algorithm.commit_embedding(request, state, {0: 0, 1: 3}, paths))

    def test_selective_packing_preserves_eager_embeddings(self):
        rng = random.Random(54309)
        for seed in range(12):
            sn = vne.SubstrateNetwork(12, seed=seed)
            for node in sn.cpu_residual:
                sn.cpu_residual[node] -= rng.randint(0, 30)
            request = vne.VirtualNetworkGenerator().generate(seed, 0, rng)
            eager = vne.LegacyAdaptiveVNE(sn.clone(), selective_packing=False)
            selective = vne.LegacyAdaptiveVNE(sn.clone(), selective_packing=True)
            old, new = eager.embed(request), selective.embed(request)
            self.assertEqual(old, new)
            self.assertEqual(eager.sn.empty_state(), selective.sn.empty_state())
            self.assertLessEqual(selective.packing_checks, eager.packing_checks)

    def test_lazy_and_eager_paths_preserve_results_and_rollback(self):
        rng = random.Random(84037)
        for seed in range(20):
            sn = vne.SubstrateNetwork(10, seed=seed)
            background = vne.VirtualNetworkRequest(-1, 0, 100,
                                                   {node: rng.randint(0, 40) for node in sn.cpu_residual}, [])
            background_algorithm = vne.BaseVNEAlgorithm(sn)
            background_state = sn.empty_state()
            for node, demand in background.node_cpu.items():
                background_algorithm.reserve_cpu(background_state, node, demand)
            background_embedding = background_algorithm.commit_embedding(
                background, background_state, {node: node for node in background.nodes}, {})
            self.assertIsNotNone(background_embedding)
            request = vne.VirtualNetworkGenerator().generate(seed, 0, rng)
            eager = vne.LegacyAdaptiveVNE(sn.clone(), lazy_paths=False)
            lazy = vne.LegacyAdaptiveVNE(sn.clone(), lazy_paths=True)
            old, new = eager.embed(request), lazy.embed(request)
            self.assertEqual(old, new)
            self.assertEqual(eager.sn.empty_state(), lazy.sn.empty_state())
            self.assertLessEqual(lazy.route_expansions, eager.route_expansions)
            if new is not None:
                vne._validate_active_state(lazy, {-1: (background, background_embedding),
                                                request.request_id: (request, new)})
                lazy.release_embedding(request, new)
                self.assertEqual(lazy.sn.empty_state(), sn.empty_state())

    def test_lazy_repair_can_request_a_second_path(self):
        sn = graph([20] * 5, [(0, 3, 2, 1), (3, 1, 2, 1),
                               (0, 4, 2, 2), (4, 1, 2, 2), (2, 3, 2, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 10, 1: 9, 2: 8},
                                           [vne.VirtualEdge(0, 1, 2), vne.VirtualEdge(1, 2, 1)],
                                           max_delay=4, max_hops=2)
        algorithm = vne.LegacyAdaptiveVNE(sn)
        state = sn.empty_state()
        mapping = {0: 0, 1: 1, 2: 2}
        for node, demand in request.node_cpu.items():
            algorithm.reserve_cpu(state, mapping[node], demand)
        routes = algorithm.route_link_set(request, mapping, state, k=3)
        self.assertEqual(routes, {(0, 1): [0, 4, 1], (1, 2): [1, 3, 2]})
        self.assertIsNotNone(algorithm.commit_embedding(request, state, mapping, routes))

    def test_trace_fingerprints_and_demand_time_are_exact(self):
        sn = graph([100, 100], [(0, 1, 100, 1)])
        request = vne.VirtualNetworkRequest(0, 10, 30, {0: 10, 1: 10}, [vne.VirtualEdge(0, 1, 10)])
        with patch.object(vne.experiments, 'SubstrateNetwork', return_value=sn), \
                patch.object(vne.experiments, 'generate_trace', return_value=[request]), \
                patch.object(vne.experiments, '_algorithm_names', return_value=['ProposedAdaptive']):
            row = vne.run_simulation(2, 100, 2)[0]
        self.assertEqual(row['ServedCPUUnitSeconds'], 400)
        self.assertEqual(row['ServedBandwidthUnitSeconds'], 200)
        self.assertAlmostEqual(row['EnergyPerServedCPUUnitSecond_Wh'], row['Energy_Wh'] / 400)
        self.assertAlmostEqual(row['EnergyPerServedBandwidthUnitSecond_Wh'], row['Energy_Wh'] / 200)
        self.assertEqual(len(row['TraceSHA256']), 64)
        self.assertEqual(len(row['TopologySHA256']), 64)

    def test_primary_baselines_match_the_frozen_non_time_outcomes(self):
        fixture = regression_fixture('baseline_regression.json')
        for item in fixture['cases']:
            expected = expected_outcomes(item)
            actual = run_case(item['case'], fixture['algorithms'])
            self.assertTrue(actual[fixture['fields']].equals(expected[fixture['fields']]))


if __name__ == '__main__':
    unittest.main()
