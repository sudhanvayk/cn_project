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
| `mock_controller_*.log` | Mock controller logs from failed-topology and corrected reroute runs |

No screenshots were captured. Temporary warm-up artifacts and empty server logs were removed. All local mock services were stopped and their ports released. Live Mininet/Ryu evidence is not included because Ryu and noninteractive sudo were unavailable.