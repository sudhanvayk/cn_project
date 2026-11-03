# Socket-Based Network Diagnostic and Path Analysis Tool for SDN (SDNScope)

**Topic 13:** Network Diagnostic and Path Analysis Tool  
**Problem Statement:** Develop a socket-based network diagnostic application that measures delay, packet loss, and path characteristics and correlates the results with the SDN network topology.  
**Protocol:** UDP  

## Evaluator Quick Start

On Ubuntu/Debian, install the venv module first:

```bash
sudo apt install python3-venv
```

```bash
git clone https://github.com/sudhanvayk/cn_project.git
cd cn_project
make install   # builds .venv, installs runtime + dev dependencies
make lint      # → All checks passed!
make test      # → 71 passed, 64% coverage
make demo      # → [SUCCESS] Full local demonstration completed successfully!
```

`make demo` runs the full 9-step localhost demonstration (no Mininet required, ~30s) and writes artifacts to `results/demo_localhost/`: `topology.json`, `paths.json`, `diagnostic_result.json`, `trace.json`, `correlation_report.json`, `report.md`, `report.html`, `rtt_timeseries.png`.

---

## 1. Executive Overview

In Software-Defined Networks (SDN), control logic is decoupled from data-plane forwarding hardware. Centralized controllers maintain global switch connection states and installed flow tables; however, localized link degradation, buffer queue congestion, and silent packet drops frequently compromise Quality of Service (QoS) long before control-plane timeouts trigger reactive failover.

Traditional diagnostic utilities (`ping`, `traceroute`) are fundamentally blind to OpenFlow forwarding tables and cannot correlate application telemetry with underlying SDN topologies. **SDNScope** bridges this gap: it combines high-precision active UDP socket probing with northbound SDN controller REST telemetry (Ryu and OpenDaylight) to measure delay, detect packet loss, authoritatively reconstruct active OpenFlow forwarding paths, localize in-network failures across multi-hop topologies, and deploy automated OpenFlow backup rerouting.

---

## 2. Requirement Traceability Matrix

The table below maps each of the **7 core problem expectations** directly to implementing source modules, primary classes, and public functions:

| # | Topic 13 Expectation | Implementing Modules | Key Classes & Functions | Description |
|---|---|---|---|---|
| **1** | **UDP diagnostic probes** | [`probe_server.py`](probe_server.py)<br>[`diagnostic_client.py`](diagnostic_client.py) | `ProbeUDPHandler.handle`<br>`run_diagnostics_single`<br>`run_diagnostics_multi` | Versioned UDP wire protocol (`SDN_PROBE v1.0`), microsecond send/recv timestamps, sequence tracking, multi-client concurrency, burst mode, and artificial drop/delay testing. |
| **2** | **Measure round-trip time** | [`diagnostic_client.py`](diagnostic_client.py) | `compute_probe_statistics`<br>`calculate_percentile` | High-precision RTT computation reporting minimum, maximum, mean, median, standard deviation jitter, **RFC 3550 inter-arrival jitter**, and **95th percentile (p95)** latency. |
| **3** | **Detect packet loss** | [`diagnostic_client.py`](diagnostic_client.py)<br>[`probe_server.py`](probe_server.py) | `compute_probe_statistics`<br>`ProbeUDPHandler.handle` | Detects lost probes via socket timeouts, calculates exact packet loss percentages, flags duplicate replies, and identifies out-of-order packet delivery. |
| **4** | **Implement path analysis** | [`path_analysis.py`](path_analysis.py) | `run_raw_udp_traceroute`<br>`run_path_analysis`<br>`parse_tracepath_output` | Dual-mode IP-layer hop tracing (UDP/ICMP raw sockets with system `tracepath`/`traceroute` fallback) reporting per-hop RTT/loss, with clear documentation of SDN Layer 2 TTL transparency. |
| **5** | **Discover SDN topology** | [`sdn_topology.py`](sdn_topology.py)<br>[`topology_graph.py`](topology_graph.py) | `discover_topology`<br>`watch_topology`<br>`SDNTopologyGraph.load_from_dict` | Discovers switches, links, and hosts from Ryu (`/v1.0/topology/*`) and OpenDaylight RESTCONF; converts into standardized graph model; monitors dynamic link state changes (`--watch`). |
| **6** | **Correlate measurements with paths** | [`flow_inspector.py`](flow_inspector.py)<br>[`correlate.py`](correlate.py) | `FlowInspector.reconstruct_active_path`<br>`correlate` | Reconstructs the **actual forwarding path** by querying installed OpenFlow flow rules (`/stats/flow/<dpid>`) and egress ports; distinguishes `flow_table` vs `assumed_shortest` sources. |
| **7** | **Identify failed paths** | [`correlate.py`](correlate.py)<br>[`reroute_helper.py`](reroute_helper.py) | `analyze_port_stats_deltas`<br>`analyze_topology_liveness`<br>`filter_and_rank_backups`<br>`apply_reroute` | Classifies health (`HEALTHY`, `DEGRADED`, `FAILED`); localizes suspect links via port drop counters, segment probes, and topology liveness diffs; prunes bad links to rank viable backups and installs flow overrides. |

