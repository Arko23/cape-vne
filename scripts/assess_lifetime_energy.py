"""Validate the recorded prototype trial and expose improvements/regressions."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scripts.analyze_full_results import archive_source_hash


METRICS = [('AcceptanceRatio','Acceptance (%)',100,False),
           ('Energy_Wh','Total energy (Wh)',1,True),
           ('EnergyPerServedCPUUnitSecond_Wh','Wh / CPU-unit-second',1,True),
           ('MeanEmbeddingTime','Mean embed (ms)',1000,True),
           ('P99EmbeddingTime','Mean run P99 (ms)',1000,True),
           ('ExecutionTime','Total embed per run (s)',1,True),
           ('MeanHops','Mean hops',1,True),('R_C','Admission R/C',1,False)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args = parser.parse_args()
    root = args.directory
    for folder in ('development','heldout_hosts_serial'):
        path = root/folder
        config = json.loads((path/'config.json').read_text(encoding='utf-8'))
        frame = pd.read_csv(path/'raw.csv',float_precision='round_trip')
        expected = {(c['name'],s,m) for c in config['cases'] for s in config['seeds'] for m in config['methods']}
        assert set(zip(frame.Case,frame.Seed,frame.Algorithm)) == expected
        assert len(frame) == len(expected)
        assert frame.groupby(['Case','Seed']).TraceSHA256.nunique().eq(1).all()
        assert frame.groupby(['Case','Seed']).TopologySHA256.nunique().eq(1).all()
        assert frame.Duration.eq(config['duration']).all()
        assert (frame.Accepted+frame.Rejected).eq(frame.NumRequests).all()
        assert archive_source_hash(path/'source.zip') == config['maintained_source_sha256']
        with zipfile.ZipFile(path/'source.zip') as archive:
            assert hashlib.sha256(archive.read('prototype/check_lifetime_energy.py')).hexdigest() == config['prototype_script_sha256']
        for metric,denominator in [('EnergyPerServedCPUUnitSecond_Wh','ServedCPUUnitSeconds'),
                                   ('EnergyPerServedBandwidthUnitSecond_Wh','ServedBandwidthUnitSeconds'),
                                   ('EnergyPerServedRequestSecond_Wh','ServedRequestSeconds')]:
            valid = frame[denominator] > 0
            np.testing.assert_allclose(frame.loc[valid,metric],frame.loc[valid,'Energy_Wh']/frame.loc[valid,denominator],rtol=1e-12)
        (path/'validation.json').write_text(json.dumps(dict(rows=len(frame),paired_cases=len(expected)//len(config['methods']),
            raw_sha256=hashlib.sha256((path/'raw.csv').read_bytes()).hexdigest(),complete=True,
            common_inputs=True,normalized_energy_reconstructed=True,source_archive_checked=True),indent=2),encoding='utf-8')
    path = root/'heldout_hosts_serial'
    frame = pd.read_csv(path/'raw.csv',float_precision='round_trip')
    means = frame.groupby('Algorithm').mean(numeric_only=True)
    p,h = means.loc['ProposedAdaptive'],means.loc['LifetimeHosts']
    rows = []
    for metric,label,scale,lower in METRICS:
        ranks = means[metric].rank(ascending=lower,method='min')
        rows.append(dict(Metric=label,Maintained=p[metric]*scale,Candidate=h[metric]*scale,
                         ChangePercent=100*(h[metric]/p[metric]-1),
                         MaintainedRank=int(ranks['ProposedAdaptive']),CandidateRank=int(ranks['LifetimeHosts'])))
    comparison = pd.DataFrame(rows)
    comparison.to_csv(root/'comparison.csv',index=False)
    cases = frame.groupby(['Case','Algorithm']).mean(numeric_only=True)
    case_rows = []
    for case in frame.Case.unique():
        old,new = cases.loc[(case,'ProposedAdaptive')],cases.loc[(case,'LifetimeHosts')]
        case_rows.append(dict(Case=case,AcceptanceChange_pp=100*(new.AcceptanceRatio-old.AcceptanceRatio),
            EnergyChange_pct=100*(new.Energy_Wh/old.Energy_Wh-1),
            NormalizedCPUChange_pct=100*(new.EnergyPerServedCPUUnitSecond_Wh/old.EnergyPerServedCPUUnitSecond_Wh-1),
            MeanTimeChange_pct=100*(new.MeanEmbeddingTime/old.MeanEmbeddingTime-1)))
    changes = pd.DataFrame(case_rows)
    changes.to_csv(root/'per_case_changes.csv',index=False)
    fig,axes = plt.subplots(1,3,figsize=(12,4),sharey=True)
    for ax,metric,title in zip(axes,['AcceptanceChange_pp','NormalizedCPUChange_pct','MeanTimeChange_pct'],
                                ['Acceptance change (percentage points)','Energy per CPU-second change (%)','Mean embedding time change (%)']):
        good = changes[metric] >= 0 if metric == 'AcceptanceChange_pp' else changes[metric] <= 0
        ax.barh(changes.Case,changes[metric],color=np.where(good,'#207567','#c75752'))
        ax.axvline(0,color='#333333',linewidth=.8)
        ax.set_title(title,fontsize=10)
        ax.grid(axis='x',alpha=.2)
    fig.suptitle('Frozen lifetime-host candidate vs maintained proposal: 4 fresh seeds per case\nDescriptive short checks; favorable in green, adverse in red',fontsize=11)
    fig.tight_layout()
    fig.savefig(root/'candidate_changes.png',dpi=180)
    fig.savefig(root/'candidate_changes.svg')
    plt.close(fig)
    lines = ['# Lifetime-aware energy trial — rejected for production','',
        'Maintained simulator unchanged. Two separate development candidates were tested on 12 paired cases/36 rows. '
        'Host placement was frozen and checked on 28 fresh paired cases/252 rows with five pinned Virne ports, '
        'EnergyAware and GreenCostRouting. Every method shared topology, trace, demands, QoS and power physics. '
        'Proposal variants shared the original RNG stream and quotas. No future arrivals or run horizon were available.','',
        'Known declared lifetimes are an extra modeling assumption. Lifetime-aware host scores relax tentative route occupancy; '
        'the exact activation argument applies to the fixed-admission routing oracle, not an optimal host/search/full-horizon policy.','',
        '## Fresh serial comparison','', '| Metric | Maintained | Candidate | Relative change | Rank maintained/candidate (9 methods) |',
        '|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f'| {row["Metric"]} | {row["Maintained"]:.6g} | {row["Candidate"]:.6g} | {row["ChangePercent"]:+.3f}% | {row["MaintainedRank"]}/{row["CandidateRank"]} |')
    lines += ['', 'Means give equal weight to each case/seed. P99 is the mean of run-level P99 values. '
              'Ranks within this nine-method diagnostic do not replace the previous 32-method full experiment.', '',
              '## Promotion decision','',
              f'Acceptance changed {100*(h.AcceptanceRatio-p.AcceptanceRatio):+.3f} percentage points; '
              f'served CPU-time changed {100*(h.ServedCPUUnitSeconds/p.ServedCPUUnitSeconds-1):+.3f}%. '
              'The host candidate failed the predeclared 2% normalized-energy improvement and 5% mean/P99 runtime gates. '
              'Sparse-network acceptance also regressed. Do not replace the maintained proposal or claim superiority.', '',
              '| Case | Acceptance change (pp) | Total energy change | Energy/CPU-second change | Mean time change |',
              '|---|---:|---:|---:|---:|']
    for row in case_rows:
        lines.append(f'| {row["Case"]} | {row["AcceptanceChange_pp"]:+.3f} | {row["EnergyChange_pct"]:+.3f}% | {row["NormalizedCPUChange_pct"]:+.3f}% | {row["MeanTimeChange_pct"]:+.3f}% |')
    lines += ['', '## Mechanism, limits and provenance','',
        'The independent fixed-admission two-hop witness reduced incremental modeled energy from 19,850 to 5,000 J with '
        'unchanged hosts, CPU/BW service, hop count and QoS. Six oracle checks cover active geometric lease ends, '
        'release, failed commits, tentative reuse, tiny-demand fallback and scalar/batched host scores. This is a mechanism '
        'example, not a 74.8% workload energy-saving claim.', '',
        'The first held-out invocation was stopped after four cases because the correctness suite briefly overlapped it. '
        'Its observations remain in heldout_hosts and are excluded from timing conclusions. The complete serial rerun '
        'repeated the frozen configuration; it was not used to tune the candidate.', '',
        'No significance or Q1/Q2 readiness claim follows from four seeds. Lifetime-aware scheduling already has close '
        '[primary-source precedents](https://arxiv.org/html/2412.09840v2), including using long-lived occupants to avoid '
        'extending host lifetime. The routing/embedding integration is an unverified novelty hypothesis, not a proved new principle.', '',
        'Pinned ports reproduce documented decision kernels with common hard QoS and corrected serial PSO evolution; '
        'the custom original baselines are not full paper reproductions. Raw data, source archives, configurations and adverse '
        'outcomes are retained. The result supports continued mechanism/evaluation work, not repeated tuning on these seeds.']
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(comparison.to_string(index=False))


if __name__ == '__main__':
    main()
