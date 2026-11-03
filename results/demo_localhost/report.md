# SDN Network Diagnostic and Path Analysis Report

**Timestamp:** `2026-11-03T15:45:42Z`  
**Overall Path Health:** 🟩 **HEALTHY** (`HEALTHY_PATH`)  
**Endpoint Target:** `h1` -> `h2` (`127.0.0.1`)  
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
| **Probes Sent / Received** | `10` sent / `10` received | `10` / `10` | OK |
| **Packet Loss Rate** | `0.00%` | `<= 0.0%` (Fail: `>= 50.0%`) | Normal |
| **Mean RTT** | `1.34 ms` | `<= 50.0 ms` | Normal |
| **Minimum / Maximum RTT** | `0.79 ms` / `1.98 ms` | N/A | Range Spread |
| **Median RTT** | `1.30 ms` | N/A | Central Tendency |
| **95th Percentile RTT (p95)** | `1.88 ms` | N/A | Tail Latency Indicator |
| **Standard Deviation Jitter** | `0.42 ms` | Low variation | Sample Deviation |
| **RFC 3550 Inter-Arrival Jitter** | `0.19 ms` | Smoothed $J = J + (|D|-J)/16$ | Statistical Standard |


### RTT Time-Series Chart
![RTT Time-Series Chart](results/demo_localhost/rtt_timeseries.png)

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
