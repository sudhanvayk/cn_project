# SDNScope — Final Verification & Mission Summary

**Project:** SDNScope (Topic 13: Socket-Based Network Diagnostic and Path Analysis Tool for SDN)  
**Release:** `v1.1.0`  
**Base Branch:** `main` (Merged from `fix/real-sdn-validation` with `--no-ff`)  
**Tag:** `v1.1.0`  
**Execution Environment:** Ubuntu 24.04 VM (`sudh-VB`, Linux kernel 7.0.0-38-generic)  
**Controller Runtime:** Ryu 4.34 in Python 3.9 venv (`~/ryu-env/bin/ryu-manager`)  
**Data Plane Testbed:** Mininet 2.3.0 + Open vSwitch 3.3.9 Diamond Topology (s1, s2, s3, h1, h2)  
**Project Tooling:** Python 3.12 (`/home/sudh/Documents/cn_project/.venv`)  

---

## 1. Executive Summary

This mission successfully finished, hardened, and verified **SDNScope** on a genuine Mininet and Ryu SDN testbed, replacing earlier mock/synthetic data with authentic empirical measurements. All 7 core expectations of Topic 13 are satisfied with reproducible proof on real network namespaces and OpenFlow 1.3 switches.

Nothing in the final results is simulated, mocked, or reused:
- **Baseline Healthy RTT:** Measured at **13.24 ms** (theoretical lower bound 8.0 ms + Python socket / OVS kernel qdisc processing; acceptable range 6–20 ms; 0.00% packet loss).
- **Impaired Degraded RTT & Loss:** Measured at **73.32 ms** (+60 ms round-trip delay injected via Linux kernel `netem`) and **10.00% loss** (5% drop per direction).
- **Hard Link Failure:** 100.00% loss, physical link severed, localized to `s1 <---> s2` with **100% confidence** within 0.01s.
- **Failover Recovery:** Rerouting deployed 12 bidirectional OpenFlow 1.3 rules (IPv4 + ARP) with priority 200 via Ryu REST API `/stats/flowentry/add`, immediately restoring connectivity across `h1 -> s1 -> s3 -> s2 -> h2` (4 hops, **19.94 ms RTT**, **0.00% loss**).

---

## 2. Requirement Traceability Matrix (All 7 Expectations Satisfied)

| # | Topic 13 Expectation | Implementing Modules | Real Testbed Verification Evidence |
|---|---|---|---|
| **1** | **UDP diagnostic probes** | `probe_server.py`<br>`diagnostic_client.py` | Executed 50 to 100 probes at 0.05s intervals using versioned JSON wire format (`SDN_PROBE v1.0`), microsecond send/recv timestamps, and sequence numbers. |
| **2** | **Measure round-trip time** | `diagnostic_client.py` | Measured RTT distributions with microsecond precision: Min, Max, Mean, Median, StdDev Jitter, RFC 3550 Inter-Arrival Jitter, and 95th percentile (p95). |
| **3** | **Detect packet loss** | `diagnostic_client.py`<br>`probe_server.py` | Detected individual lost datagrams via socket timeouts (10/100 lost in degraded, 20/20 in failed, 0/50 in healthy/recovery); flagged 0 duplicates and 0 out-of-order packets. |
| **4** | **Implement path analysis** | `path_analysis.py` | Dual-mode traceroute (`native_raw_socket` and system trace) reporting hop counts, with clear documentation of OpenFlow Layer 2 TTL transparency. |
| **5** | **Discover SDN topology** | `sdn_topology.py`<br>`topology_graph.py` | Queried Ryu REST API (`/v1.0/topology/switches`, `/links`); merged host mappings (`--hosts-file`); watched live link bounce (`sdnscope watch`). |
| **6** | **Correlate measurements with actual paths** | `flow_inspector.py`<br>`correlate.py` | Queried live OpenFlow 1.3 flow tables (`/stats/flow/<dpid>`) to reconstruct the true active forwarding path (`path_source: FLOW_TABLE`) matching destination IPs and egress ports. |
| **7** | **Identify failed paths** | `correlate.py`<br>`reroute_helper.py` | Classified path state (`HEALTHY`, `DEGRADED`, `FAILED`); localized failing core link (`s1 <---> s2`) using port stats deltas and topology diffing; ranked viable backups and deployed failover flow rules. |

---

## 3. Port & Address Map (Single Source of Truth)

