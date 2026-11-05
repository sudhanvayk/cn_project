# Environment Setup & Demonstration Guide

This document provides complete instructions for installing, configuring, and executing the **SDN Network Diagnostic and Path Analysis Suite (SDNScope)** on a real Mininet + Ryu testbed and in offline verification environments.

---

## 1. Port & Address Map (Single Source of Truth)

All modules, scripts, and documentation adhere to this single source of truth:

### Control Plane & Services
| Component / Service | Protocol | Host / Interface | Port | Notes |
|---|---|---|---|---|
| **Ryu REST API** | HTTP (REST) | `127.0.0.1` | **TCP 8080** | `/v1.0/topology/*`, `/stats/*` |
| **OpenFlow Controller** | OpenFlow 1.3 | `127.0.0.1` | **TCP 6653** | Ryu default listen port |
| **OpenDaylight (Doc)** | RESTCONF | `127.0.0.1` | **TCP 8181** | Supported format parser |
| **UDP Diagnostic Probe** | UDP | `0.0.0.0` / `10.0.0.2` | **UDP 9999** | Handled by `probe_server.py` on `h2` |

### Data Plane (Mininet Diamond Topology, OpenFlow 1.3)
| Entity | Name | DPID / IP / MAC | Connected Port Wiring | TCLink Parameters |
|---|---|---|---|---|
| **Host 1** | `h1` | IP: `10.0.0.1/24`, MAC: `00:00:00:00:00:01` | `h1-eth0` <-> `s1-eth1` | 100 Mbit/s, 1 ms delay |
| **Host 2** | `h2` | IP: `10.0.0.2/24`, MAC: `00:00:00:00:00:02` | `h2-eth0` <-> `s2-eth1` | 100 Mbit/s, 1 ms delay |
| **Switch 1** | `s1` | DPID: `1` (`0000000000000001`) | Port 1: `h1`, Port 2: `s2`, Port 3: `s3` | Inter-switch: 10 Mbit/s, 2 ms |
| **Switch 2** | `s2` | DPID: `2` (`0000000000000002`) | Port 1: `h2`, Port 2: `s1`, Port 3: `s3` | Inter-switch: 10 Mbit/s, 2 ms |
| **Switch 3** | `s3` | DPID: `3` (`0000000000000003`) | Port 1: `s1`, Port 2: `s2` | Inter-switch: 10 Mbit/s, 2 ms |

### Forwarding Paths & Latency Physics
- **Primary Path:** `h1 -> s1(in 1, out 2) -> s2(in 2, out 1) -> h2` (3 hops).  
  Theoretical one-way delay: $1\text{ ms} + 2\text{ ms} + 1\text{ ms} = 4\text{ ms}$.  
  Theoretical round-trip delay: $8\text{ ms}$.  
  Expected baseline measured RTT: **6 to 20 ms** (accommodating socket and kernel qdisc processing).
- **Backup Path:** `h1 -> s1(in 1, out 3) -> s3(in 1, out 2) -> s2(in 3, out 1) -> h2` (4 hops).  
  Theoretical one-way delay: $1\text{ ms} + 2\text{ ms} + 2\text{ ms} + 1\text{ ms} = 6\text{ ms}$.  
  Theoretical round-trip delay: $12\text{ ms}$.  
  Expected backup measured RTT: **10 to 25 ms**.

---

## 2. Python Environment Architecture

To avoid dependency conflicts between modern Python 3.12 (standard on Ubuntu 24.04) and legacy Ryu packages, the testbed strictly isolates two environments:

