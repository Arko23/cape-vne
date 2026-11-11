"""Outcome and safety witnesses for proposal-only work reduction."""
import math
import itertools
import random
import unittest
from unittest.mock import patch

import numpy as np
import vne
from vne.green import GreenAdaptiveVNE
from vne.efficient import EfficientAdaptiveVNE
from tests.test_core import graph


class ProposalPerformanceTests(unittest.TestCase):
    def test_membership_only_domain_count_matches_complete_scoring_context(self):
        rng = random.Random(10791)
        for seed in range(45):
            sn = vne.SubstrateNetwork(10, link_prob=.15, seed=seed)
            for node in sn.cpu_residual:
                sn.cpu_residual[node] -= rng.randint(0, 40)
            for edge in sn.bandwidth_residual:
                sn.bandwidth_residual[edge] = rng.randint(0, int(sn.bandwidth_capacity[edge]))
            request = vne.VirtualNetworkGenerator(max_delay=12, max_hops=3).generate(seed, 0, rng)
            algorithm = GreenAdaptiveVNE(sn)
            algorithm._green_bw = algorithm._edge_residual(sn.empty_state())
            algorithm._background_powered = sn.powered_nodes()
            mapping = {request.nodes[0]: 0}
            state = sn.empty_state()
            state['cpu'][0] -= 1
            for vnode in request.nodes[1:]:
                context = algorithm._score_context(request, vnode, mapping, state)
                expected = sum(node not in mapping.values() and node in context['allowed']
                               and state['cpu'][node] + vne.EPS >= request.node_cpu[vnode]
                               and all(math.isfinite(profile[node]) for _, profile in context['incident'])
                               for node in algorithm._nodes)
                fresh = GreenAdaptiveVNE(sn)
                fresh._green_bw = fresh._edge_residual(state)
                self.assertEqual(fresh._domain_count(request, vnode, mapping, state), expected)

    def test_local_host_matching_rejects_hall_failure_before_search(self):
        sn = graph([20] * 4, [(0, 1, 5, 1), (0, 2, 5, 1), (0, 3, 5, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1, 2: 1},
                    [vne.VirtualEdge(0, 1, 5), vne.VirtualEdge(1, 2, 5), vne.VirtualEdge(0, 2, 5)])
        algorithm = GreenAdaptiveVNE(sn)
        before = sn.empty_state()
        with patch.object(algorithm, '_backtrack', side_effect=AssertionError('Unnecessary search')):
            self.assertIsNone(algorithm.embed(request))
        self.assertEqual(algorithm.last_failure_reason, 'local_host_matching')
        self.assertEqual(algorithm.last_search_nodes, 0)
        self.assertEqual(sn.empty_state(), before)

    def test_cpu_matching_matches_exhaustive_injective_assignments(self):
        rng = random.Random(10787)
        for _ in range(60):
            capacities = [rng.randint(1, 10) for _ in range(4)]
            demands = {i: rng.randint(1, 10) for i in range(3)}
            sn = graph(capacities, [])
            request = vne.VirtualNetworkRequest(0, 0, 10, demands, [])
            feasible = any(all(demands[v] <= capacities[m[v]] for v in demands)
                           for m in itertools.permutations(range(4), 3))
            self.assertEqual(GreenAdaptiveVNE(sn)._local_matching_possible(request), feasible)

    def test_known_feasible_routes_survive_joint_host_matching(self):
        rng = random.Random(10789)
        witnesses = 0
        for seed in range(25):
            sn = vne.SubstrateNetwork(10, seed=seed)
            baseline = vne.EfficientAdaptiveVNE(sn.clone())
            request = vne.VirtualNetworkGenerator(max_delay=15, max_hops=3).generate(seed, 0, rng)
            if baseline.embed(request) is not None:
                witnesses += 1
                self.assertTrue(GreenAdaptiveVNE(sn)._local_matching_possible(request))
        self.assertGreater(witnesses, 0)

    def test_joint_profile_is_built_once_and_context_tracks_cpu_reservations(self):
        sn = graph([20] * 4, [(0, 1, 10, 1), (1, 2, 10, 1), (2, 3, 10, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 2, 1: 3},
                    [vne.VirtualEdge(0, 1, 5)], max_delay=4, max_hops=3)
        algorithm = GreenAdaptiveVNE(sn)
        algorithm._green_bw = algorithm._edge_residual(sn.empty_state())
        algorithm._background_powered = set()
        with patch.object(algorithm, '_joint_delay_layers', wraps=algorithm._joint_delay_layers) as builds:
            first = algorithm._link_profile(request, request.edges[0], 3, sn.empty_state())
            second = algorithm._link_profile(request, request.edges[0], 3, sn.empty_state())
        self.assertIs(first, second)
        self.assertEqual(builds.call_count, 1)
        state = sn.empty_state()
        original = algorithm._score_context(request, 0, {1: 3}, state)
        state['cpu'][0] -= 2
        following = algorithm._score_context(request, 0, {1: 3}, state)
        self.assertIsNot(original, following)
        self.assertNotEqual(original['pressure'], following['pressure'])

    def test_batched_host_scores_match_scalar_formula_on_changed_private_states(self):
        rng = random.Random(10783)
        for seed in range(20):
            sn = vne.SubstrateNetwork(12, seed=seed)
            for node in sn.cpu_residual:
                sn.cpu_residual[node] -= rng.randint(0, 40)
            for edge in sn.bandwidth_residual:
                sn.bandwidth_residual[edge] = rng.randint(0, int(sn.bandwidth_capacity[edge]))
            request = vne.VirtualNetworkGenerator().generate(seed, 0, rng)
            algorithm = GreenAdaptiveVNE(sn)
            algorithm._green_bw = algorithm._edge_residual(sn.empty_state())
            algorithm._background_powered = sn.powered_nodes()
            state = sn.empty_state()
            mapping = {request.nodes[0]: 0}
            vnode = request.nodes[1]
            context = algorithm._score_context(request, vnode, mapping, state)
            context['defer_packing'] = True
            actual = algorithm._host_scores(request, vnode, mapping, state, context)
            expected = [EfficientAdaptiveVNE._node_score(algorithm, request, vnode, node, mapping, state, context)
                        for node in algorithm._nodes]
            np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


if __name__ == '__main__':
    unittest.main()
