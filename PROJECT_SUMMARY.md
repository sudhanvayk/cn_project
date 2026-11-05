# SDNScope — Project Summary Document

**Project:** SDN Network Diagnostic and Path Analysis Tool  
**Topic:** Topic 13 — Socket-Based Network Diagnostic and Path Analysis Tool for SDN  
**Protocol:** UDP  
**Version:** 1.1.1  
**Working Directory:** repository root  
**Python Version:** 3.8 – 3.12  
**OS:** Linux (Ubuntu 20.04/22.04/24.04 LTS, Debian 11/12 recommended)

---

## 1. What the Project Is

**SDNScope** is an active telemetry and diagnostic platform engineered specifically for **Software-Defined Networks (SDNs)**. It bridges the gap between conventional socket-level diagnostics (like `ping` / `traceroute`) and authoritative OpenFlow control-plane state, which traditional tools cannot see.

In SDN, control logic is decoupled from data-plane forwarding hardware. Centralized controllers maintain global switch connection states and installed flow tables; however, localized link degradation, buffer queue congestion, and silent packet drops frequently compromise Quality of Service (QoS) long before control-plane timeouts trigger reactive failover. SDNScope addresses this by combining high-precision active UDP socket probing with northbound SDN controller REST telemetry (Ryu and OpenDaylight).

---

## 2. What the Project Does (7 Core Capabilities)

| # | Capability | Modules | Description |
|---|-----------|---------|-------------|
| 1 | **UDP diagnostic probes** | `probe_server.py`, `diagnostic_client.py` | Versioned UDP wire protocol (`SDN_PROBE v1.0`), microsecond send/recv timestamps, sequence tracking, multi-client concurrency, burst mode, artificial drop/delay testing. |
| 2 | **Measure round-trip time (RTT)** | `diagnostic_client.py` | High-precision RTT computation: min, max, mean, median, stddev jitter, RFC 3550 inter-arrival jitter, and 95th percentile (p95) latency. |
| 3 | **Detect packet loss** | `diagnostic_client.py`, `probe_server.py` | Detects lost probes via socket timeouts, calculates exact packet loss %, flags duplicate replies, identifies out-of-order delivery. |
| 4 | **Path analysis / tracing** | `path_analysis.py` | Dual-mode IP-layer hop tracing (UDP/ICMP raw sockets with `tracepath`/`traceroute` fallback), per-hop RTT/loss reporting. |
| 5 | **SDN topology discovery** | `sdn_topology.py`, `topology_graph.py` | Discovers switches, links, and hosts from Ryu (`/v1.0/topology/*`) and OpenDaylight RESTCONF; monitors dynamic link state changes (`--watch`). |
| 6 | **Correlate measurements with actual paths** | `flow_inspector.py`, `correlate.py` | Reconstructs the **actual forwarding path** by querying installed OpenFlow flow rules (`/stats/flow/<dpid>`) and egress ports; distinguishes `flow_table` vs `assumed_shortest` sources. |
| 7 | **Identify & localize failed paths** | `correlate.py`, `reroute_helper.py` | Classifies path health (`HEALTHY` / `DEGRADED` / `FAILED`); localizes suspect links via port drop counters, segment probes, and topology liveness diffs; prunes bad links to rank viable backups; installs flow overrides. |

---

## 3. System Architecture

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

### Data Plane
- Source host sends versioned UDP probes (`SDN_PROBE v1.0`) to destination host
- `probe_server.py` echoes probes back with timestamps
- Measures RTT, jitter, packet loss, duplicates, out-of-order delivery

### Control Plane
- `sdn_topology.py` queries Ryu/OpenDaylight REST APIs for topology (switches, links, hosts)
- `flow_inspector.py` queries OpenFlow flow tables (`/stats/flow/<dpid>`) and port statistics (`/stats/port/<dpid>`)
- `reroute_helper.py` installs backup flow rules via `/stats/flowentry/add`

---

## 4. Unified CLI (`sdnscope.py`)

All functionality is accessible via 10 subcommands:

