"""Regression tests for the maintained simulator. Run: python -B -m unittest discover -s tests -v

These are correctness checks, not evidence of research superiority.
"""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import vne
from vne import experiments


def graph(cpu, links):
    sn = vne.SubstrateNetwork(num_nodes=len(cpu), seed=0)
    sn.cpu_capacity = dict(enumerate(map(float,cpu)))
    sn.cpu_residual = dict(sn.cpu_capacity)
    sn.edges = {vne.canonical_edge(u,w):{"delay":float(delay),"bandwidth":float(bw)}
                for u,w,bw,delay in links}
    sn.neighbors = {n:set() for n in sn.cpu_capacity}
    for u,w in sn.edges:
        sn.neighbors[u].add(w)
        sn.neighbors[w].add(u)
    sn.bandwidth_capacity = {edge:data["bandwidth"] for edge,data in sn.edges.items()}
    sn.bandwidth_residual = dict(sn.bandwidth_capacity)
    return sn


class AlgorithmRegression(unittest.TestCase):
    def test_yen_returns_distinct_four_paths(self):
        sn = graph([100]*6,[(0,1,10,1),(1,2,10,1),(2,5,10,1),(1,5,10,3),
                           (0,3,10,3),(3,5,10,3),(0,4,10,4),(4,5,10,4)])
        paths = vne.BaseVNEAlgorithm(sn).find_shortest_paths(0,5,1,100,5,sn.empty_state(),k=4)
        self.assertEqual(paths,[[0,1,2,5],[0,1,5],[0,3,5],[0,4,5]])

    def test_joint_routing_needs_second_path(self):
        sn = graph([10]*4,[(0,1,1,1),(1,2,1,1),(0,3,1,2),(3,2,1,2)])
        request = vne.VirtualNetworkRequest(0,0,1,{0:1,1:1,2:1},
                    [vne.VirtualEdge(0,1,1),vne.VirtualEdge(1,2,1)],max_hops=2)
        algorithm = vne.BaseVNEAlgorithm(sn)
        state = sn.empty_state()
        self.assertIsNone(algorithm.route_link_set(request,{0:0,1:2,2:1},state,k=1))
        self.assertEqual(state,sn.empty_state())
        paths = algorithm.route_link_set(request,{0:0,1:2,2:1},state,k=3)
        self.assertEqual(paths,{(0,1):[0,3,2],(1,2):[2,1]})

    def test_proposed_recovers_feasible_request(self):
        sn = graph([10,9,8,1,1],[(0,3,2,1),(3,2,2,1),(0,4,2,2),(4,2,2,2),(1,3,2,1)])
        request = vne.VirtualNetworkRequest(0,0,10,{0:10,1:9,2:8},
                    [vne.VirtualEdge(0,2,2),vne.VirtualEdge(1,2,1)],max_delay=4,max_hops=2)
        original = sn.empty_state()
        algorithm = vne.ProposedAdaptiveVNE(sn)
        embedding = algorithm.embed(request)
        self.assertIsNotNone(embedding)
        self.assertEqual(embedding["paths"],{(0,2):[0,4,2],(1,2):[1,3,2]})
        vne._validate_active_state(algorithm,{0:(request,embedding)})
        algorithm.release_embedding(request,embedding)
        self.assertEqual(sn.empty_state(),original)
        with self.assertRaises(ValueError):
            algorithm.release_embedding(request,embedding)

    def test_search_budget_and_orphan_detection(self):
        sn = graph([10]*3,[(0,1,10,1),(1,2,10,1)])
        algorithm = vne.ProposedAdaptiveVNE(sn,search_budget=1)
        request = vne.VirtualNetworkRequest(0,0,10,{0:2,1:2},[vne.VirtualEdge(0,1,2)])
        before = sn.empty_state()
        self.assertIsNone(algorithm.embed(request))
        self.assertEqual(algorithm.last_search_nodes,1)
        self.assertEqual(sn.empty_state(),before)
        sn.cpu_residual[2] -= 1
        with self.assertRaises(AssertionError):
            vne._validate_active_state(algorithm,{})

    def test_invalid_commit_and_nan_state(self):
        sn = graph([10]*2,[(0,1,10,1)])
        algorithm = vne.BaseVNEAlgorithm(sn)
        request = vne.VirtualNetworkRequest(0,0,10,{0:2,1:2},[vne.VirtualEdge(0,1,2)])
        self.assertIsNone(algorithm.commit_embedding(request,sn.empty_state(),{0:0,1:1},{(0,1):[0,1]}))
        state = sn.empty_state()
        state["cpu"][0] = math.nan
        self.assertFalse(sn.state_is_valid(state))

    def test_noderank_converges_on_bipartite_star(self):
        sn = graph([100]*4,[(0,i,50,1) for i in range(1,4)])
        ranks = vne.NodeRankVNE(sn)._scores()
        np.testing.assert_allclose([ranks[i] for i in range(4)],[.5,1/6,1/6,1/6],atol=1e-10)
        self.assertAlmostEqual(sum(vne.GRCVNE(sn)._scores().values()),1)
        self.assertGreater(vne.GRCVNE(sn)._scores()[0],vne.GRCVNE(sn)._scores()[1])

    def test_ea_marginal_power(self):
        sn = graph([70,130],[(0,1,100,1)])
        sn.cpu_residual = {0:35.,1:26.}
        request = vne.VirtualNetworkRequest(0,0,10,{0:10},[])
        result = vne.EnergyAwareVNE(sn).embed(request)
        self.assertEqual(result["mapping"],{0:1})
        self.assertEqual(result["boot_energy_joules"],0)

    def test_pso_evaluation_is_side_effect_free(self):
        sn = graph([100]*3,[(0,1,100,1),(1,2,100,1),(0,2,100,3)])
        algorithm = vne.PSOVNE(sn,particles=2,iterations=1)
        request = vne.VirtualNetworkRequest(0,0,10,{0:10,1:10},[vne.VirtualEdge(0,1,20)])
        before = sn.empty_state()
        fitness,mapping,paths = algorithm._evaluate(request,[0,2])
        expected = request.total_cpu+sum(e.bandwidth*(len(paths[(e.u,e.v)])-1) for e in request.edges)
        self.assertEqual(fitness,expected)
        self.assertEqual(sn.empty_state(),before)


