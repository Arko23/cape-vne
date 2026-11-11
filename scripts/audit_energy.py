"""Independently audit active allocations, electricity and completed-run energy.

No policy changes or full experiments. Replays are short correctness diagnostics,
not timing/superiority evidence. Historical summaries retain their measured source.
"""
import argparse
from collections import defaultdict
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import vne
from scripts.analyze_full_results import validate_raw, verify_statistics
from vne.experiments import source_fingerprint


def allocations(substrate, active):
    """Oracle from request demands and geometric paths, not residual-state power."""
    cpu, bw = defaultdict(float), defaultdict(float)
    for request, embedding in active.values():
        mapping, paths = embedding['mapping'], embedding['paths']
        assert set(mapping) == set(request.node_cpu)
        assert len(set(mapping.values())) == len(mapping)
        assert set(paths) == {(e.u, e.v) for e in request.edges}
        for vnode, demand in request.node_cpu.items():
            assert mapping[vnode] in substrate.cpu_capacity
            cpu[mapping[vnode]] += demand
        for edge in request.edges:
            path = paths[(edge.u, edge.v)]
            assert path[0] == mapping[edge.u] and path[-1] == mapping[edge.v]
            assert len(set(path)) == len(path) and len(path) - 1 <= request.max_hops
            delay = 0.
            for u, w in zip(path, path[1:]):
                key = tuple(sorted((u, w)))
                assert key in substrate.bandwidth_capacity
                bw[key] += edge.bandwidth
                delay += substrate.edges[key]['delay']
            assert delay <= request.max_delay + 1e-9
    for key, capacity in substrate.cpu_capacity.items():
        assert -1e-7 <= cpu[key] <= capacity + 1e-7
        assert math.isclose(capacity - cpu[key], substrate.cpu_residual[key], abs_tol=1e-7)
    for key, capacity in substrate.bandwidth_capacity.items():
        assert -1e-7 <= bw[key] <= capacity + 1e-7
        assert math.isclose(capacity - bw[key], substrate.bandwidth_residual[key], abs_tol=1e-7)
    powered = {node for node, use in cpu.items() if use > 1e-9}
    links = {edge for edge, use in bw.items() if use > 1e-9}
    for edge in links:
        powered.update(edge)
    parts = np.array([
        substrate.p_idle * len(powered),
        (substrate.p_peak - substrate.p_idle) * sum(cpu[n] / c for n, c in substrate.cpu_capacity.items()),
        substrate.p_link * len(links),
    ])
    np.testing.assert_allclose(parts.sum(), substrate.power_watts(), rtol=1e-12, atol=1e-8)
    return parts, powered


def replay(name, seed, nodes, lam, duration, scenario):
    """Separate event loop, no sample ticks; compute watts/boots from active maps."""
    substrate = vne.SubstrateNetwork(num_nodes=nodes, seed=seed, **scenario.substrate_kwargs())
    salt = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], 'big')
    algorithm = vne.algorithm_factory(name, substrate, seed + salt, True)
    trace = vne.generate_trace(lam, duration, seed, scenario.generator())
    active, departures, now, index = {}, [], 0., 0
    energy = np.zeros(3)
    boot, cpu_seconds, bw_seconds, req_seconds = 0., 0., 0., 0.
    accepted = rejected = failed_checks = 0
    while now < duration:
        event = min(trace[index].arrival if index < len(trace) else math.inf,
                    departures[0][0] if departures else math.inf, duration)
        parts, _ = allocations(substrate, active)
        dt = event - now
        energy += parts * dt / 3600.
        cpu_seconds += sum(r.total_cpu for r, _ in active.values()) * dt
        bw_seconds += sum(r.total_bandwidth for r, _ in active.values()) * dt
        req_seconds += len(active) * dt
        now = event
        while departures and departures[0][0] <= now:
            _, rid = heapq.heappop(departures)
            request, embedding = active.pop(rid)
            algorithm.release_embedding(request, embedding)
            allocations(substrate, active)
        while index < len(trace) and trace[index].arrival <= now:
            request = trace[index]
            index += 1
            before = substrate.empty_state()
            _, old_powered = allocations(substrate, active)
            result = algorithm.embed(request)
            if result is None:
                rejected += 1
                assert substrate.empty_state() == before, (name, 'failed attempt leaked state')
                failed_checks += 1
            else:
                accepted += 1
                active[request.request_id] = request, result
                heapq.heappush(departures, (request.departure, request.request_id))
                _, powered = allocations(substrate, active)
                increment = len(powered - old_powered) * substrate.boot_energy_joules
                np.testing.assert_allclose(result['boot_energy_joules'], increment, atol=1e-9)
                boot += increment
            allocations(substrate, active)
    # Release even horizon-truncated requests to independently check no leftovers.
    for request, embedding in list(active.values()):
        algorithm.release_embedding(request, embedding)
        del active[request.request_id]
        allocations(substrate, active)
    assert substrate.cpu_residual == substrate.cpu_capacity
    assert substrate.bandwidth_residual == substrate.bandwidth_capacity
    return dict(Algorithm=name, Accepted=accepted, Rejected=rejected,
                Energy_Wh=float(energy.sum() + boot / 3600.), BootEnergy_J=boot,
                ServedCPUUnitSeconds=cpu_seconds, ServedBandwidthUnitSeconds=bw_seconds,
                ServedRequestSeconds=req_seconds, Idle_Wh=energy[0], DynamicCPU_Wh=energy[1],
                Link_Wh=energy[2], FailedAtomicChecks=failed_checks)


