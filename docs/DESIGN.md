# Architectural Design & Protocol Specification

## 1. Executive System Architecture

The **SDN Network Diagnostic and Path Analysis Suite** (SDNScope) is an active telemetry and diagnostic platform engineered specifically for Software-Defined Networks (SDNs). Unlike conventional network monitoring tools (such as `ping` or `traceroute`) that operate blindly across OpenFlow data planes, this tool bridges the gap between **socket-level active probe measurements** and **authoritative OpenFlow control plane state**.

```
+-----------------------------------------------------------------------------------+
|                                 APPLICATION LAYER                                 |
|                                                                                   |
|    +--------------------+    +--------------------+    +---------------------+    |
|    | diagnostic_client  |    |  flow_inspector    |    |     correlate       |    |
|    | (Active Probing)   |    |  (OF Flow Table)   |    | (Multi-Source Loc.) |    |
|    +---------+----------+    +---------+----------+    +----------+----------+    |
|              |                         |                          |               |
|              v                         v                          v               |
|    +-------------------------------------------------------------------------+    |
|    |                   UNIFIED CLI CONTROLLER: sdnscope.py                   |    |
|    +-------------------------------------------------------------------------+    |
+---------------------------------------+-------------------------------------------+
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

## 2. Active UDP Diagnostic Probe Protocol

### 2.1 Why UDP Over TCP?
1. **Zero Connection Overhead:** TCP requires a 3-way handshake (`SYN`, `SYN-ACK`, `ACK`), connection state maintenance, and teardown (`FIN`/`RST`). UDP transmits instantly without setup latency.
2. **Measurement Purity:** TCP implements end-to-end flow control, sliding window buffering, ACK coalescing, and congestion control (e.g. CUBIC, BBR). These algorithms mask individual packet drops via retransmissions and distort round-trip times via queue buffering. UDP probes reveal genuine raw network latency, microbursts, and unmasked loss rates.
3. **OpenFlow Match Fidelity:** OpenFlow switches match on IP protocol 17 (UDP) and specific UDP ports, allowing granular flow routing and flow-table tracking.

### 2.2 Wire Protocol Format
Probes are serialized as lightweight, version-tagged JSON payloads. Every packet contains:
- `magic`: Magic header string (`SDN_PROBE`) to immediately discard non-diagnostic background traffic.
- `version`: Protocol version string (`1.0`).
- `probe_id`: Unique UUID hex string identifying the individual probe.
- `seq`: Monotonically increasing sequence number (1, 2, ..., N).
- `send_time`: Client transmission timestamp recorded via `time.time()` with microsecond precision.
- `payload_pad`: Deterministic character buffer padding the frame to the user-configured `--size`.

### 2.3 Server Echo Behavior
The probe server (`probe_server.py`) operates as a multi-threaded UDP daemon:
1. Records server arrival timestamp: $T_{recv}$.
2. Inspects magic header and protocol version. Drops stray or malformed packets.
3. Implements artificial network simulation if requested:
   - `--drop-rate P`: Uniform random drop filter ($0.0 \le P \le 1.0$).
   - `--delay-ms D`: Injects artificial processing delay before echoing.
4. Records server departure timestamp: $T_{send}$.
5. Sends reply containing original client timestamp, sequence number, and server timestamps back to source address.

### 2.4 Mathematical Formulations for Metrics

#### Round-Trip Time (RTT)
$$\text{RTT} = (T_{client\_recv} - T_{client\_send}) \times 1000 \quad [\text{ms}]$$

#### Estimated One-Way Delay
$$\text{Delay}_{fwd} = (T_{server\_recv} - T_{client\_send}) \times 1000 \quad [\text{ms}]$$
$$\text{Delay}_{rev} = (T_{client\_recv} - T_{server\_send}) \times 1000 \quad [\text{ms}]$$
*(Note: Forward and reverse delays require sub-millisecond clock synchronization such as PTP/NTP; without synchronization, RTT remains the authoritative metric).*

#### Jitter Formulations
1. **Standard Deviation Jitter:**
   $$\sigma_{RTT} = \sqrt{\frac{1}{N - 1} \sum_{i=1}^N (\text{RTT}_i - \overline{\text{RTT}})^2}$$
2. **RFC 3550 Inter-Arrival Jitter (Smoothed Mean Absolute Difference):**
   $$D(i, i-1) = |\text{RTT}_i - \text{RTT}_{i-1}|$$
   $$J_i = J_{i-1} + \frac{D(i, i-1) - J_{i-1}}{16}$$
   *(The 1/16 smoothing filter conforms to RTP/RTCP RFC 3550 Section 6.4.1).*

#### 95th Percentile RTT (p95)
Computed via the nearest-rank method on sorted successful RTT samples:
$$n = \lceil 0.95 \times N \rceil$$
$$\text{p95} = \text{RTT}_{(n)}$$

---

## 3. Path Discovery: Control Plane vs. Data Plane

### 3.1 The OpenFlow Layer 2 Transparency Problem
In traditional IP networks, intermediate routers decrement the IPv4 Time-to-Live (`TTL`) field. Standard traceroute relies on receiving `ICMP Time Exceeded` messages from each router along the path.

In OpenFlow networks, switches typically forward packets at **Layer 2 (Ethernet switching)** without decrementing the IPv4 TTL field (unless an explicit `dec_ttl` OpenFlow action is configured). Consequently:
- Running standard `traceroute` inside Mininet shows **exactly 1 hop** (direct reachability to destination IP).
- `traceroute` is completely blind to intermediate OpenFlow switches (`s1`, `s2`, `s3`).

### 3.2 Flow-Table Path Reconstruction Algorithm (`flow_inspector.py`)
To discover the **actual forwarding path**, `FlowInspector` queries the SDN controller's OpenFlow flow tables:
1. Resolves source node (`h1`) and finds its access switch (`s1`) via topology mapping.
2. Sets `current_node = s1`.
3. While `current_node != destination`:
   - Queries OpenFlow flow table for `current_node` via `/stats/flow/<dpid>`.
   - Matches installed flow rules matching destination IP (`ipv4_dst`) or MAC (`eth_dst`), ranked by priority.
   - Extracts output port action (e.g. `OUTPUT:2`).
   - Looks up adjacent link connected to `(current_node, egress_port)` in `topology.json`.
   - Identifies `next_node` and appends to traversed path.
   - Updates `current_node = next_node`.
4. If flow entries are absent or controller is offline:
   - Gracefully falls back to shortest path in `SDNTopologyGraph`.
   - Labels result `path_source: "assumed_shortest"` and records exact `fallback_reason`.
   - When flow tables successfully trace the route, labels result `path_source: "flow_table"`.

---

## 4. Multi-Source Failure Localization Methodology

End-to-end packet loss only reveals that *some* node or link along the path is degraded or failed; it cannot pinpoint *where*. `correlate.py` implements a 3-tier evidence aggregation model:

### Evidence Source A: Switch Port Statistics Deltas
- Polls switch port counters (`/stats/port/<dpid>`) before and after probing.
- Computes deltas:
  $$\Delta \text{TX} = \text{TX}_{after} - \text{TX}_{before}$$
  $$\Delta \text{RX} = \text{RX}_{after} - \text{RX}_{before}$$
  $$\Delta \text{Drop} = \text{TX\_Drop}_{after} - \text{TX\_Drop}_{before}$$
- Link degradation is detected when:
  - $\Delta \text{Drop} > 0$ on switch egress port ($C = 0.85$).
  - Packets transmitted on link source port exceed received packets on destination port: $\Delta \text{TX}_{src} > \Delta \text{RX}_{dst}$ ($C = 0.75$).

### Evidence Source B: Per-Segment Probing
- When intermediate probe responders exist on intermediate hosts or switch attachments, sub-segments are measured.
- Identifies the first segment where loss spikes from nominal ($0\%$) to high ($>50\%$), or where latency jumps by $>40\text{ ms}$ ($C = 0.90$).

### Evidence Source C: Topology Liveness Diffing
- Compares the controller's active link inventory (`/v1.0/topology/links`) against the baseline topology graph.
- Any link present in the active path that is absent from controller active links is flagged as severed ($C = 1.0$).

### Combined Confidence Formulation
When multiple evidence sources independently implicate link $k$, their individual confidence scores $c_1, c_2, \dots, c_m$ are combined via weighted evidence scoring (independent multi-source evidence combination / noisy-OR model):
$$C_{\text{combined}}(k) = 1.0 - \prod_{i=1}^m (1.0 - c_i)$$
Where each source contributes an empirical detection weight $c_i \in (0, 1]$ (e.g., $1.0$ for topology link severance, $0.85$ for egress drop deltas, $0.75$ for TX/RX packet counter mismatch, $0.90$ for segment probe degradation).

---

## 5. Backup Path Re-ranking & Automated Failover

1. **Path Pruning:**
   All loop-free paths between source and destination are enumerated via Breadth-First Search (BFS) in `topology_graph.py`. Any candidate path containing a link whose suspect confidence $C \ge 0.50$ is flagged as `EXCLUDED_CORRUPT_LINK`.
2. **Hop Count Ranking:**
   Surviving paths (`VIABLE_BACKUP`) are ranked by hop count and hop delta (+hops relative to primary).
3. **Automated OpenFlow Failover (`reroute_helper.py`):**
   - Detects the branch switch where the backup route diverges from the primary route.
   - Determines the backup egress port connecting to the alternative switch.
   - Pushes an OpenFlow 1.3 flow modification rule (`priority=200`, higher than default `priority=100`) via `/stats/flowentry/add`:
     ```json
     {
       "dpid": 1,
       "priority": 200,
       "match": {"ipv4_dst": "10.0.0.2", "eth_type": 2048},
       "actions": [{"type": "OUTPUT", "port": 3}]
     }
     ```
   - Operates in safe dry-run mode by default; applies changes only when `--apply` is specified.
