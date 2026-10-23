#!/usr/bin/env python3
"""
SDN Flow Table and Port Statistics Inspector
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Communicates with Ryu's ofctl_rest API (/stats/switches, /stats/flow/<dpid>,
/stats/port/<dpid>) and ODL inventory to inspect installed flow rules,
reconstruct the ACTUAL active forwarding path used between two hosts,
and collect port-level delta statistics for failure localization.
"""

import argparse
import json
import logging
import os
import re
import sys

import requests

from sdn_topology import LLDP_DL_TYPE, LLDP_DST_MAC, dpid_to_decimal
from topology_graph import SDNTopologyGraph

DEFAULT_CONTROLLER_URL = "http://127.0.0.1:8080"
DEFAULT_TOPOLOGY_FILE = "topology.json"
DEFAULT_TIMEOUT = 5.0


def setup_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("flow_inspector")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def parse_output_port(action_str: str):
    """Extract port number or target from OpenFlow action string like 'OUTPUT:2'."""
    match = re.search(r'OUTPUT:(\d+|IN_PORT|FLOOD|ALL)', str(action_str))
    if match:
        val = match.group(1)
        return int(val) if val.isdigit() else val
    return None


def is_lldp_flow(flow: dict) -> bool:
    """Detect Ryu LLDP discovery flow: dl_type 35020, dl_dst 01:80:c2:00:00:0e, OUTPUT:CONTROLLER."""
    match = flow.get("match", {})
    dl_type = match.get("dl_type", match.get("eth_type"))
    dl_dst = match.get("dl_dst", match.get("eth_dst", ""))
    actions = flow.get("actions", [])
    has_controller_output = any("OUTPUT:CONTROLLER" in str(a) for a in actions)
    return (dl_type == LLDP_DL_TYPE and dl_dst and str(dl_dst).lower() == LLDP_DST_MAC.lower() and has_controller_output)


def is_table_miss_flow(flow: dict) -> bool:
    """Detect OpenFlow table-miss flow: priority 0 with match-all / empty match."""
    priority = flow.get("priority", 0)
    match = flow.get("match", {})
    return priority == 0 and (not match or match.get("dl_type") is None)


