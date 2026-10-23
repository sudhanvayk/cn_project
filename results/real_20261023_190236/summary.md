# Real SDN Testbed Validation Summary

**Execution Directory:** `results/real_20261023_190236`  
**Execution Timestamp:** `2026-10-23T13:32:36Z` - `2026-10-23T13:34:32Z`  
**Controller:** Ryu 4.34 (`rest_topology`, `ofctl_rest`) on TCP 8080 (REST) / TCP 6653 (OpenFlow)  
**Data Plane:** Mininet 2.3.0 + Open vSwitch 3.3.9 Diamond Topology (s1, s2, s3, h1, h2)  
**Host & Kernel:** `sudh-VB` (Linux 7.0.0-38-generic #38~24.04.4-Ubuntu x86_64)  

---

## 1. Scenario Performance Comparison

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

## 2. Key Experimental Findings

1. **Baseline Latency Physics (TCLink):**
   - Host links: 100 Mbit/s, 1 ms delay ($2 \times 1\text{ ms} = 2\text{ ms}$).
   - Inter-switch links: 10 Mbit/s, 2 ms delay ($1 \times 2\text{ ms} = 2\text{ ms}$).
   - Theoretical one-way delay: $1 + 2 + 1 = 4\text{ ms}$; theoretical round-trip delay: $8\text{ ms}$.
   - Measured healthy mean RTT: **13.24 ms** (accounting for user-space Python socket processing, OVS datapath flow lookup, and kernel qdisc queuing). Well within the expected 6–20 ms window.

2. **Degraded Path Telemetry:**
   - Linux kernel `netem` applied 30 ms delay and 5% drop on each interface of the link `s1-eth2` and `s2-eth2`.
   - Measured round-trip delay increased from 13.24 ms to **73.32 ms** ($\Delta \approx +60\text{ ms}$, matching theoretical $2 \times 30\text{ ms}$ netem addition).
   - Packet loss was measured at exactly **10.00%** (10 drops out of 100 probes, matching expected two-way compound loss: $1 - (1 - 0.05)^2 = 9.75\% \approx 10\%$).

3. **Link Failure & SDN Controller Reactivity:**
   - Physical link `s1-eth2 <-> s2-eth2` was downed via Mininet CLI.
   - Probes experienced **100% loss** on the primary route.
   - Ryu LLDP topology discovery processed the port-status / link-removal event within **0.01 seconds** (link count decreased from 6 directed links to 4 directed links).
   - Multi-source localization correlated OVS port drop counters (2 drops) with controller topology withdrawal, localizing `s1 <---> s2` with **100% confidence**.

4. **Failover & Automated Recovery:**
   - Automated rerouting dispatched 12 bidirectional OpenFlow 1.3 flow entries (IPv4 + ARP) with priority 200 via Ryu REST API `/stats/flowentry/add`.
   - Forward traffic was steered from `s1` -> `s3` (port 3) -> `s2` (port 2) -> `h2` (port 1).
   - Reverse traffic was steered from `s2` -> `s3` (port 3) -> `s1` (port 1) -> `h1` (port 1).
   - Re-probing immediately demonstrated **0.00% packet loss** with a mean RTT of **19.94 ms** (expected theoretical: $1 + 2 + 2 + 1 = 6\text{ ms}$ one-way, $12\text{ ms}$ base RTT + processing $\approx 15\text{--}20\text{ ms}$).
   - Active path was re-verified directly against live switch flow tables as `h1 -> s1 -> s3 -> s2 -> h2` (hop count 4).
