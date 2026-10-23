# Examiner Viva & Technical Interview Guide

This guide contains 20 comprehensive examiner questions and concise, technically authoritative answers covering protocol design, SDN theory, queuing metrics, and failure localization.

---

### Q1: Why is UDP chosen over TCP for diagnostic probing and delay measurements?
**Answer:**
1. **No Handshake Overhead:** TCP requires a 3-way handshake (`SYN`, `SYN-ACK`, `ACK`), connection state allocation, and teardown. UDP transmits instantaneously with zero state setup.
2. **True Network Telemetry:** TCP incorporates sliding window flow control, retransmission timers, and congestion control (CUBIC/BBR). When packets drop, TCP hides the loss from the application by retransmitting, while delay is inflated by bufferbloat. UDP probes expose the genuine raw data plane performance (unmasked packet drop rate, raw queueing latency, and microbursts).
3. **OpenFlow Granularity:** OpenFlow switches can match directly on IP protocol 17 (UDP) and destination ports without TCP sequence tracking.

---

### Q2: What is the mathematical difference between Standard Deviation Jitter and RFC 3550 Jitter?
**Answer:**
- **Standard Deviation Jitter ($\sigma_{RTT}$):** Measures the global dispersion of all round-trip times around the statistical sample mean:
  $$\sigma_{RTT} = \sqrt{\frac{1}{N - 1} \sum_{i=1}^N (\text{RTT}_i - \mu)^2}$$
- **RFC 3550 Inter-Arrival Jitter ($J$):** Measures the smoothed, short-term variation between consecutive packets, matching human perception of latency fluctuations in real-time RTP/VoIP media streams:
  $$D(i, i-1) = |\text{RTT}_i - \text{RTT}_{i-1}|$$
  $$J_i = J_{i-1} + \frac{D(i, i-1) - J_{i-1}}{16}$$
Our client reports both metrics for comprehensive statistical analysis.

---

### Q3: Why does standard traceroute report only 1 hop when running across OpenFlow switches in Mininet?
**Answer:**
Standard traceroute relies on Layer 3 IP routers decrementing the IPv4 Time-to-Live (`TTL`) header and returning an `ICMP Type 11 (Time Exceeded)` packet when TTL drops to 0.

OpenFlow switches in Mininet forward packets primarily as Layer 2 Ethernet learning bridges. Because L2 bridges forward based on MAC/VLAN headers without modifying the IP payload, the IPv4 TTL field is **not decremented** (unless an explicit OpenFlow action `dec_ttl` is installed in the flow table). Consequently, the packet reaches the target host with its original TTL intact, making the entire OpenFlow multi-switch fabric appear as a single transparent Layer 2 hop.

---

### Q4: How does `flow_inspector.py` reconstruct the authoritative forwarding path?
**Answer:**
Instead of relying on IP TTL hops, `FlowInspector` queries the SDN controller via northbound REST APIs:
1. Maps source node (`h1`) to its ingress switch (`s1`) via the topology graph.
2. Queries the switch's active flow table (`/stats/flow/<dpid>`).
3. Evaluates flow entries against the destination IP (`ipv4_dst`) or MAC (`eth_dst`), selecting the highest-priority match.
4. Parses the OpenFlow action to find the physical output port (e.g. `OUTPUT:2`).
5. Correlates the `(switch, egress_port)` pair against `topology.json` link mappings to find the downstream neighbor (`s2`).
6. Repeats the process iteratively until the destination host is reached.

---

### Q5: What happens if flow tables are unpopulated or the SDN controller is unreachable?
**Answer:**
The tool implements an explicit fallback architecture:
1. If the controller REST API times out or no matching flow rule exists, `FlowInspector` queries `SDNTopologyGraph` to calculate the shortest loop-free graph path using Breadth-First Search (BFS).
2. The result is explicitly tagged with `path_source: "assumed_shortest"` and includes a `fallback_reason` attribute detailing the exact failure cause.
3. When flow tables are successfully traversed, it is tagged `path_source: "flow_table"`. This ensures telemetry consumers always know whether a path is control-plane verified or estimated.

