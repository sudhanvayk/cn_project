# SDN Network Diagnostic and Path Analysis Report

**Timestamp:** `2026-11-05T16:54:14Z`  
**Overall Path Health:** 🟥 **FAILED** (`FAILED_PATH`)  
**Endpoint Target:** `h1` -> `h2` (`10.0.0.2`)  
**Path Identification Method:** `FLOW_TABLE`  

---

## 1. Executive Summary & Diagnostic Notice

> **Primary Path Status:** `FAILED_PATH`  
> **Diagnostic Finding:** Severe packet loss (100.00%) meets or exceeds failure threshold (50.0%).

### Active Forwarding Route
`h1 -> s1 -> s2 -> h2` (3 hops)

```
+---------------------------------------------------------------------------------+
|                       SDN TOPOLOGY AND FORWARDING PATH MAP                      |
+---------------------------------------------------------------------------------+
|                                                                                 |
|  ACTIVE FORWARDING ROUTE:                                                       |
|    [ h1 -> s1 -> s2 -> h2 ]                                                             |
|                                                                                 |
|  SUSPECTED BROKEN/DEGRADED LINKS:                                               |
|    s1 <---> s2
|                                                                                 |
|  RECOMMENDED FAILOVER BACKUP ROUTE:                                             |
|    [ h1 -> s1 -> s3 -> s2 -> h2 ]                                                             |
|                                                                                 |
+---------------------------------------------------------------------------------+
```

---

## 2. Quantitative Performance Telemetry

| Performance Metric | Measured Value | Nominal / Threshold Baseline | Health Evaluation |
|---|---|---|---|
| **Probes Sent / Received** | `20` sent / `0` received | `20` / `20` | Drops Detected |
| **Packet Loss Rate** | `100.00%` | `<= 0.0%` (Fail: `>= 50.0%`) | Threshold Exceeded |
| **Mean RTT** | `N/A` | `<= 50.0 ms` | Failed |
| **Minimum / Maximum RTT** | `N/A` / `N/A` | N/A | Range Spread |
| **Median RTT** | `N/A` | N/A | Central Tendency |
| **95th Percentile RTT (p95)** | `N/A` | N/A | Tail Latency Indicator |
| **Standard Deviation Jitter** | `N/A` | Low variation | Sample Deviation |
| **RFC 3550 Inter-Arrival Jitter** | `N/A` | Smoothed $J = J + (|D|-J)/16$ | Statistical Standard |


### RTT Time-Series Chart
![RTT Time-Series Chart](/home/sudh/cn_project-main/results/real_20261105_222258/failed/rtt_timeseries.png)

---

## 3. Failure Localization & Evidence Sources

| Rank | Suspected Link | Combined Confidence | Localization Evidence Sources |
|---|---|---|---|
| 1 | `s1 <---> s2` | `100.0%` | Port drop counters incremented: 2 dropped packets on link s2:2 <-> s1:2; Link s1 <---> s2 disappeared from active SDN controller topology |

---

## 4. Alternative Backup Routes & Failover Recommendation

| Rank | Route Status | Hop Count | Hop Penalty | Forwarding Path Route |
|---|---|---|---|---|
| 1 | `VIABLE_BACKUP` | 4 | +1 | `h1 -> s1 -> s3 -> s2 -> h2` |

### Actionable Rerouting Recommendation
> **Recommended Action:** Failover traffic to backup route **`h1 -> s1 -> s3 -> s2 -> h2`** (+1 extra hop penalty).  
> **Deployment Command:** `python3 sdnscope.py reroute --apply` (or `python3 reroute_helper.py --apply`)
