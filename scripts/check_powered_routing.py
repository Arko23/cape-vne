"""Proposal-only prototype: bounded powered-transit routing versus maintained VNE.

Not registered in the simulator and not a publication/full experiment. Both
proposal policies use the same RNG salt, inputs, accounting and total per-path
work quota. Comparators are unchanged. No historical rows are used as new data.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import vne
from vne import experiments
from scripts.audit_energy import build_graph, allocations


class WakeAvoidingVNE(vne.GreenAdaptiveVNE):
    """Experimental variant; production factory and policies remain unchanged."""
    name = 'WakeAvoidingPrototype'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.powered_route_attempts = self.powered_route_changes = 0

    def _marginal_route_watts(self, path, state, powered):
        cold = set(path) - powered
        links = {vne.canonical_edge(u,w) for u,w in zip(path,path[1:])}
        cold_links = sum(state['bw'][edge] >= self.sn.bandwidth_capacity[edge]-vne.EPS
                         for edge in links)
        return (len(cold) * (self.sn.p_idle + self.sn.boot_energy_joules/self.boot_amortization_seconds)
                + self.sn.p_link*cold_links)

    def _constrained_shortest_path(self, source, target, request_bw, max_delay,
                                   max_hops, state, removed_edges=None,
                                   removed_nodes=None, max_expansions=20000):
        before = self.route_expansions
        original = super()._constrained_shortest_path(source,target,request_bw,max_delay,max_hops,
                    state,removed_edges,removed_nodes,max_expansions)
        if original is None or len(original) <= 2 or not self.hop_routing:
            return original
        powered = (self._batch_powered if self._batch_powered is not None
                   else self.sn.powered_nodes(state))
        if all(node in powered for node in original[1:-1]):
            return original
        remaining = min(max_expansions,self.path_expansion_budget)-(self.route_expansions-before)
        if remaining <= 0:
            return original
        self.powered_route_attempts += 1
        forbidden = (set(removed_nodes or ()) |
                     (set(self._nodes)-powered-{source,target}))
        # One extra hop at most; private-state BW, hard delay and removed edges
        # apply exactly as in the original path search. No second full quota.
        alternative = super()._constrained_shortest_path(source,target,request_bw,max_delay,
            min(max_hops,len(original)),state,removed_edges,forbidden,remaining)
        if alternative is None:
            return original
        if (self._marginal_route_watts(alternative,state,powered)+vne.EPS <
                self._marginal_route_watts(original,state,powered)):
            self.powered_route_changes += 1
            return alternative
        return original


def witness_check():
    sn = build_graph([100]*5, [(0,1,100,1),(1,4,100,1),
                               (0,2,100,1),(2,3,100,1),(3,4,100,1)])
    active, helper = {}, vne.BaseVNEAlgorithm(sn)
    for node in (0,2,3,4):
        request = vne.VirtualNetworkRequest(node, 0, 1000, {0:10}, [])
        state = sn.empty_state()
        assert helper.reserve_cpu(state, node, 10)
        embedding = helper.commit_embedding(request, state, {0:node}, {})
        assert embedding is not None
        active[node] = request, embedding
    allocations(sn, active)
    maintained = vne.GreenAdaptiveVNE(sn)
    prototype = WakeAvoidingVNE(sn)
    before = sn.empty_state()
    old = maintained.find_shortest_paths(0,4,10,10,4,before,k=1)[0]
    new = prototype.find_shortest_paths(0,4,10,10,4,before,k=1)[0]
    assert old == [0,1,4]
    assert new == [0,2,3,4], f'cold-transit witness not improved: {new}'
    assert sn.empty_state() == before
    # A tight hop cap must preserve the feasible original route.
    assert prototype.find_shortest_paths(0,4,10,10,2,before,k=1) == [[0,1,4]]
    assert prototype.find_shortest_paths(0,4,10,2,4,before,k=1) == [[0,1,4]]
    # Exact quota: the alternative cannot receive another complete quota.
    for budget in (1,3,4,8,20,240):
        algorithm = WakeAvoidingVNE(sn, path_expansion_budget=budget)
        path = algorithm._constrained_shortest_path(0,4,10,10,4,before)
        assert algorithm.route_expansions <= budget
        if path is not None:
            assert len(path)-1 <= 4 and sn.path_delay(path) <= 10
    print('Cold-transit witness, QoS fallback, atomicity and shared quota passed', flush=True)
    return dict(maintained_path=old, prototype_path=new,
                maintained_additional_watts=160, prototype_additional_watts=15)


def run(output, suite, duration):
    if (output/'raw.csv').exists():
        raise ValueError('Fresh output directory required')
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    source = experiments.source_fingerprint()
    with zipfile.ZipFile(output/'source.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((root/'vne').glob('*.py')):
            archive.write(path, path.relative_to(root).as_posix())
        archive.write(root/'vne_simulation.py','vne_simulation.py')
        archive.write(Path(__file__), 'prototype/check_powered_routing.py')
    if suite == 'development':
        seeds = [13001,13002]
        cases = [('dense4',50,4,vne.Scenario()),
                 ('dense12',50,12,vne.Scenario()),
                 ('sparse',50,8,vne.Scenario(link_prob=.10)),
                 ('hard100',100,20,vne.Scenario(link_prob=.035,vnr_link_prob=.60,
                    lifetime_mean=1000,max_delay=15,max_hops=4))]
        names = ['ProposedAdaptive','WakeAvoidingPrototype']
    else:
        seeds = [14001,14002]
        cases = [('dense2',50,2,vne.Scenario()),
                 ('dense8',50,8,vne.Scenario()),
                 ('dense12',50,12,vne.Scenario()),
                 ('sparse',50,8,vne.Scenario(link_prob=.10)),
                 ('tight',50,12,vne.Scenario(max_delay=15,max_hops=4)),
                 ('hard100',100,20,vne.Scenario(link_prob=.035,vnr_link_prob=.60,
                    lifetime_mean=1000,max_delay=15,max_hops=4))]
        names = ['ProposedAdaptive','WakeAvoidingPrototype',*vne.REFERENCE_ALGORITHMS,
                 'EnergyAware','GreenCostRouting']
    spec = dict(suite=suite, duration=duration, workers=1, seeds=seeds, methods=names,
                cases=[dict(name=n,nodes=s,lam=l,scenario=c.to_dict()) for n,s,l,c in cases],
                maintained_source_sha256=source,
                prototype_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                note='Prototype diagnostics, no inferential or full-run superiority claim')
    (output/'config.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    factory = experiments.algorithm_factory
    instances = {}
    prototype_salt = int.from_bytes(hashlib.sha256(b'WakeAvoidingPrototype').digest()[:4],'big')
    maintained_salt = int.from_bytes(hashlib.sha256(b'ProposedAdaptive').digest()[:4],'big')
    scope = dict(experiments.ALGORITHM_SCOPE,
                 WakeAvoidingPrototype='Experimental powered-transit restriction, at most one extra hop, shared path quota')

    def select(name, substrate, seed, include_pso=False):
        if name == 'WakeAvoidingPrototype':
            # Same RNG stream as the maintained proposal; algorithms never use
            # scenario labels or future arrivals to choose paths.
            result = WakeAvoidingVNE(substrate,rng=random.Random(seed-prototype_salt+maintained_salt))
        else:
            result = factory(name,substrate,seed,include_pso)
        instances[name] = result
        return result

    rows = []
    for case, size, lam, scenario in cases:
        for seed in seeds:
            with patch.object(experiments,'_algorithm_names',return_value=list(names)), \
                 patch.object(experiments,'algorithm_factory',side_effect=select), \
                 patch.object(experiments,'ALGORITHM_SCOPE',scope):
                result = experiments.run_simulation(lam,duration,size,seed,True,
                    strict_invariants=True,include_ablations=True,
                    include_reference_baselines=True,scenario=scenario)
            for row in result:
                row['PoweredRouteAttempts'] = getattr(instances[row['Algorithm']],'powered_route_attempts',0)
                row['PoweredRouteChanges'] = getattr(instances[row['Algorithm']],'powered_route_changes',0)
                if row['Algorithm'] == 'WakeAvoidingPrototype':
                    parameters = json.loads(row['AlgorithmParameters'])
                    parameters.update(powered_route_extra_hops=1,powered_route_shared_quota=True,
                                      powered_route_objective='strictly lower marginal wake/link watts')
                    row['AlgorithmParameters'] = json.dumps(parameters,sort_keys=True)
                rows.append(dict(Case=case,**row))
            frame = pd.DataFrame(rows)
            for _, group in frame.groupby(['Case','Seed']):
                assert len(group) == len(names)
                assert group.TraceSHA256.nunique() == group.TopologySHA256.nunique() == 1
            frame.to_csv(output/'raw.csv',index=False)
            paired = {row['Algorithm']:row for row in result}
            p,w = paired['ProposedAdaptive'],paired['WakeAvoidingPrototype']
            print(f'{case} {seed}: accepted {p["Accepted"]}->{w["Accepted"]}, '
                  f'energy {p["Energy_Wh"]:.2f}->{w["Energy_Wh"]:.2f} Wh, '
                  f'mean {p["MeanEmbeddingTime"]*1000:.3f}->{w["MeanEmbeddingTime"]*1000:.3f} ms', flush=True)
    assert experiments.source_fingerprint() == source
    metrics = ['AcceptanceRatio','Energy_Wh','MeanEmbeddingTime','P99EmbeddingTime','ExecutionTime',
               'MeanHops','R_C','Served_R_C','EnergyPerServedCPUUnitSecond_Wh',
               'EnergyPerServedBandwidthUnitSecond_Wh','EnergyPerServedRequestSecond_Wh',
               'NodeUtil','LinkUtil','ServedCPUUnitSeconds','ServedBandwidthUnitSeconds']
    frame.groupby(['Case','Algorithm'])[metrics].mean().to_csv(output/'means.csv')
    frame.groupby('Algorithm')[metrics].mean().to_csv(output/'overall.csv')
    print(f'Completed {len(frame)} short diagnostic observations',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--witness-only',action='store_true')
    parser.add_argument('--suite',choices=('development','heldout'),default='development')
    parser.add_argument('--duration',type=float,default=1000)
    parser.add_argument('--output-dir',type=Path)
    args = parser.parse_args()
    witness_check()
    if args.witness_only:
        return
    if args.output_dir is None or not math.isfinite(args.duration) or args.duration <= 0:
        parser.error('Positive duration and output-dir required')
    run(args.output_dir,args.suite,args.duration)


if __name__ == '__main__':
    main()
