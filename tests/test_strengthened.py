"""Independent oracles and regression witnesses for the maintained implementation."""
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import vne
from vne import experiments
from vne.pruning import first_hop_packing_possible
from scripts.verify_benchmarks import case_spec, validate_cached_case
from tests.test_core import graph


class PackingOracleTests(unittest.TestCase):
    @staticmethod
    def brute_force(demands, capacities, domains):
        for assignment in itertools.product(*domains):
            used = [0.0] * len(capacities)
            for demand, port in zip(demands, assignment):
                used[port] += demand
            if all(usage <= capacity + vne.EPS for usage, capacity in zip(used, capacities)):
                return True
        return False

    def test_subset_dp_matches_independent_assignment_enumeration(self):
        rng = random.Random(22031)
        for _ in range(350):
            demands = [rng.randint(1, 8) for _ in range(rng.randint(0, 6))]
            capacities = [rng.randint(0, 15) for _ in range(rng.randint(1, 4))]
            domains = [[p for p in range(len(capacities)) if rng.random() < .7] for _ in demands]
            self.assertEqual(first_hop_packing_possible(demands, capacities, domains),
                             self.brute_force(demands, capacities, domains))

    def test_stronger_than_sum_and_threshold_count_bounds(self):
        demands, ports = [60, 60, 40], [80, 80]
        self.assertLessEqual(sum(demands), sum(ports))
        for threshold in demands:
            self.assertLessEqual(sum(d >= threshold for d in demands),
                                 sum(capacity // threshold for capacity in ports))
        self.assertFalse(first_hop_packing_possible(demands, ports))
        self.assertTrue(first_hop_packing_possible([7, 5, 3], [8, 7]))

    def test_high_degree_is_unknown_never_infeasible(self):
        self.assertIsNone(first_hop_packing_possible([2] * 11, [1]))
        sn = graph([20] * 12, [(0, n, 2, 1) for n in range(1, 12)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {n: 1 for n in range(12)},
                                           [vne.VirtualEdge(0, n, 2) for n in range(1, 12)])
        algorithm = vne.ProposedAdaptiveVNE(sn)
        self.assertTrue(algorithm._first_hop_feasible(request, 0, 0, {}, sn.empty_state()))
        self.assertEqual(algorithm.packing_bypasses, 1)

    def test_floating_threshold_regression_has_feasible_route_witness(self):
        demands = [1, 1 - .9 * vne.EPS, 1 - .9 * vne.EPS]
        sn = graph([20] * 4, [(0, 1, sum(demands), 1), (1, 2, 2, 1), (1, 3, 2, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {n: 1 for n in range(4)},
                    [vne.VirtualEdge(0, n + 1, demand) for n, demand in enumerate(demands)])
        algorithm = vne.ProposedAdaptiveVNE(sn)
        self.assertTrue(math.isfinite(algorithm._node_score(request, 0, 0, {1: 1, 2: 2, 3: 3})))
        state = sn.empty_state()
        for n in range(4):
            algorithm.reserve_cpu(state, n, 1)
        routes = {(0, 1): [0, 1], (0, 2): [0, 1, 2], (0, 3): [0, 1, 3]}
        for edge in request.edges:
            self.assertTrue(algorithm.reserve_path(state, routes[(edge.u, edge.v)], edge.bandwidth))
        embedding = algorithm.commit_embedding(request, state, {n: n for n in range(4)}, routes)
        self.assertIsNotNone(embedding)
        vne._validate_active_state(algorithm, {0: (request, embedding)})

    def test_mapped_destination_domains_enforce_optimistic_qos(self):
        sn = graph([20] * 4, [(0, 1, 5, 1), (0, 2, 5, 1), (1, 3, 5, 10), (2, 3, 5, 1)])
        algorithm = vne.ProposedAdaptiveVNE(sn)
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1, 1: 1, 2: 1},
                   [vne.VirtualEdge(0, 1, 4), vne.VirtualEdge(0, 2, 4)], max_delay=3, max_hops=2)
        # Each link individually fits, but only the second port can reach node3
        # under delay3; two unsplittable demands cannot share that capacity5.
        self.assertFalse(algorithm._first_hop_feasible(request, 0, 0, {1: 3, 2: 2}, sn.empty_state()))
        algorithm._request_profiles = {}
        self.assertTrue(algorithm._first_hop_feasible(request, 0, 0, {}, sn.empty_state()))


class ControlTests(unittest.TestCase):
    def test_registry_scopes_flags_and_actual_parameters(self):
        sn = graph([100] * 5, [(u, w, 100, 1) for u in range(5) for w in range(u + 1, 5)])
        names = vne._algorithm_names(True, True)
        self.assertEqual(len(names), 27)
        self.assertEqual(len(set(names)), 27)
        spec = vne._experiment_spec(100, 5, 1, True, True)
        for name in names:
            algorithm = vne.algorithm_factory(name, sn.clone(), 17, True)
            self.assertEqual(algorithm.name, name)
            self.assertEqual(vne.algorithm_parameters(algorithm), spec['algorithm_parameters'][name])
            self.assertIn(name, vne.ALGORITHM_SCOPE)
        for name, attribute in [('NoExactPacking', 'exact_packing'), ('NoCutPruning', 'cut_pruning'),
                                ('FixedEnergyWeight', 'adaptive_energy'),
                                ('AlwaysJointRouting', 'incremental_routing'), ('NoJointRepair', 'joint_repair')]:
            self.assertFalse(getattr(vne.algorithm_factory(name, sn, 1), attribute))
        with self.assertRaises(ValueError):
            vne.algorithm_factory('PSO', sn, 1)
        with self.assertRaises(ValueError):
            vne.algorithm_factory('Unknown', sn, 1)

    def test_score_only_preserves_order_without_computing_paper_order(self):
        sn = graph([100] * 3, [(0, 1, 100, 1), (1, 2, 100, 1), (0, 2, 100, 1)])
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 10, 1: 30, 2: 20},
                    [vne.VirtualEdge(0, 1, 10), vne.VirtualEdge(1, 2, 20)])
        expected = vne.ProposedAdaptiveVNE(sn).node_order(request)
        for cls, ranker in [(vne.GRCScoreOnlyVNE, vne.GRCVNE), (vne.NodeRankScoreOnlyVNE, vne.NodeRankVNE)]:
            control = cls(sn.clone())
            with patch.object(ranker, '_virtual_order', side_effect=AssertionError('Unneeded ranking')):
                self.assertIsNotNone(control.embed(request))
            self.assertEqual(control.node_order(request), expected)

    def test_all_registered_methods_commit_and_restore_resources(self):
        rng = random.Random(91251)
        successes = {name: 0 for name in vne._algorithm_names(True, True)}
        for _ in range(10):
            sn = graph([20] * 5, [(u, w, rng.randint(6, 15), rng.randint(1, 3))
                       for u in range(5) for w in range(u + 1, 5) if rng.random() < .8])
            request = vne.VirtualNetworkRequest(0, 0, 10, {0: 3, 1: 4, 2: 2},
                       [vne.VirtualEdge(0, 1, 3), vne.VirtualEdge(1, 2, 4)], max_delay=8, max_hops=3)
            for name in successes:
                algorithm = vne.algorithm_factory(name, sn.clone(), 63, True)
                before = algorithm.sn.empty_state()
                embedding = algorithm.embed(request)
                if embedding is not None:
                    successes[name] += 1
                    vne._validate_active_state(algorithm, {0: (request, embedding)})
                    algorithm.release_embedding(request, embedding)
                self.assertEqual(before, algorithm.sn.empty_state())
        self.assertTrue(all(count > 0 for count in successes.values()), successes)

    def test_enabling_controls_does_not_change_primary_non_time_results(self):
        common = dict(lam=8, duration=100, num_nodes=12, seed=923)
        baseline = vne.run_simulation(**common)
        expanded = {row['Algorithm']: row for row in vne.run_simulation(**common, include_pso=True, include_ablations=True)}
        for row in baseline:
            for metric in ('Accepted', 'Rejected', 'Energy_Wh', 'Revenue', 'Cost', 'ServedRequestSeconds'):
                self.assertEqual(row[metric], expanded[row['Algorithm']][metric])

    def test_empty_link_batches_are_not_route_successes(self):
        algorithm = vne.ProposedAdaptiveVNE(graph([20, 20], [(0, 1, 10, 1)]))
        request = vne.VirtualNetworkRequest(0, 0, 10, {0: 1}, [])
        self.assertIsNotNone(algorithm.embed(request))
        self.assertEqual(algorithm.fast_route_successes, 0)
        self.assertEqual(algorithm.fast_route_batches, 0)


class ProtocolTests(unittest.TestCase):
    def test_source_digest_covers_every_package_module_and_entrypoint(self):
        root = Path(vne.__file__).resolve().parents[1]
        digest = hashlib.sha256()
        for path in sorted((root / 'vne').glob('*.py')) + [root / 'vne_simulation.py']:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b'\0' + path.read_bytes() + b'\0')
        self.assertEqual(experiments.source_fingerprint(), digest.hexdigest())

    def test_scenario_validation_and_metadata(self):
        for settings in ({'link_prob': 1.1}, {'lifetime_mean': 0}, {'max_hops': 1.5},
                         {'max_delay': math.nan}, {'p_idle': 400}, {'p_link': -1}):
            with self.assertRaises(ValueError):
                vne.Scenario(**settings)
        scenario = vne.Scenario(link_prob=.1, lifetime_mean=70, max_hops=3, p_link=2)
        spec = vne._experiment_spec(100, 12, 1, False, False, scenario)
        self.assertEqual(spec['scenario'], scenario.to_dict())
        self.assertEqual(spec['model']['lifetime_mean_seconds'], 70)
        generator = scenario.generator()
        self.assertEqual(generator.max_hops, 3)
        for settings in ({'lifetime_mean': 0}, {'cpu_range': (3, 1)}, {'link_prob': -1}, {'max_hops': 0}):
            with self.assertRaises(ValueError):
                vne.VirtualNetworkGenerator(**settings)

    def test_diagnostic_cache_rejects_incomplete_wrong_and_stale_rows(self):
        case = (8, 10, 2011, 40, False)
        spec = case_spec(case)
        frame = vne._flatten_results(vne.run_simulation(10, 40, 8, 2011))
        frame['CaseGroup'] = 'primary'
        frame['ExperimentFingerprint'] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        validate_cached_case(frame, case, spec, 'primary')
        for bad in (frame.iloc[:-1], frame.drop(columns='Energy_Wh'), frame.assign(Seed=222),
                    frame.assign(ExperimentFingerprint='old'), frame.assign(AlgorithmParameters='{}')):
            with self.assertRaises(ValueError):
                validate_cached_case(bad, case, spec, 'primary')

    def test_full_checkpoint_refuses_scenario_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            frame = vne._flatten_results(vne.run_simulation(10, 40, 8, 2011))
            spec = vne._experiment_spec(40, 8, 1, False, False)
            fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
            frame['ExperimentFingerprint'] = fingerprint
            frame.to_csv(path / 'full_evaluation.csv', index=False)
            (path / 'full_evaluation.config.json').write_text(json.dumps({'fingerprint': fingerprint, 'spec': spec}))
            with self.assertRaisesRegex(ValueError, 'differs'):
                vne.run_full_evaluation(directory, (10,), (2011,), 40, 8,
                                        scenario=vne.Scenario(lifetime_mean=80))
            frame.drop(columns='EnergyPerAccepted_Wh').to_csv(path / 'full_evaluation.csv', index=False)
            with self.assertRaisesRegex(ValueError, 'columns'):
                vne.run_full_evaluation(directory, (10,), (2011,), 40, 8)


if __name__ == '__main__':
    unittest.main()
