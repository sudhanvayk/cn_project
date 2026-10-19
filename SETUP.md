# Environment Setup & Demonstration Guide

This document provides complete instructions for installing, configuring, and executing the **SDN Network Diagnostic and Path Analysis Suite** in both full Mininet SDN testbeds and lightweight offline/localhost environments.

---

## 1. System Requirements

- **Operating System:** Linux (Ubuntu 20.04 LTS, 22.04 LTS, or Debian 11/12 recommended)
- **Privileges:** `sudo` root privileges are required **only** if launching Mininet, modifying Linux `tc netem` queues, or running raw-socket traceroute.
- **Python Version:** Python 3.8 through 3.12.

---

## 2. Mininet & Open vSwitch Installation

To run hardware-emulated OpenFlow networks with real network namespaces:

```bash
# 1. Update system package index
sudo apt update

# 2. Install Mininet, Open vSwitch, and system network utilities
sudo apt install -y mininet openvswitch-switch iproute2 traceroute tracepath

# 3. Start and enable Open vSwitch daemon
sudo systemctl enable --now openvswitch-switch

# 4. Verify Mininet installation
sudo mn --test pingall
```

---

## 3. Ryu SDN Controller Setup & Python Compatibility

### Python Compatibility Note
The Ryu SDN Framework (`ryu`) was originally designed for Python 2.7 and Python 3.6–3.9. Under Python 3.10+, older upstream Ryu releases encounter incompatibilities with `collections.abc` and `eventlet`.

### Option A: Modern Virtual Environment (Recommended for Ubuntu 22.04/24.04)
The virtual environment in `.venv/` has been configured with compatible package pins:

```bash
# Activate existing workspace venv
source .venv/bin/activate

# Or install in fresh venv with modern eventlet/ryu compatibility:
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install ryu eventlet requests
```

### Option B: Dedicated Python 3.8/3.9 Environment (If using Ubuntu 20.04)
```bash
sudo apt install -y python3.9 python3.9-venv
python3.9 -m venv venv_ryu
source venv_ryu/bin/activate
pip install ryu requests
```

---

## 4. Running the Full SDN Testbed with Mininet & Ryu

### Step 1: Launch Ryu Controller
In **Terminal 1**, launch Ryu with both topology discovery and OpenFlow flow table REST APIs:
```bash
./scripts/run_ryu.sh
```
*Behind the scenes, this executes:*
```bash
ryu-manager ryu.app.rest_topology ryu.app.ofctl_rest ryu.app.simple_switch_13 --observe-links
```

### Step 2: Launch Mininet Diamond Topology
In **Terminal 2**, launch the multi-path diamond topology:
```bash
./scripts/run_topology.sh
```
*Mininet creates switches `s1`, `s2`, `s3` and hosts `h1` (10.0.0.1) and `h2` (10.0.0.2).*

### Step 3: Populate Controller MAC and Flow Tables
In the Mininet CLI:
```mininet
mininet> pingall
```

### Step 4: Start UDP Probe Echo Server on Host 2
In the Mininet CLI:
```mininet
mininet> h2 python3 probe_server.py --port 9999 &
```

### Step 5: Run Active Probing from Host 1
In the Mininet CLI:
```mininet
mininet> h1 python3 diagnostic_client.py 10.0.0.2 -p 9999 -c 10 -o diagnostic_result.json
```

### Step 6: Discover Topology and Correlate
In **Terminal 3** (Linux host terminal):
```bash
# Discover topology
python3 sdnscope.py topo -c ryu -i 127.0.0.1 -p 8080 -o topology.json

# Find all paths
python3 sdnscope.py paths -f topology.json -s h1 -d h2

# Correlate measurements and classify path health
python3 sdnscope.py correlate -d diagnostic_result.json -t topology.json -s h1
```

---

## 5. Demonstrating Degradation & Failure Scenarios in Mininet

### Scenario B: Degraded / Congested Primary Path
Inject 60ms delay and 10% packet drop on interface `s1-eth2` (the primary link):
```bash
# In Linux host terminal:
sudo tc qdisc add dev s1-eth2 root netem delay 60ms loss 10%

# In Mininet CLI, re-run diagnostics:
mininet> h1 python3 diagnostic_client.py 10.0.0.2 -p 9999 -c 10 -o diagnostic_result.json

# In Linux host terminal:
python3 sdnscope.py correlate -d diagnostic_result.json -t topology.json -s h1
# Result: [▲ DEGRADED] DEGRADED_PATH (latency & packet loss thresholds exceeded)

# Clean up delay:
sudo tc qdisc del dev s1-eth2 root
```

### Scenario C: Failed Primary Link & Failover Rerouting
Take down the primary link `s1-s2`:
```mininet
# In Mininet CLI:
mininet> link s1 s2 down

# In Mininet CLI, re-run diagnostics:
mininet> h1 python3 diagnostic_client.py 10.0.0.2 -p 9999 -c 5 -o diagnostic_result.json

# In Linux host terminal:
python3 sdnscope.py correlate -d diagnostic_result.json -t topology.json -s h1 -o correlation_report.json
# Result: [✖ FAILED] FAILED_PATH (100% loss)
# Suspected Link: s1 <---> s2 (confidence: 100%)
# Recommended Backup Route: h1 -> s1 -> s3 -> s2 -> h2 (+1 extra hop)

# Deploy backup flow rules:
python3 sdnscope.py reroute -r correlation_report.json --apply
```

---

## 6. Standalone Localhost / Mock Mode (No Root / No Mininet Required)

For environments without root permissions, kernel Open vSwitch, or Mininet (such as automated grading environments, Docker containers, or laptops):

```bash
# Run the complete automated demo in one command:
./scripts/demo_localhost.sh

# Or run all 3 scenarios (healthy, degraded, failed) automatically:
./scripts/run_all_scenarios.sh
```

All JSON telemetry, Markdown reports (`report.md`), HTML reports (`report.html`), and latency time-series charts (`rtt_timeseries.png`) are saved in `results/`.
