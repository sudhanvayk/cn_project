# SDNScope Bug Report

## BUG-001: Loopback probe target was used as the reroute destination

**Severity:** Medium
**Status:** Fixed and covered by regression test
**Affected commands:** `sdnscope reroute` and `reroute_helper.py` report-driven reroute mode

### Reproduction

1. Use a topology containing `h1` (`10.0.0.1`) and `h2` (`10.0.0.2`) connected by the primary and backup routes.
2. Create a correlation report whose `destination_node` is `h2`, whose recommended backup path ends at `h2`, and whose `destination_ip` is `127.0.0.1` (as produced by localhost probe demos).
3. Run `sdnscope.py reroute -r <report.json> -t <topology.json>` or the equivalent `reroute_helper.py` command.

### Expected behavior

When a localhost probe endpoint has been associated with a topology destination node, generated IPv4 and ARP match rules should use the destination host's topology address (`10.0.0.2`).

### Observed behavior before fix

The generated forward rules used `127.0.0.1`. The mock controller accepted the payloads with HTTP 200 but did not validate whether the match address represented a routable topology endpoint. A flow matching loopback would not direct the intended host traffic in the real topology.

### Fix and verification

Added a shared resolver that replaces loopback values with the selected destination node's topology IP when available. Added a regression test covering both report-driven reroute entry points. The regression failed before the fix with actual target `127.0.0.1`; after the fix it passed and the mock reroute output contained `10.0.0.2` in both IPv4 and ARP rules. This was an offline/mock validation; it does not claim live switch installation.

No other reproducible product bugs were found in the executed tests. Real Mininet/Ryu behavior was not evaluated in this environment.