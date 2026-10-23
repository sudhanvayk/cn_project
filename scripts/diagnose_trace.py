#!/usr/bin/env python3
"""
Diagnostic script for traceroute, raw sockets, ICMP replies, and OpenFlow flows.
"""

import os
import subprocess
import sys
import time

import requests

PROJECT_ROOT = "/home/sudh/Documents/cn_project"
sys.path.insert(0, PROJECT_ROOT)

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

from reroute_helper import install_primary_flows
from topology.diamond_topo import DiamondTopo


def run_cmd(cmd):
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.stdout.strip(), p.stderr.strip(), p.returncode


def wait_for_switches(ryu_url="http://127.0.0.1:8080", expected_count=3, timeout=30.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{ryu_url}/v1.0/topology/switches", timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) >= expected_count:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    print("=== STARTING TRACEROUTE & ICMP DIAGNOSIS ===")

    # Clean previous
    run_cmd(f"{PROJECT_ROOT}/scripts/run_ryu.sh stop || true")
    run_cmd("sudo mn -c 2>&1")
    run_cmd(f"{PROJECT_ROOT}/scripts/run_ryu.sh start")

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

    print("Waiting for switches to connect to Ryu...")
    if not wait_for_switches():
        print("[ERROR] Switches did not connect to Ryu in time")
        sys.exit(1)

    print("Installing primary flows...")
    install_primary_flows("http://127.0.0.1:8080", apply_changes=True)
    time.sleep(1.0)

    # Dump flows
    print("\n--- OVS FLOWS S1 ---")
    out, _, _ = run_cmd("sudo ovs-ofctl -O OpenFlow13 dump-flows s1")
    print(out)

    print("\n--- OVS FLOWS S2 ---")
    out, _, _ = run_cmd("sudo ovs-ofctl -O OpenFlow13 dump-flows s2")
    print(out)

    # Ping test
    print("\n--- PING TEST H1 -> H2 ---")
    ping_out = h1.cmd("ping -c 3 10.0.0.2")
    print(ping_out)

    # Find h1 interface
    intf_name = h1.defaultIntf().name
    print(f"\nH1 default interface: {intf_name}")

    # Start tcpdump on h1
    print("\n--- STARTING TCPDUMP ON H1 ---")
    h1.cmd(f"tcpdump -ni {intf_name} icmp or udp -vv -l > /tmp/h1_tcpdump.log 2>&1 &")
    time.sleep(1.0)

    # System traceroute
    print("\n--- SYSTEM TRACEROUTE: h1 traceroute -n -m 5 10.0.0.2 ---")
    tr_out = h1.cmd("traceroute -n -m 5 10.0.0.2")
    print(tr_out)

    # Also test ICMP traceroute: traceroute -I
    print("\n--- SYSTEM TRACEROUTE (ICMP MODE): h1 traceroute -I -n -m 5 10.0.0.2 ---")
    tr_icmp_out = h1.cmd("traceroute -I -n -m 5 10.0.0.2")
    print(tr_icmp_out)

    # System tracepath
    print("\n--- SYSTEM TRACEPATH: h1 tracepath -n -m 5 10.0.0.2 ---")
    tp_out = h1.cmd("tracepath -n -m 5 10.0.0.2")
    print(tp_out)

    time.sleep(1.0)
    h1.cmd("pkill -f tcpdump || true")
    time.sleep(0.5)

    print("\n--- TCPDUMP LOG ON H1 ---")
    if os.path.exists("/tmp/h1_tcpdump.log"):
        with open("/tmp/h1_tcpdump.log") as f:
            print(f.read())

    # Raw socket diagnostic inside h1
    print("\n--- PYTHON RAW SOCKET TEST INSIDE H1 ---")
    py_test = """
import socket, time
print('Testing raw ICMP socket in python inside h1...')
icmp_sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
icmp_sock.settimeout(2.0)
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
udp_sock.setsockopt(socket.SOL_IP, socket.IP_TTL, 1)
udp_sock.sendto(b'SDN_TRACEROUTE_PROBE', ('10.0.0.2', 33434))
try:
    data, addr = icmp_sock.recvfrom(512)
    print(f'SUCCESS: Received ICMP from {addr}: {len(data)} bytes')
except socket.timeout:
    print('TIMEOUT waiting for ICMP raw socket')
except Exception as e:
    print(f'EXCEPTION: {e}')
"""
    raw_res = h1.cmd(f"python3 -c \"{py_test}\"")
    print(raw_res)

    # Also test with IP_RECVERR on UDP socket!
    print("\n--- PYTHON UDP SOCKET WITH IP_RECVERR ---")
    py_err_test = """
import socket, time
print('Testing UDP socket with IP_RECVERR inside h1...')
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
udp_sock.setsockopt(socket.SOL_IP, socket.IP_TTL, 1)
udp_sock.setsockopt(socket.SOL_IP, 11, 1) # IP_RECVERR
udp_sock.sendto(b'SDN_TRACEROUTE_PROBE', ('10.0.0.2', 33435))
time.sleep(0.1)
try:
    data, ancdata, msg_flags, addr = udp_sock.recvmsg(512, 512, socket.MSG_ERRQUEUE)
    print(f'SUCCESS MSG_ERRQUEUE: addr={addr}, flags={msg_flags}, ancdata={ancdata}')
except Exception as e:
    print(f'MSG_ERRQUEUE: {e}')
"""
    raw_err_res = h1.cmd(f"python3 -c \"{py_err_test}\"")
    print(raw_err_res)

    net.stop()
    run_cmd(f"{PROJECT_ROOT}/scripts/run_ryu.sh stop || true")
    run_cmd("sudo mn -c 2>&1")


if __name__ == "__main__":
    main()