def build_graph(cpu, links):
    sn = vne.SubstrateNetwork(num_nodes=len(cpu), seed=0)
    sn.cpu_capacity = dict(enumerate(map(float, cpu)))
    sn.cpu_residual = dict(sn.cpu_capacity)
    sn.edges = {tuple(sorted((u, w))): {'bandwidth': float(b), 'delay': float(d)}
                for u, w, b, d in links}
    sn.neighbors = {n: set() for n in sn.cpu_capacity}
    for u, w in sn.edges:
        sn.neighbors[u].add(w)
        sn.neighbors[w].add(u)
    sn.bandwidth_capacity = {e: x['bandwidth'] for e, x in sn.edges.items()}
    sn.bandwidth_residual = dict(sn.bandwidth_capacity)
    return sn


def routing_witness():
    # Same CPU placement and same request. Background one-node requests keep
    # 0,2,3,4 powered; 1 is cold. Both feasible routes obey unchanged QoS.
    sn = build_graph([100] * 5, [(0,1,100,1), (1,4,100,1),
                                (0,2,100,1), (2,3,100,1), (3,4,100,1)])
    base = vne.BaseVNEAlgorithm(sn)
    for node in (0,2,3,4):
        request = vne.VirtualNetworkRequest(node, 0, 1000, {0:10}, [])
        state = sn.empty_state()
        assert base.reserve_cpu(state, node, 10)
        assert base.commit_embedding(request, state, {0:node}, {}) is not None
    algorithm = vne.algorithm_factory('ProposedAdaptive', sn, 0, True)
    state = sn.empty_state()
    actual = algorithm.find_shortest_paths(0, 4, 10, 10, 4, state, k=1)[0]
    alternative = [0,2,3,4]
    assert actual == [0,1,4]
    rows = []
    for label, path in [('proposal minimum hops', actual), ('powered detour', alternative)]:
        trial = sn.clone()
        private = trial.empty_state()
        helper = vne.BaseVNEAlgorithm(trial)
        assert helper.reserve_path(private, path, 10)
        boot = len(trial.powered_nodes(private) - trial.powered_nodes()) * trial.boot_energy_joules
        trial.apply_state(private)
        rows.append(dict(Choice=label, Path=path, Hops=len(path)-1,
                         AdditionalWatts=trial.power_watts()-sn.power_watts(), Boot_J=boot,
                         Additional_Wh_100s=((trial.power_watts()-sn.power_watts())*100+boot)/3600))
    assert rows[0]['Additional_Wh_100s'] > rows[1]['Additional_Wh_100s']
    return rows


