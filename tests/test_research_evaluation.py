"""External input/fairness and current-engine ablation contracts."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import networkx as nx
import pandas as pd
import vne
from scripts.research_evaluation import CURRENT_ABLATIONS, run
from scripts.topology_inputs import load_topology, substrate_from_topology


class ResearchEvaluationTests(unittest.TestCase):
    def test_import_retains_all_components_without_spanning_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'adjacency.gml'
            graph = nx.Graph([(0,1)])
            graph.add_node(2)
            nx.write_gml(graph,path)
            before = path.read_bytes()
            metadata,edges = load_topology(path)
            sn = substrate_from_topology(metadata,edges,3)
            self.assertEqual((metadata['nodes'],metadata['edges'],metadata['components']),(3,1,2))
            self.assertEqual(set(sn.edges),{(0,1)})
            self.assertEqual(sn.neighbors[2],set())
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(metadata['sha256'],hashlib.sha256(before).hexdigest())

    def test_html_redirect_is_rejected_as_graphml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.graphml'
            path.write_text('<html><meta http-equiv="refresh" content="0; url=home.action"></html>')
            with self.assertRaisesRegex(ValueError,'Not GraphML'):
                load_topology(path)

    def test_directed_graph_requires_an_explicit_different_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'directed.graphml'
            nx.write_graphml(nx.DiGraph([(0,1)]),path)
            with self.assertRaisesRegex(ValueError,'Directed'):
                load_topology(path,True)

    def test_multilinks_and_loops_are_never_silently_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'multiple.gml'
            graph = nx.MultiGraph()
            graph.add_edges_from([(0,1),(0,1),(0,0)])
            nx.write_gml(graph,path)
            with self.assertRaisesRegex(ValueError,'explicit --simplify'):
                load_topology(path)
            metadata,edges = load_topology(path,True)
            self.assertEqual(edges,((0,1),))
            self.assertEqual((metadata['removed_self_loops'],metadata['collapsed_parallel_edges']),(1,1))

    def test_external_resources_are_identical_across_methods_and_independent(self):
        metadata,edges = {'nodes':3},((0,1),(1,2))
        a = substrate_from_topology(metadata,edges,51,p_idle=90,p_peak=300)
        b = substrate_from_topology(metadata,edges,51,p_idle=90,p_peak=300)
        self.assertEqual((a.coordinates,a.cpu_capacity,a.edges),(b.coordinates,b.cpu_capacity,b.edges))
        a.cpu_residual[0] -= 10
        self.assertNotEqual(a.cpu_residual,b.cpu_residual)
        self.assertEqual(a.p_idle,90)
        self.assertEqual(vne.experiments._topology_sha256(a),vne.experiments._topology_sha256(b))

    def test_current_ablations_change_exactly_one_recorded_setting(self):
        base = vne.algorithm_parameters(vne.GreenAdaptiveVNE(vne.SubstrateNetwork(num_nodes=5)))
        for name,switch in CURRENT_ABLATIONS.items():
            algorithm = vne.GreenAdaptiveVNE(vne.SubstrateNetwork(num_nodes=5),**switch)
            settings = vne.algorithm_parameters(algorithm)
            difference = {k:v for k,v in settings.items() if base[k] != v}
            self.assertEqual(difference,switch,name)
            self.assertIsInstance(algorithm,vne.GreenAdaptiveVNE)

    def test_external_paired_resume_and_parameter_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tiny.gml'
            nx.write_gml(nx.complete_graph(6),path)
            args = argparse.Namespace(lambdas='6',seed_start=19991,seed_count=2,duration=80.,
                link_prob=.35,lifetime_mean=500.,max_delay=25.,max_hops=8,
                methods='ProposedAdaptive,VirneFFD',current_ablations=True,
                topology=[path],simplify=False,num_nodes=50,output_dir=Path(directory)/'out')
            run(args)
            raw = args.output_dir/'raw.csv'
            before = raw.read_bytes()
            frame = pd.read_csv(raw)
            self.assertEqual(len(frame),20)
            self.assertTrue(frame.groupby('Seed').TraceSHA256.nunique().eq(1).all())
            self.assertTrue(frame.groupby('Seed').TopologySHA256.nunique().eq(1).all())
            run(args)
            self.assertEqual(raw.read_bytes(),before)
            frame.loc[0,'AlgorithmParameters'] = '{}'
            frame.to_csv(raw,index=False)
            with self.assertRaisesRegex(ValueError,'parameters differ'):
                run(args)


if __name__ == '__main__':
    unittest.main()
