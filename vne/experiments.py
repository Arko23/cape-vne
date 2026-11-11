"""Paired experiments, strict invariants, resumable outputs and statistics."""
from __future__ import annotations
import hashlib
import heapq
import json
import math
import multiprocessing as mp
import os
import platform
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from .models import EPS, SubstrateNetwork, VirtualNetworkRequest, generate_trace, safe_mean
from .configuration import Scenario
from .algorithms import ALGORITHM_SCOPE, BaseVNEAlgorithm, algorithm_factory, algorithm_parameters, _algorithm_names

def _algorithm_snapshot(algorithm: BaseVNEAlgorithm) -> Dict[str, float]:
    return {
        "node_utilization": algorithm.sn.cpu_utilization(),
        "link_utilization": algorithm.sn.link_utilization(),
        "active_nodes": algorithm.sn.active_node_count(),
        "active_links": algorithm.sn.active_link_count(),
    }


def _validate_active_state(
    algorithm: BaseVNEAlgorithm, active: Dict[int, Tuple[VirtualNetworkRequest, Dict]]
) -> None:
    if not algorithm.sn.state_is_valid(algorithm.sn.empty_state()):
        raise AssertionError("Invalid substrate residual resources")
    cpu_used = defaultdict(float)
    bw_used = defaultdict(float)
    for request_id, (vnr, embedding) in active.items():
        if request_id != vnr.request_id or embedding.get("request_id") != request_id:
            raise AssertionError("Active request identifiers do not agree")
        if embedding.get("_released", False):
            raise AssertionError("A released embedding is still marked active")
        try:
            request_cpu, request_bw = algorithm._embedding_usage(
                vnr, embedding["mapping"], embedding["paths"]
            )
        except (ValueError, KeyError, TypeError) as error:
            raise AssertionError("Invalid active embedding: " + str(error)) from error
        for node, demand in request_cpu.items():
            cpu_used[node] += demand
        for edge, demand in request_bw.items():
            bw_used[edge] += demand
    # Iterate every physical resource, including those absent from active use.
    for node, capacity in algorithm.sn.cpu_capacity.items():
        expected = capacity - cpu_used[node]
        if abs(expected - algorithm.sn.cpu_residual[node]) > 1e-6:
            raise AssertionError("CPU bookkeeping mismatch at node " + str(node))
    for edge, capacity in algorithm.sn.bandwidth_capacity.items():
        expected = capacity - bw_used[edge]
        if abs(expected - algorithm.sn.bandwidth_residual[edge]) > 1e-6:
            raise AssertionError("Bandwidth bookkeeping mismatch at link " + str(edge))


