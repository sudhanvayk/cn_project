#!/usr/bin/env bash
# Start Ryu Controller for SDNScope with REST topology discovery and Ofctl REST API
# (NO simple_switch_13: the diamond topology has loops; flood learning causes broadcast storm).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

RYU_BIN="${RYU_BIN:-}"
if [ -z "$RYU_BIN" ]; then
    if [ -x "$HOME/ryu-env/bin/ryu-manager" ]; then
        RYU_BIN="$HOME/ryu-env/bin/ryu-manager"
    elif [ -x "/home/sudh/ryu-env/bin/ryu-manager" ]; then
        RYU_BIN="/home/sudh/ryu-env/bin/ryu-manager"
    else
        RYU_BIN="/home/sudh/ryu-env/bin/ryu-manager"
    fi
fi
PID_FILE="${RYU_PID_FILE:-/tmp/ryu_sdnscope.pid}"
DEFAULT_LOG="${RYU_LOG_FILE:-/tmp/ryu_sdnscope.log}"
REST_URL="${RYU_REST_URL:-http://127.0.0.1:8080}"

if [ ! -x "$RYU_BIN" ]; then
    echo "[ERROR] ryu-manager not found at: $RYU_BIN" >&2
    exit 1
fi

stop_ryu() {
    echo "[INFO] Stopping Ryu controller..."
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            for _ in $(seq 1 10); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
                sleep 0.5
            done
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$PID_FILE"
    fi
    # Also ensure any lingering ryu-manager with our apps is stopped
    pkill -f "ryu.app.rest_topology" 2>/dev/null || true
    echo "[INFO] Ryu controller stopped."
}

start_ryu() {
    local log_file="${1:-$DEFAULT_LOG}"
    mkdir -p "$(dirname "$log_file")"
    mkdir -p "$(dirname "$PID_FILE")"

    # Stop any stale instance first
    stop_ryu

    # Ensure ports are free
    if ss -ltnp | grep -E ':(6653|8080)\b' >/dev/null 2>&1; then
        echo "[ERROR] Port 6653 or 8080 is already in use:" >&2
        ss -ltnp | grep -E ':(6653|8080)\b' >&2
        exit 1
    fi

    echo "[INFO] Starting Ryu (rest_topology, ofctl_rest) logging to: $log_file"
    "$RYU_BIN" --observe-links ryu.app.rest_topology ryu.app.ofctl_rest > "$log_file" 2>&1 &
    local ryu_pid=$!
    echo "$ryu_pid" > "$PID_FILE"

    # Wait for REST API to become ready
    echo -n "[INFO] Waiting for Ryu REST API to respond..."
    local ready=0
    for _ in $(seq 1 30); do
        if curl -s -m 1 "$REST_URL/v1.0/topology/switches" >/dev/null 2>&1; then
            ready=1
            echo " ready (PID: $ryu_pid)"
            break
        fi
        if ! kill -0 "$ryu_pid" 2>/dev/null; then
            echo " FAILED (process died)"
            cat "$log_file" >&2
            exit 1
        fi
        echo -n "."
        sleep 0.5
    done

    if [ "$ready" -ne 1 ]; then
        echo " TIMEOUT waiting for Ryu REST API" >&2
        stop_ryu
        exit 1
    fi
}

wait_for_switches() {
    local expected_count="${1:-3}"
    local timeout="${2:-60}"
    echo "[INFO] Waiting for $expected_count switches to connect to Ryu (timeout: ${timeout}s)..."
    local start_time
    start_time=$(date +%s)

    while true; do
        local current_time
        current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        if [ "$elapsed" -ge "$timeout" ]; then
            echo "[ERROR] Timeout waiting for $expected_count switches after ${timeout}s" >&2
            local actual_body
            actual_body=$(curl -s -m 2 "$REST_URL/v1.0/topology/switches" 2>/dev/null || echo "UNREACHABLE")
            echo "[DEBUG] Current /v1.0/topology/switches: $actual_body" >&2
            return 1
        fi

        local body
        body=$(curl -s -m 2 "$REST_URL/v1.0/topology/switches" 2>/dev/null || echo "[]")
        # Count DPIDs in json array: [{"dpid": "..."}, ...]
        local count
        count=$(python3 -c "import sys, json; data=json.loads(sys.argv[1]); print(len(data))" "$body" 2>/dev/null || echo "0")
        if [ "$count" -ge "$expected_count" ]; then
            echo "[INFO] All $count switches connected successfully (took ${elapsed}s)."
            return 0
        fi
        sleep 1
    done
}

case "${1:-start}" in
    start)
        start_ryu "${2:-$DEFAULT_LOG}"
        if [ "${3:-}" = "--wait" ] || [ "${2:-}" = "--wait" ]; then
            wait_for_switches 3 60
        fi
        ;;
    wait)
        wait_for_switches "${2:-3}" "${3:-60}"
        ;;
    stop)
        stop_ryu
        ;;
    status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "[INFO] Ryu is running (PID: $(cat "$PID_FILE"))."
            curl -s "$REST_URL/v1.0/topology/switches"
            echo ""
        else
            echo "[INFO] Ryu is not running."
        fi
        ;;
    *)
        echo "Usage: $0 {start [logfile] [--wait] | wait [count] [timeout] | stop | status}"
        exit 1
        ;;
esac
