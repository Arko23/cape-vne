"""Validated per-load rankings of all recorded evaluation metrics.

Ranks describe mean outcomes, not statistical separation or an overall winner.
Utilization is ranked by highest usage for inspection, not intrinsic quality.
Quality ratios/hops are undefined for runs with no admitted/served work; the
recorded zero placeholders must not become a shortest-route ranking victory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from scripts.analyze_full_results import validate_raw, verify_summary, verify_statistics, primary_methods
from vne import REFERENCE_ALGORITHMS
from vne.experiments import analytical_results

PROPOSAL = 'ProposedAdaptive'
PRIMARY = [PROPOSAL, 'GRC', 'NodeRank', 'GreedyKSP', 'EnergyAware', 'PSO']
ALIASES = {
    PROPOSAL: 'P', 'GRC': 'GRC', 'NodeRank': 'NR', 'GreedyKSP': 'GK',
    'EnergyAware': 'EA', 'PSO': 'PSO', 'ProposedGreedy': 'PG',
    'GRCRankedSearch': 'GS', 'NodeRankSearch': 'NS', 'GreedyCSP': 'GC',
    'GRCScoreOnly': 'GSO', 'NodeRankScoreOnly': 'NSO', 'NoExactPacking': 'NEP',
    'NoCutPruning': 'NCP', 'FixedEnergyWeight': 'FEW', 'AlwaysJointRouting': 'AJ',
    'NoJointRepair': 'NJ', 'FullHopFootprint': 'FH', 'EagerPacking': 'EP',
    'EagerPathGeneration': 'EPG', 'ConflictRepair': 'CR', 'QoSBoundRouting': 'QB',
    'LegacyAdaptive': 'LA', 'CompactNoRepair': 'CNR', 'FullJointRepair': 'FJR',
    'NoCompactPlacement': 'NCL', 'GreenCostRouting': 'GCR',
    'VirneGRC': 'VG', 'VirneRWMaxMatch': 'VR', 'VirneRWBFS': 'VB',
    'VirneFFD': 'VF', 'VirnePSO': 'VP'}
# column, readable name, ascending preference, display scale, unit
METRICS = [
    ('AcceptanceRatio', 'Acceptance', False, 100, '%'),
    ('R_C', 'Admission revenue/cost', False, 1, 'ratio'),
    ('Served_R_C', 'Served revenue/cost', False, 1, 'ratio'),
    ('Energy_Wh', 'Total energy', True, 1, 'Wh'),
    ('EnergyPerAccepted_Wh', 'Energy/accepted request', True, 1, 'Wh/request'),
    ('EnergyPerServedRequestSecond_Wh', 'Energy/served request-second', True, 1, 'Wh/request-second'),
    ('EnergyPerServedCPUUnitSecond_Wh', 'Energy/served CPU-second', True, 1, 'Wh/CPU-unit-second'),
    ('EnergyPerServedBandwidthUnitSecond_Wh', 'Energy/served BW-second', True, 1, 'Wh/BW-unit-second'),
    ('MeanEmbeddingTime', 'Mean embedding time', True, 1000, 'ms'),
    ('P95EmbeddingTime', 'P95 embedding time', True, 1000, 'ms'),
    ('P99EmbeddingTime', 'P99 embedding time', True, 1000, 'ms'),
    ('ExecutionTime', 'Total embedding time', True, 1, 'seconds'),
    ('MeanHops', 'Mean hops', True, 1, 'hops'),
    ('NodeUtil', 'CPU utilization (highest usage)', False, 100, '%'),
    ('LinkUtil', 'BW utilization (highest usage)', False, 100, '%')]


def rank_means(values, ascending):
    """Competition rank: 1,1,1,1,5. Only numerical roundoff is tied.

    Alphabetical ordering inside a tied group is presentation only. Boundary
    ties are included in full top-five files rather than arbitrarily dropped.
    """
    ordered = values.dropna().sort_values(ascending=ascending, kind='stable')
    ranks, anchor, group_rank = {}, None, None
    for slot, (name, value) in enumerate(ordered.items(), 1):
        if anchor is None or not np.isclose(value, anchor, rtol=1e-12, atol=1e-12):
            anchor, group_rank = value, slot
        ranks[name] = group_rank
    result = pd.DataFrame({'Algorithm': ordered.index, 'Mean': ordered.to_numpy(),
                           'Rank': [ranks[name] for name in ordered.index]})
    return result.sort_values(['Rank', 'Algorithm']).reset_index(drop=True)


def rankable_results(raw):
    """Return an analytical view; preserve the simulator's original raw rows."""
    return analytical_results(raw)


