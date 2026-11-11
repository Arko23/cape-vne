"""Independent feasibility witnesses for the proposed method's new pruning."""
import itertools
import math
import random
import unittest

import vne
from vne import experiments
from tests.test_core import graph


class TunedRegression(unittest.TestCase):
    def test_cut_pruning_preserves_exhaustively_feasible_mappings(self):
        rng=random.Random(55012)
        feasible_count=0
        for _ in range(45):
            sn=graph([20]*4,[(u,w,rng.randint(3,12),rng.randint(1,4))
                     for u in range(4) for w in range(u+1,4) if rng.random()<.7])
            edges=[vne.VirtualEdge(0,1,rng.randint(2,7)),vne.VirtualEdge(0,2,rng.randint(2,7))]
            request=vne.VirtualNetworkRequest(0,0,10,{0:2,1:2,2:2},edges,max_delay=8,max_hops=3)
            algorithm=vne.ProposedAdaptiveVNE(sn)
            # Enumerate all simple routes independently of the VNE router.
            def paths(source,target,bandwidth):
                answers=[]
                def walk(path):
                    if path[-1]==target:
                        answers.append(path)
                        return
                    if len(path)-1>=request.max_hops:
                        return
                    for nxt in sn.neighbors[path[-1]]:
                        if nxt not in path and sn.bandwidth_residual[vne.canonical_edge(path[-1],nxt)]>=bandwidth:
                            candidate=path+[nxt]
                            if sn.path_delay(candidate)<=request.max_delay:
                                walk(candidate)
                walk([source])
                return answers
            for values in itertools.permutations(range(4),3):
                mapping=dict(enumerate(values))
                options=[paths(mapping[e.u],mapping[e.v],e.bandwidth) for e in edges]
                feasible=False
                for routes in itertools.product(*options):
                    used={edge:0 for edge in sn.edges}
                    for edge,path in zip(edges,routes):
                        for u,w in zip(path,path[1:]):
                            used[vne.canonical_edge(u,w)]+=edge.bandwidth
                    if all(used[e]<=sn.bandwidth_residual[e] for e in used):
                        feasible=True
                        break
                if not feasible:
                    continue
                feasible_count+=1
                for vnode in request.nodes:
                    other={v:p for v,p in mapping.items() if v!=vnode}
                    self.assertTrue(math.isfinite(algorithm._node_score(request,vnode,mapping[vnode],other)))
        self.assertGreater(feasible_count,100)

    def test_request_cache_refreshes_after_substrate_changes(self):
        sn=graph([20]*3,[(0,1,10,1),(1,2,10,1)])
        algorithm=vne.ProposedAdaptiveVNE(sn)
        request=vne.VirtualNetworkRequest(0,0,10,{0:2,1:2},[vne.VirtualEdge(0,1,8)])
        first=algorithm.embed(request)
        self.assertIsNotNone(first)
        algorithm.release_embedding(request,first)
        for edge in sn.bandwidth_residual:
            sn.bandwidth_residual[edge]=1
        self.assertIsNone(algorithm.embed(request))
        self.assertFalse(math.isfinite(algorithm._node_score(request,0,0,{})))

    def test_count_bound_rejects_inadequate_ports(self):
        sn=graph([20]*3,[(0,1,10,1),(0,2,2,1)])
        request=vne.VirtualNetworkRequest(0,0,10,{0:2,1:2,2:2},
                  [vne.VirtualEdge(0,1,6),vne.VirtualEdge(0,2,6)])
        self.assertFalse(math.isfinite(vne.ProposedAdaptiveVNE(sn)._node_score(request,0,0,{})))

    def test_valid_non_greedy_port_packing_remains_allowed(self):
        sn=graph([20]*4,[(0,1,8,1),(0,2,7,1),(1,3,8,1)])
        request=vne.VirtualNetworkRequest(0,0,10,{0:2,1:2,2:2,3:2},
                  [vne.VirtualEdge(0,1,7),vne.VirtualEdge(0,2,5),vne.VirtualEdge(0,3,3)])
        self.assertTrue(math.isfinite(vne.ProposedAdaptiveVNE(sn)._node_score(request,0,0,{})))


if __name__=='__main__':
    unittest.main()
