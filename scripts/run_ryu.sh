#!/usr/bin/env bash
# Start Ryu Controller with REST topology discovery, Ofctl REST API, and L2 switching
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "======================================================================"
echo "          Starting Ryu SDN Controller for Diagnostics Suite           "
echo "======================================================================"
echo " Controller Apps: rest_topology, ofctl_rest, simple_switch_13"
echo " REST Port:       8080"
echo " OpenFlow Port:   6633 / 6653"
echo " Flags:           --observe-links"
echo "----------------------------------------------------------------------"

# Locate ryu-manager in system PATH or local virtualenvs
RYU_BIN=""
if command -v ryu-manager &> /dev/null; then
    RYU_BIN="ryu-manager"
elif [ -f "$ROOT_DIR/.venv/bin/ryu-manager" ]; then
    RYU_BIN="$ROOT_DIR/.venv/bin/ryu-manager"
elif [ -f "$ROOT_DIR/venv/bin/ryu-manager" ]; then
    RYU_BIN="$ROOT_DIR/venv/bin/ryu-manager"
else
    echo "[ERROR] ryu-manager not found in PATH or virtual environments."
    echo "[HINT] Install Ryu using: pip install ryu"
    echo "       Or use the offline mock controller: python3 mock_controller.py --port 8080"
    exit 1
fi

exec "$RYU_BIN" ryu.app.rest_topology ryu.app.ofctl_rest ryu.app.simple_switch_13 --observe-links "$@"