```
+-------------------------------------------------------------------------------+
|                               UBUNTU HOST SYSTEM                              |
|                                                                               |
|  +-------------------------------------+   +-------------------------------+  |
|  |     Project Venv (.venv)            |   |     Ryu Venv (~/ryu-env)      |  |
|  |     Python 3.12                     |   |     Python 3.9 (via uv)       |  |
|  |-------------------------------------|   |-------------------------------|  |
|  |  • SDNScope Diagnostic CLI          |   |  • ryu-manager 4.34           |  |
|  |  • Requests, Matplotlib             |   |  • ryu.app.rest_topology      |  |
|  |  • Pytest, Ruff                     |   |  • ryu.app.ofctl_rest         |  |
|  |  • Topology & Graph Analysis        |   |  • Eventlet 0.30.2            |  |
|  +-------------------------------------+   +-------------------------------+  |
+-------------------------------------------------------------------------------+
```

> [!CAUTION]
> NEVER modify files in `site-packages` or attempt to install `ryu` inside the project's Python 3.12 `.venv`. Ryu 4.34 requires Python 3.9 and specific eventlet pins.

### Recipe 1: Project Environment (.venv - Python 3.12)
```bash
cd cn_project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov ruff
```

### Recipe 2: Ryu SDN Controller Environment (~/ryu-env - Python 3.9)
Using `uv` to manage the isolated Python 3.9 runtime:
```bash
# 1. Create Python 3.9 virtual environment
uv venv --python 3.9 ~/ryu-env

# 2. Activate and install required build dependencies
source ~/ryu-env/bin/activate
uv pip install "setuptools==57.5.0" wheel "eventlet==0.30.2"

# 3. Install Ryu pinned to 4.34 without build isolation
uv pip install --no-build-isolation "ryu==4.34"

# 4. Verify installation
~/ryu-env/bin/ryu-manager --version
# Expected output: ryu-manager 4.34
```

> [!WARNING]
> Without the explicit `==4.34` pin, dependency resolvers will select an incompatible broken legacy release (`ryu 2.2`). `os-ken` cannot be substituted because it lacks the required `rest_topology` application.

---

## 3. Mininet & Open vSwitch Installation

One-shot bootstrap (installs packages, enables OVS, runs a pingall smoke test):

```bash
sudo bash scripts/bootstrap_live_env.sh
```

Or manually:

```bash
# 1. Install Mininet, Open vSwitch, and system utilities
sudo apt update
sudo apt install -y mininet openvswitch-switch iproute2 traceroute python3-venv

# 2. Start and enable Open vSwitch service
sudo systemctl enable --now openvswitch-switch

# 3. Verify Open vSwitch and Mininet operation
sudo mn --test pingall
```

> [!NOTE]
> `make real-check` and `make real-scenarios` prompt for your sudo password once if passwordless sudo is not configured. If `python3 -m venv` fails with "ensurepip is not available", `make install` automatically falls back to `venv --without-pip` plus the system pip. Installing `python3-venv` (done above) also resolves it.

---

## 4. Starting the Ryu Controller

Launch Ryu with link discovery and OpenFlow 1.3 flow inspection REST modules:

```bash
# Using the automated wrapper (recommended):
./scripts/run_ryu.sh start

# Or manually:
~/ryu-env/bin/ryu-manager --observe-links ryu.app.rest_topology ryu.app.ofctl_rest
```

> [!CRITICAL]
> **DO NOT** load `ryu.app.simple_switch_13` or any MAC-learning switch!  
> The diamond topology contains physical cycles (`s1-s2`, `s1-s3`, `s3-s2`). Standard learning switches flood broadcast frames (ARP) along loops, triggering immediate broadcast storms that freeze the kernel and VM. All forwarding in SDNScope is governed by deterministic, static OpenFlow rules installed via REST API.

To verify Ryu is running and healthy:
```bash
./scripts/run_ryu.sh status
curl -s http://127.0.0.1:8080/v1.0/topology/switches
```

To stop Ryu cleanly:
```bash
./scripts/run_ryu.sh stop
```

---

## 5. Flow Management & Host Discovery Architecture

### Static Flow Injection
Because MAC-learning switches are omitted, flow entries are installed via Ryu's `/stats/flowentry/add` REST endpoint:
- **Primary Flows (Priority 100):** Forward traffic along `h1 <-> s1 <-> s2 <-> h2`.
  ```bash
  ./scripts/install_primary_flows.sh --apply
  ```