---

### Q6: How does the 3-tier failure localization methodology work?
**Answer:**
End-to-end packet loss only indicates path failure, not the failing link. We isolate faults using three independent evidence sources:
1. **Evidence Source A (Port Statistics Deltas):** Queries `/stats/port/<dpid>` before and after probing. Identifies links where egress drops increment ($\Delta \text{Drop} > 0$) or where egress TX packets do not match ingress RX packets on the neighbor switch ($\Delta \text{TX} > \Delta \text{RX}$).
2. **Evidence Source B (Per-Segment Probing):** When probe responders exist on intermediate switches or hosts, sub-segments are tested to find the exact link where packet loss or RTT jumps.
3. **Evidence Source C (Topology Liveness):** Queries the controller's active link inventory (`/v1.0/topology/links`) and detects links on the expected route that completely disappeared from LLDP topology discovery.

---

### Q7: How are suspect link confidence scores mathematically combined?
**Answer:**
When multiple evidence sources independently implicate a link, their individual confidences $c_1, c_2, \dots, c_m$ are aggregated using weighted evidence scoring (independent multi-source evidence combination):
$$C_{\text{combined}} = 1.0 - \prod_{i=1}^m (1.0 - c_i)$$
For example, if port stats indicates a drop with confidence $0.85$ and a segment probe indicates loss with confidence $0.90$:
$$C = 1.0 - (1 - 0.85)(1 - 0.90) = 1.0 - (0.15 \times 0.10) = 0.985 \quad (98.5\%)$$

---

### Q8: What rules govern the health classification of a network path?
**Answer:**
Paths are classified against configurable thresholds in `config.json`:
- **`HEALTHY_PATH`:** Packet Loss $\le 0.0\%$ AND Mean RTT $\le \text{degraded\_rtt\_ms}$ (default 50.0 ms).
- **`DEGRADED_PATH`:** Packet Loss $> 0.0\%$ and $< 50.0\%$, OR Mean RTT $> 50.0\text{ ms}$.
- **`FAILED_PATH`:** Packet Loss $\ge 50.0\%$ (severe outage/unreachable).
The report includes an explicit human-readable string explaining the classification rationale.

---

### Q9: Why are host-to-switch edge links protected from end-to-end failure inference?
**Answer:**
In a tree/diamond network topology, host access links (e.g. `h1 <---> s1` and `s2 <---> h2`) are single points of host attachment. All alternative paths connecting `h1` and `h2` must traverse these edge links.

If end-to-end packet loss naively marked every link along the path as suspected corrupt, the access links would be penalized ($C \ge 0.50$), and **every candidate backup path would be disqualified**. By restricting unconfirmed end-to-end inference to intermediate switch-to-switch core links (`s1 <---> s2`), viable backup paths (e.g. `h1 -> s1 -> s3 -> s2 -> h2`) remain eligible for failover.

---

### Q10: In the degraded scenario, why was the 60% confidence on s1-s2 based on path-membership rather than port drop measurements?
**Answer:**
In the real degraded scenario, link impairment was injected using Linux kernel `tc netem` on interfaces `s1-eth2` and `s2-eth2`.
- **Raw Kernel Qdisc Drops:** `tc -s qdisc show dev s1-eth2` recorded **5 dropped packets**, and `s2-eth2` recorded **8 dropped packets**.
- **OVS OpenFlow Port Counters:** `/stats/port/1` and `/stats/port/2` reported `tx_dropped = 0` and `rx_dropped = 0` because OVS handed frames to the Linux veth netdevice before the kernel qdisc dropped them.
- **Topology Liveness:** The link remained link-state UP in Ryu (`/v1.0/topology/links` reported all links active).
- **Segment Probes:** None were configured on the diamond topology.

Because all direct in-switch measurements reported 0 drops, `correlate.py` fell back to **path-membership heuristic inference** ($C = 0.60$). This is explicitly an inference, **not a direct physical measurement**. It flags the intermediate core link along the degraded route so that backup route re-ranking can recommend `h1 -> s1 -> s3 -> s2 -> h2`.

