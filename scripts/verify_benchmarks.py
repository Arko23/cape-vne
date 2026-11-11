"""Run a fixed diagnostic matrix. Diagnostics do not establish paper superiority."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vne  # Configure numerical thread defaults before importing pandas.
import pandas as pd
from vne.experiments import _atomic_write_csv, _experiment_spec


def case_spec(case):
    nodes, load, seed, duration, all_algorithms = case
    return {"load": load, "seed": seed,
            "experiment": _experiment_spec(duration, nodes, 1, all_algorithms, all_algorithms,
                                             include_reference_baselines=all_algorithms)}


def validate_cached_case(frame, case, spec, group):
    """A readable prefix of an interrupted CSV is not a completed case."""
    nodes, load, seed, duration, all_algorithms = case
    required = {"Lambda", "Seed", "Algorithm", "NumSubstrateNodes", "Duration", "CaseGroup",
                "Accepted", "Rejected", "NumRequests", "AlgorithmScope", "AlgorithmParameters",
                "AcceptanceRatio", "Energy_Wh", "EnergyPerAccepted_Wh",
                "EnergyPerServedRequestSecond_Wh", "MeanEmbeddingTime", "ExperimentFingerprint"}
    expected = spec["experiment"]["algorithms"]
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if (not required.issubset(frame.columns) or len(frame) != len(expected)
            or set(frame.Algorithm) != set(expected) or frame.Algorithm.duplicated().any()):
        raise ValueError("Incomplete or invalid cached case; choose a fresh output directory")
    checks = (("Lambda", load), ("Seed", seed), ("NumSubstrateNodes", nodes),
              ("Duration", duration), ("CaseGroup", group), ("ExperimentFingerprint", fingerprint))
    if any(not frame[column].eq(value).all() for column, value in checks):
        raise ValueError("Cached case rows do not match their experiment metadata")
    if not frame.Accepted.add(frame.Rejected).eq(frame.NumRequests).all():
        raise ValueError("Cached case request accounting is invalid")
    for row in frame.itertuples():
        if (row.AlgorithmScope != spec["experiment"]["algorithm_scope"][row.Algorithm]
                or json.loads(row.AlgorithmParameters) != spec["experiment"]["algorithm_parameters"][row.Algorithm]):
            raise ValueError("Cached case algorithm metadata is invalid")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='results/diagnostics')
    parser.add_argument('--quick',action='store_true',help='Small integration check including all registered methods')
    args=parser.parse_args()
    out=Path(args.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    cases=[(n,load,seed,1000,False) for n in (20,50,100) for load in (2,6,10,14) for seed in (2011,2017)]
    # These are separate stress/control checks, excluded from the main mean.
    extras=[(50,6,2119,5000,False),(150,6,2129,500,False),
            (20,6,2203,400,True),(50,6,2207,400,True)]
    if args.quick:
        cases=[(12,10,2011,80,False)]
        extras=[(14,10,2203,80,True)]
    specs=[case_spec(case) for case in cases+extras]
    manifest={'schema':2,'primary_cases':cases,'extra_cases':extras,'case_specs':specs,
              'workers':1,'tuning':'none; current default policies',
              'purpose':'Fresh diagnostic assessment, not a powered publication experiment.'}
    path=out/'manifest.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=json.loads(json.dumps(manifest)):
        raise ValueError('Different source, settings or environment; choose a fresh directory')
    path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    frames=[]
    for index,(nodes,load,seed,duration,all_algorithms) in enumerate(cases+extras):
        file=out/f'case_{index:02d}.csv'
        case=(nodes,load,seed,duration,all_algorithms)
        spec=specs[index]
        group='primary' if index<len(cases) else 'stress_or_control'
        tick=time.perf_counter()
        if file.exists():
            frame=pd.read_csv(file, float_precision='round_trip')
        else:
            frame=vne._flatten_results(vne.run_simulation(load,duration,nodes,seed,
                      include_pso=all_algorithms,include_ablations=all_algorithms,
                      include_reference_baselines=all_algorithms))
            frame['CaseGroup']=group
            frame['ExperimentFingerprint']=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
            validate_cached_case(frame,case,spec,group)
            _atomic_write_csv(frame,file)
        validate_cached_case(frame,case,spec,group)
        frames.append(frame)
        print(f'Completed {index+1}/{len(cases+extras)}: nodes={nodes}, load={load}, seed={seed}, elapsed={time.perf_counter()-tick:.1f}s',flush=True)
    combined=pd.concat(frames,ignore_index=True)
    _atomic_write_csv(combined,out/'all_cases.csv')
    primary=combined[combined.CaseGroup=='primary']
    metrics=['AcceptanceRatio','Energy_Wh','EnergyPerAccepted_Wh','EnergyPerServedRequestSecond_Wh','MeanEmbeddingTime']
    _atomic_write_csv(primary.groupby('Algorithm')[metrics].mean().reset_index(),out/'primary_means.csv')
    print(primary.groupby('Algorithm')[metrics].mean().to_string(),flush=True)


if __name__=='__main__':
    main()
