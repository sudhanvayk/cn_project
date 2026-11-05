#!/usr/bin/env bash
# Pre-flight check gate for Real Mininet + Ryu SDN verification
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "=== 1. Checking Sudo Access ==="
if ! sudo -n true 2>/dev/null; then
    echo "[INFO] Passwordless sudo is not configured; requesting credentials once..."
    if ! sudo -v; then
        echo "[ERROR] sudo authentication failed. Mininet scenarios require root."
        exit 1
    fi
fi
echo "SUDO_OK"

echo "=== 2. Checking Mininet & Open vSwitch ==="
for tool in mn ovs-vsctl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[ERROR] $tool not found. Install Mininet/Open vSwitch:"
        echo "        sudo apt update && sudo apt install -y mininet openvswitch-switch"
        exit 1
    fi
    echo "found: $(command -v "$tool")"
done
sudo ovs-vsctl show | head -n 5

echo "=== 3. Checking Ryu Manager Environment ==="
RYU_BIN="${RYU_BIN:-}"
if [ -z "$RYU_BIN" ]; then
    if [ -x "$HOME/ryu-env/bin/ryu-manager" ]; then
        RYU_BIN="$HOME/ryu-env/bin/ryu-manager"
    elif command -v ryu-manager >/dev/null 2>&1; then
        RYU_BIN="$(command -v ryu-manager)"
    fi
fi
if [ -z "$RYU_BIN" ] || [ ! -x "$RYU_BIN" ]; then
    echo "[ERROR] ryu-manager not found. Set RYU_BIN or create ~/ryu-env."
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
if [ ! -x ".venv/bin/python" ]; then
    echo "[ERROR] .venv not found. Run 'make install' first."
    exit 1
fi
.venv/bin/python -m pytest -q
.venv/bin/ruff check .

echo "=== PRE-FLIGHT GATE: ALL CHECKS PASSED ==="
