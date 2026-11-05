# Genuine SDN Testbed Verification Evidence

This document compiles the genuine execution transcripts, command outputs, and comparative telemetry captured from running the **SDNScope** diagnostic suite on a real Mininet + Ryu OpenFlow testbed.

---

## 1. Environment & Hardware Metadata

Captured during live harness execution (`results/latest/env.txt`):
```text
=== Environment Metadata ===
Date: 2026-10-23T13:32:36Z
Hostname: sudh-VB
Kernel: Linux sudh-VB 7.0.0-38-generic #38~24.04.4-Ubuntu SMP PREEMPT_DYNAMIC Mon Sep 14 16:37:11 UTC 2 x86_64 x86_64 x86_64 GNU/Linux
Git Branch: fix/real-sdn-validation
Git Commit: 9dca4a08e1e8e35a349b606da481afdf1743237e
System Python: Python 3.12.3
Venv Python: Python 3.12.3
Ryu Version: ryu-manager 4.34 (Python 3.9 in ~/ryu-env)
Mininet Version: 2.3.0
OVS Version: ovs-vsctl (Open vSwitch) 3.3.9
```

---

## 2. Gate 1: Pre-Flight Verification

Executed via `scripts/preflight_check.sh`:
```text
=== SDN Diagnostic Suite Pre-Flight Verification ===
[1/6] Sudo Passwordless Check:
SUDO_OK
[2/6] Mininet & OVS Installation Check:
/usr/bin/mn
/usr/bin/ovs-vsctl
ovs-vsctl (Open vSwitch) 3.3.9
DB Schema 8.4.0
[3/6] Ryu Manager (Isolated venv) Check:
~/ryu-env/bin/ryu-manager
ryu-manager 4.34
[4/6] Port Conflict Check (6653, 6633, 8080, 9999):
PORTS_FREE
[5/6] Python Diagnostic Environment Check:
Python 3.12.3
[6/6] Unit Test Suite & Linter Check:
69 passed in 5.76s
All checks passed!
======================================================
[SUCCESS] All pre-flight checks passed! Environment ready for real SDN testbed.
```

---

## 3. Gate 3: Live Bring-Up & Real Fixture Capture

### 3.1 Open vSwitch Bridge & Controller State
```text
$ sudo ovs-vsctl show
495e8e78-fa6c-486d-85fa-71df296f8c85
    Bridge s3
        Controller "tcp:127.0.0.1:6653"
            is_connected: true
        fail_mode: secure
        Port s3-eth1
            Interface s3-eth1
        Port s3-eth2
            Interface s3-eth2
        Port s3
            Interface s3
                type: internal
    Bridge s1
        Controller "tcp:127.0.0.1:6653"
            is_connected: true
        fail_mode: secure
        Port s1-eth1
            Interface s1-eth1
        Port s1-eth2
            Interface s1-eth2
        Port s1-eth3
            Interface s1-eth3
        Port s1
            Interface s1
                type: internal
    Bridge s2
        Controller "tcp:127.0.0.1:6653"
            is_connected: true
        fail_mode: secure
        Port s2-eth1
            Interface s2-eth1
        Port s2-eth2
            Interface s2-eth2
        Port s2-eth3
            Interface s2-eth3
        Port s2
            Interface s2
                type: internal
    ovs_version: "3.3.9"
```

### 3.2 Sanity Ping Verification (Baseline Primary Path)
```text
PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=11.5 ms
64 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=11.8 ms
64 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=9.03 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2009ms
rtt min/avg/max/mdev = 9.034/10.785/11.843/1.247 ms
```

### 3.3 Real Diamond Fixture Capture Verification
Real controller fixtures were captured into `tests/fixtures/real_diamond/` and verified with `tests/test_real_diamond_fixtures.py`:
- 3 distinct OpenFlow 1.3 switch DPIDs: `1`, `2`, `3`
- 3 bidirectional inter-switch links (6 directed links)
- Hardware MAC addresses are unique to the host VM and disjoint from synthetic fixtures:
  - `s1-eth1`: `3a:aa:0d:75:43:5e`, `s1-eth2`: `2e:d3:b1:39:22:4f`, `s1-eth3`: `96:8f:78:30:b4:75`
  - `s2-eth1`: `de:21:90:e1:6b:81`, `s2-eth2`: `12:77:14:2a:b7:01`, `s2-eth3`: `6a:34:5f:40:ef:45`
  - `s3-eth1`: `a6:a3:76:1a:c7:b0`, `s3-eth2`: `ce:7b:4a:d5:89:fd`

---

## 4. Gate 4: Real Scenario Suite Execution & Results

