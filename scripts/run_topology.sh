#!/usr/bin/env bash
# Launch Mininet with diamond topology
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "======================================================================"
echo "         Starting Mininet Diamond Topology (Requires Sudo/Root)       "
echo "======================================================================"

if ! command -v mn &> /dev/null; then
    echo "[ERROR] 'mn' (Mininet) executable was not found."
    echo "[HINT] Install Mininet: sudo apt update && sudo apt install -y mininet openvswitch-switch"
    echo "       Or run the standalone localhost demo: ./scripts/demo_localhost.sh"
    exit 1
fi

sudo python3 "$ROOT_DIR/topology/diamond_topo.py" "$@"
