"""Independent paper-equation, evaluation and search-control regression checks."""
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import vne
from vne import experiments
from tests.test_core import graph
from tests import test_core


class RecheckRegression(unittest.TestCase):
    def test_rankings_match_independent_linear_system(self):
        # Solve (I - .85 P^T)r = .15 p instead of copying the iteration.
        rng=random.Random(89223)
        for _ in range(100):
            n=rng.randint(2,9)
            cpu=np.array([rng.randint(0,20) for _ in range(n)],dtype=float)
            bw=np.zeros((n,n))
            for u in range(n):
                for w in range(u+1,n):
                    bw[u,w]=bw[w,u]=rng.randint(0,20) if rng.random()<.5 else 0
            adjacency={u:[(w,bw[u,w]) for w in range(n) if bw[u,w]>0] for u in range(n)}
            for kind in ('grc','noderank'):
                resource=cpu if kind=='grc' else cpu*bw.sum(axis=1)
                personal=resource if resource.sum()>0 else cpu if cpu.sum()>0 else np.ones(n)
                personal=personal/personal.sum()
                transitions=bw.copy() if kind=='grc' else (bw>0)*(cpu*bw.sum(axis=1))[None,:]
                for u in range(n):
                    transitions[u]=transitions[u]/transitions[u].sum() if transitions[u].sum()>0 else personal
                expected=np.linalg.solve(np.eye(n)-.85*transitions.T,.15*personal)
                actual=vne._resource_walk_rank(list(range(n)),dict(enumerate(cpu)),adjacency,kind)
                np.testing.assert_allclose(list(actual.values()),expected,atol=2e-11,rtol=0)

    def test_rankings_apply_to_virtual_graph_and_scale_invariant(self):
        sn=graph([20,50,30],[(0,1,30,1),(1,2,10,1)])
        request=vne.VirtualNetworkRequest(0,0,10,{0:30,1:20,2:50},[vne.VirtualEdge(0,1,10),vne.VirtualEdge(1,2,30)])
        for cls in (vne.GRCVNE,vne.NodeRankVNE):
            algorithm=cls(sn)
            scores=algorithm._scores(request)
            self.assertEqual(algorithm._virtual_order(request),sorted(request.nodes,key=lambda n:(-scores[n],-request.node_cpu[n],n)))
            old=algorithm._scores()
            scaled=sn.clone()
            scaled.cpu_residual={n:c*3 for n,c in sn.cpu_residual.items()}
            scaled.bandwidth_residual={e:b*5 for e,b in sn.bandwidth_residual.items()}
            np.testing.assert_allclose(list(old.values()),list(cls(scaled)._scores().values()),atol=1e-12)

    def test_all_primary_green_metrics_have_statistics(self):
        frame=test_core.EvaluationRegression.observations()
        for m in ('EnergyPerServedRequestSecond_Wh','MeanEmbeddingTime','P95EmbeddingTime'):
            frame[m]=frame.Energy_Wh
        with tempfile.TemporaryDirectory() as directory:
            summary=vne.write_summary(frame,Path(directory)/'summary.csv')
            result=vne.write_statistics(frame,Path(directory)/'statistics.csv')
        metrics={'EnergyPerServedRequestSecond_Wh','MeanEmbeddingTime','P95EmbeddingTime','ExecutionTime'}
        self.assertTrue(metrics.issubset(set(summary.Metric)))
        self.assertTrue(metrics.issubset(set(result.Metric)))
        self.assertTrue(result[result.Metric.isin(metrics)].preferred_direction.eq('lower').all())

    def test_summary_excludes_undefined_infinite_observations(self):
        frame=test_core.EvaluationRegression.observations()
        frame.loc[(frame.Algorithm=='GRC')&(frame.Seed==0),'Energy_Wh']=math.inf
        with tempfile.TemporaryDirectory() as directory:
            result=vne.write_summary(frame,Path(directory)/'summary.csv')
        rows=result[(result.Algorithm=='GRC')&(result.Metric=='Energy_Wh')]
        self.assertTrue(rows.n.eq(9).all())
        self.assertTrue(np.isfinite(rows['mean']).all())

    def test_rank_controls_share_legacy_engine_and_budgets(self):
        sn=graph([100]*3,[(0,1,100,1),(1,2,100,1),(0,2,100,1)])
        proposal=vne.LegacyAdaptiveVNE(sn)
        request=vne.VirtualNetworkRequest(0,0,10,{0:10,1:10},[vne.VirtualEdge(0,1,10)])
        for cls in (vne.GRCRankedSearchVNE,vne.NodeRankSearchVNE):
            control=cls(sn.clone())
            for attribute in ('search_budget','route_budget','path_expansion_budget','candidate_limit','k_paths'):
                self.assertEqual(getattr(control,attribute),getattr(proposal,attribute))
            self.assertIs(control._backtrack.__func__,proposal._backtrack.__func__)
            self.assertIs(control._constrained_shortest_path.__func__,proposal._constrained_shortest_path.__func__)
            self.assertIsNotNone(control.embed(request))

    def test_algorithm_order_does_not_change_non_time_outcomes(self):
        first=vne.run_simulation(6,duration=150,num_nodes=12,seed=823)
        from vne import algorithms
        with patch.object(algorithms,'DEFAULT_ALGORITHMS',tuple(reversed(vne.DEFAULT_ALGORITHMS))):
            second=vne.run_simulation(6,duration=150,num_nodes=12,seed=823)
        a={r['Algorithm']:r for r in first}
        b={r['Algorithm']:r for r in second}
        for name in a:
            for metric in ('Accepted','Rejected','Energy_Wh','Revenue','Cost','ServedRequestSeconds','RouteExpansions'):
                self.assertEqual(a[name][metric],b[name][metric])
            self.assertIn('AlgorithmScope',a[name])

    def test_baselines_commit_feasible_requests_and_release_exactly(self):
        rng=random.Random(8134)
        accepted=0
        for _ in range(40):
            sn=graph([rng.randint(8,20) for _ in range(5)],[(u,w,rng.randint(5,15),rng.randint(1,4)) for u in range(5) for w in range(u+1,5) if rng.random()<.7])
            request=vne.VirtualNetworkRequest(0,0,10,{0:5,1:6,2:4},[vne.VirtualEdge(0,1,4),vne.VirtualEdge(1,2,3)],max_delay=10,max_hops=4)
            for cls in (vne.ProposedAdaptiveVNE,vne.GRCVNE,vne.NodeRankVNE,vne.GreedyKSPVNE,vne.EnergyAwareVNE):
                algorithm=cls(sn.clone())
                before=algorithm.sn.empty_state()
                embedding=algorithm.embed(request)
                if embedding is not None:
                    accepted+=1
                    vne._validate_active_state(algorithm,{0:(request,embedding)})
                    algorithm.release_embedding(request,embedding)
                self.assertEqual(algorithm.sn.empty_state(),before)
        self.assertGreater(accepted,100)


if __name__=='__main__':
    unittest.main()