Executed via `./scripts/run_all_scenarios.sh`. The table below is the 2026-10-23 run (`results/real_20261023_190236/`); section 4.3 records the latest 2026-11-05 run with qdisc telemetry enabled.

### Comparative Scenario Performance Summary
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
| **Suspected Broken Link** | None | `s1 <---> s2` (60.0% archived run; 95.0% with qdisc telemetry) | `s1 <---> s2` (100.0% confidence) | None |
| **Recommended Backup Route** | `h1 -> s1 -> s3 -> s2 -> h2` | `h1 -> s1 -> s3 -> s2 -> h2` | `h1 -> s1 -> s3 -> s2 -> h2` | N/A (Already active) |

### 4.2 Raw Telemetry Breakdown: Degraded Scenario Localization
The archived run assigned 60.0% confidence to `s1 <---> s2`; the correlator now consumes the captured qdisc counters and reports 95.0% on the same data. All telemetry sources were investigated:
1. **OVS Port Statistics (`/stats/port`):**
   - Switch `s1`, Port 2 (connecting to `s2`): `tx_dropped: 0`, `rx_dropped: 0`, `tx_errors: 0`, `rx_errors: 0`.
   - Switch `s2`, Port 2 (connecting to `s1`): `tx_dropped: 0`, `rx_dropped: 0`, `tx_errors: 0`, `rx_errors: 0`.
   - *Finding:* Because packet drops were injected via the Linux kernel `netem` qdisc on the veth pair, Open vSwitch transferred frames to the network device without internal drop, so OpenFlow port counters reported **zero drops**.
2. **Linux Kernel Qdisc Telemetry (`tc -s qdisc show dev s1-eth2` / `s2-eth2`):**
   - `s1-eth2`: `qdisc netem 10: root refcnt 5 limit 1000 delay 30ms loss 5% — Sent 19365 bytes 138 pkt (dropped 5)`
   - `s2-eth2`: `qdisc netem 10: root refcnt 5 limit 1000 delay 30ms loss 5% — Sent 25930 bytes 131 pkt (dropped 8)`
   - *Finding:* All packet drops occurred in the Linux kernel netem queue; this kernel metric is not exposed over northbound OpenFlow REST APIs, so it must be scraped out-of-band.
3. **Topology Liveness (`/v1.0/topology/links`):**
   - Link carrier remained UP. Ryu reported all 6 directed links (3 bidirectional links) active.
4. **Segment Probes:** None executed.
5. **Localization Origin:** The 60.0% confidence in the table above (2026-10-23 run) was generated by `correlate.py`'s **path-membership heuristic fallback** because qdisc counters were not yet wired into the correlator. Re-correlating the same capture with `--qdisc-before/--qdisc-after` attributes the **13-drop delta (5 + 8)** against **10 lost probes** and localizes `s1 <---> s2` at **95.0% confidence** — a direct measurement. The 2026-10-25 run (9 + 3 = 12 drops vs. 11 lost probes) independently yields the same 95.0%. The heuristic is retained only for runs without qdisc telemetry. Transcript: `TEST_EVIDENCE/qdisc_recorrelation.txt`.

### 4.3 Live qdisc-validation run (2026-11-05)

A fresh full suite was executed on Ubuntu 26.04 with Mininet 2.3.0, Open vSwitch 3.7.1 and Ryu 4.34, with `scenario_runner.py` passing `tc_qdisc_before.txt` / `tc_qdisc_after.txt` into `correlate.py`:

| Scenario | Probes Sent / Received | Loss | Mean RTT | Localization |
|---|---|---|---|---|
| `healthy` | 50 / 50 | 0.00% | 9.68 ms | No suspects |
| `degraded` | 100 / 92 | 8.00% | 66.33 ms | `s1 <---> s2` at **95.0%** from 17 qdisc drops (`s1-eth2` +10, `s2-eth2` +7) |
| `failed` | 20 / 0 | 100.00% | N/A | `s1 <---> s2` at **100%** (port drops + topology liveness) |
| `recovery` (pre-reroute) | 20 / 0 | 100.00% | N/A | `s1 <---> s2` at **100%** |
| `recovery` (post-reroute) | 50 / 50 | 0.00% | 14.29 ms | `HEALTHY_PATH` on `h1 -> s1 -> s3 -> s2 -> h2` |

Artifacts: `results/real_20261105_222258/` (`results/latest`). The earlier `results/real_20261105_150848/` run independently yielded 95.0% from 19 drops. Together they are the end-to-end proof that qdisc counters upgrade localization from the 60% heuristic to a direct 95% measurement.

---

## 5. Live CLI Verification Output