class EvaluationRegression(unittest.TestCase):
    @staticmethod
    def observations():
        rows=[]
        for lam,value in ((2,.8),(4,.2)):
            for seed in range(10):
                for name in vne.DEFAULT_ALGORITHMS+("PSO",):
                    rows.append({"Lambda":lam,"Seed":seed,"Algorithm":name,
                        **{m:value if name=="ProposedAdaptive" else .5 for m in
                           ("AcceptanceRatio","R_C","Energy_Wh","NodeUtil","LinkUtil","MeanHops","ExecutionTime")}})
        return pd.DataFrame(rows)

    def test_per_load_statistics_and_pso(self):
        with tempfile.TemporaryDirectory() as directory:
            results=vne.write_statistics(self.observations(),Path(directory)/"stats.csv")
            rows=results[(results.Baseline=="GRC")&(results.Metric=="AcceptanceRatio")]
            np.testing.assert_allclose(rows.p_value,[.001953125,.001953125])
            np.testing.assert_allclose(rows.matched_pairs_rank_biserial,[1,-1])
            self.assertIn("PSO",set(results.Baseline))
            self.assertTrue(results.status.eq("ok").all())
            self.assertTrue(results.q_value.ge(results.p_value).all())
            summary=vne.write_summary(self.observations(),Path(directory)/"summary.csv")
            self.assertEqual(set(summary.Lambda),{2,4})
            with self.assertRaises(ValueError):
                vne.write_statistics(pd.concat([self.observations(),self.observations().iloc[:1]]),Path(directory)/"bad.csv")

    def test_rank_biserial_not_sign_count(self):
        frame=self.observations()
        frame=frame[(frame.Lambda==2)&(frame.Seed<4)].copy()
        differences=[.1,.2,.3,-.9]
        for row in frame.itertuples():
            if row.Algorithm=="ProposedAdaptive":
                frame.loc[row.Index,"AcceptanceRatio"]=.5+differences[row.Seed]
        with tempfile.TemporaryDirectory() as directory:
            results=vne.write_statistics(frame,Path(directory)/"stats.csv")
            row=results[(results.Baseline=="GRC")&(results.Metric=="AcceptanceRatio")].iloc[0]
            self.assertAlmostEqual(row.matched_pairs_rank_biserial,.2)

    def test_horizon_integration_and_physical_boot(self):
        original_class=vne.SubstrateNetwork
        def fixture(**kwargs):
            return original_class(num_nodes=2,cpu_range=(100,100),bw_range=(100,100),seed=1)
        trace=[vne.VirtualNetworkRequest(0,10,30,{0:10.,1:10.},[vne.VirtualEdge(0,1,10.)]),
               vne.VirtualNetworkRequest(1,80,120,{0:10.,1:10.},[vne.VirtualEdge(0,1,10.)])]
        with patch.object(experiments,"SubstrateNetwork",fixture),patch.object(experiments,"generate_trace",return_value=trace):
            records=vne.run_simulation(2,100,2,include_pso=True,include_ablations=True,sample_interval=10)
        self.assertEqual(len(records),len(vne._algorithm_names(True, True)))
        for row in records:
            self.assertEqual(row["Accepted"],2)
            self.assertAlmostEqual(row["Energy_Wh"],(345*40+200)/3600)
            self.assertAlmostEqual(row["NodeUtil"],.04)
            self.assertAlmostEqual(row["LinkUtil"],.04)
            self.assertEqual(row["ServedRevenue"],30*40)
            self.assertEqual(row["ServedRequestSeconds"],40)
            self.assertEqual(row["BootEnergy_J"],200)
            self.assertGreaterEqual(row["SimulationWallTime"],row["ExecutionTime"])

    def test_transit_power_and_boot_reuse(self):
        sn=graph([100]*3,[(0,1,100,1),(1,2,100,1)])
        algorithm=vne.BaseVNEAlgorithm(sn)
        for rid,expected_boot in ((0,150),(1,0)):
            request=vne.VirtualNetworkRequest(rid,0,10,{0:10.,1:10.},[vne.VirtualEdge(0,1,10.)])
            state=sn.empty_state()
            algorithm.reserve_cpu(state,0,10)
            algorithm.reserve_cpu(state,2,10)
            paths=algorithm.route_link_set(request,{0:0,1:2},state)
            embedding=algorithm.commit_embedding(request,state,{0:0,1:2},paths)
            self.assertEqual(embedding["boot_energy_joules"],expected_boot)
            self.assertEqual(sn.active_node_count(),3)
            if rid==0:
                self.assertEqual(sn.power_watts(),500)

    def test_input_validation(self):
        for kwargs in ({"duration":0},{"duration":math.nan},{"sample_interval":0},{"lam":math.inf}):
            args={"lam":2,"duration":10,**kwargs}
            with self.assertRaises(ValueError):
                vne.run_simulation(**args)

    def test_incompatible_checkpoint_is_rejected_without_relabeling(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            checkpoint=path/"full_evaluation.csv"
            self.observations().to_csv(checkpoint,index=False)
            before=checkpoint.read_bytes()
            with self.assertRaisesRegex(ValueError,"lacks experiment"):
                vne.run_full_evaluation(directory,lambdas=(2,),seeds=(0,),duration=20,num_nodes=12,workers=1)
            self.assertEqual(checkpoint.read_bytes(),before)
            metadata=path/"full_evaluation.config.json"
            metadata.write_text(json.dumps({"fingerprint":"old-config"}))
            with self.assertRaisesRegex(ValueError,"differs"):
                vne.run_full_evaluation(directory,lambdas=(2,),seeds=(0,),duration=20,num_nodes=12,workers=1)
            self.assertEqual(metadata.read_text(),json.dumps({"fingerprint":"old-config"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
