#!/usr/bin/env bash
# Run all real SDN diagnostic scenarios in fresh Mininet + Ryu sessions.
# Output is saved to results/real_<YYYYmmdd_HHMMSS>/{healthy,degraded,failed,recovery}/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
RUN_NAME="real_$TIMESTAMP"
RUN_DIR="$ROOT_DIR/results/$RUN_NAME"
mkdir -p "$RUN_DIR"

echo "======================================================================"
echo "      REAL MININET + RYU SDN DIAGNOSTIC AND PATH ANALYSIS RUN         "
echo "======================================================================"
echo " Run Directory: $RUN_DIR"
echo " Started At:    $(date)"
echo "----------------------------------------------------------------------"

# Ensure sudo credentials are available (prompt once if needed)
if ! sudo -n true 2>/dev/null; then
    echo "[INFO] Requesting sudo credentials for Mininet scenarios..."
    sudo -v || { echo "[ERROR] Sudo authentication failed"; exit 1; }
fi

# Record environment metadata to env.txt
ENV_TXT="$RUN_DIR/env.txt"
{
    echo "=== Environment Metadata ==="
    echo "Date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Hostname: $(hostname)"
    echo "Kernel: $(uname -a)"
    echo "Git Branch: $(git branch --show-current 2>/dev/null || echo 'unknown')"
    echo "Git Commit: $(git rev-parse HEAD 2>/dev/null || echo 'unknown')"
    echo "System Python: $(python3 --version 2>&1)"
    echo "Venv Python: $(.venv/bin/python --version 2>&1 || echo 'none')"
    echo "Ryu Version: $($HOME/ryu-env/bin/ryu-manager --version 2>&1 || echo 'none')"
    echo "Mininet Version: $(mn --version 2>&1 || echo 'none')"
    echo "OVS Version: $(ovs-vsctl --version 2>&1 | head -n 1)"
} > "$ENV_TXT"

cleanup_session() {
    sudo mn -c >/dev/null 2>&1 || true
    "$SCRIPT_DIR/run_ryu.sh" stop >/dev/null 2>&1 || true
    pkill -9 -f "probe_server.py" 2>/dev/null || true
    sleep 1
}

run_scenario() {
    local scenario="$1"
    local sc_dir="$RUN_DIR/$scenario"
    mkdir -p "$sc_dir"

    echo -e "\n======================================================================"
    echo ">>> EXECUTING REAL SCENARIO: $(echo "$scenario" | tr '[:lower:]' '[:upper:]') <<<"
    echo "======================================================================"

    cleanup_session

    local ryu_log="$sc_dir/ryu.log"
    "$SCRIPT_DIR/run_ryu.sh" start "$ryu_log"

    echo "[INFO] Running Mininet scenario orchestrator for: $scenario"
    sudo python3 "$ROOT_DIR/topology/scenario_runner.py" "$scenario" -o "$sc_dir"

    cleanup_session
    echo "[INFO] Scenario $scenario finished."
}

# Run all 4 scenario phases
SCENARIOS=("healthy" "degraded" "failed" "recovery")
for sc in "${SCENARIOS[@]}"; do
    run_scenario "$sc"
done

# Fix ownership so the invoking (non-root) user owns all results
OWNER="${SUDO_USER:-$(id -un)}"
OWNER_GROUP="$(id -gn "$OWNER" 2>/dev/null || id -gn)"
sudo chown -R "$OWNER:$OWNER_GROUP" "$RUN_DIR" "$ROOT_DIR" 2>/dev/null || true

# Check that core artifacts exist for all scenarios
GATES_PASSED=1
for sc in "${SCENARIOS[@]}"; do
    if [ ! -f "$RUN_DIR/$sc/diagnostic_result.json" ] || [ ! -f "$RUN_DIR/$sc/correlation_report.json" ]; then
        echo "[ERROR] Missing critical results in $RUN_DIR/$sc"
        GATES_PASSED=0
    fi
done

if [ "$GATES_PASSED" -eq 1 ]; then
    rm -f results/latest
    ln -sf "$RUN_NAME" results/latest
    echo -e "\n======================================================================"
    echo " [SUCCESS] All scenarios completed successfully!"
    echo " Real results linked to: results/latest -> $RUN_NAME"
    echo " Results folder: $RUN_DIR"
    echo "======================================================================"
else
    echo -e "\n[WARNING] Some scenario verification gates failed. results/latest was NOT updated."
    exit 1
fi
