# Changelog

All notable changes to the **SDNScope** (Socket-Based Network Diagnostic and Path Analysis Tool for SDN) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.1] - 2026-10-23

### Fixed
- **OpenFlow Forwarding Activation in Test Harnesses:** Changed `apply_changes: bool = True` in `reroute_helper.py` (`install_primary_flows`, `install_backup_flows`) so programmatically instantiated testbeds apply flows live, ensuring `h1` can reach `h2` and receive ICMP replies.
- **Trace Hop 1 Reachability:** Verified `sdnscope.py trace 10.0.0.2` receives ICMP Port Unreachable replies from `h2` at Hop 1 (0% loss, ~11.8 ms RTT); added system traceroute/tracepath fallback in `path_analysis.py` if raw socket times out.
- **Unit Testing:** Added unit tests in `tests/test_path_analysis.py` verifying Hop 1 reachable parsing and system utility fallbacks (71 total pytest tests passing).

### Changed
- **Degraded Scenario Evidence Transparency:** Explicitly classified the 60% confidence on `s1 <---> s2` in `correlate.py`, `docs/DESIGN.md`, `docs/VIVA.md`, and `docs/EVIDENCE.md` as a **path-membership heuristic fallback**, NOT a physical measurement. Documented raw values from `/stats/port` (`tx_dropped: 0`) and `tc -s qdisc show dev s1-eth2` (5 drops on s1-eth2, 8 drops on s2-eth2).

---

## [1.1.0] - 2026-10-23

### Added
- **Real SDN Testbed Harness:**
  - `scripts/run_ryu.sh`: Automated Ryu controller lifecycle manager with readiness checks for OpenFlow 1.3 switch connections.
  - `topology/scenario_runner.py`: Root Mininet orchestrator executing all 4 real network scenarios (`healthy`, `degraded`, `failed`, `recovery`).
  - `scripts/run_all_scenarios.sh`: End-to-end master test suite with environment snapshotting, telemetry collection, and symlink management (`results/latest/`).
  - `scripts/verify_live_cli.py`: Live CLI harness verifying `topo`, `paths`, `trace`, `watch` (with live link bounce), and `report`.
  - `scripts/preflight_check.sh`: Automated pre-flight validation verifying sudo access, binaries, isolated Python environments, ports, and unit tests (`make real-check`).
- **Bidirectional & ARP Failover Routing:**
  - Added symmetric bidirectional flow generation to `reroute_helper.py` (`generate_flow_entries`) installing forward IPv4/ARP flows and reverse IPv4/ARP flows along backup paths at OpenFlow priority 200.
  - Unit tests verifying bidirectional flow generation and port mapping in `tests/test_reroute_helper.py`.
- **Hybrid Host Discovery:**
  - Added `merge_hosts_file` in `sdn_topology.py` to overcome Ryu's empty `/v1.0/topology/hosts` endpoint under static flow operation without learning switches.
  - Tags host entries with `host_source: "hosts_file"` (or `host_source: "controller"`).
- **Genuine Fixtures & Tests:**
  - Genuine Mininet 2.3.0 + Ryu 4.34 fixtures captured in `tests/fixtures/real_diamond/`.
  - Unit test suite in `tests/test_real_diamond_fixtures.py` asserting MAC address uniqueness, switch DPIDs, and highest-priority flow matching.
- **Evidence Documentation:**
  - Created `docs/EVIDENCE.md` compiling raw execution transcripts, pre-flight logs, live CLI outputs, and comparative scenario performance tables.

### Fixed
- **OpenFlow Controller Port Mismatch:** Aligned OpenFlow controller listening port to standard `6653` across `diamond_topo.py`, `config.json`, scripts, and docs.
- **Ryu Port Normalization:** Corrected `sdn_topology.py` and `flow_inspector.py` to parse 8-character zero-padded string port numbers (`"00000002"`) returned by Ryu into integer identifiers.
- **Switch Port "LOCAL" Handling:** Fixed `correlate.py` `index_stats` to gracefully parse non-numeric internal switch ports (such as `"LOCAL"`).
- **Report Generator Formatting:** Fixed `report_generator.py` with `fmt_ms()` and `fmt_pct()` helpers to safely format `NoneType` metric values under 100% packet loss without raising `TypeError`.
- **Link DPID Normalization:** Added `dpid_to_switch_id` normalization in `correlate.py` link liveness checking to ensure consistent DPID comparison between topology representations.
- **Namespace Isolation:** Directed data-plane commands (`probe`, `trace`, `ping`) to execute inside Mininet host network namespaces (`h1`), while directing control-plane management commands (`topo`, `paths`, `correlate`, `report`, `reroute`) to the host environment.

### Changed
- Clarified failure localization algorithm across all documentation as weighted evidence scoring (independent multi-source evidence combination / noisy-OR model), removing misleading Bayesian terminology.
- Updated `README.md`, `SETUP.md`, `docs/DESIGN.md`, `docs/VIVA.md`, and `docs/schemas.md` with the single-source-of-truth Port & Address Map and genuine real-testbed measurements.

---

## [1.0.0] - 2026-10-19

### Added
- Initial implementation satisfying Topic 13 (Socket-based network diagnostic and path analysis tool for SDN).
- UDP diagnostic client (`diagnostic_client.py`) and multi-threaded probe server (`probe_server.py`) with wire protocol `SDN_PROBE v1.0`.
- Dual-mode path analysis (`path_analysis.py`) supporting native raw socket ICMP/UDP traceroute and system trace fallback.
- SDN topology discovery (`sdn_topology.py`) supporting Ryu REST API and OpenDaylight RESTCONF.
- Graph analysis engine (`topology_graph.py`) implementing BFS simple path discovery and comparison.
- OpenFlow flow-table path reconstruction (`flow_inspector.py`) querying controller flow entries.
- Multi-source failure localization and backup path ranking (`correlate.py`).
- Automated OpenFlow backup path rerouting assistant (`reroute_helper.py`).
- Visual report generator (`report_generator.py`) producing Markdown, HTML, and Matplotlib latency charts.
- Unified command-line interface (`sdnscope.py`).
- Mock SDN controller (`mock_controller.py`) for offline demonstrations.
