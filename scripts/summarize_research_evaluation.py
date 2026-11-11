"""Descriptive per-topology/load ranks and current-engine ablation effects."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from vne.experiments import analytical_results


METRICS = [('AcceptanceRatio',False),('Energy_Wh',True),
           ('EnergyPerServedCPUUnitSecond_Wh',True),('EnergyPerServedBandwidthUnitSecond_Wh',True),
           ('MeanEmbeddingTime',True),('P99EmbeddingTime',True),('ExecutionTime',True),
           ('MeanHops',True),('R_C',False)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args = parser.parse_args()
    root = args.directory
    config = json.loads((root/'config.json').read_text(encoding='utf-8'))
    frame = analytical_results(pd.read_csv(root/'raw.csv',float_precision='round_trip'))
    expected = {(c['name'],load,seed,method) for c in config['inputs'] for load in config['lambdas']
                for seed in config['seeds'] for method in config['methods']}
    assert len(frame) == len(expected)
    assert set(zip(frame.Case,frame.Lambda,frame.Seed,frame.Algorithm)) == expected
    ranks,effects,proposal = [],[],[]
    for (case,load),group in frame.groupby(['Case','Lambda']):
        means = group.groupby('Algorithm')[[m for m,_ in METRICS]].mean()
        p = means.loc['ProposedAdaptive']
        summary = dict(Case=case,Lambda=load,AcceptancePercent=p.AcceptanceRatio*100)
        for metric,lower in METRICS:
            position = means[metric].rank(ascending=lower,method='min')
            summary[metric+'_rank'] = position['ProposedAdaptive']
            for method,value in means[metric].items():
                ranks.append(dict(Case=case,Lambda=load,Metric=metric,Algorithm=method,Mean=value,
                                  Rank=position[method],ValidRuns=int(group[group.Algorithm.eq(method)][metric].notna().sum())))
        proposal.append(summary)
        for method in config['ablation_switches']:
            c = means.loc[method]
            effects.append(dict(Case=case,Lambda=load,Control=method,
                AcceptanceDifference_pp=(c.AcceptanceRatio-p.AcceptanceRatio)*100,
                EnergyPerCPUChange_pct=(c.EnergyPerServedCPUUnitSecond_Wh/p.EnergyPerServedCPUUnitSecond_Wh-1)*100,
                MeanTimeChange_pct=(c.MeanEmbeddingTime/p.MeanEmbeddingTime-1)*100,
                Note='Control minus proposal; positive acceptance/lower time/energy favors control'))
    pd.DataFrame(ranks).to_csv(root/'ranks.csv',index=False)
    pd.DataFrame(effects).to_csv(root/'current_ablation_effects.csv',index=False)
    pd.DataFrame(proposal).to_csv(root/'proposal_ranks.csv',index=False)
    lines = ['# Descriptive external-topology / current-ablation check','',
        f'{len(frame)} rows; {len(config["seeds"])} seeds per topology/load; '
        f'{config["duration"]:g} simulated seconds; {len(config["methods"])} methods; one worker.','',
        'These short tests validate the added evaluation path and reveal failures. '
        'They do not establish publication significance. Every method receives the same imported adjacency, '
        'synthetic capacities/delay, trace, QoS, power model and horizon within each case.', '',
        '| Topology | Load /100s | Acceptance % | Acceptance rank | Total energy rank | Energy/CPU rank | Mean time rank | P99 rank | Hops rank |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in proposal:
        lines.append(f'| {r["Case"]} | {r["Lambda"]:g} | {r["AcceptancePercent"]:.2f} | '
                     + ' | '.join(f'{r[m+"_rank"]:.0f}' for m in
                       ['AcceptanceRatio','Energy_Wh','EnergyPerServedCPUUnitSecond_Wh','MeanEmbeddingTime','P99EmbeddingTime','MeanHops']) + ' |')
    lines += ['', 'Ranks use equal seed-weighted means, minimum rank for ties and omit undefined no-service quality. '
        'P99 ranks compare mean run-level P99 values. Absolute energy must be read with served resource-time and '
        'admission; lower energy from serving fewer requests is not equal-service superiority.', '',
        '## Consequence','',
        'The maintained proposal is competitive on admissions in several cases but is not uniformly strong on '
        'small/sparse imported networks. High-load Abilene and mean/tail time are clear failure cases. '
        'CPU-normalized energy ranks also deteriorate on some low-load sparse graphs. Do not present the earlier '
        'dense synthetic results as broad topology robustness or an overall winner.', '',
        'All 32 maintained methods remain present. The eight additional current-engine switches are controls, '
        'not published algorithms. Their per-case effects are in current_ablation_effects.csv; all method/metric '
        'means and ranks are in ranks.csv. Per-topology summary and paired-test files are reconstructed by the '
        'evaluation harness. Two seeds are insufficient for useful confirmatory significance conclusions.', '',
        'The next policy study must explain sparse feasible-domain/routing conflicts on development traces, '
        'then freeze its policy before fresh confirmation. Use run.md for the separate 30-seed commands. '
        'No additional full experiment was launched here.']
    (root/'ANALYSIS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(pd.DataFrame(proposal).to_string(index=False))


if __name__ == '__main__':
    main()