def position(table, name):
    selected = table[table.Algorithm.eq(name)]
    return selected.iloc[0] if len(selected) else pd.Series(
        {'Rank': np.nan, 'Mean': np.nan, 'DisplayMean': np.nan})


def rank_number(value):
    return int(value) if pd.notna(value) else np.nan


def rank_label(value):
    return str(int(value)) if pd.notna(value) else 'undefined'


def top_five(frame, aliases=False, values=False):
    selected = frame[frame.Rank.le(5)]
    groups = []
    for rank, group in selected.groupby('Rank', sort=True):
        names = [ALIASES.get(name, name) if aliases else name for name in group.Algorithm]
        if len(names) > 1:
            label = '='.join(names)
        else:
            label = names[0]
        if values:
            label += f" ({group.DisplayMean.iloc[0]:.6g})"
        groups.append(label)
    return ' > '.join(groups) or 'undefined'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--source-archive', type=Path,
                        help='Validate historical data against its matching source ZIP')
    args = parser.parse_args()
    directory = args.directory.resolve()
    raw_hash = hashlib.sha256((directory/'full_evaluation_with_pso_ablations.csv').read_bytes()).hexdigest()
    raw, spec, loads, seeds = validate_raw(directory, args.source_archive)
    summary = pd.read_csv(directory/'summary_with_pso_ablations.csv', float_precision='round_trip')
    statistical = pd.read_csv(directory/'statistics_with_pso_ablations.csv', float_precision='round_trip')
    checked_summary = verify_summary(raw, summary)
    checked_statistics = verify_statistics(raw, statistical)
    if set(summary.Metric) != {entry[0] for entry in METRICS}:
        raise ValueError('Metric registry differs from the recorded summary')
    columns = [entry[0] for entry in METRICS]
    analytical = rankable_results(raw)
    means = analytical.groupby(['Lambda', 'Algorithm'])[columns].mean()
    defined = analytical.groupby(['Lambda', 'Algorithm'])[columns].count()
    rankings, primary_rankings, compact, proposal_positions = [], [], [], []
    cohort = primary_methods(raw)
    for load in sorted(loads):
        for metric, label, ascending, scale, unit in METRICS:
            values = means.loc[load, metric]
            ranks = rank_means(values, ascending)
            ranks['Lambda'], ranks['Metric'], ranks['MetricLabel'] = load, metric, label
            ranks['Direction'] = 'lower' if ascending else 'higher'
            ranks['DisplayMean'], ranks['DisplayUnit'] = ranks.Mean*scale, unit
            ranks['DefinedSeeds'] = defined.loc[load, metric].reindex(ranks.Algorithm).to_numpy()
            rankings.append(ranks)
            primary = rank_means(values.reindex(cohort), ascending)
            primary['Lambda'], primary['Metric'] = load, metric
            primary_rankings.append(primary)
            ours = position(ranks, PROPOSAL)
            our_primary = position(primary, PROPOSAL)
            tied_names = ranks[ranks.Rank.eq(ours.Rank)].Algorithm.tolist()
            winners = ranks[ranks.Rank.eq(1)].Algorithm.tolist()
            proposal_positions.append(dict(Lambda=load, Metric=metric, MetricLabel=label,
                ProposalRank=rank_number(ours.Rank), Methods=len(ranks), PrimaryRank=rank_number(our_primary.Rank),
                ProposalMean=ours.Mean, DisplayMean=ours.DisplayMean, Unit=unit,
                TiedAlgorithms=';'.join(tied_names), MeanLeaders=';'.join(winners)))
            compact.append(dict(Lambda=load, Metric=metric, Label=label,
                TopFive=top_five(ranks, aliases=True), OurRank=rank_number(ours.Rank),
                OurValue=ours.DisplayMean, Unit=unit, Tied=len(tied_names) > 1))
    out = directory/'rankings'
    out.mkdir(exist_ok=True)
    all_ranks = pd.concat(rankings, ignore_index=True)
    all_ranks.to_csv(out/'all_rankings.csv', index=False)
    all_ranks[all_ranks.Rank.le(5)].to_csv(out/'top_five.csv', index=False)
    pd.concat(primary_rankings, ignore_index=True).to_csv(out/'primary_only_rankings.csv', index=False)
    proposal = pd.DataFrame(proposal_positions)
    proposal.to_csv(out/'proposal_positions.csv', index=False)
    compact = pd.DataFrame(compact)
    compact.to_csv(out/'compact_tables.csv', index=False)
    report = ['# Latest full-run scenario and metric rankings', '',
        f'{len(loads)} arrival loads ×{len(seeds)} seeds ×{len(spec["algorithms"])} methods = {len(raw):,} validated rows. '
        f'Fixed substrate: {spec["num_nodes"]} nodes; horizon: {spec["duration_seconds"]:g} seconds; '
        f'workers: {spec["workers"]}. Source `{spec["source_sha256"]}`.', '',
        'A scenario here means arrival load, measured in requests per100 seconds. '
        'Density, sizes, QoS, demand distributions, power and lifetimes were not varied. '
        f'All means average the{len(seeds)} seeds equally within load. '
        f'Ranks compare all{len(spec["algorithms"])} methods, '
        'including proposal ablations and experimental variants.', '',
        f'The primary cohort for this report is: {", ".join(cohort)}. '
        'Reference-code ports and their common-model extensions are described in REFERENCES.md.', '',
        'Ties share competition rank (e.g.1,1,1,1,5); alphabetical order inside a tie has no performance meaning. '
        '`=` denotes a numerical tie, while `>` orders methods by the stated metric preference. '
        'Boundary ties are included even if more than five methods appear. Rankings are descriptive; '
        'nearby ranks are not necessarily statistically separated. CPU/BW utilization lists highest usage, '
        'which is not intrinsically better. Lower total energy may mean less admitted service; '
        'mean hops is conditional on the admitted requests. No-admission runs have undefined hops/admission R/C; '
        'zero-served-cost runs have undefined served R/C. Their raw zero placeholders are excluded from '
        'quality averages/ranks, and DefinedSeeds records the number of contributing runs. '
        'Methods with no defined value are unranked for that metric; all raw results remain unchanged. '
        'P95/P99 values are means of per-run percentiles, '
        'not pooled request-level percentiles.', '',
        '## Proposal positions', '',
        '| Metric | '+' | '.join(f'λ{load:g}' for load in sorted(loads))+' |',
        '|---|'+'---:|'*len(loads)]
    for metric, label, ascending, scale, unit in METRICS:
        rows = proposal[proposal.Metric.eq(metric)].set_index('Lambda')
        report.append('| '+label+(' ↓' if ascending else ' ↑')+' | '+
            ' | '.join(rank_label(rows.loc[load, 'ProposalRank']) +
                (' (tied)' if ';' in rows.loc[load, 'TiedAlgorithms'] else '') for load in sorted(loads))+' |')
    for load in sorted(loads):
        report += ['', f'## Arrival load {load:g} requests/100 seconds', '',
            f'| Metric | Top five methods (rank order; values in stated units) | Proposal rank/{len(spec["algorithms"])} | Proposal value |',
            '|---|---|---:|---:|']
        for metric, label, ascending, scale, unit in METRICS:
            ranks = all_ranks[all_ranks.Lambda.eq(load) & all_ranks.Metric.eq(metric)]
            ours = proposal[proposal.Lambda.eq(load) & proposal.Metric.eq(metric)].iloc[0]
            report.append(f"| {label} {'↓' if ascending else '↑'} ({unit}) | {top_five(ranks, values=True)} | "
                f"{rank_label(ours.ProposalRank)}{' (tied)' if ';' in ours.TiedAlgorithms else ''} | "
                f"{format(ours.DisplayMean, '.6g') if pd.notna(ours.DisplayMean) else 'undefined'} |")
    report += ['', '## Paired checks of relevant controls', '',
        f'The following comparisons use the run\'s seed-paired Wilcoxon tests and BH correction '
        f'across{statistical.p_value.notna().sum()} valid tests. '
        'Only comparisons against ProposedAdaptive exist; other methods\' ordinal ranks are not pairwise significance claims.', '',
        '| Control | Metric | Loads favoring proposal (q<0.05) | Loads favoring control (q<0.05) | Remaining loads |',
        '|---|---|---|---|---|']
    for name in ('LegacyAdaptive', 'CompactNoRepair', 'FullJointRepair', 'NoCompactPlacement',
                 'GreenCostRouting', 'QoSBoundRouting', 'NoJointRepair', 'NoExactPacking',
                 'ConflictRepair', 'AlwaysJointRouting'):
        if name not in spec['algorithms']:
            continue
        for metric, label, ascending, *_ in METRICS[:3] + [METRICS[5], METRICS[8]]:
            subset = statistical[statistical.Baseline.eq(name) & statistical.Metric.eq(metric)]
            preferred = -subset.mean_paired_difference if ascending else subset.mean_paired_difference
            good = subset[subset.q_value.lt(.05) & preferred.gt(1e-9)].Lambda.tolist()
            bad = subset[subset.q_value.lt(.05) & preferred.lt(-1e-9)].Lambda.tolist()
            remaining = sorted(set(loads)-set(good)-set(bad))
            fmt = lambda items: ', '.join(f'{value:g}' for value in items) or 'none'
            report.append(f'| {name} | {label} | {fmt(good)} | {fmt(bad)} | {fmt(remaining)} |')
    scope = ('The primary competitors are pinned Virne ports with documented QoS and execution adaptations.'
             if set(REFERENCE_ALGORITHMS).issubset(spec['algorithms'])
             else 'GRC/NodeRank are ranking adaptations; the other primary baselines are custom policies.')
    report += ['', f'Runtime reflects {spec["workers"]} worker(s). {scope} This run does not establish superiority over '
        'unrun complete published methods, real-topology generalization or novelty.', '',
        'Machine-readable outputs: [all ranks](all_rankings.csv), [top five including ties](top_five.csv), '
        '[proposal positions](proposal_positions.csv) and [six-method primary-only ranks](primary_only_rankings.csv).']
    (out/'REPORT.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    validation = dict(raw_sha256=raw_hash, source_sha256=spec['source_sha256'], rows=len(raw),
        summary_rows_verified=checked_summary, statistics=checked_statistics, methods=len(spec['algorithms']),
        loads=sorted(loads), seeds=sorted(seeds), rank_definition='competition, numerical ties at rtol/atol1e-12')
    if hashlib.sha256((directory/'full_evaluation_with_pso_ablations.csv').read_bytes()).hexdigest() != raw_hash:
        raise ValueError('Raw input changed during ranking')
    (out/'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    print(proposal.pivot(index='MetricLabel', columns='Lambda', values='ProposalRank').to_string())
    print('Raw, summary, source/inputs and paired statistics verified. Ranking report: '+str(out/'REPORT.md'))


if __name__ == '__main__':
    main()
