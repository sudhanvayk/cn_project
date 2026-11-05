# Changelog

All notable changes to the **SDNScope** (Socket-Based Network Diagnostic and Path Analysis Tool for SDN) project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.2] - 2026-11-05

### Added
- **Kernel Qdisc Evidence Source:** `correlate.py` now parses `tc -s qdisc` counters (`parse_qdisc_stats`, `load_qdisc_stats`, `analyze_qdisc_deltas`). A positive drop delta maps to the owning Mininet link and scores it at $C = 0.95$. Exposed via `--qdisc-before` / `--qdisc-after` on `sdnscope correlate` and `sdnscope localize`, and included in the report as `qdisc_drop_delta`.
- **Live Wiring:** `topology/scenario_runner.py` passes the existing `tc_qdisc_before.txt` / `tc_qdisc_after.txt` captures into correlation, upgrading degraded-link localization from the 60% heuristic to a 95% direct measurement.
- **Tests:** Added `tests/test_qdisc_stats.py` covering raw/JSON parsing, delta attribution, noisy-OR combination, and end-to-end correlation on a degraded path.

### Fixed
- **Venv Bootstrap on Ubuntu 26.04:** `make install` now falls back to `python3 -m venv --without-pip` plus the system pip when `ensurepip` is unavailable (the `python3.14-venv` package is not installed by default).
- **Interactive Sudo:** `make real-check` and `make real-scenarios` prompt for credentials once when passwordless sudo is not configured, instead of failing immediately.
- **Live Setup Reproducibility:** Removed hardcoded `/home/sudh/Documents/cn_project` paths from `scenario_runner.py`, `scripts/capture_real_fixtures.py`, and `scripts/diagnose_trace.py`; all now derive the repository root from `__file__`.
- **Testbed Bootstrap:** Added `scripts/bootstrap_live_env.sh` (`sudo bash ...`) to install Mininet/Open vSwitch and run a pingall smoke test.
- **Ryu Discovery:** `scripts/run_ryu.sh` and `scripts/preflight_check.sh` fall back to `command -v ryu-manager` and fail with an actionable message instead of a hardcoded path. `run_ryu.sh` resolves the invoking user's home from `$SUDO_USER`, so `sudo python3 scripts/verify_live_cli.py` finds `~/ryu-env` instead of `/root/ryu-env`.
- **Live CLI Harness Fail-Fast:** `scripts/verify_live_cli.py` now aborts with the Ryu log tail if controller startup fails, verifies all three switches connected, confirms every flow rule installed and the baseline ping succeeded, and restores result ownership to the repository owner instead of a hardcoded user.
- **Result Ownership:** `scripts/run_all_scenarios.sh` now chowns results to `${SUDO_USER:-$(id -un)}` rather than a fixed username.

### Changed
- **Degraded Localization Documentation:** `docs/DESIGN.md`, `docs/EVIDENCE.md`, `FINAL_SUMMARY.md`, `README.md`, and `SETUP.md` now distinguish the archived 60% heuristic result from the 95% qdisc-based re-correlation of the same dataset.

---

## [1.1.1] - 2026-10-23

### Fixed
- **OpenFlow Forwarding Activation in Test Harnesses:** Changed `apply_changes: bool = True` in `reroute_helper.py` (`install_primary_flows`, `install_backup_flows`) so programmatically instantiated testbeds apply flows live, ensuring `h1` can reach `h2` and receive ICMP replies.
- **Trace Hop 1 Reachability:** Verified `sdnscope.py trace 10.0.0.2` receives ICMP Port Unreachable replies from `h2` at Hop 1 (0% loss, ~11.8 ms RTT); added system traceroute/tracepath fallback in `path_analysis.py` if raw socket times out.
- **Unit Testing:** Added unit tests in `tests/test_path_analysis.py` verifying Hop 1 reachable parsing and system utility fallbacks (71 total pytest tests passing).

### Changed
- **Degraded Scenario Evidence Transparency:** Explicitly classified the 60% confidence on `s1 <---> s2` in `correlate.py`, `docs/DESIGN.md`, and `docs/EVIDENCE.md` as a **path-membership heuristic fallback**, NOT a physical measurement. Documented raw values from `/stats/port` (`tx_dropped: 0`) and `tc -s qdisc show dev s1-eth2` (5 drops on s1-eth2, 8 drops on s2-eth2).

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
- Updated `README.md`, `SETUP.md`, `docs/DESIGN.md`, and `docs/schemas.md` with the single-source-of-truth Port & Address Map and genuine real-testbed measurements.

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