| Entity / Service | Interface / Node | Protocol / Transport | Port / Address | Description |
|---|---|---|---|---|
| **Ryu REST Northbound** | Host loopback | HTTP (JSON) | **TCP 8080** | `/v1.0/topology/*`, `/stats/*` |
| **OpenFlow Controller** | Host loopback | OpenFlow 1.3 | **TCP 6653** | Ryu controller listening socket |
| **OpenDaylight RESTCONF** | Host loopback | RESTCONF (Doc) | **TCP 8181** | Supported schema parser |
| **UDP Diagnostic Probe** | Host `h2` (`10.0.0.2`) | UDP | **UDP 9999** | Server socket handled by `probe_server.py` |
| **Host 1 (h1)** | Mininet namespace `h1` | IPv4 / Ethernet | `10.0.0.1/24` | MAC `00:00:00:00:00:01`, attached to `s1-eth1` |
| **Host 2 (h2)** | Mininet namespace `h2` | IPv4 / Ethernet | `10.0.0.2/24` | MAC `00:00:00:00:00:02`, attached to `s2-eth1` |
| **Switch 1 (s1)** | OVS Bridge `s1` | OpenFlow 1.3 | DPID `1` | Port 1: `h1`, Port 2: `s2` (primary), Port 3: `s3` (backup) |
| **Switch 2 (s2)** | OVS Bridge `s2` | OpenFlow 1.3 | DPID `2` | Port 1: `h2`, Port 2: `s1` (primary), Port 3: `s3` (backup) |
| **Switch 3 (s3)** | OVS Bridge `s3` | OpenFlow 1.3 | DPID `3` | Port 1: `s1`, Port 2: `s2` (backup transit switch) |

---

## 4. Real Scenario Performance Comparison

Telemetry captured during end-to-end execution of `./scripts/run_all_scenarios.sh` (`results/real_20261023_190236/`):

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

---

## 5. Live CLI Verification

All CLI subcommands were exercised live against the running Mininet and Ryu testbed via `scripts/verify_live_cli.py`:

1. **`sdnscope.py topo`:** Discovered all 3 switches (`s1`, `s2`, `s3`) and both hosts (`h1`, `h2`) with 5 bidirectional links.
2. **`sdnscope.py paths -s h1 -d h2`:** Identified shortest path `h1 -> s1 -> s2 -> h2` (3 hops) and alternative path `h1 -> s1 -> s3 -> s2 -> h2` (4 hops, +1 extra hop).
3. **`sdnscope.py trace 10.0.0.2`:** Executed native raw socket traceroute from inside host `h1`, reporting OpenFlow Layer 2 TTL transparency with notice detailing controller flow table authority.
4. **`sdnscope.py watch`:** Ran live topology event watcher for 5 seconds; captured physical link severance event `[EVENT DETECTED]: ● LINK DOWN: s1 <---> s2` immediately when bounced in Mininet.
5. **`sdnscope.py report`:** Generated valid, self-contained Markdown (`report.md`), HTML (`report.html`), and latency time-series visual charts (`rtt_timeseries.png`).

---

## 6. Key Technical Innovations & Resolved Bugs

1. **OpenFlow Controller Port Standardization:** Fixed controller listening port mismatch from 6633 to 6653 across diamond topology, config, scripts, and docs.
2. **Ryu Port Format Parsing:** Normalized 8-character zero-padded string port numbers (`"00000002"`) returned by Ryu into integer identifiers so link lookups succeed.
3. **Internal Switch Port "LOCAL" Handling:** Fixed `correlate.py` `index_stats` to gracefully parse non-numeric internal switch ports without raising `ValueError`.
4. **Report Generator NoneType Formatting:** Fixed `report_generator.py` with `fmt_ms()` and `fmt_pct()` helpers to safely format `None` values under 100% loss.
5. **Symmetric Bidirectional Rerouting:** Upgraded `reroute_helper.py` to generate complete forward (IPv4/ARP toward `10.0.0.2`) and reverse (IPv4/ARP toward `10.0.0.1`) flow rules at OpenFlow priority 200, resolving echo reply drops along backup routes.
6. **Namespace Separation:** Routed data-plane probes (`probe`, `trace`) through Mininet namespaces (`h1`), while routing control-plane REST queries through the host environment (`127.0.0.1:8080`).
7. **Hybrid Host Discovery:** Integrated `--hosts-file` merge into `sdn_topology.py` to overcome Ryu's empty `/v1.0/topology/hosts` endpoint when operating under static flows without learning switches.
8. **Isolated Controller Runtime:** Pinned Ryu 4.34 in a separate Python 3.9 virtual environment (`~/ryu-env`) using `uv`, leaving the project `.venv` on Python 3.12.

---

## 7. Quality Assurance Gates

- **Unit & Integration Tests:** 69 passed in 7.51s (74% coverage across core modules, 100% on test files).
- **Static Code Analysis:** `ruff check .` passed with 0 lint errors.
- **Bytecode Compilation:** `python3 -m py_compile` passed with 0 syntax errors across all `.py` files.
- **Secrets Audit:** 0 credentials or plaintext passwords present in codebase.
- **Clean Clone Test:** Tested in `/tmp/cn_clean`; 69 passed without uncommitted dependencies.
- **Working Tree:** 0 uncommitted changes; working tree clean.

---

## 8. Git Release Summary

- **Branch:** Merged `fix/real-sdn-validation` into `main` via merge commit.
- **Tag:** `v1.1.0`
- **Total Commits Added:** 34 granular Conventional Commits (exceeding the target of 25+).
