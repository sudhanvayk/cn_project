#!/usr/bin/env python3
"""
Mininet Diamond Topology for SDN Diagnostic and Path Analysis
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Topology:
      h1 (10.0.0.1)
        |
       s1 (DPID 1)
      /  \\
(pri)/    \\(alt)
    s2    s3 (DPID 3)
     \\    /
      \\  /
       s2 (DPID 2)
        |
      h2 (10.0.0.2)

Primary Path: h1 -> s1 -> s2 -> h2 (3 hops)
Alternative:  h1 -> s1 -> s3 -> s2 -> h2 (4 hops)
"""

import sys

try:
    from mininet.cli import CLI
    from mininet.link import TCLink
    from mininet.log import info, setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo
except ImportError:
    print("[WARN] Mininet is not installed in the current Python environment.", file=sys.stderr)
    print("[INFO] Refer to SETUP.md for installation instructions or use scripts/demo_localhost.sh.", file=sys.stderr)


class DiamondTopo(Topo):
    """Diamond topology with primary s1-s2 link and backup s1-s3-s2 path."""

    def build(self):
        # 1. Add Switches (OpenFlow 1.3)
        s1 = self.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13")
        s3 = self.addSwitch("s3", dpid="0000000000000003", protocols="OpenFlow13")

        # 2. Add Hosts
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

        # 3. Add Host Links
        # h1 connects to s1 port 1
        self.addLink(h1, s1, port1=1, port2=1, cls=TCLink, bw=100, delay="1ms")
        # h2 connects to s2 port 1
        self.addLink(h2, s2, port1=1, port2=1, cls=TCLink, bw=100, delay="1ms")

        # 4. Add Inter-Switch Links (TCLink allows delay and bandwidth shaping)
        # Primary link: s1 port 2 <-> s2 port 2
        self.addLink(s1, s2, port1=2, port2=2, cls=TCLink, bw=10, delay="2ms")

        # Backup path: s1 port 3 <-> s3 port 1, s3 port 2 <-> s2 port 3
        self.addLink(s1, s3, port1=3, port2=1, cls=TCLink, bw=10, delay="2ms")
        self.addLink(s3, s2, port1=2, port2=3, cls=TCLink, bw=10, delay="2ms")


topos = {"diamond": (lambda: DiamondTopo())}


def run():
    topo = DiamondTopo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(name, ip="127.0.0.1", port=6633),
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True
    )
    info("*** Starting Network ***\n")
    net.start()
    info("*** Populating Initial ARP Tables ***\n")
    net.pingAll()
    info("*** Running Mininet CLI ***\n")
    CLI(net)
    info("*** Stopping Network ***\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