---

## 3. Port & Address Map (Single Source of Truth)

All modules, scripts, and documentation strictly adhere to this port and address assignment:

### Control Plane & Services
| Component / Service | Protocol | Host / Interface | Port | Purpose / Endpoint |
|---|---|---|---|---|
| **Ryu REST API** | HTTP (JSON) | `127.0.0.1` | **TCP 8080** | Northbound REST (`/v1.0/topology/*`, `/stats/*`) |
| **OpenFlow Controller** | OpenFlow 1.3 | `127.0.0.1` | **TCP 6653** | Ryu default OpenFlow listen port for OVS switches |
| **OpenDaylight RESTCONF** | HTTP / RESTCONF | `127.0.0.1` | **TCP 8181** | Supported schema format (`/restconf/operational/...`) |
| **UDP Diagnostic Probe Service** | UDP | `0.0.0.0` / `10.0.0.2` | **UDP 9999** | Server socket handled by `probe_server.py` on `h2` |

### Data Plane (Mininet Diamond Topology)
| Node | Type | DPID / IP / MAC | Connected Port Wiring | TCLink Parameters |
|---|---|---|---|---|
| **h1** | Host | `10.0.0.1/24` (MAC: `00:00:00:00:00:01`) | `h1-eth0` <-> `s1-eth1` | 100 Mbit/s, 1 ms delay |
| **h2** | Host | `10.0.0.2/24` (MAC: `00:00:00:00:00:02`) | `h2-eth0` <-> `s2-eth1` | 100 Mbit/s, 1 ms delay |
| **s1** | Switch | DPID: `1` (`0000000000000001`) | Port 1: `h1`, Port 2: `s2`, Port 3: `s3` | Inter-switch: 10 Mbit/s, 2 ms |
| **s2** | Switch | DPID: `2` (`0000000000000002`) | Port 1: `h2`, Port 2: `s1`, Port 3: `s3` | Inter-switch: 10 Mbit/s, 2 ms |
| **s3** | Switch | DPID: `3` (`0000000000000003`) | Port 1: `s1`, Port 2: `s2` | Inter-switch: 10 Mbit/s, 2 ms |

---

## 4. System Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                 APPLICATION LAYER                                 |
|                                                                                   |
|    +--------------------+    +--------------------+    +---------------------+    |
|    | diagnostic_client  |    |  flow_inspector    |    |     correlate       |    |
|    | (Active Probes)    |    |  (OF Flow Table)   |    | (Multi-Source Loc.) |    |
|    +---------+----------+    +---------+----------+    +----------+----------+    |
|              |                         |                          |               |
|              +-------------------------+--------------------------+               |
|                                        |                                          |
|                                        v                                          |
|                     UNIFIED CLI CONTROLLER: sdnscope.py                           |
|    +-------------------------------------------------------------------------+    |
+----------------------------------------+------------------------------------------+
                                         |
        +--------------------------------+-------------------------------+
        |                                                                |
        v                                                                v
