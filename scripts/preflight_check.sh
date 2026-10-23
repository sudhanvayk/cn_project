#!/usr/bin/env bash
# Pre-flight check gate for Real Mininet + Ryu SDN verification
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "=== 1. Checking Sudo Access ==="
sudo -n true && echo "SUDO_OK"

echo "=== 2. Checking Mininet & Open vSwitch ==="
which mn ovs-vsctl
sudo ovs-vsctl show | head -n 5

echo "=== 3. Checking Ryu Manager Environment ==="
RYU_BIN="${RYU_BIN:-$HOME/ryu-env/bin/ryu-manager}"
if [ ! -x "$RYU_BIN" ]; then
    echo "[ERROR] ryu-manager not found at $RYU_BIN"
    exit 1
fi
"$RYU_BIN" --version

echo "=== 4. Checking Ports (6653, 6633, 8080, 9999) ==="
if ss -ltnp | grep -E ':(6653|6633|8080|9999)\b'; then
    echo "[ERROR] Stale processes listening on required ports. Please run 'sudo mn -c && pkill -f ryu-manager'."
    exit 1
fi
echo "Ports free."

echo "=== 5. Running Pytest Suite & Linter ==="
.venv/bin/python -m pytest -q
.venv/bin/ruff check .

echo "=== PRE-FLIGHT GATE: ALL CHECKS PASSED ==="
