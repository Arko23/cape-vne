"""Serial development/held-out checks using the unchanged event simulator.

This is a short diagnostic, not the full experiment or publication evidence.
An archived source ZIP can be selected to replay the previous proposal fairly.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import sys
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--archive-current', action='store_true')
    parser.add_argument('--suite', choices=('development', 'heldout'), default='development')
    parser.add_argument('--methods', default='ProposedAdaptive,GreedyCSP,VirneFFD,VirneGRC,VirneRWBFS,VirnePSO,GreenCostRouting')
    parser.add_argument('--duration', type=float, default=2000)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--energy-weight', type=float, help='Explicit development-only proposal candidate')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'raw.csv').exists():
        parser.error('Choose a fresh directory; diagnostic observations are never overwritten.')
    snapshot = args.snapshot.resolve() if args.snapshot else None
    if args.archive_current:
        if snapshot:
            parser.error('--archive-current and --snapshot are mutually exclusive')
        snapshot = output / 'source.zip'
        with zipfile.ZipFile(snapshot, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((ROOT / 'vne').glob('*.py')):
                archive.write(path, path.relative_to(ROOT).as_posix())
            archive.write(ROOT / 'vne_simulation.py', 'vne_simulation.py')
    sys.path.insert(0, str(snapshot or ROOT))
    import pandas as pd
    import vne
    from vne import experiments

    names = (experiments._algorithm_names(True, True, True) if args.methods == 'all'
             else args.methods.split(','))
    valid = set(experiments._algorithm_names(True, True, True))
    if len(set(names)) != len(names) or not set(names) <= valid:
        parser.error('Invalid or duplicate algorithm names')
    if args.suite == 'development':
        cases = [('dense4', 50, 4, vne.Scenario()),
                 ('dense12', 50, 12, vne.Scenario()),
                 ('hard50', 50, 12, vne.Scenario(link_prob=.06, vnr_link_prob=.65,
                      lifetime_mean=800, max_delay=12, max_hops=3)),
                 ('hard100', 100, 20, vne.Scenario(link_prob=.035, vnr_link_prob=.60,
                      lifetime_mean=1000, max_delay=15, max_hops=4))]
        seeds = [7101, 7102]
    else:
        cases = [('dense2', 50, 2, vne.Scenario()),
                 ('dense8', 50, 8, vne.Scenario()),
                 ('dense12', 50, 12, vne.Scenario()),
                 ('sparse', 50, 8, vne.Scenario(link_prob=.10)),
                 ('tight', 50, 12, vne.Scenario(max_delay=15, max_hops=4)),
                 ('hard100', 100, 20, vne.Scenario(link_prob=.035, vnr_link_prob=.60,
                      lifetime_mean=1000, max_delay=15, max_hops=4))]
        seeds = [8101, 8102, 8103]
    if snapshot:
        with zipfile.ZipFile(snapshot) as archive:
            hashes = {name: hashlib.sha256(archive.read(name)).hexdigest()
                      for name in sorted(archive.namelist()) if name.endswith('.py')}
    else:
        hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT / 'vne').glob('*.py'))}
    metadata = dict(suite=args.suite, duration=args.duration, workers=1,
                    profile=args.profile, methods=names, seeds=seeds,
                    proposal_energy_weight=args.energy_weight,
                    source_hashes=hashes, source_snapshot=str(snapshot) if snapshot else None,
                    cases=[dict(name=n, nodes=s, lam=l, scenario=c.to_dict()) for n, s, l, c in cases],
                    note='Short diagnostic; current full-run simulator, constraints and accounting; no significance claim.')
    (output / 'config.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    rows = []
    profiler = cProfile.Profile() if args.profile else None
    factory = experiments.algorithm_factory

    def candidate_factory(name, substrate, seed, include_pso=False):
        algorithm = factory(name, substrate, seed, include_pso)
        if name == 'ProposedAdaptive' and args.energy_weight is not None:
            if not 0 <= args.energy_weight <= 1:
                raise ValueError('energy-weight must be in [0,1]')
            algorithm.energy_weight = args.energy_weight
        return algorithm

    for case, size, lam, scenario in cases:
        for seed in seeds:
            with patch.object(experiments, '_algorithm_names', return_value=names), \
                    patch.object(experiments, 'algorithm_factory', side_effect=candidate_factory):
                if profiler:
                    profiler.enable()
                result = experiments.run_simulation(lam, args.duration, size, seed,
                    include_pso=True, include_ablations=True, include_reference_baselines=True,
                    strict_invariants=True, scenario=scenario)
                if profiler:
                    profiler.disable()
            rows.extend(dict(Case=case, **row) for row in result)
            pd.DataFrame(rows).to_csv(output / 'raw.csv', index=False)
            proposal = next((r for r in result if r['Algorithm'] == 'ProposedAdaptive'), None)
            if proposal:
                print(f"{case} seed={seed}: acceptance={proposal['AcceptanceRatio']:.4f} "
                      f"energy={proposal['Energy_Wh']:.1f}Wh "
                      f"mean={proposal['MeanEmbeddingTime']*1000:.3f}ms "
                      f"p99={proposal['P99EmbeddingTime']*1000:.3f}ms", flush=True)
    frame = pd.DataFrame(rows)
    for _, group in frame.groupby(['Case', 'Seed']):
        assert group.TraceSHA256.nunique() == group.TopologySHA256.nunique() == 1
        assert group.shape[0] == len(names)
    metrics = ['AcceptanceRatio', 'Energy_Wh', 'MeanEmbeddingTime', 'P99EmbeddingTime',
               'ExecutionTime', 'MeanHops', 'EnergyPerServedRequestSecond_Wh',
               'EnergyPerServedCPUUnitSecond_Wh', 'EnergyPerServedBandwidthUnitSecond_Wh',
               'NodeUtil', 'LinkUtil', 'SearchNodes', 'PackingChecks', 'QoSBoundTransitions']
    frame.groupby(['Case', 'Algorithm'])[metrics].mean().to_csv(output / 'means.csv')
    if profiler:
        profiler.dump_stats(output / 'profile.pstats')
        with (output / 'profile.txt').open('w', encoding='utf-8') as stream:
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(50)
    print(f'Wrote {len(rows)} validated diagnostic rows to {output}', flush=True)


if __name__ == '__main__':
    main()