| Subcommand | Purpose | Key Arguments |
|---|-----------|-------------|
| `probe` | Run active UDP diagnostic probe client | `target_ip -p 9999 -c 10 --interval 0.05 --burst -n h2` |
| `serve` | Start multi-threaded UDP probe server | `-p 9999 -b 0.0.0.0 --drop-rate 0.10 --delay-ms 50` |
| `trace` | Execute hop-by-hop IP layer path trace | `target_ip -m 30 --timeout 2.0 -o trace.json` |
| `topo` | Discover switches, links, and hosts via REST | `-c ryu -i 127.0.0.1 -p 8080 -o topology.json` |
| `paths` | Find and rank all loop-free simple paths (BFS) | `-s h1 -d h2 -f topology.json` |
| `correlate` | Correlate telemetry, localize faults, rank backups | `-d diag.json -t topo.json -s h1 -e h2 --controller <url>` |
| `watch` | Monitor live SDN topology changes in real time | `-w 5 -c ryu -i 127.0.0.1 -p 8080` |
| `localize` | Run dedicated multi-source failure localization | `-t topo.json --baseline-stats b.json --current-stats c.json --qdisc-before qb.txt --qdisc-after qa.txt` |
| `reroute` | Install OpenFlow backup flow modifications | `-r report.json -t topo.json -c <url> [--apply]` |
| `report` | Generate Markdown, HTML, and chart reports | `-r report.json -d diag.json -m report.md -H report.html` |

---

## 5. Multi-Source Failure Localization Methodology

`correlate.py` implements a 4-source evidence aggregation model:

### Evidence Source A: Switch Port Statistics Deltas
- Polls switch port counters (`/stats/port/<dpid>`) before and after probing
- Computes deltas: ΔTX, ΔRX, ΔDrop
- Link degradation detected when drop counters increment or TX > RX mismatch

### Evidence Source B: Per-Segment Probing
- Measures sub-segments along the active path
- Identifies where loss spikes or RTT jumps occur

### Evidence Source C: Topology Liveness Diffing
- Compares controller's active link inventory against baseline topology
- Links absent from active topology are flagged as severed (confidence = 1.0)

### Evidence Source D: Kernel Qdisc Drop Deltas
- Parses `tc -s qdisc show dev <iface>` captures before and after probing
- Maps interface names to topology links and attributes drop deltas (confidence = 0.95)
- Measures `netem` drops directly, which OVS port counters cannot see

### Combined Confidence
When multiple evidence sources implicate a link, confidences are combined via weighted evidence scoring (independent combination):  
**C_combined = 1.0 - Π(1.0 - c_i)**

---

## 6. Automated Failover (Reroute)

- Prunes candidate paths containing suspected-bad links (confidence ≥ 0.50)
- Ranks surviving backup paths by hop count
- Generates OpenFlow 1.3 flow modification rules via `/stats/flowentry/add`
- Operates in safe dry-run mode by default; applies changes only with `--apply`
- Example rule: `DPID 1 | Match: {ipv4_dst: 10.0.0.2} | Action: OUTPUT port 3 | Priority: 200`

---

## 7. File Inventory

### Core Source Modules
| File | Purpose |
|---|---|
| `sdnscope.py` | Unified CLI controller (v1.0.0) — 10 subcommands |
| `probe_server.py` | Multi-threaded UDP probe echo server with artificial drop/delay |
| `diagnostic_client.py` | Active UDP probing client with RTT/loss statistics |
| `path_analysis.py` | IP-layer hop tracing (traceroute/tracepath wrapper) |
| `sdn_topology.py` | SDN topology discovery from Ryu/OpenDaylight REST APIs |
| `topology_graph.py` | In-memory graph model with BFS path finding |
| `flow_inspector.py` | OpenFlow flow-table inspection and active path reconstruction |
| `correlate.py` | Measurement/topology correlation, failure localization, backup ranking |
| `reroute_helper.py` | OpenFlow backup path flow rule generation and deployment |
| `report_generator.py` | Markdown/HTML report generation with charts |
| `mock_controller.py` | Mock Ryu SDN controller REST server for offline testing |
| `config.json` | Configuration (ports, thresholds, controller settings) |

