# Test Evidence Index

Captured from the 2026-11-02 tester run. The complete localhost demo was repeated after the reroute fix; outputs from that run are in `localhost_demo/` so existing tracked `results/demo_localhost/` artifacts remain unchanged.

| Evidence | Contents |
|---|---|
| `localhost_demo_repeat.txt` | Full transcript of the repeat `make run` workflow, including discovery, paths, UDP probe, correlation, reroute, and report generation |
| `localhost_demo/` | Generated topology/path/correlation/diagnostic/trace JSON, Markdown and HTML reports, and RTT chart from the repeated demo |
| `topology_failed.txt`, `topology_failed.json` | Mock-controller failed topology discovery (primary link absent) |
| `diagnostic_failed.txt`, `diagnostic_failed.json` | Three probes against a 100% drop server; all timed out |
| `correlation_failed.txt`, `correlation_failed.json` | Failed-path classification, 100% topology-liveness localization, and backup route recommendation |
| `reroute_failed.txt` | Initial mock reroute output that exposed the loopback destination defect |
| `reroute_failed_fixed.txt` | Reroute output after the fix; IPv4 and ARP rules use `10.0.0.2` and are accepted by the mock |
| `diagnostic_delay.txt`, `diagnostic_delay.json` | Five probes after warm-up with configured 30 ms delay; measured mean RTT 30.696 ms and 0% loss |
| `diagnostic_partial_loss.txt`, `diagnostic_partial_loss.json` | Twenty probes after warm-up with configured 40% drop; observed 9/20 loss (45%) |
| `invalid_target.txt` | Invalid target rejected with nonzero exit and validation message |
| `qdisc_recorrelation.txt`, `qdisc_recorrelation.json` | Offline re-correlation of the archived `results/real_20261023_190236/degraded` live capture with `--qdisc-before/--qdisc-after`: 13 kernel qdisc drops (5 + 8) localize `s1 <---> s2` at 95.0% (controller was stopped, so the path falls back to the topology graph) |
| `live_cli_verification_20261105.txt` | Successful 2026-11-05 live run of `scripts/verify_live_cli.py` on Mininet 2.3.0 + OVS 3.7.1 + Ryu 4.34: topology (5 nodes, 5 links), 2 paths, trace Hop 1 reachable at 0% loss, `LINK DOWN: s1 <---> s2` watch event, and report generation. Generated artifacts are in `results/cli_verification/`. |
| `mock_controller_*.log` | Mock controller logs from failed-topology and corrected reroute runs |

No screenshots were captured. Temporary warm-up artifacts and empty server logs were removed. All local mock services were stopped and their ports released. Live Mininet/Ryu evidence is included from the 2026-11-05 runs: the latest four-scenario suite is in `results/real_20261105_222258/` (`results/latest`), the earlier repeat is in `results/real_20261105_150848/`, and the CLI transcript is `live_cli_verification_20261105.txt`.