class FlowInspector:
    """Inspects flow tables and port metrics from SDN controller."""

    def __init__(self, controller_url: str = DEFAULT_CONTROLLER_URL,
                 topology_file: str = DEFAULT_TOPOLOGY_FILE,
                 timeout: float = DEFAULT_TIMEOUT,
                 verbose: bool = False):
        self.controller_url = controller_url.rstrip("/")
        self.topology_file = topology_file
        self.timeout = timeout
        self.logger = setup_logger(verbose)
        self.graph = SDNTopologyGraph()
        if os.path.exists(topology_file):
            self.graph.load_from_file(topology_file)

    def get_switches(self) -> list:
        """Fetch active DPIDs from /stats/switches."""
        url = f"{self.controller_url}/stats/switches"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.logger.warning(f"Could not query {url}: {e}")
            return []

    def get_flows(self, dpid: int) -> list:
        """Fetch installed flow rules for given DPID from /stats/flow/<dpid>.

        Ryu ofctl_rest expects a decimal DPID in the URL and returns
        {"<decimal dpid>": [flows]}.
        """
        dpid_decimal = dpid_to_decimal(dpid)
        url = f"{self.controller_url}/stats/flow/{dpid_decimal}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get(str(dpid_decimal), [])
        except Exception as e:
            self.logger.warning(f"Failed to fetch flow rules from {url}: {e}")
            return []

    def get_port_stats(self, dpid: int) -> list:
        """Fetch port statistics for given DPID from /stats/port/<dpid>."""
        url = f"{self.controller_url}/stats/port/{dpid}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get(str(dpid), [])
        except Exception as e:
            self.logger.warning(f"Failed to fetch port stats from {url}: {e}")
            return []

    def match_flow_rule(self, flows: list, dst_ip: str = None, dst_mac: str = None) -> dict:
        """
        Find highest priority flow rule matching destination IP or MAC.

        Parses real Ryu ofctl_rest OpenFlow 1.3 legacy match keys:
          dl_src, dl_dst, dl_type, in_port (integer), nw_src, nw_dst
        Accepts eth_src/eth_dst/eth_type as aliases too.
        Skips LLDP discovery flows and table-miss flows.
        """
        matching_rules = []
        for flow in flows:
            # Skip LLDP discovery flows
            if is_lldp_flow(flow):
                continue
            # Skip table-miss flows
            if is_table_miss_flow(flow):
                continue

            match = flow.get("match", {})
            priority = flow.get("priority", 0)

            # Normalize match keys: accept both legacy (dl_*, nw_*) and
            # modern (eth_*, ipv4_*) forms.
            match_dl_dst = match.get("dl_dst", match.get("eth_dst"))
            match_nw_dst = match.get("nw_dst", match.get("ipv4_dst"))

            matches_ip = (dst_ip and (match_nw_dst == dst_ip or match_dl_dst == dst_ip))
            matches_mac = (dst_mac and (match_dl_dst == dst_mac))

            if matches_ip or matches_mac:
                matching_rules.append((priority, flow))

        if not matching_rules:
            return None

        # Sort by priority descending
        matching_rules.sort(key=lambda x: x[0], reverse=True)
        return matching_rules[0][1]

    @staticmethod
    def _ports_match(p1, p2) -> bool:
        """Safely match port identifiers across integer and zero-padded hex formats."""
        if p1 is None or p2 is None:
            return False
        try:
            s1 = str(p1)
            s2 = str(p2)
            v1 = int(s1, 16) if (len(s1) > 4 or s1.startswith("0x")) else int(s1)
            v2 = int(s2, 16) if (len(s2) > 4 or s2.startswith("0x")) else int(s2)
            return v1 == v2
        except (ValueError, TypeError):
            return str(p1).lower() == str(p2).lower()

    def find_link_by_egress_port(self, current_switch: str, port_no: int) -> dict:
        """Find link in topology originating from current_switch on given port."""
        for link in self.graph.links:
            src = link.get("source")
            dst = link.get("destination")
            src_p = link.get("src_port")
            dst_p = link.get("dst_port")

            if src == current_switch and self._ports_match(src_p, port_no):
                return {"next_node": dst, "link": link}
            elif dst == current_switch and self._ports_match(dst_p, port_no):
                return {"next_node": src, "link": link}
        return None

    def reconstruct_active_path(self, src: str, dst: str) -> dict:
        """
        Reconstruct the ACTUAL active forwarding path by following flow tables.
        Falls back to shortest path if flow tables are unavailable or unpopulated.
        """
        src_node = self.graph.resolve_node(src)
        dst_node = self.graph.resolve_node(dst)

        if not src_node or not dst_node:
            return {
                "path_source": "unresolved",
                "path": [],
                "path_str": "None",
                "hop_count": 0,
                "error": f"Could not resolve nodes for src '{src}', dst '{dst}'"
            }

        dst_node_info = self.graph.nodes.get(dst_node, {})
        dst_ip = dst_node_info.get("ip") if dst_node_info.get("type") == "host" else (dst if "." in dst else None)
        dst_mac = dst_node_info.get("mac")

        # Determine ingress switch
        ingress_switch = None
        if self.graph.nodes.get(src_node, {}).get("type") == "host":
            ingress_switch = self.graph.nodes[src_node].get("connected_to")
            # If not in node attribute, search adjacent links
            if not ingress_switch:
                neighbors = self.graph.adj.get(src_node, set())
                for n in neighbors:
                    if self.graph.nodes.get(n, {}).get("type") == "switch":
                        ingress_switch = n
                        break
        else:
            ingress_switch = src_node

        if not ingress_switch:
            return self._fallback_shortest_path(src_node, dst_node, "No ingress switch found for source")

        current_node = ingress_switch
        traversed = [src_node] if src_node != ingress_switch else []
        traversed.append(ingress_switch)
        visited_switches = set([ingress_switch])
        flow_chain = []
        max_hops = 20

        while current_node != dst_node and len(traversed) < max_hops:
            # If current node is a host or destination, stop
            if current_node == dst_node:
                break

            # Convert friendly switch ID (s1) to decimal DPID (1) for ofctl_rest
            dpid_num = None
            dpid_str = self.graph.nodes.get(current_node, {}).get("dpid")
            if dpid_str:
                dpid_num = dpid_to_decimal(dpid_str)
            if dpid_num is None:
                match = re.search(r'\d+', current_node)
                dpid_num = int(match.group(0)) if match else None

            if dpid_num is None:
                return self._fallback_shortest_path(src_node, dst_node, f"Cannot determine numeric DPID for {current_node}")

            flows = self.get_flows(dpid_num)
            rule = self.match_flow_rule(flows, dst_ip=dst_ip, dst_mac=dst_mac)

            if not rule:
                return self._fallback_shortest_path(
                    src_node, dst_node,
                    f"No matching flow entry found in {current_node} (DPID {dpid_num}) for destination {dst_ip or dst_mac}"
                )

            # Find output port from actions
            out_port = None
            for action in rule.get("actions", []):
                p = parse_output_port(action)
                if p is not None:
                    out_port = p
                    break

            if out_port is None:
                return self._fallback_shortest_path(src_node, dst_node, f"Flow rule in {current_node} has no valid OUTPUT port")

            flow_chain.append({
                "switch": current_node,
                "dpid": dpid_num,
                "match": rule.get("match"),
                "out_port": out_port
            })

            # Check if this port directly connects to the destination host
            if dst_node_info.get("type") == "host":
                if dst_node_info.get("connected_to") == current_node and dst_node_info.get("switch_port") == out_port:
                    traversed.append(dst_node)
                    break

            # Otherwise, find next switch connected to this port
            next_hop = self.find_link_by_egress_port(current_node, out_port)
            if not next_hop:
                return self._fallback_shortest_path(src_node, dst_node, f"No topology link found from {current_node} port {out_port}")

            next_node = next_hop["next_node"]
            if next_node in visited_switches:
                return self._fallback_shortest_path(src_node, dst_node, f"Forwarding loop detected at {next_node}")

            traversed.append(next_node)
            visited_switches.add(next_node)
            current_node = next_node

        if traversed[-1] != dst_node:
            # Check if destination host is attached to the last switch
            if dst_node in self.graph.adj.get(traversed[-1], set()):
                traversed.append(dst_node)

        if traversed[-1] == dst_node:
            return {
                "path_source": "flow_table",
                "path": traversed,
                "path_str": " -> ".join(traversed),
                "hop_count": len(traversed) - 1,
                "flow_chain": flow_chain,
                "note": "Path verified from active OpenFlow flow tables across switches."
            }

        return self._fallback_shortest_path(src_node, dst_node, "Flow chain ended before reaching destination")

    def _fallback_shortest_path(self, src: str, dst: str, reason: str) -> dict:
        """Fall back to graph BFS shortest path when flow entries are incomplete."""
        self.logger.debug(f"Flow-table path resolution fallback: {reason}")
        paths = self.graph.find_all_simple_paths(src, dst, max_paths=1)
        if paths:
            primary = paths[0]
            return {
                "path_source": "assumed_shortest",
                "path": primary,
                "path_str": " -> ".join(primary),
                "hop_count": len(primary) - 1,
                "fallback_reason": reason,
                "note": "Flow entries unavailable; path assumed based on BFS topological shortest path."
            }
        return {
            "path_source": "none",
            "path": [],
            "path_str": "None",
            "hop_count": 0,
            "fallback_reason": reason,
            "error": "No topological path exists between nodes."
        }


