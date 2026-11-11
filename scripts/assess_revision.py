"""Audit short revision checks, retain regressions, and plot measured timings."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import vne
from scripts.rank_results import METRICS, rank_means, rankable_results
from scripts.analyze_full_results import archive_source_hash

PROPOSAL = 'ProposedAdaptive'
SERVICE = ['Accepted', 'Rejected', 'Revenue', 'Cost', 'ServedRevenue', 'ServedCost',
           'ServedRequestSeconds', 'ServedCPUUnitSeconds', 'ServedBandwidthUnitSeconds',
           'Energy_Wh', 'BootEnergy_J', 'MeanHops', 'NodeUtil', 'LinkUtil',
           'MeanActiveNodes', 'MeanActiveLinks']


def table(frame):
    def display(value):
        return f'{value:.6g}' if isinstance(value, (float, np.floating)) else str(value)
    return '\n'.join(['| ' + ' | '.join(frame.columns) + ' |',
                     '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |',
                     *['| ' + ' | '.join(display(x) for x in row) + ' |'
                       for row in frame.itertuples(index=False, name=None)]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--timing-after', type=Path, help='Separate serial proposal replay, if supplied')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--completed-run', type=Path)
    parser.add_argument('--original-source', type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(args.before / 'raw.csv', float_precision='round_trip')
    new = pd.read_csv(args.after / 'raw.csv', float_precision='round_trip')
    configs = [json.loads((p / 'config.json').read_text()) for p in (args.before, args.after)]
    for field in ['suite', 'duration', 'workers', 'seeds', 'cases']:
        assert configs[0][field] == configs[1][field], field
    assert not any(c['profile'] for c in configs), 'Profiled calls cannot supply timing evidence'
    keys = ['Case', 'Seed']
    before = old[old.Algorithm.eq(PROPOSAL)].set_index(keys).sort_index()
    after = new[new.Algorithm.eq(PROPOSAL)].set_index(keys).sort_index()
    comparison_after = after
    if args.timing_after:
        replay_config = json.loads((args.timing_after / 'config.json').read_text())
        for field in ['suite', 'duration', 'workers', 'seeds', 'cases', 'source_hashes']:
            assert replay_config[field] == configs[1][field], field
        assert not replay_config['profile']
        comparison_after = pd.read_csv(args.timing_after / 'raw.csv', float_precision='round_trip')
        comparison_after = comparison_after[comparison_after.Algorithm.eq(PROPOSAL)].set_index(keys).sort_index()
        assert comparison_after.index.equals(after.index)
        for field in SERVICE:
            assert np.allclose(after[field], comparison_after[field], rtol=1e-12, atol=1e-9, equal_nan=True), field
    assert before.index.equals(after.index) and not before.index.duplicated().any()
    for field in ['TraceSHA256', 'TopologySHA256', 'NumRequests']:
        if field in before:
            assert before[field].equals(after[field]), field
    for _, group in new.groupby(keys):
        assert group.Algorithm.nunique() == len(configs[1]['methods'])
        assert len(group) == len(configs[1]['methods'])
        assert group.TraceSHA256.nunique() == group.TopologySHA256.nunique() == 1
    identity = {field: bool(np.allclose(before[field], after[field], rtol=1e-12, atol=1e-9, equal_nan=True))
                for field in SERVICE}
    changed = before[SERVICE].compare(after[SERVICE])
    changed.to_csv(output / 'changed_physical_outcomes.csv')
    rows = []
    for case in before.index.get_level_values('Case').unique():
        a, b = before.loc[case], comparison_after.loc[case]
        rows.append(dict(Case=case, BeforeAcceptancePct=a.AcceptanceRatio.mean()*100,
            AfterAcceptancePct=b.AcceptanceRatio.mean()*100,
            BeforeMeanMs=a.MeanEmbeddingTime.mean()*1000, AfterMeanMs=b.MeanEmbeddingTime.mean()*1000,
            MeanReductionPct=(1-b.MeanEmbeddingTime.mean()/a.MeanEmbeddingTime.mean())*100,
            BeforeP99Ms=a.P99EmbeddingTime.mean()*1000, AfterP99Ms=b.P99EmbeddingTime.mean()*1000,
            P99ReductionPct=(1-b.P99EmbeddingTime.mean()/a.P99EmbeddingTime.mean())*100,
            BeforeEnergyWh=a.Energy_Wh.mean(), AfterEnergyWh=b.Energy_Wh.mean(),
            BeforeTotalSeconds=a.ExecutionTime.mean(), AfterTotalSeconds=b.ExecutionTime.mean()))
    differences = pd.DataFrame(rows)
    differences.to_csv(output / 'proposal_changes.csv', index=False)
    work = ['SearchNodes', 'PackingChecks', 'CutChecks', 'QoSBoundBuilds', 'QoSBoundTransitions']
    work_before = before[work].groupby('Case').mean().add_prefix('Before_')
    work_after = after[work + ['HostMatchingRejections']].groupby('Case').mean().add_prefix('After_')
    work_before.join(work_after).to_csv(output / 'search_work.csv')
    rankings = []
    view = rankable_results(new)
    for case, group in [('overall', view), *list(view.groupby('Case'))]:
        means = group.groupby('Algorithm')[[m[0] for m in METRICS]].mean()
        for field, label, ascending, scale, unit in METRICS:
            ranks = rank_means(means[field], ascending)
            ranks['Case'], ranks['Metric'], ranks['MetricLabel'] = case, field, label
            ranks['DisplayMean'], ranks['Unit'] = ranks.Mean*scale, unit
            ranks['DefinedRuns'] = group.groupby('Algorithm')[field].count().reindex(ranks.Algorithm).to_numpy()
            rankings.append(ranks)
    ranked = pd.concat(rankings, ignore_index=True)
    ranked.to_csv(output / 'all_rankings.csv', index=False)
    positions = ranked[ranked.Algorithm.eq(PROPOSAL)]
    positions.to_csv(output / 'proposal_positions.csv', index=False)
    ranked[ranked.Rank.le(5)].to_csv(output / 'top_five.csv', index=False)
    all_means = view.groupby('Algorithm')[[m[0] for m in METRICS]].mean()
    all_means.to_csv(output / 'all_method_means.csv')
    old_config, new_config = configs
    # Comparator decision sources are frozen; algorithms.py may only change
    # scope/metadata. Exact non-time comparator fixtures are checked separately.
    unchanged_sources = {name: old_config['source_hashes'][name] == digest
                         for name, digest in new_config['source_hashes'].items()
                         if name in old_config['source_hashes']}
    audit = dict(rows=len(new), paired_cases=len(after), physical_identity=identity,
                 source_sha256=archive_source_hash(args.after / 'source.zip'),
                 environment=dict(python=sys.version, platform=platform.platform(),
                                  numpy=np.__version__, pandas=pd.__version__, matplotlib=matplotlib.__version__),
                 unchanged_source_files=unchanged_sources,
                 separate_timing_replay=bool(args.timing_after),
                 mean_time_reduction_pct=(1-comparison_after.MeanEmbeddingTime.mean()/before.MeanEmbeddingTime.mean())*100,
                 p99_time_reduction_pct=(1-comparison_after.P99EmbeddingTime.mean()/before.P99EmbeddingTime.mean())*100,
                 total_time_reduction_pct=(1-comparison_after.ExecutionTime.sum()/before.ExecutionTime.sum())*100,
                 before_total_embed_seconds=float(before.ExecutionTime.sum()),
                 after_total_embed_seconds=float(comparison_after.ExecutionTime.sum()))
    bound_text = ''
    if args.completed_run and args.original_source:
        run = args.completed_run.resolve()
        raw_path = run / 'full_evaluation_with_pso_ablations.csv'
        full = pd.read_csv(raw_path, float_precision='round_trip')
        spec = json.loads(raw_path.with_suffix('.config.json').read_text())['spec']
        archive_path = run / 'source.zip'
        if not archive_path.exists():
            with zipfile.ZipFile(args.original_source) as original, \
                    zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as saved:
                for name in original.namelist():
                    saved.writestr(name, original.read(name))
                if 'vne_simulation.py' not in original.namelist():
                    saved.write(ROOT / 'vne_simulation.py', 'vne_simulation.py')
        assert archive_source_hash(archive_path) == spec['source_sha256']
        scenario = vne.Scenario(**spec['scenario'])
        networks = {seed: vne.SubstrateNetwork(spec['num_nodes'], seed=int(seed),
                         **scenario.substrate_kwargs()) for seed in full.Seed.unique()}
        caps = {seed: max(sn.cpu_capacity.values()) for seed, sn in networks.items()}
        p = full[full.Algorithm.eq(PROPOSAL)].copy()
        p['CPUOnlyMinimumEnergyWh'] = scenario.p_peak*p.ServedCPUUnitSeconds/p.Seed.map(caps)/3600
        bound = float(p.CPUOnlyMinimumEnergyWh.mean())
        lowest = full.groupby('Algorithm').Energy_Wh.mean().sort_values()
        best_control_usage = full[full.Algorithm.ne(PROPOSAL)].groupby('Algorithm').NodeUtil.mean().sort_values()
        minimum_usage_coefficient = min(scenario.p_peak*spec['duration_seconds']*
            sum(sn.cpu_capacity.values())/max(sn.cpu_capacity.values())/3600 for sn in networks.values())
        first_usage_minimum_energy = minimum_usage_coefficient*best_control_usage.iloc[-1]
        audit['previous_full_run'] = dict(raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            verified_source_sha256=spec['source_sha256'], minimum_energy_same_cpu_service_wh=bound,
            lowest_energy_method=lowest.index[0], lowest_energy_wh=float(lowest.iloc[0]),
            best_comparator_cpu_usage_method=best_control_usage.index[-1],
            best_comparator_cpu_usage=float(best_control_usage.iloc[-1]),
            minimum_energy_to_equal_best_comparator_mean_cpu_usage_wh=float(first_usage_minimum_energy))
        p[['Lambda', 'Seed', 'Energy_Wh', 'ServedCPUUnitSeconds', 'CPUOnlyMinimumEnergyWh']].to_csv(
            output / 'cpu_service_energy_bound.csv', index=False)
        bound_text = (f'\nThe previous full proposal CPU service has a CPU-only energy lower bound of '
                      f'{bound/1000:.3f} kWh/run, versus {lowest.index[0]} at {lowest.iloc[0]/1000:.3f} kWh/run. '
                      'For each host, idle + linear CPU power is at least peak watts × used CPU / '
                      'maximum host capacity; integrate this over time. Links, transit and boot add '
                      'nonnegative energy. Thus beating that total while retaining the same CPU-service '
                      'volume is impossible in this model. Acceptance counts alone do not fix service volume.\n')
        if first_usage_minimum_energy > lowest.iloc[0]:
            bound_text += (f'\nEven equaling the best unchanged control mean CPU utilization '
                f'({best_control_usage.index[-1]}, {best_control_usage.iloc[-1]*100:.3f}%) requires '
                f'at least {first_usage_minimum_energy/1000:.3f} kWh/run. This uses the minimum '
                'CPU-energy/utilization coefficient over the 30 substrates, so it holds for any '
                'distribution of CPU usage across those cases. Consequently rank one in both '
                'mean CPU utilization (highest usage) and total energy (lowest energy) is '
                'mathematically incompatible on that completed grid against the unchanged controls.\n')
    (output / 'validation.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(differences))
    for axis, left, right, label in [(axes[0], 'BeforeMeanMs', 'AfterMeanMs', 'Mean embedding time (ms)'),
                                    (axes[1], 'BeforeP99Ms', 'AfterP99Ms', 'Mean run-level P99 (ms)')]:
        axis.bar(x-.19, differences[left], .38, label='Previous proposal', color='#838d9b')
        axis.bar(x+.19, differences[right], .38, label='Updated proposal', color='#228b76')
        axis.set_xticks(x, differences.Case, rotation=30, ha='right')
        axis.set_ylabel(label)
        axis.grid(axis='y', alpha=.2)
        axis.set_axisbelow(True)
        axis.legend(frameon=False)
    figure.suptitle(f"Short diagnostics: {len(configs[1]['seeds'])} seeds/scenario; serial execution; descriptive timings")
    figure.tight_layout()
    figure.savefig(output / 'timing_comparison.png', dpi=180)
    figure.savefig(output / 'timing_comparison.svg')
    plt.close(figure)
    overall = positions[positions.Case.eq('overall')][['MetricLabel', 'Rank', 'DisplayMean', 'Unit', 'DefinedRuns']]
    report = ('# Proposal revision assessment\n\n'
              f'{len(after)} paired short cases; {len(new)} observations; {new.Algorithm.nunique()} methods. '
              'Same topology/request hashes, strict active-state validation and serial execution. '
              'Development and reserved checks are separate; no statistical superiority is claimed.\n\n'
              + ('Timing changes use separate old/new proposal-only replays; all-method ranks use '
                 'the common 32-method diagnostic run. Neither is compared directly with the '
                 'earlier four-worker timings.\n\n' if args.timing_after else '')
              +
              '## Previous versus updated proposal\n\n' + table(differences) + '\n\n'
              + f'Physical outcomes identical within floating tolerance: {all(identity.values())}. '
              'The validation JSON lists each field and source identity. P99 values are means of '
              'per-run percentiles, not a pooled percentile.\n\n'
              '## Updated proposal ranks\n\n' + table(overall) + '\n\n'
              + bound_text + '\n'
              'All per-scenario rankings and top-five lists are retained in CSVs. Higher utilization '
              'is usage, not necessarily quality. Short finite-horizon outcomes can differ from the '
              'previous 20,000-second experiment. Published-method fidelity is limited to the '
              'documented pinned Virne ports/adaptations and custom controls.\n\n'
              'The objective of rank one on every metric is not established. No algorithm, scenario, '
              'energy accounting or rejected workload is hidden to manufacture that conclusion. '
              'Run the new full protocol before making publication claims.\n')
    (output / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps(audit, indent=2))
    print(overall.to_string(index=False))


if __name__ == '__main__':
    main()
