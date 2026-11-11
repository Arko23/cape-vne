"""Validate a completed paired experiment and produce reproducible comparisons.

This reads frozen raw results; it does not tune policies or alter the simulator.
Across-load means are descriptive averages, with equal weight per load/seed.
Inference remains within load and paired by seed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vne
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from vne.experiments import source_fingerprint, analytical_results


RAW_NAME = "full_evaluation_with_pso_ablations.csv"
PRIMARY = ["ProposedAdaptive", "GRC", "NodeRank", "GreedyKSP", "EnergyAware", "PSO"]
REFERENCE_PRIMARY = ['ProposedAdaptive', *vne.REFERENCE_ALGORITHMS]
METRICS = ["AcceptanceRatio", "Energy_Wh", "EnergyPerAccepted_Wh",
           "EnergyPerServedRequestSecond_Wh", "MeanEmbeddingTime", "P95EmbeddingTime"]
ADDITIONAL_METRICS = ["R_C", "Served_R_C", "P99EmbeddingTime",
                      "EnergyPerServedCPUUnitSecond_Wh", "EnergyPerServedBandwidthUnitSecond_Wh"]


def primary_methods(frame):
    """Use the reference cohort when present; preserve historical reports."""
    return REFERENCE_PRIMARY if set(REFERENCE_PRIMARY).issubset(set(frame.Algorithm)) else PRIMARY


def archive_source_hash(path):
    """Hash the measured source bytes in a ZIP without importing archived code."""
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist()
                       if name.startswith('vne/') and name.count('/') == 1
                       and name.endswith('.py'))
        if not names or 'vne_simulation.py' not in archive.namelist():
            raise ValueError('Archive lacks the simulator package or entry point')
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Archive contains duplicate entries')
        for name in names + ['vne_simulation.py']:
            digest.update(name.encode('utf-8') + b'\0' + archive.read(name) + b'\0')
    return digest.hexdigest()


def validate_raw(directory, source_archive=None):
    raw = directory / RAW_NAME
    config = json.loads(raw.with_suffix(".config.json").read_text(encoding="utf-8"))
    spec = config["spec"]
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if fingerprint != config["fingerprint"]:
        raise ValueError("Manifest fingerprint does not match its specification")
    checked_source = (archive_source_hash(source_archive) if source_archive
                      else source_fingerprint())
    if checked_source != spec["source_sha256"]:
        raise ValueError("Checked simulator source differs from the measured source")
    if "task_grid" in config:
        loads = config["task_grid"]["lambdas"]
        seeds = config["task_grid"]["seeds"]
        if (not loads or not seeds or len(set(loads)) != len(loads)
                or len(set(seeds)) != len(seeds)
                or any(not np.isfinite(load) or load <= 0 for load in loads)
                or any(not isinstance(seed, int) for seed in seeds)):
            raise ValueError("Invalid task grid in the experiment manifest")
    else:
        raise ValueError("Experiment manifest lacks its task grid; run a fresh schema-14 experiment")
    names = spec["algorithms"]
    # Preserve the measured IEEE floats: parser rounding can break Wilcoxon ties.
    frame = pd.read_csv(raw, float_precision="round_trip")
    expected = {(load, seed, name) for load in loads for seed in seeds for name in names}
    actual = set(zip(frame.Lambda, frame.Seed, frame.Algorithm))
    if len(frame) != len(expected) or actual != expected or frame.duplicated(["Lambda", "Seed", "Algorithm"]).any():
        raise ValueError("Experiment is incomplete or has duplicate/unexpected rows")
    if not frame.ExperimentFingerprint.eq(fingerprint).all():
        raise ValueError("Result fingerprints disagree with the manifest")
    if not frame.Duration.eq(spec["duration_seconds"]).all() or not frame.NumSubstrateNodes.eq(spec["num_nodes"]).all():
        raise ValueError("Result dimensions disagree with the manifest")
    counts = frame[["Accepted", "Rejected", "NumRequests"]]
    if not np.isfinite(counts).all().all() or not counts.ge(0).all().all() or not counts.eq(np.floor(counts)).all().all():
        raise ValueError("Request counts must be finite nonnegative integers")
    if not frame.Accepted.add(frame.Rejected).eq(frame.NumRequests).all():
        raise ValueError("Accepted plus rejected does not equal generated requests")
    if not frame.groupby(["Lambda", "Seed"]).NumRequests.nunique().eq(1).all():
        raise ValueError("Comparison algorithms did not share a common request count")
    for name in ('TraceSHA256', 'TopologySHA256'):
        if name in frame:
            if (not frame[name].str.fullmatch('[0-9a-f]{64}').all()
                    or not frame.groupby(['Lambda', 'Seed'])[name].nunique().eq(1).all()):
                raise ValueError(f"Common input fingerprints disagree: {name}")
    expected_acceptance = frame.Accepted / frame.NumRequests.clip(lower=1)
    np.testing.assert_allclose(frame.AcceptanceRatio, expected_acceptance, atol=1e-12, rtol=1e-12)
    for column in ("Energy_Wh", "BootEnergy_J", "ExecutionTime", "SimulationWallTime", "MeanEmbeddingTime", "P95EmbeddingTime", "ServedRequestSeconds"):
        if not np.isfinite(frame[column]).all() or not frame[column].ge(0).all():
            raise ValueError(f"Invalid values in {column}")
    for column in ("NodeUtil", "LinkUtil"):
        if not frame[column].between(-1e-9, 1 + 1e-9).all():
            raise ValueError(f"Invalid utilization in {column}")
    if (frame.Energy_Wh + 1e-9 < frame.BootEnergy_J / 3600).any():
        raise ValueError("Total energy is below boot energy")
    if (frame.ServedRequestSeconds > frame.Accepted * frame.Duration + 1e-7).any():
        raise ValueError("Served request time exceeds the horizon bound")
    for metric, divisor in (("EnergyPerAccepted_Wh", frame.Accepted),
                            ("EnergyPerServedRequestSecond_Wh", frame.ServedRequestSeconds)):
        expected_ratio = frame.Energy_Wh / divisor.replace(0, np.nan)
        np.testing.assert_allclose(frame[metric], expected_ratio, atol=1e-12, rtol=1e-10, equal_nan=True)
    for metric, divisor_name in (("EnergyPerServedCPUUnitSecond_Wh", "ServedCPUUnitSeconds"),
                                 ("EnergyPerServedBandwidthUnitSecond_Wh", "ServedBandwidthUnitSeconds")):
        if metric in frame:
            divisor = frame[divisor_name]
            if not np.isfinite(divisor).all() or not divisor.ge(0).all():
                raise ValueError(f"Invalid served resource time: {divisor_name}")
            np.testing.assert_allclose(frame[metric], frame.Energy_Wh / divisor.replace(0, np.nan),
                                       atol=1e-12, rtol=1e-10, equal_nan=True)
    np.testing.assert_allclose(frame.MeanEmbeddingTime, frame.ExecutionTime / frame.NumRequests.clip(lower=1),
                               atol=1e-12, rtol=1e-10)
    for row in frame.itertuples():
        if (row.AlgorithmScope != spec["algorithm_scope"][row.Algorithm]
                or json.loads(row.AlgorithmParameters) != spec["algorithm_parameters"][row.Algorithm]):
            raise ValueError("Per-row algorithm settings/scope disagree with the manifest")
    return frame, spec, loads, seeds


def verify_statistics(frame, result):
    """Reconstruct paired comparisons and independently apply BH rank adjustment."""
    frame = analytical_results(frame)
    statistical_metrics = ["AcceptanceRatio", "R_C", "Energy_Wh", "NodeUtil", "LinkUtil",
                           "Served_R_C", "EnergyPerAccepted_Wh", "EnergyPerServedRequestSecond_Wh",
                           "ExecutionTime", "MeanEmbeddingTime", "P95EmbeddingTime"]
    statistical_metrics += [name for name in ADDITIONAL_METRICS if name in frame and name not in statistical_metrics]
    expected = {(load, metric, baseline) for load in frame.Lambda.unique()
                for metric in statistical_metrics
                for baseline in set(frame.Algorithm) - {"ProposedAdaptive"}}
    if set(zip(result.Lambda, result.Metric, result.Baseline)) != expected:
        raise ValueError("Statistical comparison matrix is incomplete or unexpected")
    if result.duplicated(["Lambda", "Metric", "Baseline"]).any():
        raise ValueError("Duplicate statistical comparisons")
    max_p_error = max_effect_error = max_bootstrap_ci_error = 0.0
    for row in result.itertuples():
        subset = frame[(frame.Lambda == row.Lambda) & frame.Algorithm.isin(["ProposedAdaptive", row.Baseline])]
        paired = subset.pivot(index="Seed", columns="Algorithm", values=row.Metric).replace([np.inf, -np.inf], np.nan).dropna()
        differences = (paired.ProposedAdaptive - paired[row.Baseline]).to_numpy()
        if len(differences) != row.n:
            raise ValueError("Reported paired sample size is incorrect")
        mean = differences.mean() if len(differences) else np.nan
        np.testing.assert_allclose(row.mean_paired_difference, mean, atol=1e-10, rtol=1e-10, equal_nan=True)
        if len(differences) < 2:
            if row.status != "insufficient_pairs" or not np.isnan(row.p_value) or not np.isnan(row.q_value):
                raise ValueError("An insufficient comparison must not report a valid test")
            continue
        if row.status != "ok" or not np.isfinite([row.p_value, row.q_value]).all():
            raise ValueError("A complete paired comparison has no valid test")
        salt = int.from_bytes(hashlib.sha256(f"{row.Lambda}:{row.Baseline}:{row.Metric}".encode()).digest()[:8], "big")
        bootstrap = np.random.default_rng(salt).choice(differences, size=(2000, len(differences)), replace=True).mean(axis=1)
        expected_ci = np.quantile(bootstrap, [.025, .975])
        reported_ci = [row.paired_mean_ci95_low, row.paired_mean_ci95_high]
        np.testing.assert_allclose(reported_ci, expected_ci, atol=1e-10, rtol=1e-10)
        max_bootstrap_ci_error = max(max_bootstrap_ci_error, float(np.max(np.abs(expected_ci - reported_ci))))
        nonzero = differences[np.abs(differences) > vne.EPS]
        p = float(stats.wilcoxon(nonzero, method="auto", alternative="two-sided").pvalue) if len(nonzero) else 1.0
        ranks = stats.rankdata(np.abs(nonzero))
        effect = float((np.sign(nonzero) * ranks).sum() / ranks.sum()) if len(nonzero) else 0.0
        max_p_error = max(max_p_error, abs(p - row.p_value))
        max_effect_error = max(max_effect_error, abs(effect - row.matched_pairs_rank_biserial))
    valid = result.p_value.notna() & np.isfinite(result.p_value)
    values = result.loc[valid, "p_value"].to_numpy()
    order = np.argsort(values)
    adjusted_sorted = values[order] * len(values) / np.arange(1, len(values) + 1)
    adjusted_sorted = np.minimum.accumulate(adjusted_sorted[::-1])[::-1].clip(max=1)
    adjusted = np.empty_like(values)
    adjusted[order] = adjusted_sorted
    max_q_error = float(np.max(np.abs(adjusted - result.loc[valid, "q_value"].to_numpy()))) if len(values) else 0.0
    if max(max_p_error, max_q_error, max_effect_error) > 1e-8:
        raise ValueError("Statistical output does not match reconstructed paired observations")
    return {"comparisons": len(result), "valid_tests": int(valid.sum()),
            "max_p_error": max_p_error, "max_q_error": max_q_error, "max_effect_error": max_effect_error,
            "max_bootstrap_ci_error": max_bootstrap_ci_error, "csv_float_precision": "round_trip"}


def verify_summary(frame, summary):
    frame = analytical_results(frame)
    metrics = ["AcceptanceRatio", "R_C", "Energy_Wh", "NodeUtil", "LinkUtil", "MeanHops",
               "ExecutionTime", "Served_R_C", "EnergyPerAccepted_Wh", "EnergyPerServedRequestSecond_Wh",
               "MeanEmbeddingTime", "P95EmbeddingTime"]
    metrics += [name for name in ADDITIONAL_METRICS if name in frame and name not in metrics]
    expected = {(load, name, metric) for load in frame.Lambda.unique()
                for name in frame.Algorithm.unique() for metric in metrics}
    if (set(zip(summary.Lambda, summary.Algorithm, summary.Metric)) != expected
            or summary.duplicated(["Lambda", "Algorithm", "Metric"]).any()):
        raise ValueError("Summary matrix is incomplete or unexpected")
    for row in summary.itertuples():
        values = frame[(frame.Lambda == row.Lambda) & (frame.Algorithm == row.Algorithm)][row.Metric].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        if len(values) != row.n:
            raise ValueError("Summary sample size is incorrect")
        mean = values.mean() if len(values) else np.nan
        sd = values.std(ddof=1) if len(values) > 1 else np.nan
        half = stats.t.ppf(.975, len(values) - 1) * sd / np.sqrt(len(values)) if len(values) > 1 else np.nan
        np.testing.assert_allclose([row.mean, row.std, row.mean_ci95_low, row.mean_ci95_high],
                                   [mean, sd, mean - half, mean + half], atol=1e-10, rtol=1e-10)
    return len(summary)


def comparison_table(frame, statistical):
    frame = analytical_results(frame)
    rows = []
    for load in sorted(frame.Lambda.unique()):
        load_frame = frame[frame.Lambda == load]
        for name in sorted(set(load_frame.Algorithm) - {"ProposedAdaptive"}):
            for metric in METRICS:
                paired = load_frame[load_frame.Algorithm.isin(["ProposedAdaptive", name])].pivot(
                    index="Seed", columns="Algorithm", values=metric).replace([np.inf, -np.inf], np.nan).dropna()
                difference = paired.ProposedAdaptive - paired[name]
                preferred = difference if metric in ("AcceptanceRatio", "R_C", "Served_R_C") else -difference
                row = statistical[(statistical.Lambda == load) & (statistical.Baseline == name) & (statistical.Metric == metric)]
                if len(row) != 1:
                    raise ValueError("Missing critical statistical comparison")
                stats_row = row.iloc[0]
                rows.append({"Lambda": load, "Baseline": name, "Metric": metric, "Pairs": len(paired),
                             "ProposedMean": paired.ProposedAdaptive.mean(), "BaselineMean": paired[name].mean(),
                             "MeanDifference": difference.mean(), "ProposedWins": int((preferred > vne.EPS).sum()),
                             "Ties": int((np.abs(preferred) <= vne.EPS).sum()), "ProposedLosses": int((preferred < -vne.EPS).sum()),
                             "p_value": stats_row.p_value, "q_value": stats_row.q_value,
                             "MeanDifferenceCILow": stats_row.paired_mean_ci95_low,
                             "MeanDifferenceCIHigh": stats_row.paired_mean_ci95_high})
    return pd.DataFrame(rows)


def md_table(frame, columns):
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in frame[columns].itertuples(index=False, name=None):
        lines.append("| " + " | ".join(f"{value:.4f}" if isinstance(value, (float, np.floating)) else str(value) for value in row) + " |")
    return "\n".join(lines)


def plot_comparisons(frame, path, seed_count, workers):
    cohort = primary_methods(frame)
    means = frame[frame.Algorithm.isin(cohort)].groupby(["Lambda", "Algorithm"])[METRICS].mean().reset_index()
    figure, axes = plt.subplots(1, 3, figsize=(16, 5))
    settings = [("AcceptanceRatio", 100, "Acceptance (%)"),
                ("EnergyPerServedRequestSecond_Wh", 1, "Wh per served request-second"),
                ("MeanEmbeddingTime", 1000, "Mean embedding time (ms)")]
    for name in cohort:
        selected = means[means.Algorithm == name].sort_values("Lambda")
        for ax, (metric, factor, label) in zip(axes, settings):
            ax.plot(selected.Lambda, selected[metric] * factor, marker="o", label=name,
                    linewidth=2.5 if name == "ProposedAdaptive" else 1.4)
            ax.set_xlabel("Arrival rate (requests /100 seconds)")
            ax.set_ylabel(label)
            ax.grid(alpha=.25)
    axes[0].legend(fontsize=8)
    axes[2].set_yscale("log")
    figure.suptitle(f"Fresh {seed_count}-seed VNE comparison; runtime measured with {workers} workers")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    figure.savefig(path.with_suffix(".svg"))
    plt.close(figure)


def main():
    global METRICS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-archive", type=Path,
                        help="Validate historical raw data against its matching source ZIP")
    args = parser.parse_args()
    frame, spec, loads, seeds = validate_raw(args.directory, args.source_archive)
    METRICS = METRICS + [name for name in ADDITIONAL_METRICS if name in frame and name not in METRICS]
    statistical = pd.read_csv(args.directory / "statistics_with_pso_ablations.csv", float_precision="round_trip")
    audit = verify_statistics(frame, statistical)
    summary = pd.read_csv(args.directory / "summary_with_pso_ablations.csv", float_precision="round_trip")
    audit["summary_rows_verified"] = verify_summary(frame, summary)
    frame = analytical_results(frame)
    out = args.directory / "analysis"
    out.mkdir(exist_ok=True)
    means = frame.groupby("Algorithm")[METRICS].mean().reset_index()
    totals = frame.groupby("Algorithm")[["Accepted", "Rejected", "NumRequests", "Energy_Wh", "ServedRequestSeconds", "ExecutionTime"]].sum().reset_index()
    totals["PooledAcceptance"] = totals.Accepted / totals.NumRequests
    totals["PooledEnergyPerServedSecond"] = totals.Energy_Wh / totals.ServedRequestSeconds
    totals["PooledEmbeddingTime"] = totals.ExecutionTime / totals.NumRequests
    means.to_csv(out / "overall_means.csv", index=False)
    totals.to_csv(out / "pooled_totals.csv", index=False)
    by_load = frame.groupby(["Lambda", "Algorithm"])[METRICS].mean().reset_index()
    by_load.to_csv(out / "means_by_load.csv", index=False)
    comparisons = comparison_table(frame, statistical)
    comparisons.to_csv(out / "paired_comparisons.csv", index=False)
    counter_columns = [name for name in ("SearchNodes", "SearchBudgetExhaustions", "RouteExpansions", "RouteBudgetExhaustions",
                       "PathBudgetExhaustions", "CutChecks", "CutRejections", "PackingChecks", "PackingRejections",
                       "PackingDegreeBypasses", "GreenFastRouteBatches", "GreenFastRouteSuccesses", "GreenJointRepairs", "GreenRepairSuccesses",
                       "ReferenceDeployments", "ReferencePathCandidates", "ReferencePSOUpdates") if name in frame]
    frame.groupby(["Lambda", "Algorithm"])[counter_columns].mean().to_csv(out / "search_counters.csv")
    audit.update({"rows": len(frame), "loads": loads, "seeds": seeds, "algorithms": spec["algorithms"],
                  "source_sha256": spec["source_sha256"], "raw_sha256": hashlib.sha256((args.directory / RAW_NAME).read_bytes()).hexdigest(),
                  "unique_request_trace_count": int(frame.groupby(["Lambda", "Seed"]).NumRequests.first().sum()),
                  "workers": spec["workers"], "duration_seconds": spec["duration_seconds"]})
    (out / "validation.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    display = means.copy()
    display["AcceptancePercent"] = display.AcceptanceRatio * 100
    display["EmbeddingMilliseconds"] = display.MeanEmbeddingTime * 1000
    display = display.sort_values("AcceptancePercent", ascending=False)
    proposal = means.set_index("Algorithm").loc["ProposedAdaptive"]
    cohort = primary_methods(frame)
    changes = means[means.Algorithm.isin(cohort) & (means.Algorithm != "ProposedAdaptive")].copy()
    changes["AcceptanceGainPP"] = (proposal.AcceptanceRatio - changes.AcceptanceRatio) * 100
    changes["NormalizedEnergyReductionPercent"] = (1 - proposal.EnergyPerServedRequestSecond_Wh / changes.EnergyPerServedRequestSecond_Wh) * 100
    changes["TotalEnergyChangePercent"] = (proposal.Energy_Wh / changes.Energy_Wh.replace(0, np.nan) - 1) * 100
    changes["EmbeddingTimeRatio"] = proposal.MeanEmbeddingTime / changes.MeanEmbeddingTime
    changes.to_csv(out / "proposed_vs_primary.csv", index=False)
    significant = []
    for name in sorted(set(frame.Algorithm) - {"ProposedAdaptive"}):
        for metric in ("AcceptanceRatio", "EnergyPerServedRequestSecond_Wh", "MeanEmbeddingTime"):
            chosen = comparisons[(comparisons.Baseline == name) & (comparisons.Metric == metric)]
            direction = chosen.MeanDifference if metric == "AcceptanceRatio" else -chosen.MeanDifference
            significant.append({"Baseline": name, "Metric": metric,
                                "SignificantBetterLoads": int(((direction > 0) & (chosen.q_value < .05)).sum()),
                                "SignificantWorseLoads": int(((direction < 0) & (chosen.q_value < .05)).sum()),
                                "OtherLoads": int((~((direction != 0) & (chosen.q_value < .05))).sum())})
    significant = pd.DataFrame(significant)
    significant.to_csv(out / "significance_by_comparison.csv", index=False)
    sections = ["# Fresh full evaluation\n",
                f"{len(loads)} loads ×{len(seeds)} seeds ×{len(spec['algorithms'])} algorithms = {len(frame):,} observations. "
                f"Substrate nodes: {spec['num_nodes']}; horizon: {spec['duration_seconds']:g} seconds; workers: {spec['workers']}. "
                f"Unique generated requests across paired traces: {audit['unique_request_trace_count']:,}.\n",
                "The simulator source remained frozen. All expected rows, common request counts, scope/parameter metadata, "
                "resource-time ratios and reported paired statistics passed independent reconstruction checks.\n",
                "## Across-load descriptive means\n",
                "Each load/seed observation has equal weight. Energy ratios are means of per-run ratios. "
                "The separately supplied pooled totals weight requests/service differently.\n",
                md_table(display, ["Algorithm", "AcceptancePercent", "Energy_Wh", "EnergyPerServedRequestSecond_Wh", "EmbeddingMilliseconds"]),
                "\n## Proposal against primary comparison methods\n",
                "Positive acceptance gain and normalized-energy reduction favor the proposal. "
                "A positive total-energy change means it consumes more total energy; a runtime ratio above1 means it is slower.\n",
                md_table(changes, ["Algorithm", "AcceptanceGainPP", "NormalizedEnergyReductionPercent", "TotalEnergyChangePercent", "EmbeddingTimeRatio"]),
                "\n## Within-load paired significance\n",
                f"{len(seeds)} seeds are paired within each load. q<0.05 uses BH correction over all valid tests in the original statistical file. "
                "Across-load means are descriptive and do not have an overall pooled p-value. "
                "Other loads include ties, nonsignificant comparisons and undefined tests.\n",
                md_table(significant, ["Baseline", "Metric", "SignificantBetterLoads", "SignificantWorseLoads", "OtherLoads"]),
                "\n## Limits\n",
                f"This evaluates one recorded synthetic topology/workload/power scenario. Runtime was measured with {spec['workers']} workers; "
                "use separate serial experiments for isolated latency claims. "
                + ("Virne methods are ports of the pinned reference code with the common hard delay/hop gates; VirnePSO uses a documented "
                   "parent-visible serial scheduler correction. They are not verified complete original-paper reproductions. "
                   if cohort == REFERENCE_PRIMARY else
                   "GRC/NodeRank are ranking-based adaptations and the remaining primary baselines are custom implementations. ")
                + "Results do not establish superiority over omitted full-paper implementations or literature novelty. See the root REFERENCES.md.\n"]
    (out / "REPORT.md").write_text("\n".join(sections), encoding="utf-8")
    plot_comparisons(frame, out / "primary_comparison.png", len(seeds), spec['workers'])
    print(json.dumps(audit, indent=2))
    print(display[["Algorithm", "AcceptancePercent", "Energy_Wh", "EnergyPerServedRequestSecond_Wh", "EmbeddingMilliseconds"]].to_string(index=False))
    print(changes[["Algorithm", "AcceptanceGainPP", "NormalizedEnergyReductionPercent", "TotalEnergyChangePercent", "EmbeddingTimeRatio"]].to_string(index=False))


if __name__ == "__main__":
    main()
