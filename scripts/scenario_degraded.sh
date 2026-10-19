#!/usr/bin/env bash
# Scenario B: Degraded Path Demonstration
# Simulates link queue congestion with 60ms delay and 10% packet loss
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

OUT_DIR="${1:-results/scenario_degraded}"
mkdir -p "$OUT_DIR"

echo "======================================================================"
echo "          SCENARIO B: DEGRADED / CONGESTED PATH DEMONSTRATION         "
echo "======================================================================"

PORT=19902
echo "[1/4] Starting UDP probe server with injected delay (60ms) and loss (10%)..."
python3 probe_server.py --port $PORT --bind 127.0.0.1 --delay-ms 60 --drop-rate 0.10 > "$OUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
sleep 0.5

cleanup() {
    kill $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

echo "[2/4] Transmitting 15 UDP diagnostic probes under simulated congestion..."
python3 diagnostic_client.py 127.0.0.1 -p $PORT -c 15 --interval 0.05 -o "$OUT_DIR/diagnostic_result.json"

echo "[3/4] Copying topology baseline..."
cp topology.json "$OUT_DIR/topology.json"

echo "[4/4] Running correlation and failure diagnosis..."
python3 correlate.py \
    -d "$OUT_DIR/diagnostic_result.json" \
    -t "$OUT_DIR/topology.json" \
    -s h1 \
    -o "$OUT_DIR/correlation_report.json"

echo "[SUCCESS] Scenario B complete. Outputs saved in $OUT_DIR"