---

### Q11: How does the backup path ranking algorithm prune candidate paths?
**Answer:**
1. BFS enumerates all simple loop-free paths between source and destination.
2. The current active path is set aside.
3. Any alternative candidate path traversing a link in `suspected_links` with confidence $C \ge 0.50$ is marked `EXCLUDED_CORRUPT_LINK` (`is_viable: False`).
4. Surviving viable paths (`VIABLE_BACKUP`) are ranked by hop count and hop delta (+hops relative to primary).
5. The highest-ranked viable path is designated as the `recommended_backup_path`.

---

### Q11: How does automated backup rerouting work using OpenFlow modifications?
**Answer:**
When `--apply` is specified on `sdnscope reroute` (or `reroute_helper.py`):
1. Reads the `recommended_backup_path` from the correlation report (e.g. `['h1', 's1', 's3', 's2', 'h2']`).
2. Generates **symmetric, bidirectional OpenFlow 1.3 flow modification rules**:
   - **Forward flows:** Directs traffic toward destination IP `10.0.0.2` along `s1 -> s3 -> s2`.
   - **Reverse flows:** Directs return replies toward source IP `10.0.0.1` along `s2 -> s3 -> s1`.
   - **ARP flows:** Installs matching ARP (`eth_type: 2054`) rules for both IPs to ensure transparent address resolution.
3. Deploys rules with **`priority=200`** via HTTP POST to Ryu's `/stats/flowentry/add` endpoint.
4. Because priority 200 takes precedence over existing priority 100 flows, traffic immediately shifts onto the backup route without waiting for flow timeouts.
5. In dry-run mode (default), the JSON payloads are printed for inspection without modifying controller state.

---

### Q12: Why does the reroute assistant use priority 200 instead of priority 100?
**Answer:**
Standard OpenFlow forwarding rules installed for the primary route are installed with `priority=100`.

OpenFlow flow tables execute rules in descending priority order. By installing failover backup rules with **`priority=200`**, the backup route takes immediate precedence over the primary rule without having to delete existing flow entries or wait for idle timeouts. When the primary link is restored, deleting the priority 200 rules instantly reverts traffic to the primary path.

---

### Q13: What were the measured latency and loss numbers on the real testbed?
**Answer:**
On our live Mininet 2.3.0 + Ryu 4.34 testbed (kernel 7.0 / Ubuntu 24.04), actual measurements were:
- **Healthy Baseline:** 0.00% packet loss, mean RTT **13.24 ms** (theoretical baseline: 8 ms + socket/kernel qdisc overhead; window: 6–20 ms), p95 19.59 ms, jitter 3.85 ms. Active path: `h1 -> s1 -> s2 -> h2` (3 hops).
- **Degraded Path:** 10.00% packet loss (10/100 lost), mean RTT **73.32 ms** (theoretical: 13.24 ms + 60 ms netem delay $\approx 73.24\text{ ms}$), p95 87.34 ms, jitter 10.96 ms. Localized suspect link `s1 <---> s2` (60.0% confidence).
- **Failed Path:** 100.00% packet loss (20/20 lost), mean RTT N/A. Link removal processed by Ryu in 0.01 seconds. Localized suspect link `s1 <---> s2` (100.0% confidence).
- **Failover Recovery:** 0.00% packet loss (50/50 received), mean RTT **19.94 ms** (theoretical: 12 ms + overhead; window: 10–25 ms), p95 28.28 ms, jitter 3.75 ms. Active path verified from switch flow tables as `h1 -> s1 -> s3 -> s2 -> h2` (4 hops).

---

### Q14: How does burst mode expose microbursts and queueing delays?
**Answer:**
In standard mode, probes are transmitted with a regular pause (e.g. `--interval 0.1`s), allowing network buffers to drain between measurements.

In `--burst` mode, probes are injected back-to-back with zero delay ($0.0\text{ s}$). If switch port queues are shallow or congested, burst probes rapidly fill the buffer, producing measurable increases in queuing delay (RTT inflation) and packet tail-drop. This detects microburst vulnerability that standard interval probes miss.

