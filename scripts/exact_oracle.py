"""Small-instance MILP quality reference; not a new VNE method.

Binary placement and directed unsplittable unit flow with common CPU, bandwidth,
injectivity, hop and per-link delay constraints. Minimize admitted resource cost.
An optimal single-request solution is not an optimal online energy policy.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
import vne
from vne.experiments import source_fingerprint


def solve_request(substrate, request, time_limit=5.0):
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError('time_limit must be finite and positive')
    nodes = sorted(substrate.cpu_residual)
    virtual = sorted(request.node_cpu)
    if (not virtual or not math.isfinite(request.max_delay) or request.max_delay < 0
            or not math.isfinite(request.max_hops) or request.max_hops < 0
            or int(request.max_hops) != request.max_hops
            or any(not math.isfinite(cpu) or cpu < 0 for cpu in request.node_cpu.values())
            or any(e.u not in virtual or e.v not in virtual or e.u == e.v or not math.isfinite(e.bandwidth)
                   or e.bandwidth < 0 for e in request.edges)
            or len({vne.canonical_edge(e.u, e.v) for e in request.edges}) != len(request.edges)):
        raise ValueError('Use a nonempty simple virtual graph with valid demands and QoS caps')
    arcs = [(u, w) for u, w in sorted(substrate.edges) for u, w in ((u, w), (w, u))]
    placement = {(v, p): i for i, (v, p) in enumerate((v, p) for v in virtual for p in nodes)}
    offset = len(placement)
    flow = {(e, u, w): offset+i for i, (e, u, w) in
            enumerate((e, u, w) for e in range(len(request.edges)) for u, w in arcs)}
    count = offset + len(flow)
    objective = np.zeros(count)
    for (index, u, w), column in flow.items():
        objective[column] = request.edges[index].bandwidth
    data, row_ids, columns, lower, upper = [], [], [], [], []
    def row(coefficients, lo=-np.inf, hi=np.inf):
        index = len(lower)
        for column, value in coefficients.items():
            if value:
                data.append(value); row_ids.append(index); columns.append(column)
        lower.append(lo); upper.append(hi)
    for vnode in virtual:
        row({placement[vnode, p]: 1 for p in nodes}, 1, 1)
    for pnode in nodes:
        row({placement[v, pnode]: 1 for v in virtual}, hi=1)
        row({placement[v, pnode]: request.node_cpu[v] for v in virtual},
            hi=substrate.cpu_residual[pnode])
    for index, edge in enumerate(request.edges):
        for pnode in nodes:
            coefficients = {placement[edge.u, pnode]: -1}
            endpoint = placement[edge.v, pnode]
            coefficients[endpoint] = coefficients.get(endpoint, 0) + 1
            for u, w in arcs:
                if u == pnode: coefficients[flow[index, u, w]] = 1
                elif w == pnode: coefficients[flow[index, u, w]] = -1
            row(coefficients, 0, 0)
        row({flow[index, u, w]: 1 for u, w in arcs}, hi=request.max_hops)
        row({flow[index, u, w]: substrate.link_delay(u, w) for u, w in arcs}, hi=request.max_delay)
    for u, w in sorted(substrate.edges):
        row({flow[index, a, b]: edge.bandwidth
             for index, edge in enumerate(request.edges) for a, b in ((u, w), (w, u))},
            hi=substrate.bandwidth_residual[(u, w)])
    matrix = coo_matrix((data, (row_ids, columns)), shape=(len(lower), count)).tocsc()
    result = milp(objective, integrality=np.ones(count), bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix, lower, upper),
                  options={'time_limit': float(time_limit), 'mip_rel_gap': 0.0})
    statuses = {0: 'optimal', 1: 'limit_reached', 2: 'proven_infeasible',
                3: 'unbounded', 4: 'solver_error'}
    answer = dict(status=statuses.get(result.status, 'unknown'), solver_status=int(result.status),
                  message=result.message, mip_gap=getattr(result, 'mip_gap', None),
                  dual_bound=getattr(result, 'mip_dual_bound', None), embedding=None, cost=None)
    if answer['dual_bound'] is not None:
        answer['dual_bound'] += request.total_cpu
    if result.x is None:
        return answer
    mapping = {v: max(nodes, key=lambda p: result.x[placement[v, p]]) for v in virtual}
    paths = {}
    for index, edge in enumerate(request.edges):
        adjacency = {p: [] for p in nodes}
        for u, w in arcs:
            if result.x[flow[index, u, w]] > .5:
                adjacency[u].append(w)
        target = mapping[edge.v]
        def walk(path):
            if path[-1] == target: return path
            for nxt in adjacency[path[-1]]:
                if nxt not in path:
                    found = walk(path + [nxt])
                    if found: return found
            return None
        path = walk([mapping[edge.u]])
        if path is None:
            answer['status'] = 'invalid_incumbent'
            return answer
        paths[(edge.u, edge.v)] = path
    validator = vne.BaseVNEAlgorithm(substrate.clone())
    state = validator.sn.empty_state()
    for vnode, pnode in mapping.items():
        if not validator.reserve_cpu(state, pnode, request.node_cpu[vnode]):
            answer['status'] = 'invalid_incumbent'; return answer
    for edge in request.edges:
        if not validator.reserve_path(state, paths[(edge.u, edge.v)], edge.bandwidth):
            answer['status'] = 'invalid_incumbent'; return answer
    embedding = validator.commit_embedding(request, state, mapping, paths)
    if embedding is None:
        answer['status'] = 'invalid_incumbent'
        return answer
    answer['embedding'] = embedding
    answer['cost'] = embedding['cost']
    # Positive cost eliminates cycles at an optimum; extracting an incumbent's
    # simple paths can only reduce resource use. Validate optimal cost explicitly.
    if result.status == 0 and abs(embedding['cost'] - (result.fun + request.total_cpu)) > 1e-6:
        answer['status'] = 'optimal_cost_mismatch'
    return answer


def diagnostic_graph(cpu, links):
    """Construct an explicit instance without importing test fixtures."""
    sn = vne.SubstrateNetwork(num_nodes=len(cpu), seed=0)
    sn.cpu_capacity = dict(enumerate(map(float, cpu)))
    sn.cpu_residual = dict(sn.cpu_capacity)
    sn.edges = {vne.canonical_edge(u, w): {'delay': float(delay), 'bandwidth': float(bw)}
                for u, w, bw, delay in links}
    sn.neighbors = {node: set() for node in sn.cpu_capacity}
    for u, w in sn.edges:
        sn.neighbors[u].add(w)
        sn.neighbors[w].add(u)
    sn.bandwidth_capacity = {edge: data['bandwidth'] for edge, data in sn.edges.items()}
    sn.bandwidth_residual = dict(sn.bandwidth_capacity)
    return sn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=int, default=20)
    parser.add_argument('--seed', type=int, default=6501)
    parser.add_argument('--time-limit', type=float, default=5)
    parser.add_argument('--algorithms', default='ProposedAdaptive,QoSBoundRouting,ConflictRepair,GRC,NodeRank,PSO')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.cases < 1 or not math.isfinite(args.time_limit) or args.time_limit <= 0:
        parser.error('Use finite positive dimensions')
    names = args.algorithms.split(',')
    if len(set(names)) != len(names) or not set(names).issubset(vne._algorithm_names(True, True)):
        parser.error('Use unique registered algorithm names')
    manifest = dict(source_sha256=source_fingerprint(),
        oracle_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scipy_version=scipy.__version__, cases=args.cases, seed=args.seed, algorithms=names,
        time_limit_seconds=args.time_limit, objective='single-request CPU + BW-times-hops',
        note='Small diagnostic instances; not an online energy optimum or publication result')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir/'manifest.json'
    if manifest_path.exists():
        saved = json.loads(manifest_path.read_text())
        saved = {key: value for key, value in saved.items()
                 if key not in ('raw_sha256', 'instances_sha256')}
        if saved != manifest:
            raise ValueError('Oracle source or protocol changed; use a fresh output directory')
    rng = random.Random(args.seed)
    rows, instances = [], []
    for index in range(args.cases):
        size = rng.randint(5, 8)
        sn = diagnostic_graph([rng.randint(4, 12) for _ in range(size)],
                   [(u, w, rng.randint(3, 12), rng.randint(1, 4))
                    for u in range(size) for w in range(u+1, size) if rng.random() < .5])
        request = vne.VirtualNetworkRequest(index, 0, 10,
                   {n: rng.randint(2, 6) for n in range(3)},
                   [vne.VirtualEdge(0, 1, rng.randint(2, 7)),
                    vne.VirtualEdge(1, 2, rng.randint(2, 7))], max_delay=8, max_hops=3)
        exact = solve_request(sn, request, args.time_limit)
        instances.append(dict(case_id=index, cpu=list(sn.cpu_residual.values()),
            links=[[u, w, sn.bandwidth_residual[(u, w)], sn.link_delay(u, w)] for u, w in sorted(sn.edges)],
            virtual_cpu=list(request.node_cpu.values()),
            virtual_links=[[e.u, e.v, e.bandwidth] for e in request.edges],
            max_delay=request.max_delay, max_hops=request.max_hops,
            oracle={key: value for key, value in exact.items() if key != 'embedding'}))
        for name in names:
            algorithm = vne.algorithm_factory(name, sn.clone(), args.seed+index, True)
            embedding = algorithm.embed(request)
            if embedding:
                vne._validate_active_state(algorithm, {index: (request, embedding)})
            rows.append(dict(CaseID=index, Algorithm=name, OracleStatus=exact['status'],
                             OracleCost=exact['cost'], Accepted=embedding is not None,
                             Cost=embedding['cost'] if embedding else None,
                             CostGapPercent=100*(embedding['cost']/exact['cost']-1)
                             if embedding and exact['status']=='optimal' else None))
    pd.DataFrame(rows).to_csv(args.output_dir/'oracle_cases.csv', index=False)
    (args.output_dir/'instances.json').write_text(json.dumps(instances, indent=2), encoding='utf-8')
    manifest['raw_sha256'] = hashlib.sha256((args.output_dir/'oracle_cases.csv').read_bytes()).hexdigest()
    manifest['instances_sha256'] = hashlib.sha256((args.output_dir/'instances.json').read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(pd.DataFrame(rows).groupby('Algorithm')[['Accepted','CostGapPercent']].mean().to_string())
    print(pd.DataFrame(rows).drop_duplicates('CaseID').OracleStatus.value_counts().to_string())


if __name__ == '__main__':
    main()
