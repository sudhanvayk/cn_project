# 5-Minute Technical Demonstration Script

This document provides an exact, step-by-step demonstration script for examiners, evaluators, and technical presentations. It proves all 7 expectations within 5 minutes using the unified `sdnscope` CLI.

---

## Prerequisites (0:00 - 0:30)

Open a terminal in the project root `cn_project`:

```bash
# Verify environment and dependencies
make lint
make test
```
*Key Talking Point:* "Our test suite includes 35 comprehensive pytest tests verifying RFC 3550 jitter statistics, packet validation, BFS graph path enumeration, flow-table path reconstruction, and failure localization with zero lint errors."

---

## Step 1: Discover SDN Topology & Enumerate Paths (0:30 - 1:15)

Start the mock SDN controller in a background terminal (or start Ryu in Mininet):

```bash
# Terminal 1: Start Mock SDN Controller
python3 mock_controller.py --port 8080 &
CONTROLLER_PID=$!
```

In your main terminal, query the controller's northbound REST API and calculate loop-free paths:

```bash
# 1. Discover switches, links, and hosts
python3 sdnscope.py topo -c ryu -i 127.0.0.1 -p 8080 -o topology.json

# 2. Enumerate and rank all topological paths between h1 and h2
python3 sdnscope.py paths -s h1 -d h2 -f topology.json
```
*Expected Output:* Two paths discovered:
- `Rank 1 [SELECTED_SHORTEST]: h1 -> s1 -> s2 -> h2` (3 hops)
- `Rank 2 [ALTERNATIVE]:       h1 -> s1 -> s3 -> s2 -> h2` (4 hops, +1 extra hop)

---

## Step 2: Active UDP Probing & Baseline Health (1:15 - 2:00)

Start the UDP diagnostic echo server on port 9999 and transmit active UDP probes:

```bash
# Terminal 2: Start probe server
python3 sdnscope.py serve -p 9999 -b 127.0.0.1 &
SERVER_PID=$!

# Transmit 10 active UDP probes with microsecond timestamps
python3 sdnscope.py probe 127.0.0.1 -p 9999 -c 10 --interval 0.05 -n h2 -o diag_healthy.json

# Correlate baseline telemetry with SDN topology
python3 sdnscope.py correlate -d diag_healthy.json -t topology.json -s h1 -e h2 --controller http://127.0.0.1:8080
```
*Expected Output:*
- Measures: Min/Max/Mean RTT, Median, p95 Latency, Standard Deviation Jitter, and **RFC 3550 Inter-Arrival Jitter**.
- Correlates with OpenFlow flow table: `Path Source: FLOW_TABLE` (`h1 -> s1 -> s2 -> h2`).
- Health Status: `[HEALTHY_PATH]` (0.00% packet loss, nominal delay).

---

## Step 3: IP Layer Tracing & L2 OpenFlow Transparency (2:00 - 2:30)

Run IP path tracing to demonstrate the OpenFlow Layer 2 transparency phenomenon:

```bash
python3 sdnscope.py trace 127.0.0.1
```
*Key Talking Point:* "Standard traceroute shows 1 hop because Layer 2 OpenFlow switches do not decrement the IPv4 TTL. This demonstrates why our control plane `flow_inspector` is required to authoritatively determine the true switch-by-switch path."

---

## Step 4: Link Degradation & Congestion Isolation (2:30 - 3:30)

Simulate queue congestion on the primary link with 60ms delay and 10% packet drop:

```bash
# Stop previous server and start degraded server on port 9998
kill $SERVER_PID
python3 sdnscope.py serve -p 9998 -b 127.0.0.1 --delay-ms 60 --drop-rate 0.10 &
SERVER_PID=$!

# Transmit diagnostic probes under congestion
python3 sdnscope.py probe 127.0.0.1 -p 9998 -c 15 --interval 0.05 -n h2 -o diag_degraded.json

# Run correlation and failure localization
python3 sdnscope.py correlate -d diag_degraded.json -t topology.json -s h1 -e h2 --controller http://127.0.0.1:8080 -o report_degraded.json
```
*Expected Output:*
- Path Status: `DEGRADED_PATH` (Mean RTT ~62ms exceeds 50ms threshold, packet loss ~6.7%).
- Localized Suspect: Core link `s1 <---> s2` flagged.
- Re-ranked Backups: Identifies `h1 -> s1 -> s3 -> s2 -> h2` as viable failover candidate.

---

## Step 5: Complete Link Severance & Automated OpenFlow Failover (3:30 - 4:30)

Simulate hard physical link severance (`s1 <---> s2` severed, 100% loss) and execute live OpenFlow rerouting:

```bash
# 1. Switch mock controller to 'failed' scenario (s1-s2 link down)
curl -s http://127.0.0.1:8080/mock/set_scenario/failed

# 2. Transmit probes across broken link (100% loss)
kill $SERVER_PID
python3 sdnscope.py serve -p 9997 -b 127.0.0.1 --drop-rate 1.0 &
SERVER_PID=$!
python3 sdnscope.py probe 127.0.0.1 -p 9997 -c 5 --timeout 0.4 -n h2 -o diag_failed.json || true

# 3. Discover current topology with link down
python3 sdnscope.py topo -c ryu -i 127.0.0.1 -p 8080 -o topology_failed.json

# 4. Correlate with topology liveness evidence
python3 sdnscope.py correlate \
    -d diag_failed.json \
    -t topology.json \
    -s h1 \
    -e h2 \
    --current-topo topology_failed.json \
    --controller http://127.0.0.1:8080 \
    -o report_failed.json

# 5. Automatically install OpenFlow backup flow rules along h1->s1->s3->s2->h2
python3 sdnscope.py reroute \
    -r report_failed.json \
    -t topology.json \
    -c http://127.0.0.1:8080 \
    --apply
```
*Expected Output:*
- Failure Localization: `s1 <---> s2` flagged with **100.0% confidence** (Evidence C: Topology Liveness - link disappeared).
- Prunes corrupt primary path (`EXCLUDED_CORRUPT_LINK`).
- Reroute assistant automatically dispatches OpenFlow flow modifications (`OUTPUT:3` on switch 1) via `/stats/flowentry/add`.

---

## Step 6: Executive Reporting (4:30 - 5:00)

Generate formatted Markdown and HTML executive reports and telemetry charts:

```bash
python3 sdnscope.py report \
    -r report_failed.json \
    -d diag_degraded.json \
    -m report.md \
    -H report.html \
    --dir results/demo
```

Clean up background processes:
```bash
kill $SERVER_PID $CONTROLLER_PID 2>/dev/null || true
```

*Final Summary:* "In 5 minutes, we demonstrated end-to-end UDP probing, latency/jitter statistics, OpenFlow flow table route reconstruction, multi-source failure localization, and automated backup path failover."