### Documentation
| File | Purpose |
|---|---|
| `README.md` | Executive overview, requirement traceability, architecture, CLI reference, scenario walkthrough |
| `SETUP.md` | Mininet, Ryu, Python environment setup guide |
| `AUDIT.md` | Original codebase audit, gap analysis, implementation roadmap |
| `docs/DESIGN.md` | Architectural decisions, protocol formats, mathematical formulas |
| `docs/DEMO.md` | 5-minute step-by-step oral presentation demonstration script |
| `docs/schemas.md` | JSON schemas for telemetry packets, topology, and reports |

### Tests (82 tests, all passing)
| File | Purpose |
|---|---|
| `tests/test_flow_inspector.py` | Flow-table path reconstruction, legacy match key parsing, LLDP/table-miss filtering |
| `tests/test_sdn_topology.py` | DPID normalization, host parsing, topology parsing |
| `tests/test_correlation.py` | Health classification, failure localization, backup ranking |
| `tests/test_qdisc_stats.py` | Kernel qdisc parsing, drop-delta attribution, combined confidence |
| `tests/test_statistics.py` | RTT statistics, jitter, percentiles |
| `tests/test_integration.py` | UDP probe server/client end-to-end |
| `tests/test_graph.py` | Topology graph path finding |
| `tests/test_path_analysis.py` | Traceroute output parsing |
| `tests/test_report_generator.py` | Report generation |
| `tests/test_reroute_helper.py` | Flow rule generation and dry-run/apply |
| `tests/test_packet_parsing.py` | Probe packet parsing and validation |
| `tests/test_real_diamond_fixtures.py` | Live diamond fixture verification (switches, links, flows, port stats) |

### Fixtures
| Directory | Contents |
|---|---|
| `tests/fixtures/real/` | **Preserved** linear_3 topology fixtures (switches, links, hosts, flows, port stats) |
| `tests/fixtures/synthetic_diamond/` | Diamond topology fixtures in Ryu format (s1, s2, s3 switches; h1, h2 hosts; flow tables with legacy keys; port stats) |
| `tests/fixtures/real_diamond/` | Diamond fixtures captured from the live testbed, including primary/backup flow tables and per-switch port statistics |

### Results
| Directory | Contents |
|---|---|
| `results/demo_localhost/` | Standalone localhost demo outputs |
| `results/real_20261105_222258/` | **Latest** live four-scenario suite (healthy, degraded, failed, recovery); `results/latest` points here |
| `results/real_20261105_150848/` | Previous live four-scenario suite (independent qdisc validation) |
| `results/real_20261023_190236/` | Historical live four-scenario suite analysed in the evidence docs |
| `results/cli_verification/` | Live CLI verification artifacts and transcript |

### Scripts
| File | Purpose |
|---|---|
| `scripts/run_all_scenarios.sh` | Runs all 4 scenarios (healthy, degraded, failed, recovery) |
| `scripts/demo_localhost.sh` | Standalone localhost demo (no root/Mininet required) |
| `topology/diamond_topo.py` | Mininet diamond topology definition |

---

## 8. Tested Scenarios

The suite validates three scenarios with offline test fixtures, not measurements:

### Scenario A: Baseline Operation (Healthy Path)
- Condition: 0.0% packet loss, baseline RTT expected 6-20 ms (primary path: h1-s1 1ms, s1-s2 2ms, s2-h2 1ms)
- Status: Verified with offline test fixtures
- Classification: `HEALTHY_PATH`
- Active Path: `h1 → s1 → s2 → h2` (3 hops, `path_source: FLOW_TABLE`)

### Scenario B: Link Congestion & Queue Degradation
- Condition: Injected 60 ms delay, 10% drop on primary link
- Status: Verified with offline test fixtures
- Classification: `DEGRADED_PATH`
- Suspect Link: Core link `s1 ←→ s2` flagged
- Recommended Backup: `h1 → s1 → s3 → s2 → h2` (+1 extra hop)

### Scenario C: Hard Link Failure & Automated Failover
- Condition: Primary core link `s1 ←→ s2` severed (100% loss)
- Status: Verified with offline test fixtures
- Classification: `FAILED_PATH`
- Evidence: Link `s1 ←→ s2` disappeared from controller active topology (100% confidence)
- Recommended Backup: `h1 → s1 → s3 → s2 → h2` (Rank 1, VIABLE_BACKUP)
- Automated Failover: `sdnscope reroute --apply` installs rule on Switch 1, restoring connectivity via `s3`

