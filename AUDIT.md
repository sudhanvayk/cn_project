# Comprehensive Project Audit: SDN Network Diagnostic & Path Analysis Tool

**Date:** 2026-10-19  
**Branch:** `feature/complete-sdn-diagnostics`  
**Workspace:** repository root  
**Auditor:** Senior Network & SDN Systems Engineer  

---

## 1. Executive Summary

An initial architectural and code audit of the repository was performed against the requirements of **Topic 13: Network Diagnostic and Path Analysis Tool** (Socket-based UDP diagnostic application measuring delay, packet loss, path characteristics, SDN topology discovery, correlation, and failed-path identification).

The existing codebase provides a foundational prototype structure across 6 core Python scripts and configuration files. However, several critical gaps, architectural weaknesses, unhandled SDN realities (e.g. OpenFlow L2 TTL non-decrement), security flaws (hardcoded credentials), and lack of testing were identified.

---

## 2. File-by-File Audit & Status Matrix

| File | Current Status | Working Capabilities | Stubs, Weaknesses & Missing Logic | Testing Status |
|---|---|---|---|---|
| **`config.json`** | Insecure / Incomplete | Default ports, probe count, timeout, payload size, controller URLs, and basic health thresholds. | • Hardcoded plaintext password (`adminpassword`).<br>• No support for environment variable override (`CONTROLLER_PASSWORD`).<br>• No `.gitignore` protection for local secrets (`config.local.json`).<br>• No schema validation for parameters. | Untested for schema violations. |
| **`probe_server.py`** | Basic Prototype | • Listens on UDP port 9999.<br>• Echoes JSON packet back to client with send/recv timestamps.<br>• Safely catches JSON decoding errors. | • No magic bytes or protocol versioning (accepts stray UDP packets).<br>• No sequence number tracking or duplicate packet detection.<br>• Single-threaded; cannot simulate artificial delay (`--delay-ms`) or drop rate (`--drop-rate`) for testing.<br>• Basic print logging only. | Untested under high concurrency or packet corruption. |
| **`diagnostic_client.py`** | Partial | • Sends sequential UDP probe packets.<br>• Measures RTT (min, max, mean, median, stddev) and packet loss %.<br>• Outputs terminal table and JSON. | • Jitter is only calculated as sample standard deviation; lacks **RFC 3550** inter-arrival jitter smoothing ($J = J + (|D| - J)/16$).<br>• Missing **p95 RTT** and one-way delay documentation.<br>• No duplicate or out-of-order reply detection.<br>• Missing burst mode (`--burst`) for buffer/queue analysis.<br>• Single target only (no multi-target parallel probing via threads).<br>• No input validation for target IP/ports. | Untested with unit test suite; no edge case coverage (0% loss, 100% loss, 1 probe). |
| **`path_analysis.py`** | Inadequate for SDN | • Wraps system `traceroute` with fallback to `tracepath`.<br>• Parses hop count and hop IPs via regex. | • **Critical SDN Limitation Unaddressed:** L2 OpenFlow switches do not decrement IP TTL, causing traceroute in Mininet to report 1 hop directly to destination.<br>• No raw socket/UDP-ICMP traceroute implementation.<br>• No per-hop RTT or loss metrics.<br>• Does not query SDN controller for true data-plane path. | Untested with synthetic traceroute output streams. |
| **`sdn_topology.py`** | Working Prototype | • Northbound REST queries to Ryu (`/v1.0/topology/*`) and ODL.<br>• Normalizes DPIDs and switch-host links into standard nodes/links JSON. | • Fails completely when controller is offline (no mock controller mode).<br>• Does not inspect OpenFlow flow tables or port statistics.<br>• No topology refresh or `--watch` mode for live link status updates.<br>• Plaintext credentials in requests. | Untested against mock REST servers; no unit tests. |
| **`topology_graph.py`** | Working Prototype | • In-memory graph model (`SDNTopologyGraph`).<br>• BFS simple loop-free path discovery.<br>• Ranks paths by hop count and calculates extra hop cost. | • Purely topological; does not know which path is actually chosen by OpenFlow rules.<br>• Does not support link pruning (excluding suspected failed links).<br>• Assumes unweighted links. | Untested on disconnected graphs, cyclic graphs, or multi-homed topologies. |
| **`correlate.py`** | Naive Correlation | • Reads probe JSON and topology JSON.<br>• Classifies health (`HEALTHY_PATH`, `DEGRADED_PATH`, `FAILED_PATH`) based on global thresholds.<br>• Recommends shortest alternative route. | • **Coarse-Grained:** Reports path failure without localizing *where* (which switch/link) failed.<br>• Lacks port stats delta analysis (`tx_packets` vs `rx_packets` / errors).<br>• Lacks per-segment probing and topology diffing.<br>• Does not compute confidence scores or evidence records for suspects.<br>• Does not exclude failed links when ranking backup routes. | Untested on threshold boundary conditions (e.g. 0.01% loss, 50.0% loss). |
| **`README.md`** | Detailed Overview | Explains basic commands, Mininet triangular topology, and scenario definitions. | • References only manual instructions.<br>• Lacks requirement traceability matrix.<br>• Does not document flow table path reconstruction or mock modes. | Needs update to reflect new features and automated scripts. |

---

## 3. Missing Components Required for Complete Submission

1. **Flow Table Inspector (`flow_inspector.py`):**
   Reconstructs the *exact active path* by tracing OpenFlow flow rules (`/stats/flow/<dpid>`) from source host MAC/IP to destination host MAC/IP.
2. **Offline Mock SDN Controller (`mock_controller.py`):**
   A standalone lightweight HTTP server serving canned Ryu REST topology, flow stats, and port counters, enabling 100% reproducible testing and evaluation in non-SDN environments.
3. **Multi-Source Failure Localizer (`correlate.py` upgrade):**
   Combines (a) Switch port counter mismatch analysis ($\Delta tx \neq \Delta rx$, drop counters), (b) Per-segment probe anomalies, and (c) Topology link liveness diffs to assign confidence scores to suspect links.
4. **Automated Reroute Assistant (`reroute_helper.py`):**
   Generates and pushes OpenFlow flow modification rules via Ryu `/stats/flowentry/add` to reroute traffic along the recommended backup path.
5. **Unified CLI Suite (`sdnscope.py`):**
   A unified, professional CLI tool with subcommands: `probe`, `serve`, `trace`, `topo`, `paths`, `correlate`, `watch`, `localize`, `reroute`, and `report`.
6. **Reproducible Test Bed & Topologies (`topology/diamond_topo.py`, `scripts/`):**
   Mininet diamond topology (primary path `h1-s1-s2-h2`, backup `h1-s1-s3-s2-h2`), automated execution scripts, and canned scenarios (healthy, degraded with `tc netem`, failed with `link down`).
7. **Comprehensive Pytest Suite (`tests/`):**
   Targeting >80% test coverage for RFC 3550 jitter, statistics, BFS paths, flow table reconstruction, mock port stats, and CLI error handling.
8. **Automated HTML/Markdown Reporting Engine (`report.py`):**
   Generates executive reports with topology diagrams, telemetry charts, and failure diagnosis.
9. **Documentation Suite:**
   `SETUP.md`, `docs/DESIGN.md`, `docs/DEMO.md`, `docs/VIVA.md` (20 examiner questions & answers), and `docs/schemas.md`.

---

## 4. Localhost Test & CLI Validation Plan

Each existing script will be executed with `--help` and a local test case to verify base behavior and record baseline results. Identified errors or deficiencies will be systematically fixed in dedicated Git commits.
