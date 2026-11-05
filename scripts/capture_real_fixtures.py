#!/usr/bin/env python3
"""
Live bring-up and genuine fixture capture script for SDNScope (Phase 3).
Executes against real Mininet Diamond topology and Ryu controller.
Runs as root using system python3.
"""

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
    print(f"[FATAL] Mininet not found: {exc}", file=sys.stderr)
    sys.exit(1)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(PROJECT_DIR, "tests/fixtures/real_diamond")
REST_URL = "http://127.0.0.1:8080"
OF_PORT = 6653


class DiamondTopo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13", failMode="secure")
        s2 = self.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13", failMode="secure")
        s3 = self.addSwitch("s3", dpid="0000000000000003", protocols="OpenFlow13", failMode="secure")

        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

        # Host links
        self.addLink(h1, s1, port1=1, port2=1, cls=TCLink, bw=100, delay="1ms")
        self.addLink(h2, s2, port1=1, port2=1, cls=TCLink, bw=100, delay="1ms")

        # Core links
        self.addLink(s1, s2, port1=2, port2=2, cls=TCLink, bw=10, delay="2ms")
        self.addLink(s1, s3, port1=3, port2=1, cls=TCLink, bw=10, delay="2ms")
        self.addLink(s3, s2, port1=2, port2=3, cls=TCLink, bw=10, delay="2ms")


def http_get(path):
    url = f"{REST_URL.rstrip('/')}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "SDNScopeCapture/1.0"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post(path, data):
    url = f"{REST_URL.rstrip('/')}{path}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "SDNScopeCapture/1.0"},
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return resp.getcode()


