# Socket-Based Network Diagnostic and Path Analysis Tool for SDN

A comprehensive, modular Python 3 networking and diagnostics tool designed for Software-Defined Networking (SDN) environments. The framework integrates active socket-based UDP probes, traceroute hop inspection, and SDN controller REST topology discovery (Ryu and OpenDaylight) to measure performance metrics (RTT, jitter, packet loss), classify path health, diagnose network degradation and failures, and discover and rank alternative forwarding paths.

---

## 1. Problem Statement

In Software-Defined Networks (SDN), network control logic is decoupled from data-plane forwarding hardware. Although the centralized SDN controller maintains a global view of switch connections and flow tables, physical network conditions such as link degradation, traffic congestion, packet loss, and link flaps often degrade quality of service (QoS) before control-plane timeouts or OpenFlow port-status notifications trigger reactive rerouting.

Traditional diagnostic utilities (such as standard ICMP ping and traceroute) operate independently of SDN control plane intelligence and do not correlate end-to-end socket telemetry with underlying SDN topologies or alternative path availability. Network operators and students require a lightweight, programmatic diagnostic framework that:
1. Actively measures real-time data-plane latency (RTT), jitter, and packet loss using custom UDP socket probes.
2. Directly interrogates SDN controllers via REST APIs to discover active nodes, links, and hosts.
3. Automatically correlates performance measurements with SDN topology graphs.
4. Identifies failed or degraded forwarding paths and computes ranked alternative routes for intelligent traffic rerouting.

---

## 2. Objectives

- **High-Precision Data-Plane Probing:** Implement a low-overhead UDP echo server and client to gather millisecond-accurate RTT, jitter (standard deviation of RTT), and packet loss statistics.
- **Path Hop Tracing:** Incorporate hop-by-hop path analysis using standard system utilities (`traceroute`/`tracepath`) with graceful error handling and structured JSON output.
- **Multi-Controller Topology Discovery:** Support northbound REST APIs for both Ryu (`/v1.0/topology/*`) and OpenDaylight (`RESTCONF operational network-topology`) into a standardized common nodes-and-links format.
- **Graph Modeling & Path Finding:** Construct an in-memory graph of the SDN fabric to identify all loop-free simple paths between hosts using Breadth-First Search (BFS).
- **Automated Health Classification & Failure Diagnosis:** Classify paths into `HEALTHY_PATH`, `DEGRADED_PATH`, and `FAILED_PATH` based on configurable latency and packet loss thresholds.
- **Alternative Path Comparison:** Identify the selected shortest route and evaluate all available alternative backup routes ranked by hop count and cost penalty.

---

## 3. System Architecture Diagram

```
+-------------------------------------------------------------------------------+
|                             SDN CONTROL PLANE                                 |
|                                                                               |
|   +--------------------------+             +------------------------------+   |
|   |      Ryu Controller      |             |     OpenDaylight (ODL)       |   |
|   |  (rest_topology: 8080)   |     OR      |      (RESTCONF: 8181)        |   |
|   +-------------+------------+             +--------------+---------------+   |
+-----------------|-----------------------------------------|-------------------+
                  |                                         |
                  | Northbound REST APIs                    |
                  v                                         v
+-------------------------------------------------------------------------------+
|                       DIAGNOSTIC & CORRELATION ENGINE                         |
|                                                                               |
|   +-----------------------+              +--------------------------------+   |
|   |    sdn_topology.py    | ------------>|       topology_graph.py        |   |
|   |  (REST Discovery)     |              |  - Undirected Graph            |   |
|   +-----------------------+              |  - BFS Simple Path Discovery   |   |
|               |                          |  - Hop-Count Ranking Engine    |   |
|               v                          +----------------+---------------+   |
|        [topology.json]                                    |                   |
|                                                           v                   |
|                                              +----------------------------+   |
|   +-----------------------+                  |        correlate.py        |   |
|   | diagnostic_client.py  | ------------->   |  - Health Classification   |   |
|   | (UDP Probes & Stats)  |                  |    (HEALTHY/DEGRADED/FAIL) |   |
|   +-----------+-----------+                  |  - Root-Cause Diagnostics  |   |
|               |                              |  - Failover Route Ranking  |   |
|               v                              +--------------+-------------+   |
|     [diagnostic_result.json]                                |                 |
|                                                             v                 |
|                                                 [correlation_report.json]     |
+-------------------------------------------------------------|-----------------+
                                                              |
                                                              v
+-------------------------------------------------------------------------------+
|                             SDN DATA PLANE                                    |
|                                                                               |
|     [ Host 1 (Client) ]                                                       |
|       diagnostic_client.py                                                    |
|              |                                                                |
|       +------v------+                 +-------------+                         |
|       |  Switch s1  |=================|  Switch s3  | (Alternative Path)      |
|       +------+------+                 +------+------+                         |
|              | (Primary Path)                |                                |
|       +------v------+                        |                                |
|       |  Switch s2  |========================+                                |
|       +------+------+                                                         |
|              |                                                                |
|     [ Host 2 (Server) ]                                                       |
|       probe_server.py                                                         |
|                                                                               |
+-------------------------------------------------------------------------------+
```