---

## 9. Technical Limitations & Tradeoffs

1. **OpenFlow Layer 2 TTL Transparency:** Standard traceroute is transparent to OpenFlow switches (reports 1 hop). Solved by flow-table inspection as the authoritative path source.
2. **One-Way Delay Clock Synchronization:** Forward/reverse delay estimates subject to clock skew without PTP/NTP. RTT uses client-side timestamps only and is immune to skew.
3. **Control-Plane Polling Intervals:** Very short micro-outages (< 500 ms) may resolve before controller updates link inventory, requiring active segment probing.

---

## 10. Completed Validation & Optional Roadmap

### Completed during final validation

- **Live Ryu + Mininet validation:** The full four-scenario suite ran end-to-end on Ubuntu 26.04 with Mininet 2.3.0, Open vSwitch 3.7.1 and Ryu 4.34 (`results/real_20261105_222258/`).
- **Real diamond fixtures:** Live switch, link, host, flow-table and port-stat captures are present in `tests/fixtures/real_diamond/` and covered by `tests/test_real_diamond_fixtures.py`.
- **Host discovery bootstrap:** `sdn_topology.py` accepts an authoritative `hosts.json` via `--hosts-file`, and the Mininet orchestrator emits it automatically.
- **Documentation:** `README.md` and `SETUP.md` were completed with the requirement matrix, flow-table reconstruction, mock modes, live setup, and automated scripts.
- **Qdisc localization:** Kernel qdisc drop deltas are consumed by `correlate.py`; the archived 60% heuristic is retained only as a fallback.

### Optional future enhancements

| # | Task | Description | Priority |
|---|------|-------------|----------|
| 1 | **config.json security** | Remove hardcoded plaintext password; add environment variable override (`CONTROLLER_PASSWORD`); add `.gitignore` protection for `config.local.json`; add schema validation. | Medium |
| 2 | **Mock controller mode for sdn_topology.py** | Add a mock-controller fallback when the real controller is offline (the standalone localhost demo already uses `mock_controller.py`). | Medium |
| 3 | **Deeper `sdn_topology.py --watch` integration** | The unified `sdnscope.py watch` command already monitors live link state; this item covers exposing the same update loop directly from `sdn_topology.py`. | Medium |
| 4 | **Per-segment probing responders** | Implement intermediate probe responders on switch attachments for Evidence Source B (segment probing) to work end-to-end. | Medium |
| 5 | **Flow table path reconstruction with IPv6** | Extend `flow_inspector.py` match_rule to handle IPv6 match keys (`ipv6_dst`) alongside IPv4. | Low |
| 6 | **P4 / In-Band Network Telemetry (INT)** | Direct embedding of hop latency and port queue depth into packet headers at line rate. | Low |
| 7 | **Segment Routing over IPv6 (SRv6)** | Source-routed backup path deployment without requiring per-hop flow-table modifications. | Low |
| 8 | **Streaming Machine Learning Telemetry** | Real-time predictive anomaly detection to anticipate queue overflow and execute proactive traffic steering. | Low |

---

## 11. Build & Test Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run full test suite (82 tests with coverage)
make test

# Run ruff static code analysis (zero lint errors enforced)
make lint

# Run preflight verification checks
make real-check

# Run standalone localhost demonstration (no Mininet required)
make demo

# Run live Mininet+Ryu scenario suite
make real-scenarios

