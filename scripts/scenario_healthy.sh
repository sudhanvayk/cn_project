#!/usr/bin/env bash
# Scenario A: Healthy Path Demonstration
# Baseline operation with nominal delay and 0% packet loss
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if [ -f "$ROOT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python3"
fi

OUT_DIR="${1:-results/scenario_healthy}"
mkdir -p "$OUT_DIR"

echo "======================================================================"
echo "          SCENARIO A: HEALTHY PATH DEMONSTRATION                      "
echo "======================================================================"

PORT=19901
echo "[1/4] Starting UDP probe server on port $PORT..."
$PYTHON_BIN probe_server.py --port $PORT --bind 127.0.0.1 > "$OUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
sleep 0.5

cleanup() {
    kill $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

echo "[2/4] Transmitting 10 UDP diagnostic probes..."
$PYTHON_BIN diagnostic_client.py 127.0.0.1 -p $PORT -c 10 --interval 0.05 -o "$OUT_DIR/diagnostic_result.json"

echo "[3/4] Ensuring baseline topology..."
$PYTHON_BIN -c "
import json
with open('topology.json') as f:
    topo = json.load(f)
with open('$OUT_DIR/topology.json', 'w') as f:
    json.dump(topo, f, indent=2)
"

echo "[4/4] Correlating measurements with SDN topology..."
$PYTHON_BIN correlate.py \
    -d "$OUT_DIR/diagnostic_result.json" \
    -t "$OUT_DIR/topology.json" \
    -s h1 \
    -e h2 \
    -o "$OUT_DIR/correlation_report.json"

echo "[SUCCESS] Scenario A complete. Outputs saved in $OUT_DIR"