---

### Q14: How does the client detect out-of-order and duplicate packets?
**Answer:**
Every probe packet carries a strictly increasing integer sequence number `seq` and a unique probe UUID `probe_id`:
- **Duplicate Detection:** The client tracks all received `seq` numbers in a hash set. If a reply arrives with a sequence number already in the set, it is flagged as `is_duplicate = True`.
- **Out-of-Order Detection:** The client tracks `highest_seq_received`. If a reply arrives with a sequence number strictly less than `highest_seq_received`, it is flagged as `is_out_of_order = True`.

---

### Q15: What are the limitations of one-way delay estimates without PTP/NTP?
**Answer:**
Forward delay is computed as $T_{server\_recv} - T_{client\_send}$ and reverse delay as $T_{client\_recv} - T_{server\_send}$.

If the client and server clocks have an offset (skew) of $\Delta t$, the forward delay estimate will be distorted by $+\Delta t$ and the reverse delay by $-\Delta t$. Unless both machines synchronize to a precision time protocol (e.g. IEEE 1588 PTP or NTP), one-way delays are estimates. However, **Round-Trip Time (RTT)** relies solely on the client's clock and is completely immune to clock skew.

---

### Q16: How does the topology watcher (`--watch`) detect network changes?
**Answer:**
`sdnscope watch` periodically polls `/v1.0/topology/switches` and `/v1.0/topology/links` at a configurable interval:
1. Maintains state sets of switch DPIDs and normalized link tuples: `(min(src, dst), max(src, dst))`.
2. Computes set differences between iterations:
   - $S_{new} - S_{old}$: Switch added (`SWITCH ADDED`).
   - $S_{old} - S_{new}$: Switch removed (`SWITCH REMOVED`).
   - $L_{new} - L_{old}$: Link came up (`LINK UP`).
   - $L_{old} - L_{new}$: Link failed or severed (`LINK DOWN`).
3. Emits timestamped event notifications in real time.

---

### Q17: How are controller credentials secured in this codebase?
**Answer:**
Plaintext passwords were removed from `config.json`. The codebase uses:
1. Environment variable resolution: `CONTROLLER_PASSWORD` is read from `os.environ`.
2. Optional git-ignored file: `config.local.json` (listed in `.gitignore`).
3. CLI override flags: `-P` / `--password`.
4. Clear error diagnostics if credentials are absent, preventing accidental commits of secrets to version control.

---

### Q18: How does `probe_server.py` handle multiple concurrent clients?
**Answer:**
`probe_server.py` inherits from `socketserver.ThreadingMixIn` and `socketserver.UDPServer`.

Incoming UDP datagrams are dispatched to worker threads that execute `handle()` independently. This prevents slow client echoes or artificial delay injection (`--delay-ms`) on one client session from causing head-of-line blocking for other concurrent diagnostic clients.

---

### Q19: What causes false positives in failure localization, and how are they prevented?
**Answer:**
- **Source of False Positives:** Transient packet loss caused by host CPU throttling or OS socket buffer overflow could falsely appear as a link failure.
- **Mitigation:**
  1. Multi-source evidence thresholding: Link severance requires topology liveness ($C=1.0$) or confirmed port drop counters ($C=0.85$).
  2. Baseline delta windowing: Port statistics are polled *before* and *after* probing to measure strictly incremental drops, filtering out historical errors.
  3. Minimum confidence requirement ($C \ge 0.50$) before pruning backup routes.

---

### Q20: What are natural future extensions for this architecture in production networks?
**Answer:**
1. **P4 / In-Band Network Telemetry (INT):** Embedding probe telemetry directly into packet headers so switches append ingress/egress port timestamps in hardware at line rate.
2. **Dynamic Segment Routing (SRv6):** Installing backup routes via segment routing headers instead of manual OpenFlow flow table rule additions.
3. **Machine Learning Anomaly Detection:** Using streaming RTT time-series to predict queue congestion and proactively reroute traffic before packet drops occur.