# Clean caches and temporary files
make clean
```

---

## 12. Key Design Decisions (Corrected Based on Real Ryu Output)

1. **DPID Normalization:** Ryu topology API returns DPIDs as 16-char hex strings (`"0000000000000002"`), while `/stats/flow/<dpid>` and `/stats/port/<dpid>` expect decimal integers (`2`). A single tested helper (`normalize_dpid` / `dpid_to_decimal` in `sdn_topology.py`) handles conversion between all forms.

2. **Legacy OpenFlow 1.3 Match Keys:** Real `ofctl_rest` flow stats return match keys in legacy form: `dl_src`, `dl_dst`, `dl_type`, `in_port` (integer), `nw_src`, `nw_dst`. Actions are strings like `"OUTPUT:2"` or `"OUTPUT:CONTROLLER"`. The code accepts `eth_src`/`eth_dst`/`eth_type` as aliases.

3. **LLDP and Table-Miss Flow Filtering:** LLDP discovery flows (`dl_type 35020`, `dl_dst 01:80:c2:00:00:0e`, `OUTPUT:CONTROLLER`) and table-miss flows (priority 0, empty match) are explicitly skipped during path reconstruction.

4. **IPv4 Preference in Host Parsing:** `/v1.0/topology/hosts` returns populated host data only after traffic is generated. IPv6 `"::"` entries are ignored; IPv4 is preferred. Empty host lists (fresh controller) are handled gracefully.

5. **Flow Table Path Authority:** Flow-table reconstruction (`path_source: flow_table`) takes precedence over BFS shortest path (`path_source: assumed_shortest`) when flow entries are available.

---

## 13. Repository Structure

```
cn_project/
├── README.md                          # Executive overview & CLI reference
├── SETUP.md                           # Environment setup guide
├── AUDIT.md                           # Codebase audit & roadmap
├── PROJECT_SUMMARY.md                 # This document
├── config.json                        # Configuration
├── pyproject.toml                     # Ruff lint config
├── pytest.ini                         # Pytest config
├── Makefile                           # Build/test targets
├── requirements.txt                   # Python dependencies
├── sdnscope.py                        # Unified CLI (v1.0.0)
├── probe_server.py                    # UDP probe echo server
├── diagnostic_client.py               # UDP probing client
├── path_analysis.py                   # Hop-by-hop tracing
├── sdn_topology.py                    # SDN topology discovery
├── topology_graph.py                  # Graph path finding
├── flow_inspector.py                  # Flow-table inspection & path reconstruction
├── correlate.py                       # Correlation & failure localization
├── reroute_helper.py                  # Backup flow rule deployment
├── report_generator.py                # Report generation
├── mock_controller.py                 # Mock Ryu controller REST server
├── topology/
│   └── diamond_topo.py                # Mininet diamond topology
├── docs/
│   ├── DESIGN.md                      # Architecture & protocol specs
│   ├── DEMO.md                        # Demo script
│   └── schemas.md                     # JSON schemas
├── tests/
│   ├── test_flow_inspector.py         # Flow inspector tests (82 total tests)
│   ├── test_sdn_topology.py           # Topology discovery tests
│   ├── test_correlation.py            # Correlation tests
│   ├── test_statistics.py             # Statistics tests
│   ├── test_integration.py            # Integration tests
│   ├── test_graph.py                  # Graph tests
│   ├── test_path_analysis.py          # Path analysis tests
│   ├── test_report_generator.py       # Report tests
│   ├── test_reroute_helper.py         # Reroute tests
│   ├── test_packet_parsing.py         # Packet parsing tests
│   ├── test_real_diamond_fixtures.py  # Genuine diamond fixture verification
│   └── fixtures/
│       ├── real/                      # Linear_3 topology fixtures (preserved)
│       ├── synthetic_diamond/         # Diamond topology fixtures (synthetic)
│       └── real_diamond/              # Diamond topology fixtures (live capture)
├── results/
│   ├── latest/                        # Symlink to latest real execution
│   ├── real_20261105_222258/          # Latest live four-scenario run
│   ├── real_20261105_150848/          # Previous live four-scenario run
│   ├── real_20261023_190236/          # Historical live four-scenario run
│   ├── demo_localhost/                # Standalone localhost demo
│   └── cli_verification/              # Live CLI verification artifacts
└── scripts/
    ├── run_all_scenarios.sh           # Run live testbed scenarios
    ├── run_ryu.sh                     # Ryu controller runner
    ├── preflight_check.sh             # Pre-flight environment check
    └── demo_localhost.sh              # Localhost demo
```

---

**End of Project Summary**  
*All 82 tests pass. All ruff lint checks pass.*