+-------------------------------+              +------------------------------------+
|       DATA PLANE (UDP)        |              |        CONTROL PLANE (REST)        |
|                               |              |                                    |
|  [Source Host (h1)]           |              |  [SDN Controller: Ryu / ODL]       |
|    |                          |              |    |                               |
|    | Active UDP Probes        |              |    | Northbound REST APIs:         |
|    v                          |              |    |   /v1.0/topology/switches     |
|  [OpenFlow Switch s1]         |              |    |   /v1.0/topology/links        |
|    |                          |              |    |   /stats/flow/<dpid>          |
|    v                          |              |    |   /stats/port/<dpid>          |
|  [OpenFlow Switch s2/s3]      |              |    |   /stats/flowentry/add        |
|    |                          |              |    v                               |
|    v                          |              |  [sdn_topology.py Discovery]       |
|  [Destination Host (h2)]      |              +------------------------------------+
|    | [probe_server.py Echo]   |
+-------------------------------+
```

---

## 5. Unified Command-Line Interface (`sdnscope.py`)

All system functionality is accessible via the modular `sdnscope.py` CLI:

```bash
# Display help and available subcommands
.venv/bin/python sdnscope.py --help
```

### Available Subcommands

| Subcommand | Purpose | Key Arguments |
|---|---|---|
| `probe` | Run active UDP diagnostic probe client | `target_ip -p 9999 -c 50 --interval 0.05 --burst -o diag.json` |
| `serve` | Start multi-threaded UDP probe server | `-p 9999 -b 0.0.0.0 --drop-rate 0.10 --delay-ms 30` |
| `trace` | Execute hop-by-hop IP layer path trace | `target_ip -m 5 --timeout 1.0 -o trace.json` |
| `topo` | Discover switches, links, and hosts via REST | `-c ryu -i 127.0.0.1 -p 8080 --hosts-file hosts.json -o topo.json` |
| `paths` | Find and rank all loop-free simple paths (BFS) | `-s h1 -d h2 -f topo.json -o paths.json` |
| `correlate` | Correlate telemetry, localize faults, rank backups | `-d diag.json -t topo.json -s h1 -e h2 --controller <url>` |
| `watch` | Monitor live SDN topology changes in real time | `-c ryu -i 127.0.0.1 -p 8080 --interval 1` |
| `localize` | Run dedicated 3-tier failure localization | `-t topo.json --baseline-stats b.json --current-stats c.json` |
| `reroute` | Install OpenFlow backup flow modifications | `-r report.json -t topo.json -c <url> [--apply]` |
| `report` | Generate Markdown, HTML, and chart reports | `-r report.json -d diag.json -m report.md -H report.html` |

---

## 6. Real Scenario Walkthrough & Verified Results

The entire 4-scenario suite runs end-to-end on a live Mininet 2.3.0 + Ryu 4.34 testbed using [`scripts/run_all_scenarios.sh`](scripts/run_all_scenarios.sh). All artifacts are persisted in `results/real_<timestamp>/` (symlinked to `results/latest/`).

### Comparative Scenario Performance Summary
| Metric | Healthy Baseline | Degraded Path | Failed Link | Failover Recovery |
|---|---|---|---|---|
| **Scenario Name** | `healthy` | `degraded` | `failed` | `recovery` |
| **Active Forwarding Route** | `h1 -> s1 -> s2 -> h2` | `h1 -> s1 -> s2 -> h2` | `h1 -> s1 -> s2 -> h2` | `h1 -> s1 -> s3 -> s2 -> h2` |
| **Hop Count** | 3 | 3 | 3 | 4 (+1 hop) |
| **Path Source** | `FLOW_TABLE` | `FLOW_TABLE` | `FLOW_TABLE` | `FLOW_TABLE` |
| **Physical Impairment** | None (nominal) | `netem` 30ms delay, 5% loss on s1-eth2/s2-eth2 | `link s1 s2 down` (physical severed) | `link s1 s2 down` + backup flows |
| **Probes Sent / Received** | 50 / 50 | 100 / 90 | 20 / 0 | 50 / 50 |
| **Packet Loss Rate** | **0.00%** | **10.00%** | **100.00%** | **0.00%** |
| **Mean RTT** | **13.24 ms** | **73.32 ms** | **N/A** | **19.94 ms** |
| **Median RTT** | 11.81 ms | 69.57 ms | N/A | 18.89 ms |
| **Min / Max RTT** | 9.89 ms / 32.42 ms | 65.92 ms / 243.85 ms | N/A | 14.74 ms / 32.34 ms |
| **95th Percentile RTT (p95)** | 19.59 ms | 87.34 ms | N/A | 28.28 ms |
| **StdDev RTT** | 3.94 ms | 19.18 ms | N/A | 3.98 ms |
| **RFC 3550 Inter-Arrival Jitter**| 3.85 ms | 10.96 ms | N/A | 3.75 ms |
| **Path Health Verdict** | `HEALTHY_PATH` | `DEGRADED_PATH` | `FAILED_PATH` | `HEALTHY_PATH` |
| **Failure Diagnosis** | Nominal baseline | Packet loss (10.0%) & high RTT (73.32ms) | Severe packet loss (100.0%) | Nominal operation on backup route |
| **Suspected Broken Link** | None | `s1 <---> s2` (60.0% confidence) | `s1 <---> s2` (100.0% confidence) | None |
| **Recommended Backup Route** | `h1 -> s1 -> s3 -> s2 -> h2` | `h1 -> s1 -> s3 -> s2 -> h2` | `h1 -> s1 -> s3 -> s2 -> h2` | N/A (Already active) |

*(Complete raw outputs and execution logs are compiled in [`docs/EVIDENCE.md`](docs/EVIDENCE.md)).*

---

## 7. Automated Testing & Quality Gates

```bash
# Run pytest test suite (69 tests with coverage report)
make test

