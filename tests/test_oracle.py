"""MILP oracle checked against independently enumerated tiny embeddings."""
import itertools
import random
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts.exact_oracle import solve_request
import vne
from tests.test_core import graph


class ExactOracleTests(unittest.TestCase):
    def test_time_limit_is_unknown_rather_than_infeasible(self):
        sn = graph([5, 5], [(0, 1, 5, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 2, 1: 2}, [vne.VirtualEdge(0, 1, 2)])
        timeout = SimpleNamespace(status=1, x=None, message='Time limit reached')
        with patch('scripts.exact_oracle.milp', return_value=timeout):
            answer = solve_request(sn, request)
        self.assertEqual(answer['status'], 'limit_reached')
        self.assertIsNone(answer['embedding'])
        for limit in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                solve_request(sn, request, limit)

    def test_self_loop_is_rejected_under_common_virtual_graph_rules(self):
        sn = graph([5, 5], [])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 2},
                    [vne.VirtualEdge(0, 0, 9)], max_delay=0, max_hops=0)
        with patch('scripts.exact_oracle.milp') as solver:
            with self.assertRaises(ValueError):
                solve_request(sn, request)
            solver.assert_not_called()

    def test_matches_independent_placement_and_simple_route_enumeration(self):
        rng = random.Random(6509)
        for _ in range(20):
            sn = graph([rng.randint(2, 6) for _ in range(4)],
                       [(u, w, rng.randint(1, 6), rng.randint(1, 3))
                        for u in range(4) for w in range(u+1, 4) if rng.random() < .7])
            request = vne.VirtualNetworkRequest(0, 0, 10, {0: rng.randint(1, 4), 1: rng.randint(1, 4)},
                       [vne.VirtualEdge(0, 1, rng.randint(1, 5))], max_hops=3, max_delay=5)
            minimum = None
            def paths(path, target, demand):
                if path[-1] == target:
                    if sn.path_delay(path) <= request.max_delay:
                        yield path
                    return
                if len(path)-1 == request.max_hops: return
                for nxt in sn.neighbors[path[-1]]:
                    if nxt not in path and sn.bandwidth_residual[vne.canonical_edge(path[-1], nxt)] >= demand:
                        yield from paths(path+[nxt], target, demand)
            for source, target in itertools.permutations(range(4), 2):
                if sn.cpu_residual[source] < request.node_cpu[0] or sn.cpu_residual[target] < request.node_cpu[1]:
                    continue
                for path in paths([source], target, request.edges[0].bandwidth):
                    cost = request.total_cpu + request.edges[0].bandwidth*(len(path)-1)
                    minimum = cost if minimum is None else min(minimum, cost)
            answer = solve_request(sn, request)
            if minimum is None:
                self.assertEqual(answer['status'], 'proven_infeasible')
            else:
                self.assertEqual(answer['status'], 'optimal')
                self.assertAlmostEqual(answer['cost'], minimum)

    def test_bandwidth_is_shared_in_both_directions_and_hosts_are_injective(self):
        sn = graph([5, 5, 5], [(0, 1, 3, 1), (1, 2, 3, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 5, 1: 5, 2: 5},
                   [vne.VirtualEdge(0, 1, 2), vne.VirtualEdge(1, 2, 2), vne.VirtualEdge(0, 2, 2)])
        self.assertEqual(solve_request(sn, request)['status'], 'proven_infeasible')


if __name__ == '__main__':
    unittest.main()
