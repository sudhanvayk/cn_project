#!/usr/bin/env python3
"""
Verify and capture live output of all SDNScope CLI subcommands
on a live Mininet + Ryu testbed.
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.
"""

import json
import os
import signal
import subprocess
import sys
import time

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

from reroute_helper import install_primary_flows
from topology.diamond_topo import DiamondTopo


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def run_cmd(cmd):
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.stdout.strip()


def main():
    log("=== STARTING LIVE CLI VERIFICATION HARNESS ===")
    out_dir = os.path.join(PROJECT_ROOT, "results", "cli_verification")
    os.makedirs(out_dir, exist_ok=True)
    cli_log_path = os.path.join(out_dir, "cli_verification.log")
    cli_log = open(cli_log_path, "w", encoding="utf-8")

    def record(title, content):
        log(f"--- {title} ---")
        cli_log.write(f"\n{'='*70}\n=== {title} ===\n{'='*70}\n")
        cli_log.write(content + "\n")
        print(content, flush=True)

    # 1. Start Ryu
    log("Ensuring clean state & starting Ryu...")
    run_cmd(f"{PROJECT_ROOT}/scripts/run_ryu.sh stop || true")
    run_cmd("sudo mn -c 2>&1")
    run_cmd(f"{PROJECT_ROOT}/scripts/run_ryu.sh start")

    hosts_file = os.path.join(out_dir, "hosts.json")
    hosts_data = [
        {"name": "h1", "mac": "00:00:00:00:00:01", "ip": "10.0.0.1", "dpid": "0000000000000001", "port": 1},
        {"name": "h2", "mac": "00:00:00:00:00:02", "ip": "10.0.0.2", "dpid": "0000000000000002", "port": 1},
    ]
    with open(hosts_file, "w") as f:
        json.dump(hosts_data, f, indent=2)

    net = None
    try:
        log("Starting Mininet network...")
        net = Mininet(
            topo=DiamondTopo(),
            controller=lambda name: RemoteController(name, ip="127.0.0.1", port=6653),
            switch=OVSSwitch,
            link=TCLink,
            autoSetMacs=True,
        )
        net.start()
        for sw in net.switches:
            sw.cmd(f"ovs-vsctl set Bridge {sw.name} fail_mode=secure")

        h1 = net.get("h1")
        h2 = net.get("h2")
        h1.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
        h2.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
        h1.setARP("10.0.0.2", "00:00:00:00:00:02")
        h2.setARP("10.0.0.1", "00:00:00:00:00:01")

        log("Installing static primary flows...")
        install_primary_flows("http://127.0.0.1:8080")
        time.sleep(1.0)

        # Baseline ping
        ping_out = h1.cmd("ping -c 2 10.0.0.2")
        log(f"Ping sanity: {ping_out.strip()}")

        py_bin = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
        sdnscope_bin = os.path.join(PROJECT_ROOT, "sdnscope.py")
        topo_out_path = os.path.join(out_dir, "topology.json")
        paths_out_path = os.path.join(out_dir, "paths.json")

        # 1. Test sdnscope.py topo
        cmd_topo = f"{py_bin} {sdnscope_bin} topo -c ryu -i 127.0.0.1 -p 8080 --hosts-file {hosts_file} -o {topo_out_path}"
        topo_output = run_cmd(cmd_topo)
        record("COMMAND: sdnscope.py topo", topo_output)

        # 2. Test sdnscope.py paths
        cmd_paths = f"{py_bin} {sdnscope_bin} paths -s h1 -d h2 -f {topo_out_path} -o {paths_out_path}"
        paths_output = run_cmd(cmd_paths)
        record("COMMAND: sdnscope.py paths -s h1 -d h2", paths_output)

        # 3. Test sdnscope.py trace
        trace_cmd = f"{py_bin} {sdnscope_bin} trace 10.0.0.2 --timeout 1.0 --max-hops 5"
        trace_output = h1.cmd(trace_cmd)
        record("COMMAND: sdnscope.py trace 10.0.0.2 (from h1)", trace_output)

        # 4. Test sdnscope.py watch
        log("Testing sdnscope.py watch live link bounce...")
        watch_cmd = [py_bin, sdnscope_bin, "watch", "-c", "ryu", "-i", "127.0.0.1", "-p", "8080", "--interval", "1"]
        watch_proc = subprocess.Popen(watch_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        time.sleep(2.0)
        log("Bouncing link s1 <-> s2 DOWN in Mininet...")
        net.configLinkStatus("s1", "s2", "down")
        time.sleep(3.0)

        log("Stopping watch process...")
        watch_proc.send_signal(signal.SIGINT)
        try:
            watch_stdout, watch_stderr = watch_proc.communicate(timeout=3.0)
        except subprocess.TimeoutExpired:
            watch_proc.kill()
            watch_stdout, watch_stderr = watch_proc.communicate()

        watch_combined = watch_stdout + ("\nSTDERR:\n" + watch_stderr if watch_stderr else "")
        record("COMMAND: sdnscope.py watch (with live link bounce)", watch_combined)

        log("Restoring link s1 <-> s2 UP...")
        net.configLinkStatus("s1", "s2", "up")
        time.sleep(1.0)

        # 5. Test sdnscope.py report
        latest_report = os.path.join(PROJECT_ROOT, "results", "latest", "healthy", "correlation_report.json")
        latest_diag = os.path.join(PROJECT_ROOT, "results", "latest", "healthy", "diagnostic_result.json")
        md_test = os.path.join(out_dir, "test_report.md")
        html_test = os.path.join(out_dir, "test_report.html")
        cmd_report = f"{py_bin} {sdnscope_bin} report -r {latest_report} -d {latest_diag} -m {md_test} -H {html_test} --dir {out_dir}"
        report_output = run_cmd(cmd_report)
        record("COMMAND: sdnscope.py report", report_output)

    finally:
        log("Cleaning up...")
        if net:
            try:
                net.stop()
            except Exception as e:
                log(f"Error stopping Mininet: {e}")
        run_cmd(f"{PROJECT_ROOT}/scripts/run_ryu.sh stop || true")
        run_cmd("sudo mn -c 2>&1")
        cli_log.close()
        run_cmd(f"sudo chown -R sudh:sudh {PROJECT_ROOT}/results")
        log(f"Verification complete. Artifacts in: {out_dir}")


if __name__ == "__main__":
    main()
