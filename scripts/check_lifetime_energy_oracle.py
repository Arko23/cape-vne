"""Fixed-admission, event-integrated oracle for known-duration prototypes."""
import argparse
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import vne
from scripts.audit_energy import allocations, build_graph
from scripts.check_lifetime_energy import LifetimeEnergyVNE


def commit(algorithm, request, mapping, paths):
    state = algorithm.sn.empty_state()
    for node, demand in request.node_cpu.items():
        assert algorithm.reserve_cpu(state,mapping[node],demand)
    for edge in request.edges:
        assert algorithm.reserve_path(state,paths[(edge.u,edge.v)],edge.bandwidth)
    result = algorithm.commit_embedding(request,state,mapping,paths)
    assert result is not None
    return result


def integrated(sn, background, request=None, path=None):
    """Independent event replay from geometric reservations, with/without new VNR.

    Uses no lease ends, prototype scores or residual-power integration shortcut.
    CPU dynamic energy, background boot and endpoint power cancel across choices.
    """
    sn = sn.clone()
    helper = vne.BaseVNEAlgorithm(sn)
    active = {}
    boot = 0.
    for old,mapping,paths in background:
        result = commit(helper,old,mapping,paths)
        boot += result['boot_energy_joules']
        active[old.request_id] = old,result
    horizon = request.departure if request else 100.
    if request:
        result = commit(helper,request,{0:path[0],1:path[-1]},{(0,1):path})
        boot += result['boot_energy_joules']
        active[request.request_id] = request,result
    now, energy = 0., boot
    events = sorted({min(r.departure,horizon) for r,_ in active.values()} | {horizon})
    for time in events:
        watts = allocations(sn,active)[0].sum()
        energy += float(watts)*(time-now)
        now = time
        for rid,(old,result) in list(active.items()):
            if old.departure <= time:
                helper.release_embedding(old,result)
                del active[rid]
    return energy


def lifetime_witness(cls):
    sn = build_graph([100]*5,[(0,1,100,1),(1,4,100,1),(0,2,100,2),(2,4,100,2)])
    algorithm = cls(sn)
    background = []
    for node,end in ((0,200),(1,1),(2,200),(4,200)):
        old = vne.VirtualNetworkRequest(node,0,end,{0:10},[])
        commit(algorithm,old,{0:node},{})
        background.append((old,{0:node},{}))
    request = vne.VirtualNetworkRequest(10,0,100,{0:10,1:10},[vne.VirtualEdge(0,1,10)],10,2)
    state = sn.empty_state()
    assert algorithm.reserve_cpu(state,0,10) and algorithm.reserve_cpu(state,4,10)
    if isinstance(algorithm,LifetimeEnergyVNE):
        with patch.object(algorithm,'_lease_request',request):
            path = algorithm.find_shortest_paths(0,4,10,10,2,state,k=1)[0]
    else:
        path = algorithm.find_shortest_paths(0,4,10,10,2,state,k=1)[0]
    empty = build_graph([100]*5,[(0,1,100,1),(1,4,100,1),(0,2,100,2),(2,4,100,2)])
    baseline = integrated(empty,background)
    actual = integrated(empty,background,request,path)-baseline
    best = integrated(empty,background,request,[0,2,4])-baseline
    return dict(policy=cls.__name__,path=path,incremental_J=actual,best_J=best)


