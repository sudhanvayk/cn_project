# SDNScope Tester Test Cases

Results below were collected on 2026-11-02 in this checkout. `NOT RUN` is distinguished from `FAIL` when an environment prerequisite was absent.

| ID | Description and input conditions | Expected output | Actual output | Status |
|---|---|---|---|---|
| ENV-01 | Install runtime and development dependencies using `make install` | Installation completes in project venv | Completed with Python 3.12.7; requests, matplotlib, pytest, pytest-cov, and Ruff installed | PASS |
| AUTO-01 | Run `make test` | All unit/integration tests pass | 73 passed, 0 failed; total measured coverage 67% | PASS |
| AUTO-02 | Run `make lint` | Ruff reports no findings | `All checks passed!` | PASS |
| AUTO-03 | Compile project Python sources excluding `.venv` and `.git` | No syntax errors | `py_compile` exit code 0 | PASS |
| DEMO-01 | Run `make run` | Full localhost workflow exits successfully | Passed twice, including topology, paths, probes, trace fallback, correlation, reroute, and reports | PASS |
| TOPO-01 | Discover mock controller's healthy topology | 5 nodes and 5 links | 5 nodes, 5 links | PASS |
| PATH-01 | Enumerate `h1` to `h2` routes in diamond topology | Primary 3-hop and backup 4-hop paths | `h1-s1-s2-h2`; `h1-s1-s3-s2-h2` | PASS |
| UDP-01 | 10 localhost probes against normal echo server | Replies received and RTT reported | Demo recorded 10 sent, 10 received, 0% loss | PASS |
| UDP-02 | 5 probes with 30 ms server delay, following one warm-up probe | RTT near/above injected delay | 5/5 received; mean RTT 30.696 ms | PASS |
| UDP-03 | 20 probes with server drop rate 0.40, following one warm-up probe | Nonzero packet loss | 11 received, 9 lost, 45% measured loss | PASS |
| UDP-04 | 3 burst probes against server drop rate 1.0 | 100% loss and null RTT | 0 received, 3 lost, 100% loss, no RTT metrics | PASS |
| COR-01 | Failed mock topology plus full-loss diagnostic | Failed path; missing primary link localized | `FAILED_PATH`; `s1-s2` at 100% confidence from topology liveness | PASS |
| ROUTE-01 | Reroute failed report along surviving diamond path | Rules target `h2`'s topology IP and are accepted by mock | 12 IPv4/ARP rules submitted; targets use `10.0.0.2` after fix | PASS |
| REPORT-01 | Generate localhost reports and inspect file formats | JSON, Markdown, HTML, PNG artifacts valid | JSON data parses; HTML/Markdown text and PNG image produced | PASS |
| INPUT-01 | Run `sdnscope probe not-an-ip -c 1` | Nonzero exit and concise validation error | Nonzero exit; `[ERROR] Invalid IPv4 address: 'not-an-ip'` | PASS |
| CLEAN-01 | Repeat `make run` and inspect services/worktree | Repeat succeeds; background listeners stop; tracked fixtures preserved | Repeat succeeded; ports released; original tracked demo outputs restored | PASS |
| REAL-01 | Run live Mininet/Ryu scenarios | Live scenario suite results | Not run: `ryu-manager` missing and noninteractive sudo unavailable | NOT RUN |

Evidence files are catalogued in [TEST_EVIDENCE/README.md](TEST_EVIDENCE/README.md). The pre-fix reroute regression was an expected failure used to establish the defect; the final test suite passes.