Executed live against running Mininet and Ryu (`scripts/verify_live_cli.py`). The transcripts below are from the 2026-10-23 run; the 2026-11-05 re-run on Ubuntu 26.04 / Mininet 2.3.0 / OVS 3.7.1 / Ryu 4.34 reproduced every command, including the `LINK DOWN: s1 <---> s2` watch event. Full transcript: `TEST_EVIDENCE/live_cli_verification_20261105.txt`.

### 5.1 `sdnscope.py topo` Output
```text
====================================================================
                 SDN TOPOLOGY DISCOVERY REPORT
====================================================================
 Controller Type:   RYU
 Controller URL:    http://127.0.0.1:8080
 Discovered At:     2026-10-23T13:39:29Z
 Total Nodes:       5
 Total Links:       5
--------------------------------------------------------------------

[Discovered Nodes]:
Node ID      Type         IP / DPID                 Connected To   
--------------------------------------------------------------------
s1           switch       0000000000000001          -              
s2           switch       0000000000000002          -              
s3           switch       0000000000000003          -              
h1           host         10.0.0.1                  s1             
h2           host         10.0.0.2                  s2             

[Discovered Links]:
Source          <--->    Destination     Link Type           
--------------------------------------------------------------------
s2              <--->    s1              switch-to-switch    
s3              <--->    s1              switch-to-switch    
s3              <--->    s2              switch-to-switch    
h1              <--->    s1              host-to-switch      
h2              <--->    s2              host-to-switch      
====================================================================
```

### 5.2 `sdnscope.py paths -s h1 -d h2` Output
```text
======================================================================
               SDN PATH DISCOVERY AND COMPARISON REPORT
======================================================================
 Source:            h1
 Destination:       h2
 Total Paths Found: 2
----------------------------------------------------------------------
Rank   Role                   Hops     Extra    Path Route
----------------------------------------------------------------------
1      SELECTED_SHORTEST      3        0        h1 -> s1 -> s2 -> h2
2      ALTERNATIVE            4        +1       h1 -> s1 -> s3 -> s2 -> h2
======================================================================
```

### 5.3 `sdnscope.py trace 10.0.0.2` (OpenFlow L2 Transparency & Hop 1 Reachability)
```text
========================================================================
              NETWORK PATH ANALYSIS REPORT (IP Layer)
========================================================================
 Target Host:       10.0.0.2
 Tracing Method:    native_raw_socket
 Total Hops Found:  1
------------------------------------------------------------------------
Hop   IP Address             Loss %     Avg RTT      Status      
------------------------------------------------------------------------
1     10.0.0.2               0.0%       11.88 ms     REACHABLE   
------------------------------------------------------------------------
[SDN PATH TRANSPARENCY NOTICE]:
In standard OpenFlow/Mininet networks, switches forward packets at Layer 2 without decrementing the IPv4 TTL field (unless explicit dec_ttl actions exist). Consequently, intermediate OpenFlow switches are transparent to standard traceroute; the destination host answers directly at Hop 1 via ICMP Port Unreachable. Authoritative multi-switch forwarding paths are determined by querying the SDN controller flow tables (see flow_inspector.py).
========================================================================
```

### 5.4 `sdnscope.py watch` (Live Link Bounce Detection)
```text
====================================================================
       SDN Topology Live Watcher Running (Interval: 1s)
====================================================================
 Press Ctrl+C to terminate watcher.
--------------------------------------------------------------------
[INFO] 19:09:46 - Connecting to Ryu REST API at http://127.0.0.1:8080...
[INFO] 19:09:46 - Initial baseline: 3 nodes, 3 links.
[INFO] 19:09:47 - Connecting to Ryu REST API at http://127.0.0.1:8080...
[INFO] 19:09:48 - Connecting to Ryu REST API at http://127.0.0.1:8080...

[EVENT DETECTED @ 19:09:48]:
  ● LINK DOWN: s1 <---> s2
[INFO] 19:09:49 - Connecting to Ryu REST API at http://127.0.0.1:8080...
[INFO] 19:09:50 - Connecting to Ryu REST API at http://127.0.0.1:8080...

[INFO] Topology watcher stopped by user.
```

---

## 6. Gate 5: Quality Assurance Gates

> **Snapshot note:** the transcript below is from the 2026-10-23 environment (69 tests). The final submission host runs **82 tests passed with 68% total coverage** (`make test`), and `make lint` reports no errors.

- **Pytest:** 69 passed in 7.00s (74% coverage across core modules, 100% on core test files)
- **Ruff:** All checks passed (`0` lint errors)
- **py_compile:** Zero syntax or byte-compile errors across all project `.py` files
- **Secrets Audit:** 0 credentials or passwords found in repository
- **Clean Clone Test:** Cloned to `/tmp/cn_clean`; 69 passed in 5.15s without uncommitted dependencies
