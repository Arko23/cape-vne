"""Green-policy tests; run with python -m unittest test_green -v."""
import ast
import math
from pathlib import Path
import random
import unittest

import vne
from vne import experiments
from tests.test_core import graph


class GreenRegression(unittest.TestCase):
    def test_energy_priority_reuses_powered_host_when_feasible(self):
        sn=graph([100,100],[(0,1,100,1)])
        sn.cpu_residual[1]=50
        request=vne.VirtualNetworkRequest(0,0,100,{0:10},[])
        # Explicit energy priority: balanced defaults may prefer CPU headroom
        # over consolidation on an already half-full host.
        algorithm=vne.LegacyAdaptiveVNE(sn,energy_weight=1.0)
        result=algorithm.embed(request)
        self.assertEqual(result['mapping'],{0:1})
        self.assertEqual(result['boot_energy_joules'],0)

    def test_prefers_powered_transit_path_over_cold_shortcut(self):
        sn=graph([100]*4,[(0,1,100,1),(1,3,100,1),(0,2,100,2),(2,3,100,2)])
        for node in (0,2,3):
            sn.cpu_residual[node]=90
        algorithm=vne.LegacyAdaptiveVNE(sn)
        paths=algorithm.find_shortest_paths(0,3,10,10,3,sn.empty_state(),k=1)
        self.assertEqual(paths,[[0,2,3]])
        self.assertLess(algorithm.path_cost(paths[0],sn.empty_state()),algorithm.path_cost([0,1,3],sn.empty_state()))

    def test_fast_route_path_does_not_invoke_joint_repair(self):
        sn=graph([100]*3,[(0,1,100,1),(1,2,100,1),(0,2,100,1)])
        algorithm=vne.LegacyAdaptiveVNE(sn)
        request=vne.VirtualNetworkRequest(0,0,100,{0:10,1:10},[vne.VirtualEdge(0,1,10)])
        result=algorithm.embed(request)
        self.assertIsNotNone(result)
        self.assertGreater(algorithm.fast_route_successes,0)
        self.assertEqual(algorithm.joint_route_repairs,0)

    def test_repairs_earlier_route_to_admit_request(self):
        sn=graph([10,9,8,1,1],[(0,3,2,1),(3,1,2,1),(0,4,2,2),(4,1,2,2),(2,3,2,1)])
        request=vne.VirtualNetworkRequest(0,0,10,{0:10,1:9,2:8},
                   [vne.VirtualEdge(0,1,2),vne.VirtualEdge(1,2,1)],max_delay=4,max_hops=2)
        algorithm=vne.LegacyAdaptiveVNE(sn)
        result=algorithm.embed(request)
        self.assertIsNotNone(result)
        self.assertEqual(result['paths'],{(0,1):[0,4,1],(1,2):[1,3,2]})
        vne._validate_active_state(algorithm,{0:(request,result)})

    def test_shortest_green_path_matches_exhaustive_oracle(self):
        rng=random.Random(81203)
        for _ in range(200):
            n=rng.randint(3,7)
            links=[(u,w,rng.randint(5,20),rng.randint(1,7)) for u in range(n) for w in range(u+1,n) if rng.random()<.55]
            sn=graph([100]*n,links)
            for node in range(n):
                if rng.random()<.4:
                    sn.cpu_residual[node]=80
            algorithm=vne.LegacyAdaptiveVNE(sn)
            state=sn.empty_state()
            bandwidth=rng.randint(5,15)
            max_delay,max_hops=15,4
            feasible=[]
            def enumerate_paths(path):
                if path[-1]==n-1:
                    feasible.append(path)
                    return
                if len(path)-1>=max_hops:
                    return
                for nxt in sorted(sn.neighbors[path[-1]]):
                    edge=vne.canonical_edge(path[-1],nxt)
                    if nxt not in path and state['bw'][edge]>=bandwidth:
                        candidate=path+[nxt]
                        if sn.path_delay(candidate)<=max_delay:
                            enumerate_paths(candidate)
            enumerate_paths([0])
            actual=algorithm.find_shortest_paths(0,n-1,bandwidth,max_delay,max_hops,state,k=3)
            expected=sorted(algorithm.path_cost(p,state) for p in feasible)[:3]
            self.assertEqual(len(actual),len(expected))
            for path,cost in zip(actual,expected):
                self.assertAlmostEqual(algorithm.path_cost(path,state),cost)

    def test_budget_rejection_does_not_mutate_substrate(self):
        sn=graph([100]*4,[(0,1,100,1),(1,2,100,1),(2,3,100,1)])
        algorithm=vne.LegacyAdaptiveVNE(sn,search_budget=1)
        request=vne.VirtualNetworkRequest(0,0,100,{0:10,1:10},[vne.VirtualEdge(0,1,10)])
        before=sn.empty_state()
        self.assertIsNone(algorithm.embed(request))
        self.assertEqual(sn.empty_state(),before)
        self.assertEqual(algorithm.search_budget_exhaustions,1)


if __name__=='__main__':
    unittest.main(verbosity=2)
