#!/usr/bin/env bash
# Install static bidirectional flows for the primary path (h1-s1-s2-h2) via Ryu ofctl_rest.
# Primary flows use priority 100.
# OpenFlow 1.3 OXM match names: eth_type 2048 (IPv4), eth_type 2054 (ARP).
set -euo pipefail

RYU_URL="${RYU_URL:-http://127.0.0.1:8080}"
MODE="dry-run"

for arg in "$@"; do
    case "$arg" in
        --apply)
            MODE="apply"
            ;;
        --dry-run)
            MODE="dry-run"
            ;;
        http://*|https://*)
            RYU_URL="$arg"
            ;;
    esac
done

ADD_URL="$RYU_URL/stats/flowentry/add"
DEL_URL="$RYU_URL/stats/flowentry/delete_strict"

# Rules array: dpid, priority, match_json, actions_json
RULES=(
    # s1: dst 10.0.0.2 -> OUTPUT 2
    '{"dpid": 1, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]}'
    '{"dpid": 1, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]}'
    # s1: dst 10.0.0.1 -> OUTPUT 1
    '{"dpid": 1, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]}'
    '{"dpid": 1, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]}'
    # s2: dst 10.0.0.2 -> OUTPUT 1
    '{"dpid": 2, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 1}]}'
    '{"dpid": 2, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 1}]}'
    # s2: dst 10.0.0.1 -> OUTPUT 2
    '{"dpid": 2, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 2}]}'
    '{"dpid": 2, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 2}]}'
)

if [ "$MODE" = "dry-run" ]; then
    echo "[DRY-RUN] Primary path flow modifications (priority 100):"
    for rule in "${RULES[@]}"; do
        echo "$rule"
    done
    echo "[INFO] Run with --apply to push to $RYU_URL"
    exit 0
fi

echo "[APPLY] Installing primary flows on $RYU_URL..."
for rule in "${RULES[@]}"; do
    # Extract dpid, priority, match for delete_strict
    del_payload=$(python3 -c "import sys, json; r=json.loads(sys.argv[1]); print(json.dumps({'dpid': r['dpid'], 'priority': r['priority'], 'match': r['match']}))" "$rule")
    curl -s -X POST "$DEL_URL" -H "Content-Type: application/json" -d "$del_payload" >/dev/null 2>&1 || true
    curl -s -f -X POST "$ADD_URL" -H "Content-Type: application/json" -d "$rule" >/dev/null
done
echo "[SUCCESS] All primary path flows installed."
