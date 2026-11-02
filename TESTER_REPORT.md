# SDNScope Tester Report

## Objective

Validate SDNScope's automated tests, localhost demonstration, UDP measurements, topology/path analysis, failure handling, reroute generation, reports, and cleanup. Record only results executed in this checkout and identify reproducible defects.

## Environment

| Item | Observed value |
|---|---|
| OS/kernel | Linux, 6.11.0-29-generic |
| Python | 3.12.7 in `.venv` |
| pytest | 9.2.0 |
| Ruff | 0.17.3 |
| requests | 2.34.2 |
| matplotlib | 3.11.2 |
| Mininet / OVS commands | `/usr/bin/mn` and `/usr/bin/ovs-vsctl` present |
| Ryu | `ryu-manager` unavailable, including `~/ryu-env` |
| Noninteractive sudo | Unavailable |
| Git branch / remote | `main`, `origin` points to `https://github.com/sudhanvayk/cn_project.git` |

## Methodology

Installed the declared project and development dependencies with `make install`; ran `make test`, `make lint`, Python bytecode compilation, and the complete `make run` localhost demo. Exercised additional UDP delay, partial-loss, and full-loss conditions against local probe servers; used the mock controller's failed topology to check discovery, fault correlation, backup path selection, and reroute submission. Checked invalid CLI input and repeated the demo to verify repeatability and cleanup. Generated artifacts are preserved in [TEST_EVIDENCE](TEST_EVIDENCE/README.md).

## Results

| Test area | Expected result | Actual result | Status |
|---|---|---|---|
| Dependency installation | Runtime and development requirements install | `make install` completed successfully in Python 3.12.7 venv | PASS |
| Unit/integration suite | No test failures | `make test`: 73 passed, 0 failed; total measured coverage 67% | PASS |
| Ruff | No lint errors | `make lint`: all checks passed | PASS |
| Python compilation | Project `.py` files compile | `py_compile` completed with exit code 0 | PASS |
| Localhost demo | Discovery, paths, probe, correlation, reroute, reports complete | `make run` completed successfully twice; both runs generated artifacts | PASS |
| Topology and paths | Discover the mock diamond and both routes | 5 nodes, 5 links; primary `h1-s1-s2-h2` and backup `h1-s1-s3-s2-h2` | PASS |
| Normal UDP probing | Replies and RTT available | Demo returned 10/10 probes, 0% loss, with RTT metrics | PASS |
| Artificial delay | Added server delay appears in RTT | 5/5 replies, mean RTT 30.696 ms with configured 30 ms delay | PASS |
| Artificial packet loss | Loss appears in probe summary | 11/20 received, 9 lost, 45% loss at configured 40% drop rate | PASS |
| Complete packet failure | All probes time out; RTT absent | 3/3 lost, 100% loss, no RTT metric | PASS |
| Failure correlation | Failed link localized; usable backup retained | `FAILED_PATH`; `s1-s2` at 100% topology-liveness confidence; selected `h1-s1-s3-s2-h2` | PASS |
| Reroute generation | Rules target the actual topology endpoint and go to mock | All 12 rules accepted by mock; IPv4 and ARP targets use `10.0.0.2` after fix | PASS |
| Report outputs | JSON, Markdown, HTML, and chart are generated | JSON files parse; Markdown/HTML are text documents; chart is valid PNG | PASS |
| Invalid input | Invalid target rejected without traceback | `not-an-ip` exited nonzero with `[ERROR] Invalid IPv4 address` | PASS |
| Cleanup/repeatability | Demo can run again and leaves services stopped | Second `make run` passed; test ports were released; generated tracked demo files restored | PASS |
| Real Mininet/Ryu scenarios | Run only if prerequisites are available | Not performed: Ryu executable and noninteractive sudo unavailable | NOT RUN |

The focused regression test was intentionally run before the fix and failed because reroute rules contained `127.0.0.1` rather than the topology destination address. After fixing the shared resolver, the regression passed through both the standalone helper and unified CLI. This expected red/green check is evidence of the defect, not an outstanding test failure.

## Bugs Identified

One reroute target-address bug was reproduced and fixed during testing. See [BUG_REPORT.md](BUG_REPORT.md). No unresolved product bugs were found in the executed checks. Real switch/controller behavior remains unverified in this environment.

## Conclusion

All executable local validation gates passed after the changes. The test run verified the mock/offline workflow, not a physical or virtual OpenFlow data plane. Live Mininet/Ryu results must not be inferred from these local checks; run `make real-check` and `make real-scenarios` in an environment with Ryu and the required privileges.