# Run ruff static code analysis
make lint

# Execute pre-flight environment check
make real-check

# Execute end-to-end Mininet+Ryu scenario suite
make real-scenarios
```

---

## 8. Technical Limitations & Engineering Tradeoffs

1. **OpenFlow Layer 2 TTL Transparency:**
   In OpenFlow fabrics without explicit `dec_ttl` actions, Layer 2 bridges forward Ethernet frames without modifying the IPv4 TTL. Standard `traceroute` is transparent to OpenFlow switches and reports only 1 hop. Our framework solves this by making OpenFlow flow-table inspection ([`flow_inspector.py`](flow_inspector.py)) the authoritative source for path discovery.
2. **One-Way Delay Clock Synchronization:**
   One-way forward ($T_{recv} - T_{send}$) and reverse delay estimates are subject to clock skew between endpoints unless hardware time synchronization (such as IEEE 1588 PTP or sub-millisecond NTP) is present. **Round-Trip Time (RTT)** relies strictly on client-side timestamps and remains mathematically immune to clock skew.
3. **Control-Plane Polling Intervals:**
   OpenFlow port statistics deltas and LLDP topology discovery operate at discrete polling intervals. Very short micro-outages ($< 500\text{ ms}$) may resolve before the controller updates its link inventory, requiring active segment probing for instantaneous detection.

---

## 9. Project Documentation Index

- [`SETUP.md`](SETUP.md): Mininet, isolated Ryu virtualenv, and system setup guide.
- [`docs/DESIGN.md`](docs/DESIGN.md): Architectural decisions, protocol formats, and mathematical formulas.
- [`docs/EVIDENCE.md`](docs/EVIDENCE.md): Full transcripts, comparative tables, and live verification logs.
- [`docs/DEMO.md`](docs/DEMO.md): 5-minute step-by-step oral presentation demonstration script.
- [`docs/VIVA.md`](docs/VIVA.md): 20 likely examiner questions with comprehensive technical answers.
- [`docs/schemas.md`](docs/schemas.md): JSON schemas for all telemetry packets, topology, and reports.
- [`CHANGELOG.md`](CHANGELOG.md): Record of changes and version releases.

## Submission

Acceptance criteria, expected outputs, and official evidence: [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md)