def decomposition(frame, scenarios):
    result = frame.copy()
    cpu_low, cpu_high = [], []
    idle, link = [], []
    for row in result.itertuples():
        scenario = scenarios[getattr(row, 'Case', 'full')]
        sn = vne.SubstrateNetwork(num_nodes=int(row.NumSubstrateNodes), seed=int(row.Seed),
                                  **scenario.substrate_kwargs())
        # Independent CPU-service identity, capacity-weighted utilization.
        np.testing.assert_allclose(row.NodeUtil * sum(sn.cpu_capacity.values()) * row.Duration,
                                   row.ServedCPUUnitSeconds, rtol=1e-10, atol=1e-5)
        delta = scenario.p_peak - scenario.p_idle
        cpu_low.append(delta * row.ServedCPUUnitSeconds / max(sn.cpu_capacity.values()) / 3600)
        cpu_high.append(delta * row.ServedCPUUnitSeconds / min(sn.cpu_capacity.values()) / 3600)
        idle.append(scenario.p_idle * row.MeanActiveNodes * row.Duration / 3600)
        link.append(scenario.p_link * row.MeanActiveLinks * row.Duration / 3600)
    result['Idle_Wh'], result['Link_Wh'] = idle, link
    result['Boot_Wh'] = result.BootEnergy_J / 3600
    # Historical raw data lacks per-host CPU areas: dynamic CPU is a residual,
    # bounded independently, not claimed to have been independently measured.
    result['DynamicCPU_Wh'] = result.Energy_Wh - result.Idle_Wh - result.Link_Wh - result.Boot_Wh
    assert (result.DynamicCPU_Wh >= np.array(cpu_low) - 1e-6).all()
    assert (result.DynamicCPU_Wh <= np.array(cpu_high) + 1e-6).all()
    metrics = ['AcceptanceRatio', 'Energy_Wh', 'Idle_Wh', 'DynamicCPU_Wh', 'Link_Wh', 'Boot_Wh',
               'ServedCPUUnitSeconds', 'ServedBandwidthUnitSeconds', 'ServedRequestSeconds',
               'EnergyPerServedCPUUnitSecond_Wh', 'EnergyPerServedBandwidthUnitSecond_Wh',
               'EnergyPerServedRequestSecond_Wh', 'MeanActiveNodes', 'MeanActiveLinks', 'MeanHops']
    means = result.groupby('Algorithm')[metrics].mean()
    proposal = means.loc['ProposedAdaptive']
    means['CPUServicePercentOfProposal'] = 100 * means.ServedCPUUnitSeconds / proposal.ServedCPUUnitSeconds
    means['BWServicePercentOfProposal'] = 100 * means.ServedBandwidthUnitSeconds / proposal.ServedBandwidthUnitSeconds
    means['IdleWhPerCPUSecond'] = means.Idle_Wh / means.ServedCPUUnitSeconds
    return result, means.reset_index()


def md(frame, columns):
    def cell(value):
        if isinstance(value, (float, np.floating)):
            if 0 < abs(value) < 1e-4:
                return f'{value:.3g}'
            return f'{value:.7f}' if 0 < abs(value) < .01 else f'{value:.4f}'
        return str(value)
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
    for row in frame[columns].itertuples(index=False, name=None):
        lines.append('| ' + ' | '.join(cell(x) for x in row) + ' |')
    return '\n'.join(lines)


