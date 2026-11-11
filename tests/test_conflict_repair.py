"""Correctness and work-budget checks for an experimental local repair policy."""
import unittest
from unittest.mock import patch
import vne
from tests.test_core import graph


class ConflictRepairTests(unittest.TestCase):
    def fixture(self):
        sn = graph([20] * 6, [(0, 2, 1, 1), (2, 1, 1, 1),
                   (0, 3, 1, 2), (3, 1, 1, 2), (4, 5, 1, 1), (3, 4, 10, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {i: 1 for i in range(5)},
                   [vne.VirtualEdge(0, 1, 1), vne.VirtualEdge(2, 3, 1),
                    vne.VirtualEdge(1, 4, 1)], max_delay=5, max_hops=2)
        mapping = {0: 0, 1: 1, 2: 4, 3: 5, 4: 2}
        paths = {(0, 1): [0, 2, 1], (2, 3): [4, 5]}
        algorithm = vne.LegacyAdaptiveVNE(sn, conflict_repair=True)
        state = sn.empty_state()
        for vnode, pnode in mapping.items():
            self.assertTrue(algorithm.reserve_cpu(state, pnode, request.node_cpu[vnode]))
        for edge in request.edges[:2]:
            self.assertTrue(algorithm.reserve_path(state, paths[(edge.u, edge.v)], edge.bandwidth))
        return algorithm, request, mapping, paths, state

    def test_local_repair_preserves_unrelated_paths_and_releases_exactly(self):
        algorithm, request, mapping, paths, state = self.fixture()
        original = algorithm.sn.empty_state()
        result = algorithm._repair_routes(request, mapping, state, paths,
                                          request.edges, request.edges[2:])
        self.assertIsNotNone(result)
        self.assertEqual(result[(2, 3)], paths[(2, 3)])
        self.assertEqual(result[(0, 1)], [0, 3, 1])
        self.assertEqual(result[(1, 4)], [1, 2])
        self.assertEqual(algorithm.conflict_repair_successes, 1)
        embedding = algorithm.commit_embedding(request, state, mapping, result)
        vne._validate_active_state(algorithm, {0: (request, embedding)})
        algorithm.release_embedding(request, embedding)
        self.assertEqual(algorithm.sn.empty_state(), original)

    def test_failed_local_repair_falls_back_without_exceeding_shared_budget(self):
        algorithm, request, mapping, paths, state = self.fixture()
        observed = []
        def failure(*args, **kwargs):
            observed.append((algorithm.route_budget, kwargs['edge_subset']))
            algorithm.route_search_nodes += algorithm.route_budget
            return None
        before = algorithm.sn.empty_state()
        with patch.object(algorithm, 'route_link_set', side_effect=failure):
            self.assertIsNone(algorithm._repair_routes(request, mapping, state, paths,
                                                      request.edges, request.edges[2:]))
        self.assertEqual(len(observed), 2)
        self.assertEqual(sum(budget for budget, _ in observed), 24)
        self.assertEqual(algorithm.route_budget, 24)
        self.assertEqual(algorithm.sn.empty_state(), before)
        self.assertEqual(algorithm.conflict_repair_fallbacks, 1)

    def test_unknown_bounded_path_failure_uses_full_repair(self):
        algorithm, request, mapping, paths, state = self.fixture()
        with patch.object(algorithm, 'find_shortest_paths', return_value=[]), \
             patch.object(algorithm, 'route_link_set', return_value=None) as route:
            self.assertIsNone(algorithm._repair_routes(request, mapping, state, paths,
                                                      request.edges, request.edges[2:]))
        self.assertEqual(route.call_count, 1)
        self.assertEqual(len(route.call_args.kwargs['edge_subset']), len(request.edges))
        self.assertEqual(algorithm.conflict_repair_attempts, 0)


if __name__ == '__main__':
    unittest.main()
