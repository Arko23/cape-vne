"""Reconstruct common inputs and summarize the completed frozen experiment.

This analyzes recorded outcomes only; no embedding evaluation or policy tuning.
Run with the repository's tested Python environment.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import vne
import numpy as np
import pandas as pd
from scripts.analyze_full_results import validate_raw
from scripts.rank_results import METRICS, rank_means
from vne.experiments import analytical_results, _trace_sha256, _topology_sha256

RUN = Path(__file__).resolve().parents[1]
OUT = RUN / 'analysis'
PROPOSAL = 'ProposedAdaptive'


def table(frame):
    columns = frame.columns.tolist()
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
    for row in frame.itertuples(index=False, name=None):
        lines.append('| ' + ' | '.join(str(value) for value in row) + ' |')
    return '\n'.join(lines)


def main():
    raw, spec, loads, seeds = validate_raw(RUN)
    raw_path = RUN / 'full_evaluation_with_pso_ablations.csv'
    original_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    scenario = vne.Scenario(**spec['scenario'])
    networks = {seed: vne.SubstrateNetwork(spec['num_nodes'], seed=seed,
                **scenario.substrate_kwargs()) for seed in seeds}
    reconstructed = 0
    max_cpu_error = max_bw_error = max_revenue_error = 0.
    min_energy_margin = float('inf')
    offered_requests = 0
    for (load, seed), group in raw.groupby(['Lambda', 'Seed']):
        network = networks[int(seed)]
        trace = vne.generate_trace(float(load), spec['duration_seconds'], int(seed), scenario.generator())
        if (not group.TraceSHA256.eq(_trace_sha256(trace)).all()
                or not group.TopologySHA256.eq(_topology_sha256(network)).all()
                or not group.NumRequests.eq(len(trace)).all()):
            raise ValueError('Regenerated inputs disagree with the recorded case')
        reconstructed += 1
        offered_requests += len(trace)
        cpu = group.NodeUtil * spec['duration_seconds'] * sum(network.cpu_capacity.values())
        routed_bw = group.LinkUtil * spec['duration_seconds'] * sum(network.bandwidth_capacity.values())
        np.testing.assert_allclose(cpu, group.ServedCPUUnitSeconds, rtol=1e-10, atol=1e-7)
        np.testing.assert_allclose(routed_bw, group.ServedCost - group.ServedCPUUnitSeconds, rtol=1e-10, atol=1e-7)
        np.testing.assert_allclose(group.ServedRevenue, group.ServedCPUUnitSeconds + group.ServedBandwidthUnitSeconds,
                                   rtol=1e-10, atol=1e-7)
        max_cpu_error = max(max_cpu_error, float(np.max(np.abs(cpu - group.ServedCPUUnitSeconds))))
        max_bw_error = max(max_bw_error, float(np.max(np.abs(routed_bw - group.ServedCost + group.ServedCPUUnitSeconds))))
        max_revenue_error = max(max_revenue_error, float(np.max(np.abs(group.ServedRevenue - group.ServedCPUUnitSeconds - group.ServedBandwidthUnitSeconds))))
        idle = scenario.p_idle * group.MeanActiveNodes * spec['duration_seconds'] / 3600
        links = scenario.p_link * group.MeanActiveLinks * spec['duration_seconds'] / 3600
        boot = group.BootEnergy_J / 3600
        dynamic = group.Energy_Wh - idle - links - boot
        factor = (scenario.p_peak - scenario.p_idle) / 3600
        low = factor * group.ServedCPUUnitSeconds / max(network.cpu_capacity.values())
        high = factor * group.ServedCPUUnitSeconds / min(network.cpu_capacity.values())
        tolerance = 1e-9 * np.maximum(1, group.Energy_Wh)
        if not ((dynamic >= low - tolerance) & (dynamic <= high + tolerance)).all():
            raise ValueError('Energy balance violates independently bounded CPU power')
        min_energy_margin = min(min_energy_margin, float((dynamic - low).min()), float((high - dynamic).min()))

    columns = [entry[0] for entry in METRICS]
    view = analytical_results(raw)
    means = view.groupby('Algorithm')[columns].mean()
    rankings = []
    rank_summary = []
    positions = pd.read_csv(RUN / 'rankings/proposal_positions.csv')
    for metric, label, ascending, scale, unit in METRICS:
        ranking = rank_means(means[metric], ascending)
        ranking['Metric'] = metric
        ranking['DisplayMean'] = ranking.Mean * scale
        ranking['Unit'] = unit
        rankings.append(ranking)
        ours = ranking[ranking.Algorithm.eq(PROPOSAL)].iloc[0]
        by_load = positions[positions.Metric.eq(metric)].sort_values('Lambda')
        rank_summary.append(dict(Metric=label, Value=float(ours.DisplayMean), Unit=unit,
            OverallRank=int(ours.Rank), PerLoadRanks='/'.join(by_load.ProposalRank.astype(int).astype(str)),
            TopFiveLoads=int(by_load.ProposalRank.le(5).sum()),
            MeanLeader=';'.join(ranking.loc[ranking.Rank.eq(1), 'Algorithm'])))
    all_rankings = pd.concat(rankings, ignore_index=True)
    all_rankings.to_csv(OUT / 'overall_all_metric_rankings.csv', index=False)
    all_rankings[all_rankings.Rank.le(5)].to_csv(OUT / 'overall_top_five.csv', index=False)
    rank_summary = pd.DataFrame(rank_summary)
    rank_summary.to_csv(OUT / 'proposal_metric_assessment.csv', index=False)
    means.to_csv(OUT / 'all_metric_means.csv')
    selected = [PROPOSAL, *vne.REFERENCE_ALGORITHMS, 'GRC', 'NodeRank', 'GreedyKSP', 'EnergyAware', 'PSO',
                'FullJointRepair', 'CompactNoRepair', 'GreenCostRouting']
    comparison = means.loc[selected, ['AcceptanceRatio', 'Energy_Wh', 'EnergyPerServedRequestSecond_Wh',
                                     'MeanEmbeddingTime', 'MeanHops']].reset_index()
    comparison.AcceptanceRatio *= 100
    comparison.MeanEmbeddingTime *= 1000
    comparison.rename(columns={'AcceptanceRatio': 'AcceptancePercent', 'MeanEmbeddingTime': 'EmbeddingMs'}, inplace=True)
    comparison.to_csv(OUT / 'comparison_for_user.csv', index=False)

    statistical = pd.read_csv(RUN / 'statistics_with_pso_ablations.csv', float_precision='round_trip')
    significance = []
    important = ['AcceptanceRatio', 'EnergyPerServedRequestSecond_Wh', 'EnergyPerServedCPUUnitSecond_Wh',
                 'EnergyPerServedBandwidthUnitSecond_Wh', 'MeanEmbeddingTime']
    for (baseline, metric), group in statistical[statistical.Metric.isin(important)].groupby(['Baseline', 'Metric']):
        direction = group.mean_paired_difference if metric == 'AcceptanceRatio' else -group.mean_paired_difference
        better = group[group.q_value.lt(.05) & direction.gt(0)].Lambda.tolist()
        worse = group[group.q_value.lt(.05) & direction.lt(0)].Lambda.tolist()
        remaining = sorted(set(loads) - set(better) - set(worse))
        fmt = lambda values: ','.join(f'{value:g}' for value in values) or 'none'
        significance.append(dict(Baseline=baseline, Metric=metric, BetterLoads=fmt(better),
            WorseLoads=fmt(worse), OtherLoads=fmt(remaining)))
    significance = pd.DataFrame(significance)
    significance.to_csv(OUT / 'significant_loads_for_user.csv', index=False)
    pooled = raw.groupby('Algorithm')[['Accepted', 'NumRequests', 'Energy_Wh', 'ExecutionTime',
              'ServedRequestSeconds', 'ServedCPUUnitSeconds', 'ServedBandwidthUnitSeconds']].sum()
    pooled['AcceptancePercent'] = pooled.Accepted / pooled.NumRequests * 100
    pooled['EmbeddingMs'] = pooled.ExecutionTime / pooled.NumRequests * 1000
    pooled['EnergyPerServedSecond_Wh'] = pooled.Energy_Wh / pooled.ServedRequestSeconds
    pooled.to_csv(OUT / 'service_volume_totals.csv')
    audit = dict(reconstructed_case_inputs=reconstructed, offered_requests=offered_requests,
        distinct_topologies=int(raw.TopologySHA256.nunique()), distinct_traces=int(raw.TraceSHA256.nunique()),
        rows=len(raw), source_sha256=spec['source_sha256'], raw_sha256=original_hash,
        max_served_cpu_identity_absolute_error=max_cpu_error, max_routed_bandwidth_identity_absolute_error=max_bw_error,
        max_served_revenue_identity_absolute_error=max_revenue_error, minimum_cpu_energy_bound_margin_Wh=min_energy_margin,
        raw_rows_modified=False, embedding_simulation_rerun=False)
    (OUT / 'independent_input_and_energy_audit.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')

    display = comparison.copy()
    for name, precision in [('AcceptancePercent', 3), ('Energy_Wh', 1),
                            ('EnergyPerServedRequestSecond_Wh', 6), ('EmbeddingMs', 3), ('MeanHops', 3)]:
        display[name] = display[name].map(lambda value: f'{value:.{precision}f}')
    rank_display = rank_summary.copy()
    rank_display.Value = rank_display.Value.map(lambda value: f'{value:.6g}')
    load_rows = positions[positions.Metric.eq('AcceptanceRatio')][['Lambda', 'DisplayMean', 'ProposalRank', 'MeanLeaders']].copy()
    load_rows.rename(columns={'DisplayMean': 'AcceptancePercent', 'ProposalRank': 'AcceptanceRank'}, inplace=True)
    load_rows.AcceptancePercent = load_rows.AcceptancePercent.map(lambda value: f'{value:.3f}')
    for metric, label in [('MeanEmbeddingTime', 'TimeRank'), ('EnergyPerServedRequestSecond_Wh', 'EnergyPerServiceRank'),
                          ('Energy_Wh', 'TotalEnergyRank'), ('MeanHops', 'HopsRank')]:
        load_rows[label] = positions[positions.Metric.eq(metric)].set_index('Lambda').ProposalRank.reindex(load_rows.Lambda).to_numpy()
    selected_significance = significance[significance.Baseline.isin(selected[1:])]
    sections = ['# Completed run assessment', '',
        'Validated 6 loads ×30 seeds ×32 methods = 5,760 rows; 50 nodes, 20,000 seconds, 4 concurrent workers. '
        'All 180 topology/request cases were regenerated and their recorded hashes and request counts matched. '
        'Served-resource identities and independent CPU-energy bounds passed. No simulation was rerun or policy changed.', '',
        '## Proposal and competitors', '',
        'Values below average 180 run-level metrics equally. Energy is modeled Wh per 20,000-second run. '
        'Normalized energy is Wh per served virtual-request-second. This is distinct from pooling all arrivals/service.', '',
        table(display), '', '## All-metric proposal assessment', '',
        'Competition ranks among all 32 methods. Per-load order is 2/4/6/8/10/12 requests per100 seconds. '
        'The mean of run-level P95/P99 measurements is not a pooled percentile. Utilization ranks indicate usage, not intrinsic quality.', '',
        table(rank_display), '', '## Load-specific performance', '', table(load_rows), '',
        'At load 12, GreenCostRouting leads acceptance by only 0.0039 percentage points; the paired difference is nonsignificant '
        '(BH q≈0.954). The proposal remains second by the numerical mean rank.', '',
        '## Paired evidence', '',
        'Better/Worse refer to within-load, seed-paired comparisons against the proposal with BH q<0.05 over the original 2,604 tests. '
        'Other includes nonsignificant comparisons. No across-load significance test or pairwise tests between other methods are claimed.', '',
        table(selected_significance), '', '## Interpretation and limits', '',
        '- Strongest result: highest average acceptance; mean rank 1 at five loads and a near-tie at load 12. '
        'It accepts 170,002 of 249,322 requests pooled (68.186%); the equal-load/run acceptance mean is 76.750%.',
        '- Service/resource efficiency is strong: energy per served CPU-second ranks 1 at loads 4–12 and 2 at load 2; '
        'energy per served virtual-bandwidth-second ranks 1 at every load.',
        '- Embedding time ranks 6–9 and total energy ranks 32 at loads 4–12. The goal of top-five placement on every metric is not met. '
        'More admitted/served demand means total energy and utilization require interpretation alongside service volume.',
        '- GreenCostRouting is the closest efficiency control: it has lower mean energy per served request-second '
        'and significantly lower values at loads 2,8,10,12. VirnePSO has significantly lower values at load 12; '
        'the load 10 difference is nonsignificant. Thus normalized energy is not universally best.',
        '- The proposal is significantly faster than all three compact controls at every load. It is significantly slower '
        'than the four non-PSO Virne ports and GreedyCSP at every load. Against GreedyKSP the time result depends on load.',
        '- Current proposal versus NoExactPacking favors the proposal for acceptance, normalized service energy and runtime '
        'at all six loads, but NoExactPacking uses the previous engine: these differences do not isolate an exact-packing contribution.',
        '- The five Virne competitors are pinned reference-code ports with documented QoS and execution adaptations. '
        'GRC/NodeRank are ranking adaptations; GreedyKSP/EnergyAware/PSO are custom baselines. '
        'These results do not verify complete published-method reproduction.',
        '- Four concurrent workers were used; embedding time excludes construction and simulator overhead. '
        'The energy model excludes algorithm-computation electricity. One fixed synthetic density/workload/power scenario '
        'with 30 seeded topologies does not establish real-topology generalization or literature novelty.', '',
        '## Files', '',
        '[All-method per-load rankings](../rankings/REPORT.md), [original comparison report](REPORT.md), '
        '[comparison chart](primary_comparison.png), [overall top five](overall_top_five.csv), '
        '[independent input/energy audit](independent_input_and_energy_audit.json), '
        '[all mean metrics](all_metric_means.csv), [pooled service volumes](service_volume_totals.csv).']
    (OUT / 'USER_SUMMARY.md').write_text('\n'.join(sections) + '\n', encoding='utf-8')
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != original_hash:
        raise ValueError('Raw data changed during this assessment')
    print(json.dumps(audit, indent=2))
    print(rank_summary.to_string(index=False))
    print(comparison.to_string(index=False))
    print('POOLED PROPOSAL:', pooled.loc[PROPOSAL].to_json())


if __name__ == '__main__':
    main()
