"""Isolated, known-duration energy candidates; never registered as production.

Online decisions see only committed reservations and the arriving request.
The same proposal RNG, budgets, simulator physics and QoS apply to every variant.
Short development/confirmation checks are not full publication experiments.
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


class LifetimeEnergyVNE(vne.GreenAdaptiveVNE):
    """Prototype: marginal activation seconds for currently admitted leases.

    Latest departures suffice because all recorded reservations are active now.
    No future arrivals, experiment horizon or scenario labels are available.
    The estimate is conditional on known durations and the current admitted set.
    """
    def __init__(self, *args, lifetime_routes=True, lifetime_hosts=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.lifetime_routes, self.lifetime_hosts = lifetime_routes, lifetime_hosts
        self._leases = {}
        self._node_leases = {n: {} for n in self.sn.cpu_capacity}
        self._link_leases = {e: {} for e in self.sn.edges}
        self._node_end = {n: -math.inf for n in self.sn.cpu_capacity}
        self._link_end = {e: -math.inf for e in self.sn.edges}
        self._lease_request = None
        self._unsafe_leases = 0

    @staticmethod
    def _safe(request):
        demands = [*request.node_cpu.values(), *(e.bandwidth for e in request.edges)]
        return (math.isfinite(request.arrival) and math.isfinite(request.departure)
                and request.departure > request.arrival
                and all(d == 0 or d > vne.EPS for d in demands))

    def embed(self, request):
        previous = self._lease_request
        self._lease_request = request if self._safe(request) and not self._unsafe_leases else None
        try:
            return super().embed(request)
        finally:
            self._lease_request = previous

    def commit_embedding(self, request, state, mapping, paths):
        result = super().commit_embedding(request, state, mapping, paths)
        if result is None:
            return None
        cpu, bw = self._embedding_usage(request, mapping, paths)
        links = {e for e, use in bw.items() if use > vne.EPS}
        nodes = {n for n, use in cpu.items() if use > vne.EPS}
        for edge in links:
            nodes.update(edge)
        unsafe = not self._safe(request)
        self._leases[request.request_id] = nodes, links, unsafe
        self._unsafe_leases += unsafe
        for resources, ends, selected in ((self._node_leases, self._node_end, nodes),
                                          (self._link_leases, self._link_end, links)):
            for resource in selected:
                resources[resource][request.request_id] = request.departure
                ends[resource] = max(ends[resource], request.departure)
        return result

    def release_embedding(self, request, embedding):
        # Common validation must succeed before lease bookkeeping changes.
        super().release_embedding(request, embedding)
        nodes, links, unsafe = self._leases.pop(request.request_id)
        self._unsafe_leases -= unsafe
        for resources, ends, selected in ((self._node_leases, self._node_end, nodes),
                                          (self._link_leases, self._link_end, links)):
            for resource in selected:
                end = resources[resource].pop(request.request_id)
                if end == ends[resource]:
                    ends[resource] = max(resources[resource].values(), default=-math.inf)

    def _tentative(self, state):
        nodes = {n for n in self._nodes
                 if state['cpu'][n] < self.sn.cpu_residual[n] - vne.EPS}
        current = self._edge_residual(state)
        background = self._green_bw if self._green_bw is not None else self._edge_residual(
            {'bw': self.sn.bandwidth_residual})
        links = {self._edges[i] for i in np.flatnonzero(current < background - vne.EPS)}
        for edge in links:
            nodes.update(edge)
        return nodes, links

    def _two_hop_context(self, state):
        powered = super()._two_hop_context(state)
        if not self.lifetime_routes or self._lease_request is None or powered is None:
            return powered
        return powered, self._tentative(state)

    def _two_hop_key(self, source, middle, target, bandwidth, delay, state, context):
        if not self.lifetime_routes or self._lease_request is None or not self.green_two_hop:
            return super()._two_hop_key(source, middle, target, bandwidth, delay, state, context)
        request = self._lease_request
        powered, (nodes, links) = context
        energy = 0.
        if middle not in nodes:
            seconds = max(0., request.departure - max(request.arrival, self._node_end[middle]))
            energy += seconds * self.sn.p_idle
            if middle not in powered and bandwidth > vne.EPS:
                energy += self.sn.boot_energy_joules
        for edge in (vne.canonical_edge(source, middle), vne.canonical_edge(middle, target)):
            if edge not in links:
                seconds = max(0., request.departure - max(request.arrival, self._link_end[edge]))
                energy += seconds * self.sn.p_link
        # Zero-BW routes do not activate links or transit nodes.
        return (energy if bandwidth > vne.EPS else 0.), delay, middle

    def _wake_delta(self, request, node, state, context):
        if state['cpu'][node] < self.sn.cpu_residual[node] - vne.EPS:
            new_wake = 0.
        else:
            seconds = max(0., request.departure - max(request.arrival, self._node_end[node]))
            new_wake = (seconds * self.sn.p_idle
                        + (0. if node in context['powered'] else self.sn.boot_energy_joules)) / request.lifetime
        old_wake = (0. if node in context['powered'] else
                    self.sn.p_idle + self.sn.boot_energy_joules / self.boot_amortization_seconds)
        weight = (self.energy_weight * (1 - .45 * context['pressure'])
                  if self.adaptive_energy else self.energy_weight)
        return -weight * (new_wake - old_wake) / max(self.sn.p_peak, vne.EPS)

    def _host_scores(self, request, vnode, mapping, state, context):
        scores = super()._host_scores(request, vnode, mapping, state, context)
        if self.lifetime_hosts and self._lease_request is not None and request.node_cpu[vnode] > vne.EPS:
            scores += np.array([self._wake_delta(request, n, state, context) for n in self._nodes])
        return scores

    def _node_score(self, request, vnode, pnode, mapping, state=None, context=None):
        score = super()._node_score(request, vnode, pnode, mapping, state, context)
        if (not self.lifetime_hosts or self._lease_request is None or context is None
                or context.get('green_host_scores') is not None or not math.isfinite(score)
                or request.node_cpu[vnode] <= vne.EPS):
            return score
        return score + self._wake_delta(request, pnode, state, context)


VARIANTS = {'LifetimeRoutes': (True, False), 'LifetimeHosts': (False, True),
            'LifetimeCombined': (True, True)}
METRICS = ['AcceptanceRatio','Energy_Wh','MeanEmbeddingTime','P99EmbeddingTime','ExecutionTime',
           'MeanHops','R_C','Served_R_C','EnergyPerServedCPUUnitSecond_Wh',
           'EnergyPerServedBandwidthUnitSecond_Wh','EnergyPerServedRequestSecond_Wh',
           'NodeUtil','LinkUtil','ServedCPUUnitSeconds','ServedBandwidthUnitSeconds']


def run(output, suite, duration, selected):
    if output.exists():
        raise ValueError('Fresh output directory required')
    output.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    source = experiments.source_fingerprint()
    with zipfile.ZipFile(output/'source.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((root/'vne').glob('*.py')):
            archive.write(path, path.relative_to(root).as_posix())
        archive.write(root/'vne_simulation.py', 'vne_simulation.py')
        archive.write(Path(__file__), 'prototype/check_lifetime_energy.py')
    seeds = [16001,16002] if suite == 'development' else [17001,17002,17003,17004]
    cases = [('dense2',50,2,vne.Scenario()), ('dense12',50,12,vne.Scenario()),
             ('sparse',50,8,vne.Scenario(link_prob=.10)),
             ('tight',50,12,vne.Scenario(max_delay=15,max_hops=4)),
             ('short',50,12,vne.Scenario(lifetime_mean=100)),
             ('hard100',100,20,vne.Scenario(link_prob=.035,vnr_link_prob=.60,
                lifetime_mean=1000,max_delay=15,max_hops=4))]
    names = ['ProposedAdaptive', *selected]
    if suite == 'heldout':
        cases.append(('long',50,8,vne.Scenario(lifetime_mean=1500)))
        names += [*vne.REFERENCE_ALGORITHMS, 'EnergyAware','GreenCostRouting']
    spec = dict(suite=suite,duration=duration,workers=1,seeds=seeds,methods=names,
        cases=[dict(name=n,nodes=s,lam=l,scenario=c.to_dict()) for n,s,l,c in cases],
        maintained_source_sha256=source,
        prototype_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        known_durations=True, future_arrivals_available=False,
        note='Prototype diagnostics; serial embedding time includes lease commit bookkeeping, release reported separately')
    (output/'config.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    factory = experiments.algorithm_factory
    base_salt = int.from_bytes(hashlib.sha256(b'ProposedAdaptive').digest()[:4],'big')

    def select(name, substrate, seed, include_pso=False):
        if name not in VARIANTS:
            return factory(name,substrate,seed,include_pso)
        salt = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4],'big')
        routes, hosts = VARIANTS[name]
        result = LifetimeEnergyVNE(substrate,rng=random.Random(seed-salt+base_salt),
                                   lifetime_routes=routes,lifetime_hosts=hosts)
        result.name = name
        return result

    scope = dict(experiments.ALGORITHM_SCOPE, **{n:'Experimental known-duration activation preference' for n in selected})
    rows = []
    for case,size,lam,scenario in cases:
        for seed in seeds:
            with patch.object(experiments,'_algorithm_names',return_value=list(names)), \
                 patch.object(experiments,'algorithm_factory',side_effect=select), \
                 patch.object(experiments,'ALGORITHM_SCOPE',scope):
                result = experiments.run_simulation(lam,duration,size,seed,True,
                    strict_invariants=True,include_ablations=True,
                    include_reference_baselines=True,scenario=scenario)
            for row in result:
                if row['Algorithm'] in VARIANTS:
                    parameters = json.loads(row['AlgorithmParameters'])
                    parameters.update(lifetime_routes=VARIANTS[row['Algorithm']][0],
                                      lifetime_hosts=VARIANTS[row['Algorithm']][1],known_durations=True)
                    row['AlgorithmParameters'] = json.dumps(parameters,sort_keys=True)
                rows.append(dict(Case=case,**row))
            frame = pd.DataFrame(rows)
            for _, group in frame.groupby(['Case','Seed']):
                assert len(group) == len(names)
                assert group.TraceSHA256.nunique() == group.TopologySHA256.nunique() == 1
            frame.to_csv(output/'raw.csv',index=False)
            print(case,seed,'; '.join(f'{r["Algorithm"]}: A={r["Accepted"]}, E={r["Energy_Wh"]:.2f}, '
                  f'T={r["MeanEmbeddingTime"]*1000:.3f}ms' for r in result if r['Algorithm'] in names[:1+len(selected)]),flush=True)
    assert experiments.source_fingerprint() == source
    frame.groupby(['Case','Algorithm'])[METRICS].mean().to_csv(output/'means.csv')
    frame.groupby('Algorithm')[METRICS].mean().to_csv(output/'overall.csv')
    print(f'Completed {len(frame)} observations',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=('development','heldout'),default='development')
    parser.add_argument('--duration',type=float,default=1500)
    parser.add_argument('--variants',nargs='+',choices=tuple(VARIANTS),default=['LifetimeRoutes','LifetimeHosts'])
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error('Positive finite duration required')
    run(args.output_dir,args.suite,args.duration,args.variants)


if __name__ == '__main__':
    main()