def save_json(filename, data):
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    filepath = os.path.join(FIXTURES_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[CAPTURED] {filename} ({len(json.dumps(data))} bytes)")


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    print("=" * 72)
    print("      LIVE RYU + MININET BRING-UP AND FIXTURE CAPTURE (PHASE 3)        ")
    print("=" * 72)

    # 1. Start Ryu
    print("\n[STEP 1] Starting Ryu Controller via scripts/run_ryu.sh...")
    subprocess.run([os.path.join(PROJECT_DIR, "scripts/run_ryu.sh"), "start", "/tmp/ryu_capture.log"], check=True)

    net = None
    try:
        # 2. Start Mininet Diamond Topology
        print("\n[STEP 2] Starting Mininet Diamond Topology...")
        topo = DiamondTopo()
        net = Mininet(
            topo=topo,
            controller=lambda name: RemoteController(name, ip="127.0.0.1", port=OF_PORT),
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

        # 3. Gate 3.1 Verification: Switches list & ovs-vsctl show
        print("\n" + "=" * 72)
        print(">>> VERIFICATION GATE 3.1: RYU UP & SWITCHES CONNECTED <<<")
        print("=" * 72)
        start_wait = time.time()
        switches_data = None
        while time.time() - start_wait < 30.0:
            try:
                sws = http_get("/v1.0/topology/switches")
                if isinstance(sws, list) and len(sws) >= 3:
                    switches_data = sws
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not switches_data:
            print("[ERROR] Failed to discover 3 switches in Ryu!")
            sys.exit(1)

        print("[GATE 3.1 REAL OUTPUT] GET /v1.0/topology/switches:")
        print(json.dumps(switches_data, indent=2))

        print("\n[GATE 3.1 REAL OUTPUT] sudo ovs-vsctl show:")
        ovs_out = subprocess.check_output(["ovs-vsctl", "show"], text=True)
        print(ovs_out)

        # 4. Install Primary Flows
        print("\n[STEP 3] Installing static primary flows...")
        primary_rules = [
            {"dpid": 1, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]},
            {"dpid": 1, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]},
            {"dpid": 1, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]},
            {"dpid": 1, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]},
            {"dpid": 2, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 1}]},
            {"dpid": 2, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 1}]},
            {"dpid": 2, "priority": 100, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 2}]},
            {"dpid": 2, "priority": 100, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 2}]},
        ]
        for r in primary_rules:
            http_post("/stats/flowentry/add", r)

        # 5. Gate 3.2 Verification: Primary flows & Ping
        print("\n" + "=" * 72)
        print(">>> VERIFICATION GATE 3.2: STATIC FLOWS INSTALLED & PING <<<")
        print("=" * 72)
        flow_s1 = http_get("/stats/flow/1")
        flow_s2 = http_get("/stats/flow/2")
        print("[GATE 3.2 REAL OUTPUT] /stats/flow/1:")
        print(json.dumps(flow_s1, indent=2))
        print("\n[GATE 3.2 REAL OUTPUT] /stats/flow/2:")
        print(json.dumps(flow_s2, indent=2))

        ping_out = h1.cmd("ping -c 3 10.0.0.2")
        print("\n[GATE 3.2 REAL OUTPUT] Mininet h1 ping -c 3 h2:")
        print(ping_out.strip())

        # 6. Gate 3.3 Verification: Links & Hosts
        print("\n" + "=" * 72)
        print(">>> VERIFICATION GATE 3.3: LINKS API & HOSTS API <<<")
        print("=" * 72)
        # Give Ryu LLDP link discovery a couple seconds to observe all links
        time.sleep(2.0)
        links_data = http_get("/v1.0/topology/links")
        hosts_data = http_get("/v1.0/topology/hosts")
        stats_switches = http_get("/stats/switches")

        print("[GATE 3.3 REAL OUTPUT] GET /v1.0/topology/links (count: %d):" % len(links_data))
        print(json.dumps(links_data, indent=2))
        print("\n[GATE 3.3 REAL OUTPUT] GET /v1.0/topology/hosts:")
        print(json.dumps(hosts_data, indent=2))

        flow_s3 = http_get("/stats/flow/3")
        port_s1 = http_get("/stats/port/1")
        port_s2 = http_get("/stats/port/2")
        port_s3 = http_get("/stats/port/3")

        # Save fixtures to tests/fixtures/real_diamond/
        print("\n[STEP 4] Saving baseline fixtures to tests/fixtures/real_diamond/...")
        save_json("switches.json", switches_data)
        save_json("links.json", links_data)
        save_json("hosts.json", hosts_data)
        save_json("stats_switches.json", stats_switches)
        save_json("flow_s1.json", flow_s1)
        save_json("flow_s2.json", flow_s2)
        save_json("flow_s3.json", flow_s3)
        save_json("port_s1.json", port_s1)
        save_json("port_s2.json", port_s2)
        save_json("port_s3.json", port_s3)

        # 7. Install Backup flows and capture flow_s*_backup.json
        print("\n[STEP 5] Installing backup flows (priority 200) and capturing backup flow fixtures...")
        backup_rules = [
            {"dpid": 1, "priority": 200, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 3}]},
            {"dpid": 1, "priority": 200, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 3}]},
            {"dpid": 3, "priority": 200, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]},
            {"dpid": 3, "priority": 200, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 2}]},
            {"dpid": 3, "priority": 200, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]},
            {"dpid": 3, "priority": 200, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 1}]},
            {"dpid": 2, "priority": 200, "match": {"eth_type": 2048, "ipv4_dst": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 3}]},
            {"dpid": 2, "priority": 200, "match": {"eth_type": 2054, "arp_tpa": "10.0.0.1"}, "actions": [{"type": "OUTPUT", "port": 3}]},
        ]
        for r in backup_rules:
            http_post("/stats/flowentry/add", r)

        flow_s1_backup = http_get("/stats/flow/1")
        flow_s2_backup = http_get("/stats/flow/2")
        flow_s3_backup = http_get("/stats/flow/3")

        save_json("flow_s1_backup.json", flow_s1_backup)
        save_json("flow_s2_backup.json", flow_s2_backup)
        save_json("flow_s3_backup.json", flow_s3_backup)

        print("\n[SUCCESS] All live responses captured to tests/fixtures/real_diamond/!")

    finally:
        print("\n[STEP 6] Teardown Mininet and Ryu...")
        if net:
            net.stop()
        subprocess.run([os.path.join(PROJECT_DIR, "scripts/run_ryu.sh"), "stop"])
        subprocess.run(["chown", "-R", "sudh:sudh", FIXTURES_DIR])
        subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
