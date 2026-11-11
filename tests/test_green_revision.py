"""Real admission, QoS-domain and marginal-power regression witnesses."""
import json
import itertools
import math
from pathlib import Path
import random
import unittest

import vne
from vne.green import GreenAdaptiveVNE
from vne.efficient import EfficientAdaptiveVNE
from tests.test_core import graph


class GreenRevisionTests(unittest.TestCase):
    def test_check_uses_actual_size_for_pso_metadata(self):
        for size in (20, 50, 80, 100):
            expected = vne._experiment_spec(80, size, 1, True, True)['algorithm_parameters']
            self.assertEqual(expected['PSO']['candidate_limit'], size)

    def test_joint_delay_layers_match_exhaustive_simple_path_oracle(self):
        rng = random.Random(97541)
        for _ in range(80):
            size = rng.randint(3, 6)
            sn = graph([20] * size, [(u, w, rng.randint(1, 8), rng.randint(0, 6))
                for u in range(size) for w in range(u + 1, size) if rng.random() < .6])
            algorithm = GreenAdaptiveVNE(sn)
            state = sn.empty_state()
            demand, hops = rng.randint(1, 6), rng.randint(1, size - 1)
            layers = algorithm._joint_delay_layers(size - 1, demand, hops, state, {})
            for source in range(size):
                expected = 0. if source == size - 1 else math.inf
                middle_nodes = set(range(size)) - {source, size - 1}
                if source != size - 1:
                    for count in range(hops):
                        for middle in itertools.permutations(middle_nodes, count):
                            path = [source, *middle, size - 1]
                            links = [vne.canonical_edge(u, w) for u, w in zip(path, path[1:])]
                            if all(e in state['bw'] and state['bw'][e] >= demand for e in links):
                                expected = min(expected, sn.path_delay(path))
                self.assertEqual(layers[-1][source], expected)

    def test_batched_separate_domains_preserve_old_packing_decisions(self):
        rng = random.Random(97543)
        for seed in range(30):
            sn = vne.SubstrateNetwork(8, link_prob=.2, seed=seed)
            for edge in sn.bandwidth_residual:
                sn.bandwidth_residual[edge] = rng.randint(0, int(sn.bandwidth_capacity[edge]))
            request = vne.VirtualNetworkGenerator(max_delay=12, max_hops=3).generate(seed, 0, rng)
            old = EfficientAdaptiveVNE(sn)
            new = GreenAdaptiveVNE(sn, joint_qos_checks=False, domain_ordering=False, green_two_hop=False)
            for vnode in request.nodes:
                for node in sn.cpu_residual:
                    other = next(v for v in request.nodes if v != vnode)
                    for mapping in ({}, {other: 7}):
                        self.assertEqual(old._first_hop_feasible(request, vnode, node, mapping, sn.empty_state()),
                                         new._first_hop_feasible(request, vnode, node, mapping, sn.empty_state()))

    def test_actual_joint_routes_are_never_pruned_by_stronger_domains(self):
        rng = random.Random(97547)
        for _ in range(90):
            sn = graph([20] * 5, [(u, w, rng.randint(2, 6), rng.randint(0, 4))
                for u in range(5) for w in range(u + 1, 5) if rng.random() < .6])
            request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1, 2: 1},
                [vne.VirtualEdge(0, 1, 2), vne.VirtualEdge(0, 2, 3)], max_delay=8, max_hops=3)
            routes = []
            for target, demand in ((3, 2), (4, 3)):
                feasible = []
                for count in range(3):
                    for middle in itertools.permutations(set(range(5)) - {0, target}, count):
                        path = [0, *middle, target]
                        links = [vne.canonical_edge(u, w) for u, w in zip(path, path[1:])]
                        if (all(e in sn.edges and sn.bandwidth_residual[e] >= demand for e in links)
                                and sn.path_delay(path) <= 8):
                            feasible.append(links)
                routes.append(feasible)
            for a, b in itertools.product(*routes):
                if all(2 * (e in a) + 3 * (e in b) <= sn.bandwidth_residual[e] for e in set(a + b)):
                    self.assertTrue(GreenAdaptiveVNE(sn)._first_hop_feasible(
                        request, 0, 0, {1: 3, 2: 4}, sn.empty_state()))
                    break

    def test_new_domains_reset_after_arrivals_releases_and_public_state_changes(self):
        sn = graph([20] * 3, [(0, 1, 5, 1), (1, 2, 5, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1},
            [vne.VirtualEdge(0, 1, 5)], max_delay=3, max_hops=2)
        algorithm = GreenAdaptiveVNE(sn)
        before = sn.empty_state()
        result = algorithm.embed(request)
        self.assertIsNotNone(result)
        vne._validate_active_state(algorithm, {0: (request, result)})
        algorithm.release_embedding(request, result)
        self.assertEqual(sn.empty_state(), before)
        self.assertIsNone(algorithm._green_bw)
        self.assertTrue(algorithm._first_hop_feasible(request, 0, 0, {1: 2}, sn.empty_state()))
        sn.bandwidth_residual[(1, 2)] = 0
        self.assertFalse(algorithm._first_hop_feasible(request, 0, 0, {1: 2}, sn.empty_state()))
        self.assertIsNone(algorithm.embed(vne.VirtualNetworkRequest(1, 0, 10,
            {0: 21, 1: 21, 2: 21}, request.edges)))
        sn.bandwidth_residual[(1, 2)] = 5
        self.assertIsNotNone(algorithm.embed(request))

    def test_joint_hop_delay_domain_rejects_separately_feasible_bounds(self):
        # The short path misses delay; the fast path misses the hop cap.
        sn = graph([20] * 5, [(0, 1, 5, 1), (1, 4, 5, 5),
                              (1, 2, 5, 1), (2, 3, 5, 1), (3, 4, 5, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1},
            [vne.VirtualEdge(0, 1, 5)], max_delay=5, max_hops=3)
        algorithm = vne.ProposedAdaptiveVNE(sn)
        self.assertFalse(algorithm._first_hop_feasible(
            request, 0, 0, {1: 4}, sn.empty_state()))
        self.assertEqual(sn.empty_state(), sn.clone().empty_state())

    def test_equal_hop_route_uses_powered_transit_when_qos_allows(self):
        sn = graph([20] * 4, [(0, 1, 10, 2), (1, 3, 10, 2),
                              (0, 2, 10, 1), (2, 3, 10, 1)])
        # A real background allocation powers node 1, but not node 2.
        sn.cpu_residual[1] -= 1
        algorithm = vne.ProposedAdaptiveVNE(sn)
        path = algorithm._constrained_shortest_path(0, 3, 5, 5, 2, sn.empty_state())
        self.assertEqual(path, [0, 1, 3])
        self.assertEqual(sn.path_hops(path), 2)
        self.assertLessEqual(sn.path_delay(path), 5)
        self.assertEqual(sn.powered_nodes(), {1})

    def test_recovers_a_constrained_center_before_unconstrained_leaves(self):
        sn = graph([10] * 3, [(0, 1, 5, 1), (0, 2, 5, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 6, 1: 6, 2: 5},
            [vne.VirtualEdge(0, 2, 5), vne.VirtualEdge(1, 2, 5)], max_delay=4, max_hops=2)
        old = EfficientAdaptiveVNE(sn.clone(), search_budget=7)
        self.assertIsNone(old.embed(request))
        algorithm = vne.ProposedAdaptiveVNE(sn, search_budget=7)
        result = algorithm.embed(request)
        self.assertIsNotNone(result)
        self.assertLessEqual(algorithm.last_search_nodes, 7)
        vne._validate_active_state(algorithm, {0: (request, result)})

    def test_two_passes_share_total_quota_and_failed_attempts_are_atomic(self):
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1, 2: 1},
            [vne.VirtualEdge(0, 1, 5), vne.VirtualEdge(1, 2, 5), vne.VirtualEdge(0, 2, 5)])
        for quota in (1, 2, 4, 8, 24):
            sn = graph([10] * 3, [(0, 1, 5, 1), (0, 2, 5, 1)])
            before = sn.empty_state()
            algorithm = GreenAdaptiveVNE(sn, search_budget=quota, greedy_first=True)
            self.assertIsNone(algorithm.embed(request))
            self.assertLessEqual(algorithm.last_search_nodes, quota)
            self.assertEqual(sn.empty_state(), before)
            self.assertEqual(algorithm.candidate_limit, 8)
            self.assertTrue(algorithm.domain_ordering)

    def test_saved_difficult_witness_remains_bounded_and_accounted(self):
        root = Path(__file__).resolve().parents[1]
        path = root / 'tests/fixtures/sparse_qos_witness.json'
        witness = json.loads(path.read_text())
        scenario = vne.Scenario(**witness['scenario'])
        sn = vne.SubstrateNetwork(witness['scenario_item']['nodes'],
            seed=witness['seed'], **scenario.substrate_kwargs())
        sn.apply_state(dict(cpu=dict(witness['state']['cpu']),
            bw={tuple(edge): value for edge, value in witness['state']['bw']}))
        data = witness['request']
        request = vne.VirtualNetworkRequest(
            **{k: value for k, value in data.items() if k not in ('node_cpu', 'edges')},
            node_cpu={int(k): value for k, value in data['node_cpu'].items()},
            edges=[vne.VirtualEdge(**edge) for edge in data['edges']])
        before = sn.empty_state()
        algorithm = vne.ProposedAdaptiveVNE(sn)
        self.assertEqual(algorithm.search_budget, 24)
        result = algorithm.embed(request)
        self.assertLessEqual(algorithm.last_search_nodes, 24)
        if result is None:
            # A finite heuristic need not recover every feasible old witness.
            # Retain and report this counterexample instead of faking a fix.
            self.assertEqual(sn.empty_state(), before)
            return
        # Saved background need not have active-request objects. Independently
        # validate this new embedding's geometry and its resource deltas.
        cpu, bw = algorithm._embedding_usage(request, result['mapping'], result['paths'])
        for node, value in before['cpu'].items():
            self.assertAlmostEqual(sn.cpu_residual[node], value - cpu.get(node, 0))
        for edge, value in before['bw'].items():
            self.assertAlmostEqual(sn.bandwidth_residual[edge], value - bw.get(edge, 0))
        algorithm.release_embedding(request, result)
        self.assertEqual(sn.empty_state(), before)


if __name__ == '__main__':
    unittest.main()
