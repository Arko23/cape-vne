"""Independent path oracle and transactional/fairness witnesses for revision."""
import itertools
import math
import random
import unittest

import vne
from vne.efficient import EfficientAdaptiveVNE
from tests.test_core import graph


class EfficientTests(unittest.TestCase):
    def test_negative_delay_is_rejected_before_using_the_dp_guarantee(self):
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            EfficientAdaptiveVNE(graph([20, 20], [(0, 1, 10, -1)]))

    def test_minimum_hop_delay_dp_matches_complete_simple_path_enumeration(self):
        rng = random.Random(61091)
        for _ in range(160):
            n = rng.randint(3, 6)
            sn = graph([20] * n, [(u, w, rng.randint(2, 8), rng.randint(0, 6))
                for u in range(n) for w in range(u + 1, n) if rng.random() < .7])
            algorithm = EfficientAdaptiveVNE(sn, path_expansion_budget=10000)
            bw, delay, hops = rng.randint(2, 6), rng.randint(1, 15), rng.randint(1, n - 1)
            removed_nodes = {1} if rng.random() < .25 else set()
            removed_edges = {next(iter(sn.edges))} if sn.edges and rng.random() < .25 else set()
            feasible = []
            for length in range(hops):
                for middle in itertools.permutations(range(1, n - 1), length):
                    path = [0, *middle, n - 1]
                    edges = [vne.canonical_edge(u, w) for u, w in zip(path, path[1:])]
                    if (not any(node in removed_nodes for node in path)
                            and all(edge in sn.edges and edge not in removed_edges
                                    and sn.bandwidth_residual[edge] >= bw for edge in edges)
                            and sn.path_delay(path) <= delay):
                        feasible.append(path)
            actual = algorithm._constrained_shortest_path(0, n - 1, bw, delay, hops,
                sn.empty_state(), removed_nodes=removed_nodes, removed_edges=removed_edges)
            self.assertEqual(actual is not None, bool(feasible))
            if actual:
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual((sn.path_hops(actual), sn.path_delay(actual)),
                                 min((sn.path_hops(p), sn.path_delay(p)) for p in feasible))

    def test_vector_profiles_preserve_the_original_values(self):
        rng = random.Random(61671)
        for _ in range(35):
            sn = graph([20] * 6, [(u, w, rng.randint(2, 10), rng.randint(1, 7))
                for u in range(6) for w in range(u + 1, 6) if rng.random() < .7])
            for edge in sn.bandwidth_residual:
                sn.bandwidth_residual[edge] = rng.randint(0, int(sn.bandwidth_capacity[edge]))
            request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1},
                [vne.VirtualEdge(0, 1, rng.randint(2, 8))], max_delay=12, max_hops=3)
            old, new = vne.LegacyAdaptiveVNE(sn), EfficientAdaptiveVNE(sn)
            for target in (None, 2, 5):
                expected = old._link_profile(request, request.edges[0], target, sn.empty_state())
                actual = new._link_profile(request, request.edges[0], target, sn.empty_state())
                for node in sn.cpu_residual:
                    if math.isfinite(expected[node]):
                        self.assertAlmostEqual(expected[node], actual[node])
                    else:
                        self.assertEqual(expected[node], actual[node])

    def test_failed_fast_batch_and_budget_leave_state_unchanged(self):
        sn = graph([20] * 3, [(0, 1, 5, 1), (1, 2, 5, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1, 2: 1},
            [vne.VirtualEdge(0, 1, 5), vne.VirtualEdge(0, 2, 5)])
        algorithm = EfficientAdaptiveVNE(sn)
        state = sn.empty_state()
        self.assertIsNone(algorithm.route_link_set(request, {0: 0, 1: 1, 2: 2}, state, k=1))
        self.assertEqual(state, sn.empty_state())
        request.edges = request.edges[:1]
        algorithm.route_budget = 1
        self.assertIsNone(algorithm.route_link_set(request, {0: 0, 1: 1}, state, k=1))
        self.assertEqual(state, sn.empty_state())
        self.assertEqual(algorithm.last_route_failure_reason, 'route_budget_exhausted')

    def test_on_demand_packing_preserves_embeddings_and_reduces_checks(self):
        for seed in range(8):
            sn = vne.SubstrateNetwork(12, seed=seed)
            request = vne.VirtualNetworkGenerator().generate(seed, 0, random.Random(seed + 61))
            eager = EfficientAdaptiveVNE(sn.clone(), on_demand_packing=False)
            lazy = EfficientAdaptiveVNE(sn.clone(), on_demand_packing=True)
            self.assertEqual(eager.embed(request), lazy.embed(request))
            self.assertEqual(eager.sn.empty_state(), lazy.sn.empty_state())
            self.assertLessEqual(lazy.packing_checks, eager.packing_checks)

    def test_commit_release_and_caches_refresh_across_requests(self):
        sn = graph([20] * 4, [(u, w, 10, 1) for u in range(4) for w in range(u + 1, 4)])
        algorithm = EfficientAdaptiveVNE(sn)
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 2, 1: 2}, [vne.VirtualEdge(0, 1, 8)])
        before = sn.empty_state()
        result = algorithm.embed(request)
        self.assertIsNotNone(result)
        vne._validate_active_state(algorithm, {0: (request, result)})
        algorithm.release_embedding(request, result)
        self.assertEqual(before, sn.empty_state())
        self.assertIsNone(algorithm._background_powered)
        for edge in sn.bandwidth_residual:
            sn.bandwidth_residual[edge] = 1
        self.assertIsNone(algorithm.embed(request))

    def test_negative_path_cache_does_not_survive_a_changed_eligible_graph(self):
        sn = graph([20] * 5, [(0, 1, 6, 1), (1, 2, 6, 1),
                             (2, 3, 6, 1), (3, 4, 5, 1)])
        algorithm = EfficientAdaptiveVNE(sn)
        blocked = sn.empty_state()
        self.assertIsNone(algorithm._constrained_shortest_path(0, 4, 6, 8, 4, blocked))
        self.assertIsNone(algorithm._constrained_shortest_path(0, 4, 6, 8, 4, blocked))
        self.assertEqual(algorithm.path_cache_hits, 1)
        # Changing eligibility must invalidate a certified failure. Reserve
        # state is deliberately independent of the immutable original capacity.
        restored = sn.empty_state()
        restored['bw'][(3, 4)] = 6
        self.assertEqual(algorithm._constrained_shortest_path(0, 4, 6, 8, 4, restored),
                         [0, 1, 2, 3, 4])

    def test_sparse_reverse_bounds_preserve_zero_delay_edges(self):
        sn = graph([20] * 4, [(0, 1, 5, 0), (1, 2, 5, 1), (2, 3, 5, 2)])
        old, new = vne.LegacyAdaptiveVNE(sn), EfficientAdaptiveVNE(sn)
        new._background_powered = sn.powered_nodes()
        self.assertEqual(old._destination_bounds(3, 5, sn.empty_state()),
                         new._destination_bounds(3, 5, sn.empty_state()))

    def test_vector_cut_sets_match_legacy_under_tentative_cpu_reservations(self):
        rng = random.Random(61439)
        for seed in range(25):
            sn = vne.SubstrateNetwork(10, seed=seed)
            for edge in sn.bandwidth_residual:
                sn.bandwidth_residual[edge] = rng.randint(0, int(sn.bandwidth_capacity[edge]))
            request = vne.VirtualNetworkGenerator().generate(seed, 0, rng)
            old, new = vne.LegacyAdaptiveVNE(sn), EfficientAdaptiveVNE(sn)
            new._background_powered = sn.powered_nodes()
            state = sn.empty_state()
            for node in state['cpu']:
                state['cpu'][node] -= 1
            for vnode in request.nodes:
                a = old._score_context(request, vnode, {}, state)
                b = new._score_context(request, vnode, {}, state)
                self.assertEqual(a['allowed'], b['allowed'])
                self.assertEqual(a['powered'], b['powered'])

    def test_public_proposal_and_factory_use_the_same_policy(self):
        sn = graph([20] * 3, [(0, 1, 10, 1), (1, 2, 10, 1)])
        direct = vne.ProposedAdaptiveVNE(sn)
        factory = vne.algorithm_factory('ProposedAdaptive', sn, 1)
        self.assertIs(type(direct), type(factory))
        self.assertEqual(vne.algorithm_parameters(direct), vne.algorithm_parameters(factory))
        self.assertEqual(direct.repair_link_limit, 4)


if __name__ == '__main__':
    unittest.main()
