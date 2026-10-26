# SDN Network Diagnostic and Path Analysis Report

**Timestamp:** `2026-10-25T11:30:52Z`  
**Overall Path Health:** 🟩 **HEALTHY** (`HEALTHY_PATH`)  
**Endpoint Target:** `h1` -> `h2` (`10.0.0.2`)  
**Path Identification Method:** `FLOW_TABLE`  

---

## 1. Executive Summary & Diagnostic Notice

> **Primary Path Status:** `HEALTHY_PATH`  
> **Diagnostic Finding:** None (Path is healthy and operating within nominal thresholds)

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
|    None (All path links operational)
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
| **Probes Sent / Received** | `50` sent / `50` received | `50` / `50` | OK |
| **Packet Loss Rate** | `0.00%` | `<= 0.0%` (Fail: `>= 50.0%`) | Normal |
| **Mean RTT** | `17.02 ms` | `<= 50.0 ms` | Normal |
| **Minimum / Maximum RTT** | `9.93 ms` / `70.27 ms` | N/A | Range Spread |
| **Median RTT** | `14.59 ms` | N/A | Central Tendency |
| **95th Percentile RTT (p95)** | `26.47 ms` | N/A | Tail Latency Indicator |
| **Standard Deviation Jitter** | `9.17 ms` | Low variation | Sample Deviation |
| **RFC 3550 Inter-Arrival Jitter** | `5.26 ms` | Smoothed $J = J + (|D|-J)/16$ | Statistical Standard |


### RTT Time-Series Chart
![RTT Time-Series Chart](/home/sudh/Documents/cn_project/results/real_20261025_170036/healthy/rtt_timeseries.png)

---

## 3. Failure Localization & Evidence Sources

No links exhibited packet loss, port drop counters, or topology churn.

---

## 4. Alternative Backup Routes & Failover Recommendation

| Rank | Route Status | Hop Count | Hop Penalty | Forwarding Path Route |
|---|---|---|---|---|
| 1 | `VIABLE_BACKUP` | 4 | +1 | `h1 -> s1 -> s3 -> s2 -> h2` |

### Actionable Rerouting Recommendation
> **Recommended Action:** Failover traffic to backup route **`h1 -> s1 -> s3 -> s2 -> h2`** (+1 extra hop penalty).  
> **Deployment Command:** `python3 sdnscope.py reroute --apply` (or `python3 reroute_helper.py --apply`)