class LeaseOracle(unittest.TestCase):
    def test_fixed_admission_equal_hop_lifetime_witness(self):
        old,new = lifetime_witness(vne.GreenAdaptiveVNE),lifetime_witness(LifetimeEnergyVNE)
        self.assertEqual(old['path'],[0,1,4])
        self.assertEqual(new['path'],[0,2,4])
        self.assertLess(new['incremental_J'],old['incremental_J'])
        self.assertEqual(new['incremental_J'],new['best_J'])

    def test_cached_lease_ends_against_active_geometry_and_release(self):
        rng = random.Random(239110)
        sn = build_graph([1000]*6,[(u,u+1,1000,1) for u in range(5)])
        algorithm,active = LifetimeEnergyVNE(sn),{}
        for rid in range(30):
            source,target = sorted(rng.sample(range(6),2))
            request = vne.VirtualNetworkRequest(rid,0,rng.randint(1,200),
                {0:2,1:3},[vne.VirtualEdge(0,1,4)],10,5)
            result = commit(algorithm,request,{0:source,1:target},{(0,1):list(range(source,target+1))})
            active[rid] = request,result
        order = list(active)
        rng.shuffle(order)
        for rid in order:
            node_end,edge_end = dict.fromkeys(sn.cpu_capacity,-float('inf')),dict.fromkeys(sn.edges,-float('inf'))
            for request,result in active.values():
                for node in result['mapping'].values():
                    node_end[node] = max(node_end[node],request.departure)
                for path in result['paths'].values():
                    for node in path:
                        node_end[node] = max(node_end[node],request.departure)
                    for u,w in zip(path,path[1:]):
                        edge = tuple(sorted((u,w)))
                        edge_end[edge] = max(edge_end[edge],request.departure)
            self.assertEqual(algorithm._node_end,node_end)
            self.assertEqual(algorithm._link_end,edge_end)
            allocations(sn,active)
            request,result = active.pop(rid)
            algorithm.release_embedding(request,result)
        self.assertFalse(algorithm._leases)
        self.assertTrue(all(end == -float('inf') for end in algorithm._node_end.values()))
        allocations(sn,active)

    def test_failed_commit_and_double_release_do_not_change_leases(self):
        sn = build_graph([100]*3,[(0,1,100,1),(1,2,100,1)])
        algorithm = LifetimeEnergyVNE(sn)
        request = vne.VirtualNetworkRequest(0,0,10,{0:10},[])
        self.assertIsNone(algorithm.commit_embedding(request,sn.empty_state(),{0:0},{}))
        self.assertFalse(algorithm._leases)
        result = commit(algorithm,request,{0:0},{})
        algorithm.release_embedding(request,result)
        with self.assertRaises(ValueError):
            algorithm.release_embedding(request,result)
        self.assertFalse(algorithm._leases)

    def test_route_key_matches_independent_energy_with_tentative_reuse(self):
        sn = build_graph([100]*5,[(0,1,100,1),(1,4,100,1),(0,2,100,2),(2,4,100,2)])
        algorithm,background = LifetimeEnergyVNE(sn),[]
        for node,end in ((0,200),(1,10),(2,80),(4,200)):
            request = vne.VirtualNetworkRequest(node,0,end,{0:10},[])
            commit(algorithm,request,{0:node},{})
            background.append((request,{0:node},{}))
        request = vne.VirtualNetworkRequest(10,0,100,{0:10,1:10},[vne.VirtualEdge(0,1,10)],10,2)
        state = sn.empty_state()
        algorithm.reserve_cpu(state,0,10)
        algorithm.reserve_cpu(state,4,10)
        empty = build_graph([100]*5,[(0,1,100,1),(1,4,100,1),(0,2,100,2),(2,4,100,2)])
        with patch.object(algorithm,'_lease_request',request):
            context = algorithm._two_hop_context(state)
            keys = [algorithm._two_hop_key(0,n,4,10,2*n,state,context)[0] for n in (1,2)]
            actual = [integrated(empty,background,request,[0,n,4]) for n in (1,2)]
            self.assertAlmostEqual(keys[0]-keys[1],actual[0]-actual[1])
            algorithm.reserve_path(state,[0,1,4],10)
            context = algorithm._two_hop_context(state)
            self.assertEqual(algorithm._two_hop_key(0,1,4,10,2,state,context)[0],0.)

    def test_unsafe_tiny_demands_fall_back(self):
        sn = build_graph([100]*5,[(0,1,100,1),(1,4,100,1),(0,2,100,2),(2,4,100,2)])
        algorithm = LifetimeEnergyVNE(sn)
        request = vne.VirtualNetworkRequest(1,0,100,{0:vne.EPS/2},[])
        result = commit(algorithm,request,{0:0},{})
        self.assertEqual(algorithm._unsafe_leases,1)
        with patch.object(vne.GreenAdaptiveVNE,'embed',return_value=None):
            self.assertIsNone(algorithm.embed(request))
            self.assertIsNone(algorithm._lease_request)
        algorithm.release_embedding(request,result)
        self.assertEqual(algorithm._unsafe_leases,0)

    def test_host_batch_and_scalar_scores_agree(self):
        sn = build_graph([100]*20,[(u,w,100,1) for u in range(20) for w in range(u+1,20)])
        algorithm = LifetimeEnergyVNE(sn,lifetime_routes=False,lifetime_hosts=True)
        for node in range(10):
            old = vne.VirtualNetworkRequest(node,0,10+node*20,{0:10},[])
            commit(algorithm,old,{0:node},{})
        request = vne.VirtualNetworkRequest(30,0,100,{0:10},[])
        state = sn.empty_state()
        with patch.object(algorithm,'_lease_request',request), \
             patch.object(algorithm,'_green_bw',algorithm._edge_residual(state)):
            context = algorithm._score_context(request,0,{},state)
            batched = algorithm._host_scores(request,0,{},state,context)
            with patch.object(algorithm,'batch_scores',False):
                for node in range(20):
                    self.assertAlmostEqual(batched[node],algorithm._node_score(request,0,node,{},state,context))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assert-maintained',action='store_true')
    args = parser.parse_args()
    if args.assert_maintained:
        result = lifetime_witness(vne.GreenAdaptiveVNE)
        print(json.dumps(result),flush=True)
        assert result['incremental_J'] <= result['best_J'], 'Maintained power tie misses lower equal-hop lifetime energy'
    else:
        print(json.dumps([lifetime_witness(vne.GreenAdaptiveVNE),lifetime_witness(LifetimeEnergyVNE)]),flush=True)
        unittest.main(argv=[sys.argv[0]],verbosity=2)