---

## 4. Folder Structure

```
cn_project/
├── .gitignore              # Git ignore rules for Python caches and temp files
├── README.md               # Complete project documentation and guide
├── requirements.txt        # Python dependency manifest (requests)
├── config.json             # Global parameters and diagnostic thresholds
├── probe_server.py         # UDP diagnostic probe echo server
├── diagnostic_client.py    # UDP active probing and statistical RTT client
├── path_analysis.py        # Traceroute/tracepath path discovery module
├── sdn_topology.py         # Ryu & OpenDaylight REST topology discovery
├── topology_graph.py       # Graph model, BFS path-finder, and ranking engine
└── correlate.py            # Diagnostic-to-topology correlation & failure detector
```

---

## 5. Installation Instructions

### Prerequisites
- Linux (Ubuntu 20.04/22.04 LTS recommended) or macOS
- Python 3.8+
- Mininet (for SDN emulation)
- Ryu SDN Framework or OpenDaylight Controller

### Setup Steps
1. Clone or extract the repository:
   ```bash
   cd ~/Documents/cn_project
   ```

2. Create and activate a Python virtual environment (optional but recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```

4. Verify that `traceroute` or `tracepath` is installed:
   ```bash
   which traceroute || sudo apt update && sudo apt install -y traceroute
   ```

---

## 6. Configuration (`config.json`)

The tool reads global defaults from `config.json`. These parameters can be customized without modifying code:

```json
{
  "udp_port": 9999,
  "probe_count": 10,
  "timeout": 2.0,
  "payload_size": 64,
  "sdn_controller_type": "ryu",
  "controller_ip": "127.0.0.1",
  "ryu_port": 8080,
  "opendaylight_port": 8181,
  "username": "admin",
  "password": "adminpassword",
  "thresholds": {
    "degraded_rtt_ms": 50.0,
    "degraded_packet_loss_percent": 0.0,
    "failed_packet_loss_percent": 50.0
  }
}
```

- `udp_port`: Listening port for `probe_server.py`.
- `probe_count`: Number of UDP probes per test session.
- `timeout`: Socket timeout in seconds per probe.
- `payload_size`: Probe payload size in bytes.
- `thresholds`:
  - `degraded_rtt_ms`: Average latency threshold above which a path is marked degraded.
  - `degraded_packet_loss_percent`: Loss threshold above which a path is marked degraded (>0%).
  - `failed_packet_loss_percent`: Loss threshold marking complete path failure (>=50%).

---

## 7. Execution Guide

### 7.1 Running `probe_server.py`
Starts the UDP echo server on the target host (e.g., Host 2).

```bash
# Listen on default port (9999) on all interfaces
python3 probe_server.py

# Listen on custom port and interface
python3 probe_server.py --port 9999 --bind 0.0.0.0
```

### 7.2 Running `diagnostic_client.py`
Sends UDP probes to the target host and records RTT and packet loss.

```bash
# Probe destination IP with default settings
python3 diagnostic_client.py 10.0.0.2

# Custom probe count, timeout, port, and output file
python3 diagnostic_client.py 10.0.0.2 -p 9999 -c 10 --timeout 1.5 -o diagnostic_result.json
```

### 7.3 Running `path_analysis.py`
Executes hop-by-hop path discovery using `traceroute`/`tracepath`.

```bash
# Trace path to destination host
python3 path_analysis.py 10.0.0.2

# Set maximum hops (TTL) and save JSON
python3 path_analysis.py 10.0.0.2 -m 15 -o path_trace.json
```

### 7.4 Running `sdn_topology.py`
Connects to the SDN controller REST API and generates `topology.json`.

```bash
# Query Ryu controller running locally on port 8080
python3 sdn_topology.py --controller ryu --ip 127.0.0.1 --port 8080 -o topology.json

# Query OpenDaylight controller running on port 8181 with credentials
python3 sdn_topology.py --controller opendaylight --ip 127.0.0.1 --port 8181 -u admin -P adminpassword -o topology.json
```

### 7.5 Running `topology_graph.py`
Inspects candidate routes between two nodes in the topology.

```bash
# Find all simple paths between h1 and h2
python3 topology_graph.py -f topology.json -s h1 -d h2

# Query by IP address
python3 topology_graph.py -f topology.json -s 10.0.0.1 -d 10.0.0.2 -m 5
```

### 7.6 Running `correlate.py`
Correlates measurement metrics with the SDN topology to detect failures and rank alternative paths.

```bash
# Run correlation engine
python3 correlate.py -d diagnostic_result.json -t topology.json -s h1 -o correlation_report.json
```

---

## 8. Mininet & Ryu Setup Commands

### Step 1: Start Ryu Controller with Topology REST API
In terminal 1:
```bash
ryu-manager ryu.app.rest_topology ryu.app.simple_switch_13
```

### Step 2: Launch Mininet with Triangular / Multi-Path Topology
In terminal 2, start Mininet with 3 switches forming a triangle (offering redundant paths between h1 and h2):
```bash
sudo mn --controller=remote,ip=127.0.0.1,port=6633 --topo=triangle \
  --custom - << 'EOF'
from mininet.topo import Topo

class TriangleTopo(Topo):
    def build(self):
        # 3 Switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')

        # 2 Hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')

        # Host links
        self.addLink(h1, s1)
        self.addLink(h2, s2)

        # Inter-switch links forming triangle
        self.addLink(s1, s2)  # Primary route (1 hop between switches)
        self.addLink(s1, s3)  # Alternate leg 1
        self.addLink(s3, s2)  # Alternate leg 2
topos = {'triangle': (lambda: TriangleTopo())}
EOF
```

### Step 3: Populate ARP & Controller MAC Tables
In the Mininet CLI:
```mininet
mininet> pingall
```

---

## 9. Demonstrating Healthy, Congested, and Failed Paths

### Scenario A: Healthy Path Demonstration
1. On `h2` in Mininet, start `probe_server.py`:
   ```mininet
   mininet> h2 python3 probe_server.py &
   ```
2. On `h1`, run the diagnostic client:
   ```mininet
   mininet> h1 python3 diagnostic_client.py 10.0.0.2 -o diagnostic_result.json
   ```
3. Fetch topology:
   ```bash
   python3 sdn_topology.py --controller ryu -o topology.json
   ```
4. Correlate:
   ```bash
   python3 correlate.py -d diagnostic_result.json -t topology.json -s h1
   ```
   **Result:** `[✔ HEALTHY] PATH STATUS: HEALTHY_PATH` (0.00% packet loss, ~1-2 ms latency).

---

### Scenario B: Degraded / Congested Path Demonstration
Simulate queue delay or congestion on link `s1-s2` using Linux Traffic Control (`tc`):
1. In Linux host terminal, inject 60ms delay and 10% packet loss on `s1-eth2`:
   ```bash
   sudo tc qdisc add dev s1-eth2 root netem delay 60ms loss 10%
   ```
2. On `h1` in Mininet, rerun diagnostics:
   ```mininet
   mininet> h1 python3 diagnostic_client.py 10.0.0.2 -c 10 -o diagnostic_result.json
   ```
3. Run correlation:
   ```bash
   python3 correlate.py -d diagnostic_result.json -t topology.json -s h1
   ```
   **Result:** `[▲ DEGRADED] PATH STATUS: DEGRADED_PATH`
   - *Reason:* Packet loss of 10.00% detected and mean RTT (68.4 ms) exceeds latency limit (50.0 ms).
   - *Recommendation:* Failover to Alternative Path #2 (`h1 -> s1 -> s3 -> s2 -> h2`).
4. Clean up the simulated delay:
   ```bash
   sudo tc qdisc del dev s1-eth2 root
   ```

---

### Scenario C: Failed Path Demonstration
Simulate an outright link failure on the primary link `s1-s2`:
1. In Mininet CLI, take down the primary link:
   ```mininet
   mininet> link s1 s2 down
   ```
2. On `h1`, run the client:
   ```mininet
   mininet> h1 python3 diagnostic_client.py 10.0.0.2 -c 5 --timeout 1.0 -o diagnostic_result.json
   ```
3. Run correlation:
   ```bash
   python3 correlate.py -d diagnostic_result.json -t topology.json -s h1
   ```
   **Result:** `[✖ FAILED] PATH STATUS: FAILED_PATH`
   - *Reason:* Severe packet loss (100.00%) meets or exceeds failure threshold (50.0%).
   - *Action:* Primary route is down. SDN Controller instructed to route traffic over Alternative Path (`h1 -> s1 -> s3 -> s2 -> h2`) (+1 hop penalty).

---

## 10. Concepts & Metric Explanations

| Metric / Concept | Definition & SDN Context |
|---|---|
| **Round-Trip Time (RTT)** | Total elapsed time from sending a UDP probe packet to receiving the server's reply. Indicates propagation, queuing, and processing delay across SDN switches. |
| **Packet Loss** | Percentage of sent UDP probes that fail to elicit a reply before socket timeout. Indicates buffer overflows, traffic drops, or physical link disconnection. |
| **Jitter (StdDev)** | Standard deviation of probe RTT measurements. Measures packet delay variation caused by fluctuating switch queue lengths and traffic bursts. |
| **Path Correlation** | Mapping data-plane probe measurements (IP-level) to the underlying SDN topology graph (OpenFlow switches, ports, and links) discovered via controller REST APIs. |
| **Failed-Path Detection** | Identifying unviable paths when packet loss reaches or exceeds critical thresholds (default: >= 50%). |
| **Alternative-Path Comparison** | Ranking redundant paths through the SDN fabric by hop count and cost penalty (+extra hops) to recommend optimal failover paths. |

---

## 11. Sample JSON Outputs

### Diagnostic Client Output (`diagnostic_result.json`)
```json
{
  "timestamp": "2026-10-15T22:35:30Z",
  "target_ip": "10.0.0.2",
  "destination_port": 9999,
  "probe_count": 5,
  "timeout_seconds": 2.0,
  "payload_size_bytes": 64,
  "summary": {
    "sent": 5,
    "received": 5,
    "lost": 0,
    "packet_loss_percent": 0.0,
    "min_rtt_ms": 1.15,
    "max_rtt_ms": 1.84,
    "mean_rtt_ms": 1.42,
    "median_rtt_ms": 1.38,
    "stddev_rtt_ms": 0.26
  },
  "probes": [
    {
      "probe_id": 1,
      "send_time": 1792083850.12,
      "status": "SUCCESS",
      "rtt_ms": 1.42,
      "recv_time": 1792083850.12142
    }
  ]
}
```

### Discovered Topology Output (`topology.json`)
```json
{
  "controller_type": "ryu",
  "controller_url": "http://127.0.0.1:8080",
  "discovered_at": "2026-10-15T22:40:00Z",
  "nodes": [
    {"id": "s1", "type": "switch", "dpid": "0000000000000001"},
    {"id": "s2", "type": "switch", "dpid": "0000000000000002"},
    {"id": "s3", "type": "switch", "dpid": "0000000000000003"},
    {"id": "h1", "type": "host", "ip": "10.0.0.1", "connected_to": "s1"},
    {"id": "h2", "type": "host", "ip": "10.0.0.2", "connected_to": "s2"}
  ],
  "links": [
    {"source": "h1", "destination": "s1", "type": "host-to-switch"},
    {"source": "s1", "destination": "s2", "type": "switch-to-switch"},
    {"source": "s1", "destination": "s3", "type": "switch-to-switch"},
    {"source": "s3", "destination": "s2", "type": "switch-to-switch"},
    {"source": "h2", "destination": "s2", "type": "host-to-switch"}
  ]
}
```

### Correlation & Failure Diagnosis Output (`correlation_report.json`)
```json
{
  "timestamp": "2026-10-15T22:45:00Z",
  "path_status": "DEGRADED_PATH",
  "source_node": "h1",
  "destination_node": "h2",
  "destination_ip": "10.0.0.2",
  "candidate_paths": [
    ["h1", "s1", "s2", "h2"],
    ["h1", "s1", "s3", "s2", "h2"]
  ],
  "selected_shortest_path": {
    "path": ["h1", "s1", "s2", "h2"],
    "path_str": "h1 -> s1 -> s2 -> h2",
    "hop_count": 3
  },
  "failed_path_reason": "Path degradation detected: packet loss of 10.00% detected and mean RTT (68.40 ms) exceeds latency limit (50.00 ms).",
  "packet_loss_percentage": 10.0,
  "mean_rtt": 68.4,
  "alternative_paths": [
    {
      "rank": 2,
      "path": ["h1", "s1", "s3", "s2", "h2"],
      "path_str": "h1 -> s1 -> s3 -> s2 -> h2",
      "hop_count": 4,
      "extra_hops": 1
    }
  ],
  "path_comparison": [
    {
      "rank": 1,
      "role": "SELECTED_SHORTEST",
      "path": ["h1", "s1", "s2", "h2"],
      "path_str": "h1 -> s1 -> s2 -> h2",
      "hop_count": 3,
      "extra_hops": 0
    },
    {
      "rank": 2,
      "role": "ALTERNATIVE",
      "path": ["h1", "s1", "s3", "s2", "h2"],
      "path_str": "h1 -> s1 -> s3 -> s2 -> h2",
      "hop_count": 4,
      "extra_hops": 1
    }
  ]
}
```

---

## 12. Troubleshooting & FAQ

- **`traceroute` command not found:** Install traceroute with `sudo apt install traceroute` or allow the module to fall back to `tracepath`.
- **Ryu connection refused:** Ensure Ryu is started with `rest_topology` enabled: `ryu-manager ryu.app.rest_topology ryu.app.simple_switch_13`.
- **OpenDaylight 401 Unauthorized:** Verify username and password in `config.json` (defaults: `admin`/`adminpassword`).
- **No paths discovered in graph:** Verify that host IPs in Mininet match the IPs discovered by the controller, or test connectivity with `pingall` first.
