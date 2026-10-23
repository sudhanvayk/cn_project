#!/usr/bin/env python3
"""
Scenario Runner for Real Mininet + Ryu SDN Diagnostics Suite.
Executes scenarios (healthy, degraded, failed, recovery) against a live
Mininet Diamond topology and Ryu controller.

Must be executed as root with system python3.
Uses only the standard library and Mininet (REST via urllib).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    from mininet.link import TCLink
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo
except ImportError as exc:
    print(f"[FATAL] Mininet is required to run scenario_runner: {exc}", file=sys.stderr)
    sys.exit(1)

PROJECT_DIR = "/home/sudh/Documents/cn_project"
VENV_PYTHON = os.path.join(PROJECT_DIR, ".venv/bin/python")
SDNSCOPE_CLI = os.path.join(PROJECT_DIR, "sdnscope.py")
DEFAULT_REST_URL = "http://127.0.0.1:8080"
DEFAULT_OF_PORT = 6653


class SecureDiamondTopo(Topo):
    """Diamond topology (s1, s2, s3) with OpenFlow 1.3."""

    def build(self):
        s1 = self.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13", failMode="secure")
        s2 = self.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13", failMode="secure")
        s3 = self.addSwitch("s3", dpid="0000000000000003", protocols="OpenFlow13", failMode="secure")

        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

        # Host links: 100 Mbps, 1 ms
        self.addLink(h1, s1, port1=1, port2=1, cls=TCLink, bw=100, delay="1ms")
        self.addLink(h2, s2, port1=1, port2=1, cls=TCLink, bw=100, delay="1ms")

        # Inter-switch links: 10 Mbps, 2 ms
        # Primary: s1:2 <-> s2:2
        self.addLink(s1, s2, port1=2, port2=2, cls=TCLink, bw=10, delay="2ms")
        # Backup: s1:3 <-> s3:1, s3:2 <-> s2:3
        self.addLink(s1, s3, port1=3, port2=1, cls=TCLink, bw=10, delay="2ms")
        self.addLink(s3, s2, port1=2, port2=3, cls=TCLink, bw=10, delay="2ms")


def rest_get(url: str, timeout: float = 5.0):
    """Perform HTTP GET returning decoded JSON or None on error."""
    req = urllib.request.Request(url, headers={"User-Agent": "ScenarioRunner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def rest_post(url: str, data: dict, timeout: float = 5.0):
    """Perform HTTP POST with JSON body."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ScenarioRunner/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode()


def wait_for_switches(rest_url: str, expected_count: int = 3, timeout: float = 60.0):
    """Wait until Ryu REST API returns expected number of DPIDs."""
    switches_url = f"{rest_url.rstrip('/')}/v1.0/topology/switches"
    start = time.time()
    while time.time() - start < timeout:
        sws = rest_get(switches_url, timeout=2.0)
        if isinstance(sws, list) and len(sws) >= expected_count:
            return True
        time.sleep(1.0)
    return False


def install_primary_flows(rest_url: str):
    """Install primary path flows on s1 and s2 via ofctl_rest."""
    base = rest_url.rstrip("/")
    add_url = f"{base}/stats/flowentry/add"
    del_url = f"{base}/stats/flowentry/delete_strict"

    rules = [
        # s1: dst 10.0.0.2 -> OUTPUT 2 (toward s2)
        {"dpid": 1, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]},
        {"dpid": 1, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]},
        # s1: dst 10.0.0.1 -> OUTPUT 1 (toward h1)
        {"dpid": 1, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]},
        {"dpid": 1, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]},
        # s2: dst 10.0.0.2 -> OUTPUT 1 (toward h2)
        {"dpid": 2, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 1}]},
        {"dpid": 2, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 1}]},
        # s2: dst 10.0.0.1 -> OUTPUT 2 (toward s1)
        {"dpid": 2, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 2}]},
        {"dpid": 2, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 2}]},
    ]

    for rule in rules:
        del_rule = {"dpid": rule["dpid"], "priority": rule["priority"], "match": rule["match"]}
        try:
            rest_post(del_url, del_rule, timeout=2.0)
        except Exception:
            pass
        rest_post(add_url, rule, timeout=2.0)


