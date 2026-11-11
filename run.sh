#!/usr/bin/env bash
# run.sh: Execution wrapper for the CAPE-VNE simulator on Linux / macOS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect Python interpreter
if [[ -n "${VNE_PYTHON:-}" ]]; then
    PYTHON_BIN="${VNE_PYTHON}"
elif [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
elif [[ -x "${SCRIPT_DIR}/venv/bin/python" ]]; then
    PYTHON_BIN="${SCRIPT_DIR}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: Python interpreter not found. Please install Python 3.10+." >&2
    exit 1
fi

cd "${SCRIPT_DIR}"
exec "${PYTHON_BIN}" -B "${SCRIPT_DIR}/vne_simulation.py" "$@"
