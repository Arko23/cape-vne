"""Reference policy contracts, independent of the proposal's router."""
import random
import copy
import math
import pickle
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import networkx as nx
import numpy as np

import vne
from tests.test_core import graph
from tests import virne_oracle as native
from tests.helpers import regression_fixture, run_case, expected_outcomes


class ReferenceBaselineContracts(unittest.TestCase):
    def test_registry_metadata_and_analysis_select_reference_cohort(self):
        from scripts.analyze_full_results import PRIMARY, REFERENCE_PRIMARY, primary_methods
        import pandas as pd
        names = vne._algorithm_names(True, True, True)
        self.assertEqual(len(names), 32)
        self.assertEqual(names[:27], vne._algorithm_names(True, True))
        spec = vne._experiment_spec(80, 14, 2, True, True, include_reference_baselines=True)
        self.assertTrue(spec['include_reference_baselines'])
        self.assertEqual(spec['algorithms'], names)
        pso = spec['algorithm_parameters']['VirnePSO']
        self.assertEqual((pso['particles'], pso['iterations'], pso['k_paths']), (8, 12, 10))
        self.assertEqual(pso['reference_source_sha256'], native.ARCHIVE_SHA256)
        self.assertEqual(primary_methods(pd.DataFrame({'Algorithm': names})), REFERENCE_PRIMARY)
        self.assertEqual(primary_methods(pd.DataFrame({'Algorithm': names[:27]})), PRIMARY)

    def test_comparator_outcomes_and_proposal_service_match_the_frozen_before_source(self):
        fixture = regression_fixture('policy_regression.json')
        self.assertEqual(fixture['algorithms'], vne._algorithm_names(True, True))
        fields = [field for field in fixture['fields'] if field != 'AlgorithmParameters']
        for item in fixture['cases']:
            expected = expected_outcomes(item)
            actual = run_case(item['case'], vne._algorithm_names(True, True, True),
                              include_reference_baselines=True).reindex(expected.index)
            controls = expected.index.difference(['ProposedAdaptive'])
            np.testing.assert_allclose(actual.loc[controls, fields], expected.loc[controls, fields], rtol=0, atol=0)
            self.assertTrue(actual.loc[controls, 'AlgorithmParameters'].equals(expected.loc[controls, 'AlgorithmParameters']))
            # The proposal deliberately performs less search. Freeze physical
            # outcomes, without requiring its old work counters or new flags.
            service = ['Accepted', 'Rejected', 'Revenue', 'Cost', 'ServedRevenue', 'ServedCost',
                       'ServedRequestSeconds', 'ServedCPUUnitSeconds', 'ServedBandwidthUnitSeconds',
                       'Energy_Wh', 'BootEnergy_J', 'MeanHops', 'NodeUtil', 'LinkUtil',
                       'MeanActiveNodes', 'MeanActiveLinks']
            np.testing.assert_allclose(actual.loc['ProposedAdaptive', service].astype(float),
                                       expected.loc['ProposedAdaptive', service].astype(float), rtol=0, atol=0)

    def test_ffd_uses_absolute_cpu_instead_of_legacy_cpu_fraction(self):
        from vne.reference_baselines import VirneFFDVNE
        substrate = graph([100, 50, 50, 50],
                          [(i, j, 100, 1) for i in range(4) for j in range(i + 1, 4)])
        substrate.cpu_residual[0] = 60
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 5, 1: 5},
                                           [vne.VirtualEdge(0, 1, 5)])
        previous = vne.GreedyKSPVNE(substrate.clone()).embed(request)
        reference = VirneFFDVNE(substrate.clone()).embed(request)
        self.assertEqual(previous['mapping'], {0: 1, 1: 2})
        self.assertEqual(reference['mapping'], {0: 0, 1: 1})

    def test_reference_defaults_and_distinct_identities(self):
        from vne.reference_baselines import REFERENCE_CLASSES, VirnePSOVNE
        substrate = graph([100] * 4, [(0, 1, 100, 1), (1, 2, 100, 1), (2, 3, 100, 1)])
        for name, cls in REFERENCE_CLASSES.items():
            algorithm = cls(substrate.clone(), random.Random(7))
            self.assertEqual(algorithm.name, name)
            self.assertEqual(algorithm.k_paths, 10)
            self.assertIsNone(algorithm.path_expansion_budget)
            self.assertIsNone(algorithm.route_budget)
        pso = VirnePSOVNE(substrate)
        self.assertEqual((pso.particles, pso.iterations), (8, 12))
        self.assertEqual((pso.p_i, pso.p_c, pso.p_s), (.1, .2, .7))

    def test_reference_routing_has_no_shared_joint_repair(self):
        from vne.reference_baselines import VirneFFDVNE
        substrate = graph([100, 90, 80, 70],
                          [(0, 1, 100, 1), (1, 2, 100, 1), (2, 3, 100, 1)])
        algorithm = VirneFFDVNE(substrate)
        algorithm.route_link_set = lambda *a, **kw: self.fail('Shared proposal router used')
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 5, 1: 5},
                                           [vne.VirtualEdge(0, 1, 5)])
        self.assertIsNotNone(algorithm.embed(request))

    def test_rank_values_and_orders_match_unchanged_native_classes(self):
        from vne.reference_baselines import reference_rank
        for seed in range(20):
            rng = random.Random(seed)
            network = native.Network(nx.cycle_graph(5 + seed % 5))
            for node in network:
                network.nodes[node]['cpu'] = rng.uniform(1, 100)
            for link in network.edges:
                network.edges[link]['bw'] = rng.uniform(1, 100)
            for method, cls_name in [('ffd', 'FFDNodeRank'), ('grc', 'GRCNodeRank'), ('rw', 'RWNodeRank')]:
                with self.subTest(seed=seed, method=method):
                    expected = native.NAMESPACE[cls_name]().rank(network)
                    actual = reference_rank(network, method)
                    self.assertEqual(list(actual), list(expected))
                    np.testing.assert_allclose(list(actual.values()), list(expected.values()), rtol=1e-12, atol=1e-12)

    def test_mapping_and_routing_match_native_heuristic_decisions(self):
        from vne.reference_baselines import REFERENCE_CLASSES
        for seed in range(30):
            rng = random.Random(seed + 4901)
            size = 7 + seed % 3
            links = [(node, (node + 1) % size, rng.randrange(3, 20), 1) for node in range(size)]
            links += [(0, node, rng.randrange(3, 20), 1) for node in range(2, size - 1)]
            sn = graph([rng.randrange(8, 40) for _ in range(size)], links)
            for node in sn.cpu_residual:
                sn.cpu_residual[node] *= rng.uniform(.2, 1)
            # Reversed edges expose native Graph.edges source/target tie-breaking.
            request = vne.VirtualNetworkRequest(seed, 0, 10,
                {node: rng.randrange(2, 16) for node in range(4)},
                [vne.VirtualEdge(2, 0, rng.randrange(2, 12)), vne.VirtualEdge(1, 3, rng.randrange(2, 12)),
                 vne.VirtualEdge(0, 1, rng.randrange(2, 12)), vne.VirtualEdge(3, 2, rng.randrange(2, 12))],
                max_hops=100, max_delay=10000)
            for name in ('VirneGRC', 'VirneRWMaxMatch', 'VirneFFD', 'VirneRWBFS'):
                with self.subTest(seed=seed, name=name):
                    expected = native.heuristic(sn, request, name)
                    actual_sn = sn.clone()
                    original = actual_sn.empty_state()
                    algorithm = REFERENCE_CLASSES[name](actual_sn)
                    actual = algorithm.embed(request)
                    self.assertEqual(actual is not None, expected['result'])
                    if actual is None:
                        self.assertEqual(actual_sn.empty_state(), original)
                        continue
                    self.assertEqual(actual['mapping'], expected.node_slots)
                    for edge in request.edges:
                        key = vne.canonical_edge(edge.u, edge.v)
                        expected_key = next(e for e in expected.link_paths if vne.canonical_edge(*e) == key)
                        pairs = expected.link_paths[expected_key]
                        path = [pairs[0][0]] + [pair[1] for pair in pairs]
                        if expected_key[0] != edge.u:
                            path.reverse()
                        self.assertEqual(actual['paths'][(edge.u, edge.v)], path)
                    algorithm.release_embedding(request, actual)
                    self.assertEqual(actual_sn.empty_state(), original)

    def test_native_process_loop_discards_child_updates(self):
        engine = native.NativeMetaRunProbe()
        result = native.NAMESPACE['ParticleSwarmOptimizationSolver'].meta_run(engine, None, None)
        self.assertTrue(engine.child_changed.is_set())
        self.assertEqual(result, 0)
        self.assertEqual(engine.particles[0].position, 0)

    def test_native_pso_lambdas_are_not_windows_spawn_picklable(self):
        cls = native.NAMESPACE['ParticleSwarmOptimizationSolver']
        engine = cls(native.Controller(), None, native.Counter(), None, None)
        with self.assertRaises((AttributeError, pickle.PicklingError)):
            pickle.dumps(engine.add)

    def test_pso_matches_native_initialization_and_update_kernel(self):
        from vne.reference_baselines import VirnePSOVNE

        class NumpyStreams:
            def __init__(self, stream):
                self.random = stream

            def __getattr__(self, key):
                return getattr(np, key)

        class TraceController(native.Controller):
            def deploy_with_node_slots(self, virtual, physical, slots, solution, **kwargs):
                trace.append(dict(slots))
                return super().deploy_with_node_slots(virtual, physical, slots, solution, **kwargs)

        for seed in range(6):
            with self.subTest(seed=seed):
                sn = graph([100, 45, 90, 70, 60, 80, 55],
                           [(node, (node + 1) % 7, 10 + node * 2, 1) for node in range(7)] + [(0, 3, 30, 1)])
                request = vne.VirtualNetworkRequest(1, 0, 10, {0: 12, 1: 14, 2: 8},
                    [vne.VirtualEdge(0, 1, 8), vne.VirtualEdge(1, 2, 5), vne.VirtualEdge(2, 0, 6)],
                    max_hops=100, max_delay=10000)
                port = VirnePSOVNE(sn.clone(), random.Random(seed))
                source_random = random.Random()
                source_random.setstate(port.rng.getstate())
                source_numpy = np.random.RandomState()
                source_numpy.set_state(port.np_rng.get_state())
                virtual, physical = native.networks(sn, request)
                trace = []
                source = native.NAMESPACE['ParticleSwarmOptimizationSolver'](
                    TraceController(), None, native.Counter(), None,
                    SimpleNamespace(solver=SimpleNamespace(node_ranking_method='order')))
                source.best_individual = None
                source.candidates_dict = {v: list(physical) for v in virtual}
                with patch.dict(native.NAMESPACE, random=source_random, np=NumpyStreams(source_numpy)):
                    native.NAMESPACE['rank_nodes'](virtual, 'order')
                    native.NAMESPACE['rank_nodes'](physical, 'order')
                    source.initialize(virtual, physical)
                    for _ in range(source.max_iteration):
                        # Synchronous parent-visible correction: all particles use
                        # the same global snapshot, as the process-launch loop does.
                        leader = source.best_individual
                        source.best_individual = copy.deepcopy(leader)
                        for particle in source.particles:
                            source.evolve(particle)
                        source.best_individual = leader
                        source.update_best_individual(source.particles)
                actual_trace = []
                deploy = port._deploy
                def recording_deploy(req, slots, net):
                    actual_trace.append(dict(slots))
                    return deploy(req, slots, net)
                port._deploy = recording_deploy
                actual = port.embed(request)
                self.assertEqual(actual_trace, trace)
                best = source.best_individual
                self.assertEqual(actual is not None, best.best_solution['result'])
                if actual:
                    self.assertEqual(actual['mapping'], best.best_solution.node_slots)
                self.assertEqual(port.reference_pso_updates, 8 * 12)
                self.assertEqual(len(port.history), 13)
                self.assertTrue(all(b <= a for a, b in zip(port.history, port.history[1:])))
                self.assertAlmostEqual(port.history[-1], best.best_fitness)

    def test_reference_hard_qos_and_failed_request_rollback(self):
        from vne.reference_baselines import REFERENCE_CLASSES, reference_rank, resource_graph
        sn = graph([100, 90, 80, 70], [(0, 1, 2, 20), (1, 2, 2, 20), (2, 3, 2, 20)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 5, 1: 5},
                                           [vne.VirtualEdge(0, 1, 1)], max_delay=1, max_hops=1)
        for name, cls in REFERENCE_CLASSES.items():
            with self.subTest(name=name):
                substrate = sn.clone()
                before = substrate.empty_state()
                self.assertIsNone(cls(substrate, random.Random(17)).embed(request))
                self.assertEqual(substrate.empty_state(), before)
        for node in sn.cpu_residual:
            sn.cpu_residual[node] = 0
        for link in sn.bandwidth_residual:
            sn.bandwidth_residual[link] = 0
        for method in ('grc', 'rw'):
            values = reference_rank(resource_graph(sn), method)
            self.assertTrue(all(math.isfinite(value) for value in values.values()))


if __name__ == '__main__':
    unittest.main()