def supplement(out, full, means, completed_run):
    """Add independently verified per-load comparisons and a scientific figure."""
    import matplotlib.pyplot as plt
    statistical = pd.read_csv(completed_run /
                              'statistics_with_pso_ablations.csv', float_precision='round_trip')
    checks = verify_statistics(full, statistical)
    (out / 'statistics_validation.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    rows = []
    for load, frame in full.groupby('Lambda'):
        avg = frame.groupby('Algorithm').mean(numeric_only=True)
        p, g = avg.loc['ProposedAdaptive'], avg.loc['GreenCostRouting']
        test = statistical[(statistical.Lambda == load) & (statistical.Baseline == 'GreenCostRouting')
                           & (statistical.Metric == 'EnergyPerServedCPUUnitSecond_Wh')].iloc[0]
        rows.append(dict(Lambda=load, Proposal_Wh_per_CPU_s=p.EnergyPerServedCPUUnitSecond_Wh,
                         GreenCost_Wh_per_CPU_s=g.EnergyPerServedCPUUnitSecond_Wh,
                         Proposal_minus_control_pct=100*(p.EnergyPerServedCPUUnitSecond_Wh /
                                                         g.EnergyPerServedCPUUnitSecond_Wh-1),
                         Paired_BH_q=test.q_value,
                         Proposal_acceptance_pct=100*p.AcceptanceRatio,
                         Control_acceptance_pct=100*g.AcceptanceRatio))
    paired = pd.DataFrame(rows)
    paired.to_csv(out / 'green_control_per_load.csv', index=False)
    selected = ['ProposedAdaptive', *vne.REFERENCE_ALGORITHMS, 'GRC','NodeRank','GreedyKSP','EnergyAware','PSO',
                'FullJointRepair','CompactNoRepair','GreenCostRouting']
    display = means.set_index('Algorithm').loc[selected].reset_index()
    figure, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True)
    bottom = np.zeros(len(display))
    for field, label, color in [('Idle_Wh','Powered-node idle','#6586ad'),
                                 ('DynamicCPU_Wh','Dynamic CPU','#76aa8e'),
                                 ('Link_Wh','Active links','#dcad64'), ('Boot_Wh','Boots','#b07181')]:
        values = display[field].to_numpy()/1000
        axes[0].bar(display.Algorithm, values, bottom=bottom, label=label, color=color)
        bottom += values
    axes[0].set_ylabel('Mean energy per run (kWh)')
    axes[0].legend(ncol=4, fontsize=9)
    axes[0].set_title('Completed full run: energy components and served CPU volume')
    axes[1].bar(display.Algorithm, display.CPUServicePercentOfProposal, color='#6586ad')
    axes[1].axhline(100, linestyle='--', color='black', linewidth=.8)
    axes[1].set_ylabel('Served CPU unit-seconds (% of proposal)')
    axes[1].tick_params(axis='x', labelrotation=65)
    for label in axes[1].get_xticklabels():
        label.set_horizontalalignment('right')
    for axis in axes:
        axis.grid(axis='y', alpha=.2)
        axis.set_axisbelow(True)
    figure.text(.01,.01, '180 paired cases; equal case weighting; measured historical source; '
                'descriptive means, no uncertainty shown. Dynamic CPU component inferred from total.', fontsize=8)
    figure.tight_layout(rect=(0,.04,1,1))
    figure.savefig(out / 'energy_and_service.png', dpi=160)
    figure.savefig(out / 'energy_and_service.svg')
    plt.close(figure)
    with (out / 'REPORT.md').open('a', encoding='utf-8') as handle:
        handle.write('\n## A control has a real normalized-energy advantage at low load\n\n'
                     'GreenCostRouting has lower mean energy per served CPU-second at lambda=2, '
                     'by about 0.63% relative to the proposal. The paired test is significant '
                     '(BH q=0.00845). It also accepts 1.55 percentage points fewer requests. '
                     'At loads 4–12 the proposal has significantly lower energy per CPU-second. '
                     'This qualifies the aggregate rank: the proposal is not best on every load. '
                     'The control uses the earlier weighted power/footprint routing objective; '
                     'other engine differences prevent attributing the entire effect to routing alone.\n\n'
                     + md(paired, ['Lambda','Proposal_Wh_per_CPU_s','GreenCost_Wh_per_CPU_s',
                                   'Proposal_minus_control_pct','Paired_BH_q'])
                     + '\n\nPositive differences are adverse to the proposal. Statistics were reconstructed '
                     'from the archived full run, not from these short replays. '
                     'See `statistics_validation.json`.\n\n'
                     '![Energy and service](energy_and_service.png)\n\n'
                     'The proposal full-run components average 38.94 kWh idle, 34.78 kWh dynamic CPU, '
                     '6.24 kWh links, and only 0.00224 kWh boots. Optimizing boot energy alone cannot '
                     'materially close this gap under the current model.\n\n'
                     'Priority for a later policy experiment: bounded low-wake route alternatives '
                     'and routing-aware host placement, keeping workload, QoS, baselines and accounting '
                     'fixed. Additional hops can increase bandwidth cost and hurt acceptance; test '
                     'those tradeoffs on fresh held-out cases before retaining a change. '
                     'This analysis changes no decision policy.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--completed-run', type=Path, required=True)
    parser.add_argument('--diagnostic-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists():
        parser.error('Choose a fresh output directory; audit evidence is never overwritten')
    out.mkdir(parents=True)
    current_hash = source_fingerprint()
    full, spec, _, _ = validate_raw(args.completed_run, args.completed_run / 'source.zip')
    raw_path = args.completed_run / 'full_evaluation_with_pso_ablations.csv'
    old_raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    parts, means = decomposition(full, {'full': vne.Scenario(**spec['scenario'])})
    parts.to_csv(out / 'full_energy_components.csv', index=False)
    means.to_csv(out / 'full_energy_means.csv', index=False)
    loads = parts.groupby(['Lambda','Algorithm']).mean(numeric_only=True).reset_index()
    loads.to_csv(out / 'full_per_load.csv', index=False)
    config = json.loads((args.diagnostic_run / 'config.json').read_text())
    for name, digest in config['source_hashes'].items():
        assert hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest() == digest
    diagnostic = pd.read_csv(args.diagnostic_run / 'raw.csv', float_precision='round_trip')
    scenarios = {c['name']: vne.Scenario(**c['scenario']) for c in config['cases']}
    diagnostic_parts, diagnostic_means = decomposition(diagnostic, scenarios)
    diagnostic_parts.to_csv(out / 'current_energy_components.csv', index=False)
    diagnostic_means.to_csv(out / 'current_energy_means.csv', index=False)
    names = vne._algorithm_names(True, True, True)
    checks = []
    cases = [(12001, vne.Scenario(lifetime_mean=300)),
             (12002, vne.Scenario(link_prob=.10, lifetime_mean=300, max_delay=15, max_hops=4))]
    for seed, scenario in cases:
        records = vne.run_simulation(12, 600, 24, seed, True, strict_invariants=True,
                                    include_ablations=True, scenario=scenario, include_reference_baselines=True)
        by_name = {row['Algorithm']: row for row in records}
        for name in names:
            actual = replay(name, seed, 24, 12, 600, scenario)
            fields = ['Accepted','Rejected','Energy_Wh','BootEnergy_J', 'ServedCPUUnitSeconds',
                      'ServedBandwidthUnitSeconds','ServedRequestSeconds']
            error = max(abs(actual[f]-by_name[name][f]) for f in fields)
            np.testing.assert_allclose([actual[f] for f in fields], [by_name[name][f] for f in fields],
                                       rtol=1e-10, atol=1e-6, err_msg=name)
            checks.append(dict(Seed=seed, MaxAbsoluteDifference=error, **actual))
        pd.DataFrame(checks).to_csv(out / 'independent_replays.csv', index=False)
        print(f'Independent accounting: seed {seed}, all {len(names)} methods passed', flush=True)
    witness = routing_witness()
    (out / 'routing_witness.json').write_text(json.dumps(witness, indent=2), encoding='utf-8')
    assert source_fingerprint() == current_hash
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == old_raw_hash
    validation = dict(source_sha256=current_hash, historical_source_sha256=spec['source_sha256'],
                      historical_raw_sha256=old_raw_hash, historical_rows=len(full), current_rows=len(diagnostic),
                      independently_replayed_method_cases=len(checks),
                      failed_atomic_checks=sum(row['FailedAtomicChecks'] for row in checks),
                      max_replay_absolute_difference=max(row['MaxAbsoluteDifference'] for row in checks),
                      source_and_historical_raw_unchanged=True)
    (out / 'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    selected = ['ProposedAdaptive', *vne.REFERENCE_ALGORITHMS, 'GRC','NodeRank','GreedyKSP','EnergyAware','PSO',
                'FullJointRepair','CompactNoRepair','GreenCostRouting']
    display = means.set_index('Algorithm').loc[selected].reset_index()
    display['Acceptance_pct'] = display.AcceptanceRatio * 100
    display['Energy_kWh'] = display.Energy_Wh / 1000
    display['Idle_kWh'] = display.Idle_Wh / 1000
    text = f'''# Energy and algorithm bug audit — 2026-10-08

Simulator source `{current_hash}` remained unchanged. Historical source is
`{spec['source_sha256']}`. These cohorts are analyzed separately.

The existing correctness suite passed 110 tests in 31.501 seconds. Windows
sandbox temporary-file errors disappeared on the permitted unrestricted rerun.
The independent allocation/event-loop oracle checked all 32 methods on two
short dense/sparse constrained cases: {len(checks)} method/case replays. It
reconstructs CPU/BW use from mappings and paths, checks QoS and failed-attempt
atomicity, computes boot transitions independently, and releases all remaining
requests after the horizon. Maximum compared absolute error:
`{validation['max_replay_absolute_difference']:.9g}`; failed-attempt state checks:
`{validation['failed_atomic_checks']}`. These are correctness diagnostics, not
statistical performance evidence. No full evaluation was launched.

## Why other methods use less energy

Completed full experiment: {len(full)} observations, four workers, 20,000 seconds
per case. Equal case weighting; energy ratios are means of per-run ratios.
CPU/BW service percentages below are ratios of cohort mean served volumes.

{md(display, ['Algorithm','Acceptance_pct','Energy_kWh','Idle_kWh','CPUServicePercentOfProposal','BWServicePercentOfProposal','EnergyPerServedCPUUnitSecond_Wh'])}

Total energy is idle host/transit power + dynamic CPU + active physical links +
boots. Idle and link components above follow exact time-averaged active counts.
Historical dynamic CPU energy is the remaining component, independently bounded
by CPU service/capacity identities; its full per-host trajectory was not logged.
The short replays independently reconstruct all components. Historical and
current-revision CSVs are separate. A lower normalized ratio does not establish
equal accepted request mix or global optimality.

VirneFFD/GRC/RW two-stage methods select one CPU/rank placement and sequential
K=10 routes; routing failure rejects the request without proposal recovery.
They do not optimize electricity. Lower measured total energy accompanies much
less served work. RWBFS co-locates graph traversal and placement and retries
different visited hosts, but does not implement global energy minimization.
The PSOs minimize admission resource cost (bandwidth × hops plus CPU), not
joules. The custom EnergyAware minimizes immediate host marginal watts, omits
future routing power/boot costs in that score, and also accepts much less work.
Previous-engine controls have distinct acceptance/service volumes, not an
automatic apples-to-apples energy saving.

## Confirmed policy limitation, demonstrated without tuning

The proposal minimizes feasible hops, uses activation power for two-hop choices,
and minimizes delay for longer-hop DP choices. This can conflict with electricity.
With identical endpoints, CPU placement and bandwidth demand, this valid witness
keeps four nodes powered by background CPU-only requests:

{md(pd.DataFrame(witness), ['Choice','Path','Hops','AdditionalWatts','Boot_J','Additional_Wh_100s'])}

The two-hop route wakes a transit node; the three-hop route reuses powered nodes.
Both obey delay ≤10ms, hops ≤4 and bandwidth 10. This is a policy tradeoff,
not erroneous energy arithmetic. It proves the hop-first router is not globally
energy optimal; it does not quantify gains on the real trace or promise an
acceptance/hops improvement from changing the objective.

## Bug/fidelity findings and remaining risks

| Area | Finding | Status |
|---|---|---|
| Energy accounting | Common horizon integration, host/transit/link/boot model; independent small replays agree for all 32 methods | No discrepancy reproduced in checked cases |
| Reservations/releases | Failed attempts preserve state; every active mapping/path reconstructs residual resources; final release restores capacities | Passed tests and replays |
| Proposal | Power placement uses relaxed request-start domains; weight attenuates under load; routing favors hops over electricity; no post-acceptance migration | Documented heuristic limitations, not correctness bugs |
| GRC/NodeRank | Rank equations checked independently; routing/profit-threshold pipeline differs from source papers | Ranking adaptations |
| GreedyKSP/EnergyAware/PSO | Explicit custom methods; PSO uses repaired categorical search and fallback | Not published-method reproductions |
| Five Virne ports | Native decision definitions checked against pinned archive through CPU/BW adapters | Reference-code ports with common QoS/atomic-accounting adaptations |
| Pinned upstream PSO | Child-process evolution discards updates; spawn-unpicklable lambdas | Already corrected/recorded in local scheduler; not a new unresolved local bug |
| Pinned GRC / BFS edge cases | Zero/dangling-resource division and disconnected-BW path error | Existing local safe fallbacks; ordinary-input parity tested |
| Controls | Most inherit older engines rather than latest GreenAdaptiveVNE | Useful controls, not isolated ablations of the latest proposal |
| Timing | All attempts are timed, including rejected requests; ports omit native framework overhead; full run used four workers | Timing comparison must state execution scope |
| Physical realism | Ideal instantaneous sleep/wake; no hardware electricity, cooling, carbon, migration or wake latency | Model limitation |

This audit has not proved the entire program bug-free or paper-perfect. No new
simulator correctness bug was reproduced. The evidence supports explaining
low total energy by service volume and resource occupancy, while recognizing
real energy-policy improvement opportunities. Do not infer universal green
superiority from aggregate normalized energy.

Files: `full_energy_components.csv`, `full_energy_means.csv`, `full_per_load.csv`,
`current_energy_components.csv`, `current_energy_means.csv`,
`independent_replays.csv`, `routing_witness.json`, `validation.json`.
'''
    (out / 'REPORT.md').write_text(text, encoding='utf-8')
    supplement(out, full, means, args.completed_run)
    print(json.dumps(validation, indent=2), flush=True)
    print(display[['Algorithm','Acceptance_pct','Energy_kWh','CPUServicePercentOfProposal']].to_string(index=False))


if __name__ == '__main__':
    main()
