#!/usr/bin/env bash
# Scenario C: Failed Path & Reroute Demonstration
# Simulates complete link failure (100% loss) and triggers backup path rerouting
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

OUT_DIR="${1:-results/scenario_failed}"
mkdir -p "$OUT_DIR"

echo "======================================================================"
echo "          SCENARIO C: FAILED PATH & FAILOVER DEMONSTRATION            "
echo "======================================================================"

PORT=19903
MOCK_PORT=18093

echo "[1/5] Starting mock SDN controller in 'failed' scenario..."
python3 mock_controller.py --port $MOCK_PORT --scenario failed > "$OUT_DIR/controller.log" 2>&1 &
MOCK_PID=$!

echo "[2/5] Starting probe server with 100% drop rate (simulating severed link)..."
python3 probe_server.py --port $PORT --bind 127.0.0.1 --drop-rate 1.0 > "$OUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
sleep 0.5

cleanup() {
    kill $SERVER_PID 2>/dev/null || true
    kill $MOCK_PID 2>/dev/null || true
}
trap cleanup EXIT

echo "[3/5] Transmitting 5 UDP diagnostic probes across broken primary link..."
python3 diagnostic_client.py 127.0.0.1 -p $PORT -c 5 --timeout 0.5 -o "$OUT_DIR/diagnostic_result.json" || true

echo "[4/5] Discovering controller topology with link down..."
python3 sdn_topology.py --controller ryu --ip 127.0.0.1 --port $MOCK_PORT -o "$OUT_DIR/topology.json"

echo "[5/5] Running correlation, failure localization, and backup path ranking..."
python3 correlate.py \
    -d "$OUT_DIR/diagnostic_result.json" \
    -t "$OUT_DIR/topology.json" \
    -s h1 \
    -e h2 \
    --controller "http://127.0.0.1:$MOCK_PORT" \
    -o "$OUT_DIR/correlation_report.json"

echo "[OPTIONAL REROUTE] Demonstrating automated OpenFlow backup path deployment:"
python3 reroute_helper.py \
    -r "$OUT_DIR/correlation_report.json" \
    -t "$OUT_DIR/topology.json" \
    -c "http://127.0.0.1:$MOCK_PORT" \
    --apply

echo "[SUCCESS] Scenario C complete. Outputs saved in $OUT_DIR"