def collect_controller_telemetry(rest_url: str, output_dir: str, prefix: str):
    """Collect topology, flow tables, and port stats from Ryu REST API."""
    base = rest_url.rstrip("/")

    # 1. Topology
    switches = rest_get(f"{base}/v1.0/topology/switches") or []
    links = rest_get(f"{base}/v1.0/topology/links") or []
    hosts = rest_get(f"{base}/v1.0/topology/hosts") or []

    with open(os.path.join(output_dir, f"{prefix}_switches.json"), "w") as f:
        json.dump(switches, f, indent=2)
    with open(os.path.join(output_dir, f"{prefix}_links.json"), "w") as f:
        json.dump(links, f, indent=2)
    with open(os.path.join(output_dir, f"{prefix}_hosts.json"), "w") as f:
        json.dump(hosts, f, indent=2)

    # 2. Flow tables & Port stats for s1, s2, s3
    port_stats_combined = {}
    for dpid in [1, 2, 3]:
        flows = rest_get(f"{base}/stats/flow/{dpid}") or {}
        with open(os.path.join(output_dir, f"{prefix}_flow_s{dpid}.json"), "w") as f:
            json.dump(flows, f, indent=2)

        p_stats = rest_get(f"{base}/stats/port/{dpid}") or {}
        with open(os.path.join(output_dir, f"{prefix}_port_s{dpid}.json"), "w") as f:
            json.dump(p_stats, f, indent=2)
        if str(dpid) in p_stats:
            port_stats_combined[str(dpid)] = p_stats[str(dpid)]

    with open(os.path.join(output_dir, f"{prefix}_port_stats.json"), "w") as f:
        json.dump(port_stats_combined, f, indent=2)

    return port_stats_combined


def run_cmd(cmd: str):
    """Execute bash command and return (code, stdout, stderr)."""
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err


