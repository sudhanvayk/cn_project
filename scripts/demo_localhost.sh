#!/usr/bin/env bash
# Standalone Localhost Demonstration Script
# Demonstrates full SDN diagnostic workflow using sdnscope CLI on localhost
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "======================================================================"
echo "          SDNSCOPE FULL LOCALHOST DEMONSTRATION (NO MININET)          "
echo "======================================================================"

PYTHON_BIN="python3"
if [ -f "$ROOT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python3"
fi

DEMO_DIR="results/demo_localhost"
mkdir -p "$DEMO_DIR"

PROBE_PORT=19990
MOCK_PORT=18080

# 1. Start Mock SDN Controller
echo -e "\n[STEP 1] Starting Mock Ryu SDN Controller on port $MOCK_PORT..."
$PYTHON_BIN mock_controller.py --port $MOCK_PORT > "$DEMO_DIR/mock_controller.log" 2>&1 &
MOCK_PID=$!

# 2. Start UDP Diagnostic Probe Server
echo "[STEP 2] Starting UDP Probe Server on port $PROBE_PORT..."
$PYTHON_BIN sdnscope.py serve -p $PROBE_PORT -b 127.0.0.1 > "$DEMO_DIR/probe_server.log" 2>&1 &
SERVER_PID=$!
sleep 0.5

cleanup() {
    echo -e "\n[CLEANUP] Stopping background services..."
    kill $SERVER_PID 2>/dev/null || true
    kill $MOCK_PID 2>/dev/null || true
}
trap cleanup EXIT

# 3. Discover SDN Topology
echo -e "\n[STEP 3] Discovering SDN Controller Topology via Northbound REST..."
$PYTHON_BIN sdnscope.py topo -c ryu -i 127.0.0.1 -p $MOCK_PORT -o "$DEMO_DIR/topology.json"

# 4. Enumerate Topological Paths
echo -e "\n[STEP 4] Finding and Ranking All Simple Loop-Free Paths between h1 and h2..."
$PYTHON_BIN sdnscope.py paths -f "$DEMO_DIR/topology.json" -s h1 -d h2 -o "$DEMO_DIR/paths.json"

# 5. Execute UDP Active Telemetry Probing
echo -e "\n[STEP 5] Transmitting Active UDP Probes (Measuring RTT, Loss, RFC 3550 Jitter)..."
$PYTHON_BIN sdnscope.py probe 127.0.0.1 -p $PROBE_PORT -c 10 --interval 0.05 -o "$DEMO_DIR/diagnostic_result.json"

# 6. Perform IP-Layer Path Tracing
echo -e "\n[STEP 6] Inspecting IP Hop Path (with SDN L2 Transparency Notice)..."
$PYTHON_BIN sdnscope.py trace 127.0.0.1 -o "$DEMO_DIR/trace.json"

# 7. Correlate Telemetry with SDN Topology & Localize Failures
echo -e "\n[STEP 7] Correlating Socket Telemetry with SDN Topology & Diagnosing Path..."
$PYTHON_BIN sdnscope.py correlate \
    -d "$DEMO_DIR/diagnostic_result.json" \
    -t "$DEMO_DIR/topology.json" \
    -s h1 \
    -e h2 \
    --controller "http://127.0.0.1:$MOCK_PORT" \
    -o "$DEMO_DIR/correlation_report.json"

# 8. Test Failure Scenario Rerouting
echo -e "\n[STEP 8] Demonstrating Automated Backup Route Deployment via OpenFlow Modifications..."
$PYTHON_BIN sdnscope.py reroute \
    -r "$DEMO_DIR/correlation_report.json" \
    -t "$DEMO_DIR/topology.json" \
    -c "http://127.0.0.1:$MOCK_PORT" \
    --apply

# 9. Generate Complete Visual Reports
echo -e "\n[STEP 9] Generating Markdown and HTML Executive Reports..."
$PYTHON_BIN sdnscope.py report \
    -r "$DEMO_DIR/correlation_report.json" \
    -d "$DEMO_DIR/diagnostic_result.json" \
    -m "$DEMO_DIR/report.md" \
    -H "$DEMO_DIR/report.html" \
    --dir "$DEMO_DIR"

echo -e "\n======================================================================"
echo " [SUCCESS] Full local demonstration completed successfully!"
echo " Artifacts saved in: $DEMO_DIR"
echo "======================================================================"
