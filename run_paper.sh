#!/usr/bin/env bash
# run_paper.sh: Full 5,760-run experimental benchmark execution launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="${1:-full}"
WORKERS="${2:-4}"
SEED_COUNT="${3:-30}"
SEED_START="${4:-11000}"
DURATION="${5:-20000}"
OUTPUT_DIR="${6:-results/benchmark_${MODE}}"

# Generate comma-separated seed sequence
SEEDS=$(seq -s, "${SEED_START}" $((SEED_START + SEED_COUNT - 1)))

echo "=========================================================="
echo "CAPE-VNE Simulation Benchmark"
echo "Mode:         ${MODE}"
echo "Workers:      ${WORKERS}"
echo "Seeds:        ${SEED_COUNT} (${SEED_START} .. $((SEED_START + SEED_COUNT - 1)))"
echo "Duration:     ${DURATION} seconds"
echo "Arrivals (λ): [2, 4, 6, 8, 10, 12] VNRs / 100s"
echo "Substrate:    50 nodes, Erdős-Rényi p = 0.35"
echo "Output Dir:   ${OUTPUT_DIR}"
echo "=========================================================="

bash "${SCRIPT_DIR}/run.sh" \
    --mode "${MODE}" \
    --duration "${DURATION}" \
    --seeds "${SEEDS}" \
    --workers "${WORKERS}" \
    --num-nodes 50 \
    --lambdas "2,4,6,8,10,12" \
    --include-pso \
    --include-ablations \
    --include-reference-baselines \
    --link-prob 0.35 \
    --vnr-link-prob 0.4 \
    --lifetime-mean 500 \
    --max-delay 25 \
    --max-hops 8 \
    --p-idle 150 \
    --p-peak 350 \
    --p-link 5 \
    --boot-energy-joules 50 \
    --output-dir "${OUTPUT_DIR}"