- **Backup Flows (Priority 200):** Forward traffic along `h1 <-> s1 <-> s3 <-> s2 <-> h2`.
  ```bash
  ./scripts/install_backup_flows.sh --apply
  ```

### Host Discovery Caveat
In an SDN network with static flow tables and no learning switch, OpenFlow switches process packets entirely in the datapath without dispatching `OFPT_PACKET_IN` messages to the controller. Consequently, Ryu's `/v1.0/topology/hosts` endpoint remains empty.

SDNScope addresses this transparently:
1. The Mininet orchestrator emits an authoritative `hosts.json` mapping host names, MACs, IPs, and attachment switch ports.
2. `sdn_topology.py` merges this file via `--hosts-file`, tagging host records with `host_source: "hosts_file"` (or `host_source: "controller"` when packet-in records exist).
3. Switch and link discovery continue to originate natively from live controller REST endpoints (`/v1.0/topology/switches` and `/links`).

---

## 6. Running the Real Scenario Test Suite

The automated suite runs all 4 real network scenarios end-to-end on the live Mininet + Ryu testbed:

```bash
# Run all scenarios with one command (requires sudo for Mininet):
./scripts/run_all_scenarios.sh
```

### Scenario Execution Flow
1. **Healthy:** Validates nominal RTT (13.24 ms, 0% loss) along primary route `h1 -> s1 -> s2 -> h2`.
2. **Degraded:** Injects kernel `netem` delay (+30 ms) and loss (5%) on `s1-eth2` and `s2-eth2`, producing 10% loss and 73.32 ms RTT. Captures `tc -s qdisc` before/after probing and localizes `s1 <---> s2` at **95% confidence** from the qdisc drop delta (60% path-membership heuristic only if qdisc telemetry is unavailable).
3. **Failed:** Simulates physical link severance (`link s1 s2 down`), producing 100% loss. Correlates OVS port drops with controller topology withdrawal (100% confidence).
4. **Recovery:** Deploys bidirectional OpenFlow rules along backup route `h1 -> s1 -> s3 -> s2 -> h2` at priority 200. Probes confirm full recovery (19.94 ms RTT, 0% loss).

All artifacts, JSON telemetry, Markdown reports (`report.md`), HTML reports (`report.html`), and latency time-series charts (`rtt_timeseries.png`) are stored in `results/real_<timestamp>/` and symlinked to `results/latest/`.

---

## 7. Exercising Live CLI Subcommands

> [!TIP]
> `sudo python3 scripts/verify_live_cli.py` runs every subcommand below in one shot
> (it starts Ryu itself, bounces `s1 <-> s2` during `watch`, and stops cleanly). It now
> aborts with the Ryu log tail if the controller or flows fail to come up.

With Ryu and Mininet active, run SDNScope CLI commands:

```bash
# 1. Discover live SDN topology
.venv/bin/python sdnscope.py topo -c ryu -i 127.0.0.1 -p 8080 --hosts-file results/latest/healthy/hosts.json

# 2. Compare paths between endpoints
.venv/bin/python sdnscope.py paths -s h1 -d h2 -f results/latest/healthy/topology.json

# 3. Analyze network path hops
# Note: Executed inside h1 namespace; OpenFlow L2 switches bridge without TTL decrement
sudo ip netns exec mn.h1 .venv/bin/python sdnscope.py trace 10.0.0.2

# 4. Watch live topology events (bounces, link up/down)
.venv/bin/python sdnscope.py watch -c ryu -i 127.0.0.1 -p 8080 --interval 1

# 5. Generate Markdown and HTML visual reports
.venv/bin/python sdnscope.py report \
  -r results/latest/degraded/correlation_report.json \
  -d results/latest/degraded/diagnostic_result.json \
  -m results/latest/degraded/report.md \
  -H results/latest/degraded/report.html \
  --dir results/latest/degraded
```