def main():
    parser = argparse.ArgumentParser(description="SDNScope Mininet Scenario Runner")
    parser.add_argument("scenario", choices=["healthy", "degraded", "failed", "recovery"],
                        help="Scenario to execute")
    parser.add_argument("-o", "--output-dir", required=True, help="Directory to save artifacts and logs")
    parser.add_argument("--ryu-url", default=DEFAULT_REST_URL, help=f"Ryu REST API URL (default: {DEFAULT_REST_URL})")
    parser.add_argument("--of-port", type=int, default=DEFAULT_OF_PORT, help=f"OpenFlow controller port (default: {DEFAULT_OF_PORT})")
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    mininet_log_path = os.path.join(output_dir, "mininet.log")
    mininet_log = open(mininet_log_path, "w")

    def log(msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        mininet_log.write(line + "\n")
        mininet_log.flush()

    log(f"Starting scenario '{args.scenario}' in directory: {output_dir}")

    # Write hosts file for topology discovery
    hosts_json_path = os.path.join(output_dir, "hosts.json")
    hosts_data = [
        {"name": "h1", "mac": "00:00:00:00:00:01", "ip": "10.0.0.1", "dpid": "0000000000000001", "port": 1},
        {"name": "h2", "mac": "00:00:00:00:00:02", "ip": "10.0.0.2", "dpid": "0000000000000002", "port": 1},
    ]
    with open(hosts_json_path, "w") as f:
        json.dump(hosts_data, f, indent=2)

    net = None
    try:
        topo = SecureDiamondTopo()
        net = Mininet(
            topo=topo,
            controller=lambda name: RemoteController(name, ip="127.0.0.1", port=args.of_port),
            switch=OVSSwitch,
            link=TCLink,
            autoSetMacs=True,
        )

        log("Starting Mininet network...")
        net.start()

        # Enforce fail-mode secure on all bridges
        for sw in net.switches:
            sw.cmd(f"ovs-vsctl set Bridge {sw.name} fail_mode=secure")

        h1 = net.get("h1")
        h2 = net.get("h2")

        # Disable IPv6 multicast noise
        h1.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
        h2.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")

        # Static ARP entries
        h1.setARP("10.0.0.2", "00:00:00:00:00:02")
        h2.setARP("10.0.0.1", "00:00:00:00:00:01")

        # Dump network layout to mininet.log
        mininet_log.write("=== NETWORK LINKS ===\n")
        for link in net.links:
            mininet_log.write(f"{link}\n")
        mininet_log.write("=====================\n\n")

        # Wait for switches in Ryu
        log("Waiting for 3 switches to connect to Ryu...")
        if not wait_for_switches(args.ryu_url, expected_count=3, timeout=60.0):
            log("[ERROR] Timeout waiting for 3 switches to register in Ryu")
            sys.exit(1)
        log("All 3 switches registered in Ryu.")

        # Install primary flows
        log("Installing static primary flows (priority 100)...")
        install_primary_flows(args.ryu_url)

        # Baseline sanity ping
        log("Running sanity ping from h1 to h2...")
        ping_out = h1.cmd("ping -c 3 10.0.0.2")
        mininet_log.write("=== SANITY PING ===\n" + ping_out + "\n===================\n")
        log(f"Ping output:\n{ping_out.strip()}")

        # Start probe echo server on h2
        probe_server_py = os.path.join(PROJECT_DIR, "probe_server.py")
        probe_server_log = os.path.join(output_dir, "probe_server.log")
        log("Starting probe_server on h2 (0.0.0.0:9999)...")
        h2.cmd(f"PYTHONDONTWRITEBYTECODE=1 {VENV_PYTHON} {probe_server_py} -b 0.0.0.0 -p 9999 > {probe_server_log} 2>&1 &")
        time.sleep(1.0)

        # Helper to run CLI command from h1
        def run_h1_cli(cmd_str: str) -> str:
            full_cmd = f"PYTHONDONTWRITEBYTECODE=1 {VENV_PYTHON} {SDNSCOPE_CLI} {cmd_str}"
            log(f"Executing on h1: {full_cmd}")
            out = h1.cmd(full_cmd)
            mininet_log.write(f"=== CLI EXEC: {cmd_str} ===\n{out}\n========================\n")
            return out

        # Snapshot BEFORE probing
        log("Collecting telemetry baseline BEFORE probing...")
        collect_controller_telemetry(args.ryu_url, output_dir, "before")

        # Discover baseline topology with hosts file
        topo_json_path = os.path.join(output_dir, "topology.json")
        run_h1_cli(f"topo -c ryu -i 127.0.0.1 -p 8080 --hosts-file {hosts_json_path} -o {topo_json_path}")

        # Enumerate loop-free paths
        paths_json_path = os.path.join(output_dir, "paths.json")
        run_h1_cli(f"paths -s h1 -d h2 -f {topo_json_path} -o {paths_json_path}")

        diag_json_path = os.path.join(output_dir, "diagnostic_result.json")
        report_json_path = os.path.join(output_dir, "correlation_report.json")
        md_report_path = os.path.join(output_dir, "report.md")
        html_report_path = os.path.join(output_dir, "report.html")

        # -------------------------------------------------------------
        # SCENARIO EXECUTION
        # -------------------------------------------------------------
        if args.scenario == "healthy":
            log("Executing HEALTHY scenario: 50 probes at 0.05s interval...")
            run_h1_cli(f"probe 10.0.0.2 -p 9999 -c 50 --interval 0.05 -o {diag_json_path}")

            # Collect AFTER telemetry
            collect_controller_telemetry(args.ryu_url, output_dir, "after")

            # Correlate
            run_h1_cli(
                f"correlate -d {diag_json_path} -t {topo_json_path} -s h1 -e h2 "
                f"--controller {args.ryu_url} "
                f"--baseline-stats {os.path.join(output_dir, 'before_port_stats.json')} "
                f"--current-stats {os.path.join(output_dir, 'after_port_stats.json')} "
                f"-o {report_json_path}"
            )

            # Generate reports
            run_h1_cli(f"report -r {report_json_path} -d {diag_json_path} -m {md_report_path} -H {html_report_path} --dir {output_dir}")

        elif args.scenario == "degraded":
            log("Executing DEGRADED scenario: applying 30ms delay & 5% loss to s1-eth2 and s2-eth2...")
            # Use Mininet TCLink interface config
            net.get("s1").intf("s1-eth2").config(delay="30ms", loss=5)
            net.get("s2").intf("s2-eth2").config(delay="30ms", loss=5)

            # Record tc qdisc
            _, tc1_before, _ = run_cmd("tc -s qdisc show dev s1-eth2")
            _, tc2_before, _ = run_cmd("tc -s qdisc show dev s2-eth2")
            with open(os.path.join(output_dir, "tc_qdisc_before.txt"), "w") as f:
                f.write("s1-eth2:\n" + tc1_before + "\ns2-eth2:\n" + tc2_before)

            # Probe with count 100
            log("Running 100 probes at 0.05s interval across impaired link...")
            run_h1_cli(f"probe 10.0.0.2 -p 9999 -c 100 --interval 0.05 -o {diag_json_path}")

            # Record tc qdisc after
            _, tc1_after, _ = run_cmd("tc -s qdisc show dev s1-eth2")
            _, tc2_after, _ = run_cmd("tc -s qdisc show dev s2-eth2")
            with open(os.path.join(output_dir, "tc_qdisc_after.txt"), "w") as f:
                f.write("s1-eth2:\n" + tc1_after + "\ns2-eth2:\n" + tc2_after)

            collect_controller_telemetry(args.ryu_url, output_dir, "after")

            # Correlate
            run_h1_cli(
                f"correlate -d {diag_json_path} -t {topo_json_path} -s h1 -e h2 "
                f"--controller {args.ryu_url} "
                f"--baseline-stats {os.path.join(output_dir, 'before_port_stats.json')} "
                f"--current-stats {os.path.join(output_dir, 'after_port_stats.json')} "
                f"-o {report_json_path}"
            )

            run_h1_cli(f"report -r {report_json_path} -d {diag_json_path} -m {md_report_path} -H {html_report_path} --dir {output_dir}")

        elif args.scenario in ["failed", "recovery"]:
            log("Executing FAILED scenario: severing primary link s1 <-> s2...")
            net.configLinkStatus("s1", "s2", "down")

            log("Running probes on severed link (expecting ~100% loss)...")
            run_h1_cli(f"probe 10.0.0.2 -p 9999 -c 20 --interval 0.05 --timeout 0.5 -o {diag_json_path}")

            # Poll Ryu topology for link removal up to 30s
            log("Polling Ryu topology for link removal event...")
            poll_start = time.time()
            link_removed = False
            detect_time = 0.0
            links_url = f"{args.ryu_url.rstrip('/')}/v1.0/topology/links"

            while time.time() - poll_start < 30.0:
                current_links = rest_get(links_url) or []
                s1_s2_found = False
                for lnk in current_links:
                    s_dpid = lnk.get("src", {}).get("dpid")
                    d_dpid = lnk.get("dst", {}).get("dpid")
                    if (s_dpid == "0000000000000001" and d_dpid == "0000000000000002") or \
                       (s_dpid == "0000000000000002" and d_dpid == "0000000000000001"):
                        s1_s2_found = True
                        break
                if not s1_s2_found:
                    detect_time = time.time() - poll_start
                    link_removed = True
                    log(f"Link s1 <-> s2 removal detected by Ryu in {detect_time:.2f} seconds!")
                    break
                time.sleep(0.5)

            with open(os.path.join(output_dir, "link_failure_detection.txt"), "w") as f:
                f.write(f"link_removed: {link_removed}\ndetection_time_seconds: {detect_time:.2f}\n")

            # Discover current active topology after link failure
            topo_current_path = os.path.join(output_dir, "topology_current.json")
            run_h1_cli(f"topo -c ryu -i 127.0.0.1 -p 8080 --hosts-file {hosts_json_path} -o {topo_current_path}")

            collect_controller_telemetry(args.ryu_url, output_dir, "after")

            # Correlate with current topology diffing
            run_h1_cli(
                f"correlate -d {diag_json_path} -t {topo_json_path} -s h1 -e h2 "
                f"--controller {args.ryu_url} --current-topo {topo_current_path} "
                f"--baseline-stats {os.path.join(output_dir, 'before_port_stats.json')} "
                f"--current-stats {os.path.join(output_dir, 'after_port_stats.json')} "
                f"-o {report_json_path}"
            )

            run_h1_cli(f"report -r {report_json_path} -d {diag_json_path} -m {md_report_path} -H {html_report_path} --dir {output_dir}")

            # Reroute dry-run
            reroute_dry_run_txt = os.path.join(output_dir, "reroute_dry_run.txt")
            dry_out = run_h1_cli(f"reroute -r {report_json_path} -t {topo_json_path} -c {args.ryu_url}")
            with open(reroute_dry_run_txt, "w") as f:
                f.write(dry_out)

            if args.scenario == "recovery":
                log("Executing RECOVERY: applying backup flow modifications (priority 200)...")
                reroute_apply_txt = os.path.join(output_dir, "reroute_apply.txt")
                apply_out = run_h1_cli(f"reroute -r {report_json_path} -t {topo_json_path} -c {args.ryu_url} --apply")
                with open(reroute_apply_txt, "w") as f:
                    f.write(apply_out)

                time.sleep(2.0)

                diag_rec_path = os.path.join(output_dir, "diagnostic_result_recovered.json")
                log("Re-probing along recovered backup path...")
                run_h1_cli(f"probe 10.0.0.2 -p 9999 -c 50 --interval 0.05 -o {diag_rec_path}")

                collect_controller_telemetry(args.ryu_url, output_dir, "recovered")

                report_rec_path = os.path.join(output_dir, "correlation_report_recovered.json")
                md_rec_path = os.path.join(output_dir, "report_recovered.md")
                html_rec_path = os.path.join(output_dir, "report_recovered.html")

                run_h1_cli(
                    f"correlate -d {diag_rec_path} -t {topo_current_path} -s h1 -e h2 "
                    f"--controller {args.ryu_url} "
                    f"-o {report_rec_path}"
                )
                run_h1_cli(f"report -r {report_rec_path} -d {diag_rec_path} -m {md_rec_path} -H {html_rec_path} --dir {output_dir}")
                log("RECOVERY verification complete!")

        log(f"Scenario '{args.scenario}' completed successfully.")

    finally:
        log("Tearing down Mininet and background processes...")
        run_cmd("pkill -9 -f probe_server.py || true")
        if net:
            try:
                net.stop()
            except Exception as e:
                log(f"Error during net.stop(): {e}")
        mininet_log.close()


if __name__ == "__main__":
    main()
