#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export PYTHONDONTWRITEBYTECODE=1

python3 parity_harness.py
python3 main.py mixed --duration 100 --cpus 2 --no-stats --seed 1
python3 main.py warp --duration 100 --cpus 2 --no-stats --seed 1
python3 main.py starvation --duration 100 --cpus 2 --no-stats --seed 1

echo "All parity checks passed."
