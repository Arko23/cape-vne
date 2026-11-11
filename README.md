# CAPE-VNE: Coordinated Adaptive Pruning and Embedding for Virtual Networks

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Reproducibility](https://img.shields.io/badge/Benchmark-5%2C760%20Runs%20Verified-success.svg)](results/)

This repository provides the complete, official open-source implementation and evaluation artifacts for **CAPE-VNE** (Coordinated Adaptive Pruning and Embedding for Virtual Networks), prepared for publication in **Elsevier *Computer Communications* (COMCOM)**.

---

## 1. System Overview

Online Virtual Network Embedding (VNE) requires allocating virtual nodes and links onto shared physical substrate infrastructure under joint compute, bandwidth, latency, and hop constraints. Traditional green consolidation approaches suffer from the **Consolidation Rejection Trap**: by packing virtual workloads onto a minimum number of physical chassis, they exhaust incident egress bandwidth and create localized perimeter bottlenecks, resulting in severe long-term request rejections.

**CAPE-VNE** overcomes this trap through a coordinated seven-stage pipeline:
1. **Injective Compute & Bipartite Cut Feasibility Certificates (`vne/pruning.py`):** Pre-screens infeasible requests in $<0.1\text{ ms}$ before executing graph searches.
2. **Incident Cut-Capacity Screening (`vne/pruning.py`):** Enforces sound threshold and aggregate bandwidth capacity cuts.
3. **Exact First-Hop Subset Packing DP (`vne/efficient.py`):** Uses bitmask dynamic programming over egress ports to eliminate early routing blockages.
4. **Two-Pass Hybrid Search Engine (`vne/algorithms.py`):** Employs Pass 1 greedy construction followed by Pass 2 fail-first recursive recovery under a strict expansion budget ($B=24$).
5. **Multi-Attribute Green Host Scoring (`vne/green.py`):** Balances compute headroom, link quality, and marginal booting power via a load-adaptive energy weight $\widetilde{\omega}_E(t)$.
6. **Power-Aware Multi-Tier Link Routing (`vne/efficient.py`):** Combines 1-hop shortcuts, 2-hop power-aware intersections, and hop-layered dynamic programming with Yen's KSP repair.
7. **Atomic State Transactions (`vne/models.py`):** Ensures zero orphaned reservations upon admission failure.

---

## 2. Repository Structure

```
cape-vne/
├── README.md                      # This comprehensive documentation file
├── LICENSE                        # Open-source MIT license
├── requirements.txt               # Base dependency specification
├── requirements-tested.txt        # Pinned versions tested during benchmarking
├── vne_simulation.py              # CLI entry point for single and batch simulations
├── run.sh / run.ps1               # Quick execution helper scripts (Linux/macOS and Windows)
├── run_paper.sh / run_paper.ps1   # Benchmark suite runners for paper evaluation
├── ALGORITHM_GUIDE.md             # Algorithmic and architectural design reference
├── REFERENCES.md                  # Implementation fidelity and baseline lineage
├── vne/                           # Core algorithmic pipeline
│   ├── algorithms.py              # Search engine, Pass 1 greedy, Pass 2 recovery, Yen's KSP
│   ├── pruning.py                 # Stage 1-2 compute certificates and incident cut filters
│   ├── efficient.py               # Stage 3 subset packing DP and Stage 6 multi-tier routing
│   ├── green.py                   # Stage 5 dynamic green utility and load-adaptive weights
│   ├── models.py                  # Graph data structures, substrate models, atomic transactions
│   ├── experiments.py             # Evaluation runners, metrics collectors, Poisson generators
│   ├── cli.py                     # Command-line interface definitions
│   └── configuration.py           # Experiment configurations and baseline presets
├── scripts/                       # Reproduction and data analysis utilities
│   ├── reproduce_paper_results.py # Instant reproduction of paper Tables 4, 5, 6, and 7
│   ├── analyze_full_results.py    # Statistical aggregation and figure generation
│   ├── rank_results.py            # Ordinal ranking across all 32 algorithms
│   ├── audit_energy.py            # Work-normalized energy calculation audit
│   └── topology_inputs.py         # Substrate and virtual topology generators
├── tests/                         # Unit and integration test suite
│   ├── test_pruning.py            # Stage 1-3 certificate and cut pruning unit tests
│   ├── test_efficient.py          # Dynamic programming subset packing unit tests
│   ├── test_green.py              # Power models and load-adaptive scoring tests
│   ├── test_conflict_repair.py    # Yen's KSP and joint link repair tests
│   └── test_reference_baselines.py# Baseline and Virne reference port unit tests
├── third_party/                   # Standardized third-party reference ports
│   └── virne/                     # Pinned reference implementations from the Virne library
└── results/                       # Master evaluation results archive
    └── full_30seeds_32methods/    # Complete 5,760-run evaluation dataset
        ├── full_evaluation_with_pso_ablations.csv # Raw 8.28 MB simulation records
        ├── analysis/              # Pre-computed statistical summaries and tests
        │   ├── overall_means.csv  # Grand means across all 180 runs per method
        │   ├── means_by_load.csv  # Performance aggregated by arrival rate lambda
        │   └── paired_comparisons.csv # Wilcoxon paired signed-rank test outputs
        └── rankings/              # Metric rankings across all evaluation conditions
```

---

## 3. Quickstart & Environment Setup

### 3.1 Installation

Clone the repository and install dependencies inside a Python virtual environment:

```bash
# Clone the repository
git clone https://github.com/<your-username>/cape-vne.git
cd cape-vne

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # On Windows: .venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

### 3.2 Running a Quick Simulation

To execute a test run comparing CAPE-VNE with baselines:

```bash
# On Linux / macOS:
./run.sh

# On Windows (PowerShell):
.\run.ps1
```

Or run directly via Python CLI:

```bash
python3 vne_simulation.py --help
```

---

## 4. Instant Reproduction of Published Paper Results

The repository includes the complete evaluation dataset comprising **5,760 full simulation runs** across **32 algorithms**, **30 independent topological random seeds** ($11000 \le \text{seed} \le 11029$), and **6 traffic arrival rates** ($\lambda \in \{2, 4, 6, 8, 10, 12\}$).

To reproduce the four primary tables published in the manuscript without re-running thousands of CPU hours:

```bash
python3 scripts/reproduce_paper_results.py
```

This standalone script (requiring zero external libraries) parses the benchmark dataset and outputs:
* **Table 4:** Grand Mean Performance Summary for the 11 primary algorithms (Acceptance Ratio, R/C Ratio, Energy per VNR, Gross Energy, Work-Normalized Energy per CPU-second, and Latency per VNR).
* **Table 5:** Detailed Breakdown of Mean Acceptance Ratio across traffic loads ($\lambda \in [2, 12]$).
* **Table 6:** Component Ablation Matrix isolating the contributions of Stage 2 incident cuts, Stage 3 bitmask DP, Stage 4 recovery, Stage 5 adaptive weights, and Stage 6 link repair.
* **Table 7:** Paired Two-Sided Wilcoxon Signed-Rank Tests across $N=30$ seeds under moderate ($\lambda=6$) and saturated ($\lambda=12$) traffic, reporting raw $p$-values, Benjamini-Hochberg FDR $q$-values, and rank-biserial correlations.

---

## 5. End-to-End Benchmark Simulation

To execute the full simulation benchmark from scratch:

```bash
# On Linux / macOS:
./run_paper.sh

# On Windows (PowerShell):
.\run_paper.ps1
```

The experiment runner coordinates parallel simulation workers across the parameter space:
* **Substrate Network:** 50-node Waxman random graphs ($\alpha=0.5, \beta=0.2$).
* **Virtual Network Requests:** 3 to 10 nodes per slice with Poisson arrivals $\lambda \in \{2, 4, 6, 8, 10, 12\}$ per 100 seconds and exponentially distributed lifetimes ($\mu = 500\text{ s}$).
* **Simulation Horizon:** $T = 20{,}000\text{ s}$ per run.

Simulation outputs are automatically written to `results/` in CSV and JSON formats.

---

## 6. Algorithmic Pipeline & Source File Mapping

| Architectural Stage | Key Mathematical Operation | Source Code Implementation |
|---|---|---|
| **Stage 1: Feasibility Certificates** | Injective compute sorting & bipartite DFS matching | `vne/pruning.py:augmenting_path_matching()` |
| **Stage 2: Incident Cut Screening** | Host egress incident residual bandwidth cuts | `vne/pruning.py:incident_cut_filter()` |
| **Stage 3: First-Hop Subset Packing** | Bitmask dynamic programming over egress ports | `vne/efficient.py:subset_packing_dp()` |
| **Stage 4: Two-Pass Search Engine** | Pass 1 greedy construction & Pass 2 fail-first search | `vne/algorithms.py:two_pass_search()` |
| **Stage 5: Multi-Attribute Green Scoring** | Dynamic green utility with adaptive weight $\widetilde{\omega}_E(t)$ | `vne/green.py:dynamic_green_score()` |
| **Stage 6: Multi-Tier Routing** | 1-hop shortcut, 2-hop intersection & layered DP | `vne/efficient.py:multi_tier_route()` |
| **Stage 7: Atomic Transaction Commit** | Injective validation & isolated trial rollback | `vne/models.py:TrialState.commit()` |

---

## 7. Running Unit Tests

To run the automated test suite verifying algorithm correctness, certificate soundness, and baseline implementations:

```bash
python3 -m unittest discover -s tests
```

---

## 8. Baseline Reference Implementations

The benchmark incorporates 31 comparison algorithms across four cohorts:
1. **Standardized Virne Ports:** `VirnePSO`, `VirneRWBFS`, `VirneGRC`, `VirneRWMaxMatch`, and `VirneFFD` ported from the [GeminiLight/Virne](https://github.com/GeminiLight/virne) framework (details in `REFERENCES.md` and `third_party/virne/NOTICE.md`).
2. **Classical Heuristics:** `GRC` (Gong et al., INFOCOM 2014), `NodeRank` (Cheng et al., CCR 2011), `GreedyKSP` (Yu et al., 2008), and `GreedyCSP`.
3. **Power-Aware Consolidation:** `EA-VNE` (Su et al., IEEE/ACM ToN 2014).
4. **Metaheuristics:** `PSO-VNE` (Zhang et al., Computer Networks 2013).
5. **Systematic Ablations:** 21 ablation variants isolating cut pruning, exact packing, joint repair, compactness penalties, and search structures.

---

## 9. License & Attribution

* The CAPE-VNE codebase and artifacts are licensed under the **MIT License** (see [LICENSE](LICENSE)).
* Third-party reference code ported from the Virne library is distributed under the **Apache License 2.0** (see [third_party/virne/NOTICE.md](third_party/virne/NOTICE.md)).

---

## 10. Citation

If you use this codebase, benchmark dataset, or algorithmic pipeline in your research, please cite our manuscript:

```bibtex
@article{islam2026cape_vne,
  title     = {Bounded Online Virtual Network Embedding with Joint Feasibility Certificates and Multi-Tier Power-Aware Routing},
  author    = {Islam, Md Shakib Al and Mondol, Mark Protik and Islam, Md. Motaharul},
  journal   = {Computer Communications},
  publisher = {Elsevier},
  year      = {2026},
  note      = {Under Review}
}
```
