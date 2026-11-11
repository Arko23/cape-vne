"""Independent witnesses for admissible QoS pruning and relaxed-state caching."""
import itertools
import random
import unittest

import vne
from tests.test_core import graph


class QoSBoundsTests(unittest.TestCase):
    def fixture(self, bounded, budget=240):
        # One branch violates delay, another cannot meet the hop cap.
        substrate = graph([20] * 6, [(0, 1, 5, 2), (1, 2, 5, 10),
                          (0, 3, 5, 1), (3, 4, 5, 1), (4, 2, 5, 1),
                          (0, 5, 5, 2), (5, 2, 5, 2)])
        algorithm = vne.LegacyAdaptiveVNE(substrate, qos_route_bounds=bounded,
                                          path_expansion_budget=budget)
        state = substrate.empty_state()
        for node in state['cpu']:
            state['cpu'][node] -= 1  # Equal powered-node cost for all branches.
        return algorithm, state

    def test_bounds_preserve_feasible_path_and_reduce_expansions(self):
        plain, state = self.fixture(False)
        bounded, _ = self.fixture(True)
        expected = plain.find_shortest_paths(0, 2, 5, 5, 2, state, k=1)
        self.assertEqual(expected, [[0, 5, 2]])
        self.assertEqual(bounded.find_shortest_paths(0, 2, 5, 5, 2, state, k=1), expected)
        self.assertLess(bounded.route_expansions, plain.route_expansions)
        self.assertGreater(bounded.qos_bound_prunes, 0)

    def test_avoiding_impossible_prefixes_can_rescue_a_bounded_search(self):
        plain, state = self.fixture(False, budget=3)
        bounded, _ = self.fixture(True, budget=3)
        self.assertEqual(plain.find_shortest_paths(0, 2, 5, 5, 2, state, k=1), [])
        self.assertEqual(bounded.find_shortest_paths(0, 2, 5, 5, 2, state, k=1), [[0, 5, 2]])
        self.assertEqual(plain.path_budget_exhaustions, 1)

    def test_tentative_reservations_cannot_poison_bounds_after_repair(self):
        substrate = graph([20] * 3, [(0, 1, 5, 1), (1, 2, 5, 1)])
        algorithm = vne.LegacyAdaptiveVNE(substrate, qos_route_bounds=True)
        reserved = substrate.empty_state()
        reserved['bw'][(0, 1)] = 1
        self.assertEqual(algorithm.find_shortest_paths(0, 2, 5, 3, 2, reserved, k=1), [])
        self.assertEqual(algorithm.find_shortest_paths(0, 2, 5, 3, 2,
                                                     substrate.empty_state(), k=1), [[0, 1, 2]])

    def test_bounded_paths_match_complete_simple_path_enumeration(self):
        rng = random.Random(6729)
        for _ in range(60):
            substrate = graph([20] * 5, [(u, w, rng.randint(2, 6), rng.randint(1, 5))
                              for u in range(5) for w in range(u + 1, 5) if rng.random() < .65])
            algorithm = vne.LegacyAdaptiveVNE(substrate, qos_route_bounds=True,
                                              path_expansion_budget=10000)
            state = substrate.empty_state()
            bandwidth, delay, hops = rng.randint(2, 5), rng.randint(3, 12), rng.randint(1, 4)
            feasible = []
            for length in range(hops):
                for middle in itertools.permutations([1, 2, 3], length):
                    path = [0, *middle, 4]
                    edges = [vne.canonical_edge(u, w) for u, w in zip(path, path[1:])]
                    if all(e in state['bw'] and state['bw'][e] >= bandwidth for e in edges):
                        if sum(substrate.link_delay(u, w) for u, w in zip(path, path[1:])) <= delay:
                            feasible.append(path)
            actual = algorithm.find_shortest_paths(0, 4, bandwidth, delay, hops, state, k=1)
            self.assertEqual(bool(actual), bool(feasible))
            if feasible:
                self.assertAlmostEqual(algorithm.path_cost(actual[0], state),
                                       min(algorithm.path_cost(p, state) for p in feasible))


if __name__ == '__main__':
    unittest.main()
