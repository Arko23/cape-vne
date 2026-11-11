"""Supplemental, resumable paired external-topology/current-engine evaluation.

Does not replace the maintained 32-method full evaluation. Every current-engine
ablation changes one declared switch; older controls retain their old identities.
Serial only: use this for uncontended timing and mechanism-specific evidence.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
import vne
from vne import experiments
from scripts.topology_inputs import load_topology, substrate_from_topology
from scripts.analyze_full_results import archive_source_hash, verify_summary, verify_statistics


CURRENT_ABLATIONS = {
    'CurrentNoPacking': {'exact_packing':False},
    'CurrentIndependentQoS': {'joint_qos_checks':False},
    'CurrentFixedOrder': {'domain_ordering':False},
    'CurrentNoGreedyFirst': {'greedy_first':False},
    'CurrentDelayTwoHop': {'green_two_hop':False},
    'CurrentScalarScores': {'batch_scores':False},
    'CurrentNoCompact': {'compact_weight':0.},
    'CurrentNoRepair': {'joint_repair':False},
}


def run(args):
    loads = [float(x) for x in args.lambdas.split(',')]
    seeds = list(range(args.seed_start,args.seed_start+args.seed_count))
    if (len(loads) != len(set(loads)) or not loads or any(not math.isfinite(x) or x <= 0 for x in loads)
            or args.seed_count < 1 or not math.isfinite(args.duration) or args.duration <= 0):
        raise ValueError('Unique positive finite loads, seed-count and duration required')
    scenario = vne.Scenario(link_prob=args.link_prob,lifetime_mean=args.lifetime_mean,
                            max_delay=args.max_delay,max_hops=args.max_hops)
    available = experiments._algorithm_names(True,True,True)
    names = available if args.methods == 'all' else args.methods.split(',')
    if len(names) != len(set(names)) or not set(names) <= set(available):
        raise ValueError('Invalid or duplicate algorithm names')
    names = list(names)
    if args.current_ablations:
        if 'ProposedAdaptive' not in names:
            raise ValueError('Current ablations require ProposedAdaptive as their paired anchor')
        names.extend(CURRENT_ABLATIONS)
    inputs = []
    for file in args.topology or []:
        metadata, edges = load_topology(file,args.simplify)
        inputs.append((Path(file).stem,metadata,edges))
    if not inputs:
        if args.num_nodes < 2:
            raise ValueError('num-nodes must be >=2')
        inputs = [('synthetic',dict(nodes=args.num_nodes),None)]
    if len({name for name,_,_ in inputs}) != len(inputs):
        raise ValueError('Unique topology filenames required')
    params = {}
    for case,metadata,edges in inputs:
        params[case] = {}
        for name in names:
            # Reference ports deliberately visit up to the substrate's actual
            # number of nodes. Parameter manifests therefore vary by topology.
            substrate = (vne.SubstrateNetwork(num_nodes=metadata['nodes'],seed=0)
                         if edges is None else substrate_from_topology(metadata,edges,0))
            algorithm = (vne.GreenAdaptiveVNE(substrate,**CURRENT_ABLATIONS[name])
                         if name in CURRENT_ABLATIONS else vne.algorithm_factory(name,substrate,0,True))
            params[case][name] = vne.algorithm_parameters(algorithm)
    spec = dict(schema=1,source_sha256=experiments.source_fingerprint(),workers=1,
                methods=names,seeds=seeds,lambdas=loads,duration=args.duration,scenario=scenario.to_dict(),
                inputs=[dict(name=name,**metadata) for name,metadata,_ in inputs],
                ablation_switches=CURRENT_ABLATIONS if args.current_ablations else {},algorithm_parameters=params,
                harness_sha256={n:hashlib.sha256((ROOT/'scripts'/n).read_bytes()).hexdigest()
                                for n in ('research_evaluation.py','topology_inputs.py')},
                note='External adjacency uses synthetic resources/delay. Current ablations share the proposal RNG; serial timing.')
    output = args.output_dir
    manifest,raw = output/'config.json',output/'raw.csv'
    if output.exists():
        if not manifest.exists() or json.loads(manifest.read_text(encoding='utf-8')) != spec:
            raise ValueError('Output metadata differs; choose a fresh output directory')
        rows = pd.read_csv(raw,float_precision='round_trip').to_dict('records') if raw.exists() else []
    else:
        rows = []
        output.mkdir(parents=True)
        manifest.write_text(json.dumps(spec,indent=2),encoding='utf-8')
        with zipfile.ZipFile(output/'source.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((ROOT/'vne').glob('*.py')):
                archive.write(path,path.relative_to(ROOT).as_posix())
            archive.write(ROOT/'vne_simulation.py','vne_simulation.py')
            for name in spec['harness_sha256']:
                archive.write(ROOT/'scripts'/name,'scripts/'+name)
            for name,metadata,edges in inputs:
                if edges is not None:
                    path = Path(metadata['path'])
                    archive.write(path,'topologies/'+path.name)
    if archive_source_hash(output/'source.zip') != spec['source_sha256']:
        raise ValueError('Preserved source archive differs from the measured source')
    with zipfile.ZipFile(output/'source.zip') as archive:
        for name,digest in spec['harness_sha256'].items():
            if hashlib.sha256(archive.read('scripts/'+name)).hexdigest() != digest:
                raise ValueError('Preserved evaluation harness differs')
        for _,metadata,edges in inputs:
            if edges is not None:
                if hashlib.sha256(archive.read('topologies/'+Path(metadata['path']).name)).hexdigest() != metadata['sha256']:
                    raise ValueError('Preserved topology input differs')
    expected = {(name,load,seed,method) for name,_,_ in inputs for load in loads for seed in seeds for method in names}
    observed = {(r['Case'],r['Lambda'],r['Seed'],r['Algorithm']) for r in rows}
    if len(observed) != len(rows) or not observed <= expected:
        raise ValueError('Duplicate or unexpected checkpoint rows')
    for key in {(r['Case'],r['Lambda'],r['Seed']) for r in rows}:
        members = [r for r in rows if (r['Case'],r['Lambda'],r['Seed']) == key]
        if {r['Algorithm'] for r in members} != set(names):
            raise ValueError('Incomplete method block; refusing to combine partial paired cases')
        if len({r['TraceSHA256'] for r in members}) != 1 or len({r['TopologySHA256'] for r in members}) != 1:
            raise ValueError('Checkpoint methods have mismatched inputs')
        if any(r['SourceSHA256'] != spec['source_sha256'] for r in members):
            raise ValueError('Checkpoint source differs')
        if any(json.loads(r['AlgorithmParameters']) != params[key[0]][r['Algorithm']] for r in members):
            raise ValueError('Checkpoint algorithm parameters differ')
        if any(r['Duration'] != args.duration for r in members):
            raise ValueError('Checkpoint duration differs')
        metadata = next(m for n,m,_ in inputs if n == key[0])
        if any(r['NumSubstrateNodes'] != metadata['nodes']
               or r['InputSHA256'] != metadata.get('sha256','synthetic') for r in members):
            raise ValueError('Checkpoint topology metadata differs')
    factory = experiments.algorithm_factory
    proposal_salt = int.from_bytes(hashlib.sha256(b'ProposedAdaptive').digest()[:4],'big')

    def select(name,substrate,seed,include_pso=False):
        if name not in CURRENT_ABLATIONS:
            return factory(name,substrate,seed,include_pso)
        salt = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4],'big')
        algorithm = vne.GreenAdaptiveVNE(substrate,rng=random.Random(seed-salt+proposal_salt),**CURRENT_ABLATIONS[name])
        algorithm.name = name
        return algorithm

    scope = dict(experiments.ALGORITHM_SCOPE,**{n:'Current-engine ablation: '+json.dumps(s,sort_keys=True)
                                              for n,s in CURRENT_ABLATIONS.items()})
    for name,metadata,edges in inputs:
        def build(num_nodes,seed,**kwargs):
            return substrate_from_topology(metadata,edges,seed,**kwargs)
        for load in loads:
            for seed in seeds:
                if (name,load,seed,names[0]) in observed:
                    continue
                with patch.object(experiments,'_algorithm_names',return_value=list(names)), \
                     patch.object(experiments,'algorithm_factory',side_effect=select), \
                     patch.object(experiments,'ALGORITHM_SCOPE',scope):
                    if edges is None:
                        result = experiments.run_simulation(load,args.duration,metadata['nodes'],seed,True,
                            include_ablations=True,include_reference_baselines=True,scenario=scenario)
                    else:
                        with patch.object(experiments,'SubstrateNetwork',side_effect=build):
                            result = experiments.run_simulation(load,args.duration,metadata['nodes'],seed,True,
                                include_ablations=True,include_reference_baselines=True,scenario=scenario)
                assert {r['Algorithm'] for r in result} == set(names)
                assert len({r['TraceSHA256'] for r in result}) == len({r['TopologySHA256'] for r in result}) == 1
                rows.extend(dict(Case=name,InputSHA256=metadata.get('sha256','synthetic'),
                                 SourceSHA256=spec['source_sha256'],**r) for r in result)
                experiments._atomic_write_csv(pd.DataFrame(rows),raw)
                print(f'{name}: lambda={load}, seed={seed}, {len(result)} methods complete',flush=True)
    assert len(rows) == len(expected) and experiments.source_fingerprint() == spec['source_sha256']
    frame = pd.DataFrame(rows)
    for name,_,_ in inputs:
        destination = output/name
        destination.mkdir(exist_ok=True)
        case = frame[frame.Case.eq(name)]
        summary = vne.write_summary(case,destination/'summary.csv')
        statistics = vne.write_statistics(case,destination/'statistics.csv')
        verify_summary(case,summary)
        verify_statistics(case,statistics)
    validation = dict(expected_rows=len(expected),actual_rows=len(frame),source_sha256=spec['source_sha256'],
        raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        common_inputs_checked=True,summary_reconstruction=True,paired_statistics_bh_reconstruction=True)
    (output/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
    report = ('# Supplemental research evaluation\n\n'
              f'{len(frame)} rows, {len(seeds)} paired seeds, {len(loads)} loads, {len(inputs)} topologies, '
              f'{len(names)} methods. One worker; summaries and BH-corrected paired tests are separate by topology.\n\n'
              'Raw results, parameter settings, external-file hashes, topology/trace hashes and archived source are preserved. '
              'Imported adjacency retains every component and adds no spanning tree. CPU, bandwidth, delay, workload '
              'and power are synthetic; these are not measurements of an operating network.\n\n'
              'Current-engine ablations change one explicit switch. Older controls and all original comparators retain '
              'their maintained policies. Pinned Virne ports include the documented common-QoS adaptations and PSO scheduler correction. '
              'Small seed counts do not support a broad superiority or publication-readiness claim.\n')
    (output/'REPORT.md').write_text(report,encoding='utf-8')
    print(f'Completed {len(rows)} rows; summaries and paired statistics are separate by topology',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topology',action='append',type=Path)
    parser.add_argument('--simplify',action='store_true',help='Explicitly collapse parallel edges/remove self loops; no physical capacity inference')
    parser.add_argument('--num-nodes',type=int,default=50)
    parser.add_argument('--methods',default='all',help='Default all 32 maintained methods; comma-separated diagnostic subset allowed')
    parser.add_argument('--current-ablations',action='store_true')
    parser.add_argument('--seed-start',type=int,default=18000)
    parser.add_argument('--seed-count',type=int,default=30)
    parser.add_argument('--duration',type=float,default=20000)
    parser.add_argument('--lambdas',default='2,4,6,8,10,12')
    parser.add_argument('--link-prob',type=float,default=.35)
    parser.add_argument('--lifetime-mean',type=float,default=500)
    parser.add_argument('--max-delay',type=float,default=25)
    parser.add_argument('--max-hops',type=int,default=8)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