def main():
    parser = argparse.ArgumentParser(
        description="Inspect SDN Flow Tables and Reconstruct Active Data-Plane Forwarding Paths."
    )
    parser.add_argument("-s", "--source", required=True, help="Source node ID or IP (e.g. h1 or 10.0.0.1)")
    parser.add_argument("-d", "--dest", required=True, help="Destination node ID or IP (e.g. h2 or 10.0.0.2)")
    parser.add_argument("-c", "--controller", default=DEFAULT_CONTROLLER_URL, help=f"SDN controller URL (default: {DEFAULT_CONTROLLER_URL})")
    parser.add_argument("-t", "--topo", default=DEFAULT_TOPOLOGY_FILE, help=f"Topology JSON file (default: {DEFAULT_TOPOLOGY_FILE})")
    parser.add_argument("-o", "--output", help="Optional output JSON filepath")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    inspector = FlowInspector(
        controller_url=args.controller,
        topology_file=args.topo,
        verbose=args.verbose
    )

    result = inspector.reconstruct_active_path(args.source, args.dest)

    print("=" * 72)
    print("           SDN ACTIVE FORWARDING PATH INSPECTION REPORT")
    print("=" * 72)
    print(f" Source:          {args.source}")
    print(f" Destination:     {args.dest}")
    print(f" Path Source:     {result.get('path_source').upper()}")
    print(f" Active Path:     {result.get('path_str')}")
    print(f" Hop Count:       {result.get('hop_count')}")
    if "fallback_reason" in result:
        print(f" Fallback Reason: {result.get('fallback_reason')}")
    if "note" in result:
        print(f" Note:            {result.get('note')}")
    print("=" * 72)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"[INFO] Path inspection saved to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to save {args.output}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