def _trace_sha256(trace):
    records = [[r.request_id, r.arrival, r.departure, sorted(r.node_cpu.items()),
                sorted((e.u, e.v, e.bandwidth) for e in r.edges),
                r.max_delay, r.max_hops, r.slice_type] for r in trace]
    return hashlib.sha256(json.dumps(records, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _topology_sha256(substrate):
    records = {'coordinates': sorted(substrate.coordinates.items()),
               'cpu': sorted(substrate.cpu_capacity.items()),
               'links': sorted((u, v, data['bandwidth'], data['delay'])
                               for (u, v), data in substrate.edges.items())}
    return hashlib.sha256(json.dumps(records, sort_keys=True, allow_nan=False).encode()).hexdigest()


def run_simulation(lam, duration=10000.0, num_nodes=50, seed=42,
                   include_pso=False, sample_interval=100.0,
                   strict_invariants=True, include_ablations=False, scenario=None,
                   include_reference_baselines=False):
    """Common trace/topology; simulation time unit is one second.

    Revenue/Cost/R_C measure admission-based resource sums. ServedRevenue,
    ServedCost and Served_R_C integrate resource-time actually served inside
    [0,duration]. ExecutionTime measures embed calls only; SimulationWallTime
    includes event processing, validation and accounting.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    if not math.isfinite(sample_interval) or sample_interval <= 0:
        raise ValueError("sample_interval must be finite and positive")
    if not math.isfinite(lam) or lam <= 0:
        raise ValueError("lambda must be finite and positive")
    scenario = scenario or Scenario()
    trace = generate_trace(lam, duration, seed, generator=scenario.generator())
    trace_hash = _trace_sha256(trace)
    results = []
    names = _algorithm_names(include_pso, include_ablations, include_reference_baselines)
    # Deterministic counterbalancing reduces a fixed first/last timing bias.
    # This separate RNG never changes workload, topology or algorithm streams.
    random.Random(seed + 0x564E45).shuffle(names)
    for name in names:
        substrate = SubstrateNetwork(num_nodes=num_nodes, seed=seed, **scenario.substrate_kwargs())
        topology_hash = _topology_sha256(substrate)
        # Stable per-name algorithm seed: enabling/reordering controls cannot
        # change any existing algorithm's random stream.
        salt = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")
        construction_start = time.perf_counter()
        algorithm = algorithm_factory(name, substrate, seed + salt, include_pso)
        initialization_seconds = time.perf_counter() - construction_start
        active = {}
        departures = []
        next_arrival_index = 0
        now = 0.0
        next_sample = sample_interval
        cpu_area = link_area = active_node_area = active_link_area = 0.0
        energy_wh = revenue = cost = boot_joules = 0.0
        served_revenue = served_cost = served_request_seconds = 0.0
        served_cpu_seconds = served_bandwidth_seconds = 0.0
        hop_sum = routed_virtual_links = accepted = rejected = 0
        embed_seconds = release_seconds = validation_seconds = 0.0
        snapshots = []
        attempt_times = []
        start = time.perf_counter()
        while now < duration:
            next_request = trace[next_arrival_index].arrival if next_arrival_index < len(trace) else math.inf
            next_departure = departures[0][0] if departures else math.inf
            next_event = min(next_request, next_departure, next_sample, duration)
            if next_event < now - EPS:
                raise RuntimeError("Simulation time moved backwards")
            dt = max(0.0, next_event - now)
            cpu_area += substrate.cpu_utilization() * dt
            link_area += substrate.link_utilization() * dt
            active_node_area += substrate.active_node_count() * dt
            active_link_area += substrate.active_link_count() * dt
            energy_wh += substrate.power_watts() * dt / 3600.0
            served_revenue += sum(e["revenue"] for _, e in active.values()) * dt
            served_cost += sum(e["cost"] for _, e in active.values()) * dt
            served_request_seconds += len(active) * dt
            served_cpu_seconds += sum(r.total_cpu for r, _ in active.values()) * dt
            served_bandwidth_seconds += sum(r.total_bandwidth for r, _ in active.values()) * dt
            now = next_event
            # Release first for simultaneous departure/arrival events.
            while departures and departures[0][0] <= now:
                _, rid = heapq.heappop(departures)
                old_request, embedding = active.pop(rid)
                tick = time.perf_counter()
                algorithm.release_embedding(old_request, embedding)
                release_seconds += time.perf_counter() - tick
            if strict_invariants:
                tick = time.perf_counter()
                _validate_active_state(algorithm, active)
                validation_seconds += time.perf_counter() - tick
            while next_arrival_index < len(trace) and trace[next_arrival_index].arrival <= now:
                request = trace[next_arrival_index]
                next_arrival_index += 1
                tick = time.perf_counter()
                embedding = algorithm.embed(request)
                attempt_time = time.perf_counter() - tick
                embed_seconds += attempt_time
                attempt_times.append(attempt_time)
                if embedding is None:
                    rejected += 1
                else:
                    active[request.request_id] = (request, embedding)
                    heapq.heappush(departures, (request.departure, request.request_id))
                    accepted += 1
                    revenue += embedding["revenue"]
                    cost += embedding["cost"]
                    boot_joules += embedding["boot_energy_joules"]
                    hop_sum += sum(len(p) - 1 for p in embedding["paths"].values())
                    routed_virtual_links += len(embedding["paths"])
                if strict_invariants:
                    tick = time.perf_counter()
                    _validate_active_state(algorithm, active)
                    validation_seconds += time.perf_counter() - tick
            while next_sample <= now and next_sample <= duration:
                snapshots.append({"time": next_sample, **_algorithm_snapshot(algorithm)})
                next_sample += sample_interval
        total_energy = energy_wh + boot_joules / 3600.0
        if strict_invariants and _trace_sha256(trace) != trace_hash:
            raise AssertionError("An algorithm mutated the shared request trace")
        results.append({
            "Lambda": float(lam), "Seed": int(seed), "Algorithm": name,
            "AlgorithmScope": ALGORITHM_SCOPE[name],
            "AlgorithmParameters": json.dumps(algorithm_parameters(algorithm), sort_keys=True),
            "TraceSHA256": trace_hash, "TopologySHA256": topology_hash,
            "Accepted": accepted, "Rejected": rejected,
            "AcceptanceRatio": accepted / max(len(trace), 1),
            "Revenue": revenue, "Cost": cost, "R_C": revenue / cost if cost > EPS else 0.0,
            "ServedRevenue": served_revenue, "ServedCost": served_cost,
            "Served_R_C": served_revenue / served_cost if served_cost > EPS else 0.0,
            "ServedRequestSeconds": served_request_seconds,
            "ServedCPUUnitSeconds": served_cpu_seconds,
            "ServedBandwidthUnitSeconds": served_bandwidth_seconds,
            "Energy_Wh": total_energy, "BootEnergy_J": boot_joules,
            "EnergyPerAccepted_Wh": total_energy / accepted if accepted else math.nan,
            "EnergyPerServedRequestSecond_Wh": total_energy / served_request_seconds if served_request_seconds else math.nan,
            "EnergyPerServedCPUUnitSecond_Wh": total_energy / served_cpu_seconds if served_cpu_seconds else math.nan,
            "EnergyPerServedBandwidthUnitSecond_Wh": total_energy / served_bandwidth_seconds if served_bandwidth_seconds else math.nan,
            "NodeUtil": cpu_area / duration, "LinkUtil": link_area / duration,
            "MeanSampleNodeUtil": safe_mean([s["node_utilization"] for s in snapshots]),
            "MeanSampleLinkUtil": safe_mean([s["link_utilization"] for s in snapshots]),
            "MeanActiveNodes": active_node_area / duration,
            "MeanActiveLinks": active_link_area / duration,
            "MeanHops": hop_sum / max(routed_virtual_links, 1),
            "ExecutionTime": embed_seconds,
            "MeanEmbeddingTime": safe_mean(attempt_times),
            "P95EmbeddingTime": float(np.percentile(attempt_times, 95)) if attempt_times else 0.0,
            "P99EmbeddingTime": float(np.percentile(attempt_times, 99)) if attempt_times else 0.0,
            "SimulationWallTime": time.perf_counter() - start,
            "InitializationTime": initialization_seconds,
            "ReleaseTime": release_seconds, "ValidationTime": validation_seconds,
            "RouteExpansions": algorithm.route_expansions,
            "RouteSearchNodes": getattr(algorithm, "route_search_nodes", 0),
            "RouteBudgetExhaustions": getattr(algorithm, "route_budget_exhaustions", 0),
            "PathBudgetExhaustions": getattr(algorithm, "path_budget_exhaustions", 0),
            "SearchNodes": getattr(algorithm, "search_nodes", 0),
            "SearchBudgetExhaustions": getattr(algorithm, "search_budget_exhaustions", 0),
            "GreenFastRouteSuccesses": getattr(algorithm,"fast_route_successes",0),
            "GreenJointRepairs": getattr(algorithm,"joint_route_repairs",0),
            "GreenRepairSuccesses": getattr(algorithm,"repair_successes",0),
            "GreenFastRouteBatches": getattr(algorithm,"fast_route_batches",0),
            "GreenFastRouteBatchLinks": getattr(algorithm,"fast_route_batch_links",0),
            "AlwaysJointRouteBatches": getattr(algorithm,"always_joint_batches",0),
            "CutChecks": getattr(algorithm,"cut_checks",0),
            "CutRejections": getattr(algorithm,"cut_rejections",0),
            "PackingChecks": getattr(algorithm,"packing_checks",0),
            "PackingRejections": getattr(algorithm,"packing_rejections",0),
            "PackingDegreeBypasses": getattr(algorithm,"packing_bypasses",0),
            "HostMatchingRejections": getattr(algorithm,"host_matching_rejections",0),
            "ConflictRepairAttempts": getattr(algorithm,"conflict_repair_attempts",0),
            "ConflictRepairSuccesses": getattr(algorithm,"conflict_repair_successes",0),
            "ConflictRepairFallbacks": getattr(algorithm,"conflict_repair_fallbacks",0),
            "ConflictRepairReroutedLinks": getattr(algorithm,"conflict_repair_links",0),
            "ConflictProbeExpansions": getattr(algorithm,"conflict_probe_expansions",0),
            "ConflictLocalRouteStates": getattr(algorithm,"conflict_local_states",0),
            "ConflictFallbackRouteStates": getattr(algorithm,"conflict_fallback_states",0),
            "QoSBoundPrunes": getattr(algorithm,"qos_bound_prunes",0),
            "QoSBoundBuilds": getattr(algorithm,"qos_bound_builds",0),
            "QoSBoundLayers": getattr(algorithm,"qos_bound_layers",0),
            "QoSBoundTransitions": getattr(algorithm,"qos_bound_transitions",0),
            "PathDPTransitions": getattr(algorithm,"dp_transitions",0),
            "PathCacheHits": getattr(algorithm,"path_cache_hits",0),
            "TwoHopShortcuts": getattr(algorithm,"two_hop_successes",0),
            "JointRepairSizeSkips": getattr(algorithm,"repair_size_skips",0),
            "ReferenceDeployments": getattr(algorithm,"reference_deployments",0),
            "ReferencePathCandidates": getattr(algorithm,"reference_path_candidates",0),
            "ReferencePSOUpdates": getattr(algorithm,"reference_pso_updates",0),
            "Convergence": list(algorithm.history),
            "NumRequests": len(trace), "Duration": float(duration), "NumSubstrateNodes": int(num_nodes),
        })
    return results


def _flatten_results(records: List[Dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        row = dict(record)
        row.pop("Convergence", None)
        rows.append(row)
    return pd.DataFrame(rows)


def _task_worker(task):
    lam, seed, duration, num_nodes, include_pso, include_ablations, scenario, *reference = task
    return run_simulation(lam, duration, num_nodes, seed, include_pso,
                          include_ablations=include_ablations, scenario=scenario,
                          include_reference_baselines=bool(reference and reference[0]))


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _complete_task_keys(frame, expected_algorithms):
    if frame.empty:
        return set()
    return {(float(lam), int(seed)) for (lam,seed), group in frame.groupby(["Lambda","Seed"])
            if set(group.Algorithm) == set(expected_algorithms)
            and not group.Algorithm.duplicated().any()}


def run_full_evaluation(output_dir="results", lambdas=(2,4,6,8,10,12),
                        seeds=tuple(range(10)), duration=10000.0, num_nodes=50,
                        workers=1, include_pso=False, resume=True, include_ablations=False,
                        scenario=None, include_reference_baselines=False):
    if stats is None:
        raise RuntimeError("Full evaluation requires scipy for reported statistics")
    if not lambdas or not seeds or len(set(lambdas)) != len(lambdas) or len(set(seeds)) != len(seeds):
        raise ValueError("lambdas and seeds must be nonempty and contain no duplicates")
    if duration <= 0 or not math.isfinite(duration) or num_nodes < 2 or workers < 1:
        raise ValueError("Invalid duration, substrate size or worker count")
    if any(not math.isfinite(x) or x <= 0 for x in lambdas):
        raise ValueError("All lambdas must be finite and positive")
    workers = min(int(workers), 4)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    suffix = ("_with_pso" if include_pso else "") + ("_ablations" if include_ablations else "")
    checkpoint = output / ("full_evaluation" + suffix + ".csv")
    config_path = checkpoint.with_suffix(".config.json")
    scenario = scenario or Scenario()
    spec = _experiment_spec(duration, num_nodes, workers, include_pso, include_ablations, scenario,
                            include_reference_baselines)
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    expected = spec["algorithms"]
    task_grid = {"lambdas": [float(load) for load in lambdas],
                 "seeds": [int(seed) for seed in seeds]}
    existing = pd.DataFrame()
    if resume and checkpoint.exists():
        if not config_path.exists():
            raise ValueError("Checkpoint lacks experiment metadata; choose a new output directory or --no-resume")
        old_config = json.loads(config_path.read_text(encoding="utf-8"))
        if old_config.get("fingerprint") != fingerprint:
            raise ValueError("Checkpoint configuration/code/environment differs; choose a new output directory or --no-resume")
        existing = pd.read_csv(checkpoint, float_precision='round_trip')
        required = {"Lambda","Seed","Algorithm","Duration","NumSubstrateNodes","ExperimentFingerprint",
                    "Accepted","Rejected","NumRequests","AcceptanceRatio","Energy_Wh","Revenue",
                    "Cost","R_C","Served_R_C","NodeUtil","LinkUtil","MeanHops","ExecutionTime",
                    "EnergyPerAccepted_Wh",
                    "EnergyPerServedRequestSecond_Wh","MeanEmbeddingTime","P95EmbeddingTime",
                    "AlgorithmScope","AlgorithmParameters"}
        if not required.issubset(existing.columns) or existing.duplicated(["Lambda","Seed","Algorithm"]).any():
            raise ValueError("Checkpoint columns or unique task keys are invalid")
        if (not existing.ExperimentFingerprint.eq(fingerprint).all()
                or not existing.Duration.eq(duration).all()
                or not existing.NumSubstrateNodes.eq(num_nodes).all()
                or not set(existing.Algorithm).issubset(expected)):
            raise ValueError("Checkpoint rows do not match experiment metadata")
        if not existing.Accepted.add(existing.Rejected).eq(existing.NumRequests).all():
            raise ValueError("Checkpoint request accounting is invalid")
        for row in existing.itertuples():
            if (row.AlgorithmScope != spec["algorithm_scope"][row.Algorithm]
                    or json.loads(row.AlgorithmParameters) != spec["algorithm_parameters"][row.Algorithm]):
                raise ValueError("Checkpoint algorithm metadata is invalid")
        previous_grid = old_config.get("task_grid", {})
        if (not existing.Lambda.isin(lambdas).all() or not existing.Seed.isin(seeds).all()
                or not set(previous_grid.get("lambdas", [])).issubset(lambdas)
                or not set(previous_grid.get("seeds", [])).issubset(seeds)):
            raise ValueError("Requested grid omits checkpoint cases; include the previous grid or choose a new output directory")
    completed = _complete_task_keys(existing, expected)
    tasks = [(float(l),int(s),float(duration),int(num_nodes),include_pso,include_ablations,scenario,include_reference_baselines)
             for l in lambdas for s in seeds]
    pending = [t for t in tasks if (t[0],t[1]) not in completed]
    if not existing.empty:
        pending_keys = {(t[0],t[1]) for t in pending}
        existing = existing[[ (float(l),int(s)) not in pending_keys for l,s in zip(existing.Lambda,existing.Seed) ]]
    # Write only after resume compatibility is established; never relabel stale data.
    config_path.write_text(json.dumps({"fingerprint":fingerprint,"spec":spec,
                                       "task_grid":task_grid}, indent=2), encoding="utf-8")
    all_frames = [existing] if not existing.empty else []
    print("VNE full evaluation:", len(tasks), "tasks;",len(pending),"pending;", workers,"workers")
    if pending:
        with mp.get_context("spawn").Pool(processes=min(workers,len(pending)), maxtasksperchild=2) as pool:
            for records in pool.imap_unordered(_task_worker, pending, chunksize=1):
                frame = _flatten_results(records)
                frame["ExperimentFingerprint"] = fingerprint
                all_frames.append(frame)
                _atomic_write_csv(pd.concat(all_frames,ignore_index=True), checkpoint)
                print("completed lambda =",records[0]["Lambda"],"seed =",records[0]["Seed"])
    merged = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    result = merged[merged.Lambda.isin(lambdas) & merged.Seed.isin(seeds)].copy()
    result = result.sort_values(["Lambda","Seed","Algorithm"]).reset_index(drop=True)
    write_summary(result, output / ("summary" + suffix + ".csv"))
    write_statistics(result, output / ("statistics" + suffix + ".csv"))
    plot_cdf(result, output / ("acceptance_cdf" + suffix + ".png"))
    return result


def _benjamini_hochberg(p_values: Sequence[float]) -> List[float]:
    if not p_values:
        return []
    order = np.argsort(np.asarray(p_values))
    adjusted = np.empty(len(p_values), dtype=float)
    running = 1.0
    for rank in range(len(order) - 1, -1, -1):
        idx = order[rank]
        value = float(p_values[idx]) * len(order) / (rank + 1)
        running = min(running, value)
        adjusted[idx] = min(1.0, running)
    return adjusted.tolist()


def analytical_results(frame):
    """Mask undefined service quality without changing recorded raw outcomes."""
    result = frame.copy()
    for metric, denominator in (("MeanHops", "Accepted"), ("R_C", "Cost"),
                                ("Served_R_C", "ServedCost")):
        if metric in result and denominator in result:
            result.loc[result[denominator].le(0), metric] = np.nan
    return result


def write_summary(frame, path):
    frame = analytical_results(frame)
    metrics = ["AcceptanceRatio","R_C","Energy_Wh","NodeUtil","LinkUtil","MeanHops","ExecutionTime"]
    metrics += [m for m in ("Served_R_C","EnergyPerAccepted_Wh",
        "EnergyPerServedRequestSecond_Wh","MeanEmbeddingTime","P95EmbeddingTime","P99EmbeddingTime",
        "EnergyPerServedCPUUnitSecond_Wh","EnergyPerServedBandwidthUnitSecond_Wh") if m in frame]
    rows = []
    for (lam, name), group in frame.groupby(["Lambda","Algorithm"]):
        for metric in metrics:
            x = group[metric].replace([np.inf,-np.inf],np.nan).dropna().to_numpy()
            n = len(x)
            mean = float(np.mean(x)) if n else math.nan
            sd = float(np.std(x,ddof=1)) if n > 1 else math.nan
            half = float(stats.t.ppf(.975,n-1) * sd / math.sqrt(n)) if n > 1 and stats is not None else math.nan
            rows.append({"Lambda":lam,"Algorithm":name,"Metric":metric,"n":n,"mean":mean,
                         "std":sd,"mean_ci95_low":mean-half,"mean_ci95_high":mean+half})
    summary = pd.DataFrame(rows)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    summary.to_csv(path,index=False)
    return summary


def write_statistics(frame, path):
    """Within-load, seed-paired Wilcoxon; BH family is all valid tests in this file.

    Paired differences must be independent across seeds; signed-rank inference
    assumes a symmetric difference distribution. Bootstrap CI is a percentile
    interval for the mean paired difference, not a signed-rank confidence interval.
    """
    if stats is None:
        raise RuntimeError("scipy is required for inferential statistics")
    if frame.duplicated(["Lambda","Seed","Algorithm"]).any():
        raise ValueError("Duplicate load/seed/algorithm observations must not be averaged")
    frame = analytical_results(frame)
    metrics = ["AcceptanceRatio","R_C","Energy_Wh","NodeUtil","LinkUtil"]
    metrics += [m for m in ("Served_R_C","EnergyPerAccepted_Wh",
        "EnergyPerServedRequestSecond_Wh","ExecutionTime","MeanEmbeddingTime",
        "P95EmbeddingTime","P99EmbeddingTime","EnergyPerServedCPUUnitSecond_Wh",
        "EnergyPerServedBandwidthUnitSecond_Wh") if m in frame]
    rows = []
    for lam, load_frame in frame.groupby("Lambda"):
        for baseline in sorted(set(load_frame.Algorithm) - {"ProposedAdaptive"}):
            for metric in metrics:
                pivot = load_frame[load_frame.Algorithm.isin(["ProposedAdaptive",baseline])].pivot(
                    index="Seed",columns="Algorithm",values=metric)
                if not {"ProposedAdaptive",baseline}.issubset(pivot.columns):
                    continue
                pivot = pivot.replace([np.inf,-np.inf],np.nan).dropna()
                differences = (pivot.ProposedAdaptive-pivot[baseline]).to_numpy()
                n = len(differences)
                nonzero = differences[np.abs(differences) > EPS]
                pvalue = math.nan
                effect = math.nan
                status = "insufficient_pairs"
                ci_low = ci_high = math.nan
                if n >= 2:
                    status = "ok"
                    if len(nonzero) == 0:
                        pvalue, effect = 1.0, 0.0
                    else:
                        ranks = stats.rankdata(np.abs(nonzero))
                        effect = float(np.sum(np.sign(nonzero)*ranks)/np.sum(ranks))
                        try:
                            pvalue = float(stats.wilcoxon(nonzero, alternative="two-sided", method="auto").pvalue)
                        except ValueError as error:
                            status = "test_error: " + str(error)
                    salt = int.from_bytes(hashlib.sha256(f"{lam}:{baseline}:{metric}".encode()).digest()[:8],"big")
                    rng = np.random.default_rng(salt)
                    means = rng.choice(differences,size=(2000,n),replace=True).mean(axis=1)
                    ci_low,ci_high = map(float,np.quantile(means,[.025,.975]))
                rows.append({"Lambda":lam,"Metric":metric,"Baseline":baseline,"n":n,
                             "mean_paired_difference":float(np.mean(differences)) if n else math.nan,
                             "preferred_direction": "higher" if metric in ("AcceptanceRatio","R_C","Served_R_C") else "lower" if metric.startswith("Energy") or metric in ("ExecutionTime","MeanEmbeddingTime","P95EmbeddingTime","P99EmbeddingTime") else "context_dependent",
                             "paired_mean_ci95_low":ci_low,"paired_mean_ci95_high":ci_high,
                             "p_value":pvalue,"matched_pairs_rank_biserial":effect,"status":status})
    columns = ["Lambda","Metric","Baseline","n","mean_paired_difference","preferred_direction","paired_mean_ci95_low",
               "paired_mean_ci95_high","p_value","matched_pairs_rank_biserial","status"]
    result = pd.DataFrame(rows,columns=columns)
    result["q_value"] = np.nan
    finite = result.p_value.notna() & np.isfinite(result.p_value)
    result.loc[finite,"q_value"] = _benjamini_hochberg(result.loc[finite,"p_value"].tolist())
    result["correction_family"] = "all valid tests in this file"
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(path,index=False)
    return result


def plot_cdf(frame, path):
    if frame.empty:
        return
    loads = sorted(frame.Lambda.unique())
    cols = min(3,len(loads))
    rows = math.ceil(len(loads)/cols)
    figure, axes = plt.subplots(rows,cols,figsize=(5*cols,4*rows),squeeze=False)
    for ax,lam in zip(axes.flat,loads):
        for algorithm,group in frame[frame.Lambda.eq(lam)].groupby("Algorithm"):
            values = np.sort(group.AcceptanceRatio.to_numpy())
            ax.step(values,np.arange(1,len(values)+1)/len(values),where="post",label=algorithm)
        ax.set(title=f"Acceptance across seeds; lambda={lam:g} per 100 s",
               xlabel="Acceptance ratio (fraction)",ylabel="Empirical cumulative probability")
        ax.grid(alpha=.25)
        ax.legend(fontsize=7)
    for ax in list(axes.flat)[len(loads):]:
        ax.set_visible(False)
    figure.tight_layout()
    figure.savefig(path,dpi=180)
    plt.close(figure)


def run_scalability_experiment(output_dir="results", substrate_sizes=(25,50,75,100,150),
                               seeds=tuple(range(10)), duration=5000.,workers=1,
                               include_pso=False,include_ablations=False,resume=True,scenario=None,
                               include_reference_baselines=False):
    """Fixed-arrival-rate size sweep, not an equal-load-ratio experiment.

    At fixed extra-edge probability, density and offered load/capacity change
    with size. Interpret time/capacity results accordingly; a constant-degree,
    capacity-scaled workload is a separate required experiment for scale claims.
    """
    if not substrate_sizes or len(set(substrate_sizes)) != len(substrate_sizes):
        raise ValueError("substrate_sizes must be nonempty and unique")
    frames = []
    for size in substrate_sizes:
        frame = run_full_evaluation(str(Path(output_dir)/f"size_{size}"),(6.,),seeds,duration,
                                    size,workers,include_pso,resume,include_ablations,scenario,
                                    include_reference_baselines)
        frame["ScalabilityNodes"] = size
        frames.append(frame)
    result = pd.concat(frames,ignore_index=True)
    _atomic_write_csv(result,Path(output_dir)/"scalability.csv")
    summary = result.groupby(["ScalabilityNodes","Algorithm"])[["ExecutionTime","AcceptanceRatio","Energy_Wh"]].agg(["mean","std","count"])
    summary.to_csv(Path(output_dir)/"scalability_summary.csv")
    return result


def smoke_test(duration=250., num_nodes=20, include_pso=False, include_ablations=False, scenario=None,
               include_reference_baselines=False):
    frame = _flatten_results(run_simulation(4,duration,num_nodes,42,include_pso,
                                            sample_interval=50, include_ablations=include_ablations,
                                            scenario=scenario, include_reference_baselines=include_reference_baselines))
    assert set(frame.Algorithm) == set(_algorithm_names(include_pso,include_ablations,include_reference_baselines))
    assert frame.AcceptanceRatio.between(0,1).all()
    assert frame.Energy_Wh.ge(0).all()
    print(frame[["Algorithm","Accepted","Rejected","AcceptanceRatio","Energy_Wh","ExecutionTime"]].to_string(index=False))
    print("VNE smoke test passed (sanity check, not algorithm-fidelity proof).")
    return frame


def source_fingerprint():
    """Hash every maintained package module and the executable entry point."""
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / 'vne').glob('*.py')) + [root / 'vne_simulation.py']
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def _experiment_spec(duration, num_nodes, workers, include_pso, include_ablations, scenario=None,
                     include_reference_baselines=False):
    """Source digest covers all model/algorithm defaults and module logic."""
    import scipy
    scenario = scenario or Scenario()
    names = _algorithm_names(include_pso, include_ablations, include_reference_baselines)
    fixture = SubstrateNetwork(num_nodes=int(num_nodes), seed=0)
    import networkx
    return {"schema": 14, "duration_seconds": float(duration), "num_nodes": int(num_nodes),
            "scenario": scenario.to_dict(),
            "workers": int(workers), "algorithms": names,
            "algorithm_scope": {name:ALGORITHM_SCOPE[name] for name in names},
            "include_reference_baselines": bool(include_reference_baselines),
            "networkx": networkx.__version__,
            "algorithm_order": "deterministic per-seed shuffle; separate RNG",
            "source_sha256": source_fingerprint(),
            "algorithm_parameters": {name: algorithm_parameters(algorithm_factory(name, fixture, 0, include_pso)) for name in names},
            "hardware": {"system": platform.system(), "release": platform.release(),
                         "machine": platform.machine(), "processor": platform.processor(),
                         "logical_cpus": os.cpu_count()},
            "thread_environment": {name: os.environ.get(name) for name in
                ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')},
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__,
            "model": {"time_unit": "seconds", "arrival_unit": "requests/100 seconds",
                      "topology": "connected random spanning tree plus independent extra links",
                      "link_probability": scenario.link_prob, "cpu_range": [70,130], "bandwidth_range": [40,80],
                      "vnr_nodes": [3,7], "vnr_cpu": [17,42], "vnr_bandwidth": [37,72],
                      "vnr_link_probability": scenario.vnr_link_prob, "lifetime_mean_seconds": scenario.lifetime_mean,
                      "max_virtual_link_delay_ms": scenario.max_delay, "max_virtual_link_hops": scenario.max_hops,
                      "power": "idle+linear CPU for host/transit powered nodes; active-link watts",
                      "node_idle_watts": scenario.p_idle, "node_peak_watts": scenario.p_peak,
                      "active_link_watts": scenario.p_link,
                      "boot_joules_per_node": scenario.boot_energy_joules},
            "adaptations": "paper-based GRC/NodeRank scores + shared bounded unsplittable QoS routing",
            "proposal_policy": {"parameters":algorithm_parameters(algorithm_factory('ProposedAdaptive', fixture, 0)),
                                "placement":"marginal host power/headroom minus bandwidth-weighted optimistic extra hops",
                                "search":"one original-order greedy construction, then constrained-node recovery; both share the total24-state quota",
                                "feasibility":"request-start joint hop/delay port domains and exact local packing; necessary conditions only",
                                "routing":"minimum feasible hops; two-hop activation-power preference then delay; longer-hop minimum-delay DP and graph-keyed caches",
                                "repair":"K=3 joint recovery only for at most four closed links; remaining placement search stays bounded",
                                "path_work":"reachable vertex-layer expansions; separate path DP and joint-bound layer/arc-work counters; bounds are timed inside embed",
                                "optimality":"single-link minimum hops if completed; no whole-request/global energy guarantee"},
            "legacy_green_policy": {"energy_weight":0.45,"node_budget":24,"route_budget":24,
                             "path_expansion_budget":240,"candidate_limit":8,"repair_k":3,"boot_amortization_seconds":500,
                             "hop_footprint":0.25,"selective_packing":True,"lazy_paths":True,"conflict_repair":False,"qos_route_bounds":False,
                             "placement_checks":"shared request profiles, conservative cut bounds, exact packing on ranked shortlist up to degree 10; conservative QoS domains",
                             "routing_objective":"earlier marginal power + 0.25 per-hop footprint + congestion + delay; lazy fast then repair"}}


