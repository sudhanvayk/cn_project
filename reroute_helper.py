#!/usr/bin/env python3
"""
SDN Backup Path Flow Rerouting Assistant
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Reads diagnosis reports, identifies the recommended failover route, and installs
high-priority OpenFlow flow entries along the backup path via Ryu's /stats/flowentry/add API.
Defaults to safe --dry-run mode; requires explicit --apply to push flow modifications.
"""

import argparse
import json
import logging
import os
import re
import sys

import requests

from topology_graph import SDNTopologyGraph

DEFAULT_CONTROLLER_URL = "http://127.0.0.1:8080"
DEFAULT_REPORT_FILE = "correlation_report.json"
DEFAULT_TOPOLOGY_FILE = "topology.json"
DEFAULT_PRIORITY = 200
DEFAULT_TIMEOUT = 5.0


def setup_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("reroute_helper")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def extract_dpid_num(node_str: str) -> int:
    """Extract integer DPID from switch name like 's1' or 'openflow:1'."""
    m = re.search(r'\d+', node_str)
    return int(m.group(0)) if m else None


def _generate_unidirectional_rules(path: list, graph: SDNTopologyGraph, target_ip: str,
                                   priority: int = DEFAULT_PRIORITY,
                                   include_arp: bool = False) -> list:
    """Generate flow modification payloads for one direction along a path."""
    flow_rules = []
    switches = [n for n in path if graph.nodes.get(n, {}).get("type") == "switch"]

    for i in range(len(switches)):
        curr_sw = switches[i]
        dpid = extract_dpid_num(curr_sw)

        # Determine next node in path
        if i + 1 < len(switches):
            next_node = switches[i + 1]
        else:
            # Last switch connects to destination host
            next_node = path[-1]

        # Find egress port connecting curr_sw to next_node
        egress_port = None
        for link in graph.links:
            s, d = link.get("source"), link.get("destination")
            if s == curr_sw and d == next_node:
                egress_port = link.get("src_port")
                break
            elif d == curr_sw and s == next_node:
                egress_port = link.get("dst_port")
                break

        if egress_port is None:
            # Fall back to host switch_port if next_node is host
            if graph.nodes.get(next_node, {}).get("type") == "host":
                egress_port = graph.nodes[next_node].get("switch_port", 1)
            else:
                egress_port = 1

        payload_ipv4 = {
            "dpid": dpid,
            "cookie": 1,
            "cookie_mask": 1,
            "table_id": 0,
            "idle_timeout": 0,
            "hard_timeout": 0,
            "priority": priority,
            "flags": 1,
            "match": {
                "ipv4_dst": target_ip,
                "eth_type": 2048,
            },
            "actions": [
                {
                    "type": "OUTPUT",
                    "port": int(egress_port),
                }
            ],
        }
        flow_rules.append(payload_ipv4)

        if include_arp:
            payload_arp = {
                "dpid": dpid,
                "cookie": 1,
                "cookie_mask": 1,
                "table_id": 0,
                "idle_timeout": 0,
                "hard_timeout": 0,
                "priority": priority,
                "flags": 1,
                "match": {
                    "arp_tpa": target_ip,
                    "eth_type": 2054,
                },
                "actions": [
                    {
                        "type": "OUTPUT",
                        "port": int(egress_port),
                    }
                ],
            }
            flow_rules.append(payload_arp)

    return flow_rules


def generate_flow_entries(path: list, graph: SDNTopologyGraph, dst_ip: str,
                          priority: int = DEFAULT_PRIORITY,
                          bidirectional: bool = False,
                          src_ip: str = None,
                          include_arp: bool = False) -> list:
    """
    Generate OpenFlow 1.3 flow modification rule payloads along the path.

    Args:
        path: List of node names (e.g. ['h1', 's1', 's3', 's2', 'h2'])
        graph: SDNTopologyGraph instance
        dst_ip: Destination IPv4 address
        priority: OpenFlow priority (default: DEFAULT_PRIORITY)
        bidirectional: If True, also generate reverse flows for src_ip
        src_ip: Source IPv4 address (inferred from path[0] if omitted)
        include_arp: If True, also install ARP (eth_type 2054) matching rules

    Returns:
        list of dict: OpenFlow flow entry payloads ready for /stats/flowentry/add
    """
    if priority is None:
        priority = DEFAULT_PRIORITY

    rules = _generate_unidirectional_rules(path, graph, target_ip=dst_ip,
                                           priority=priority, include_arp=include_arp)

    if bidirectional:
        resolved_src_ip = src_ip
        if not resolved_src_ip and len(path) > 0:
            first_node = path[0]
            resolved_src_ip = graph.nodes.get(first_node, {}).get("ip")

        if resolved_src_ip:
            rev_path = list(reversed(path))
            rev_rules = _generate_unidirectional_rules(rev_path, graph, target_ip=resolved_src_ip,
                                                       priority=priority, include_arp=include_arp)
            rules.extend(rev_rules)

    return rules


def build_primary_flow_rules(priority: int = 100) -> list:
    """
    Generate OpenFlow 1.3 flow entries for the primary path (h1-s1-s2-h2).
    Both IPv4 (eth_type 2048) and ARP (eth_type 2054) rules are created.
    """
    specs = [
        # s1: dst 10.0.0.2 -> OUTPUT 2 (towards s2); dst 10.0.0.1 -> OUTPUT 1 (towards h1)
        (1, "10.0.0.2", 2),
        (1, "10.0.0.1", 1),
        # s2: dst 10.0.0.2 -> OUTPUT 1 (towards h2); dst 10.0.0.1 -> OUTPUT 2 (towards s1)
        (2, "10.0.0.2", 1),
        (2, "10.0.0.1", 2),
    ]
    rules = []
    for dpid, ip, out_port in specs:
        # IPv4 rule
        rules.append({
            "dpid": dpid,
            "priority": priority,
            "match": {"eth_type": 2048, "ipv4_dst": ip},
            "actions": [{"type": "OUTPUT", "port": out_port}],
        })
        # ARP rule
        rules.append({
            "dpid": dpid,
            "priority": priority,
            "match": {"eth_type": 2054, "arp_tpa": ip},
            "actions": [{"type": "OUTPUT", "port": out_port}],
        })
    return rules


def build_backup_flow_rules(priority: int = 200) -> list:
    """
    Generate OpenFlow 1.3 flow entries for the backup path (h1-s1-s3-s2-h2).
    Both IPv4 (eth_type 2048) and ARP (eth_type 2054) rules are created.
    """
    specs = [
        # s1: dst 10.0.0.2 -> OUTPUT 3 (towards s3)
        (1, "10.0.0.2", 3),
        # s3: dst 10.0.0.2 -> OUTPUT 2 (towards s2); dst 10.0.0.1 -> OUTPUT 1 (towards s1)
        (3, "10.0.0.2", 2),
        (3, "10.0.0.1", 1),
        # s2: dst 10.0.0.1 -> OUTPUT 3 (towards s3)
        (2, "10.0.0.1", 3),
    ]
    rules = []
    for dpid, ip, out_port in specs:
        # IPv4 rule
        rules.append({
            "dpid": dpid,
            "priority": priority,
            "match": {"eth_type": 2048, "ipv4_dst": ip},
            "actions": [{"type": "OUTPUT", "port": out_port}],
        })
        # ARP rule
        rules.append({
            "dpid": dpid,
            "priority": priority,
            "match": {"eth_type": 2054, "arp_tpa": ip},
            "actions": [{"type": "OUTPUT", "port": out_port}],
        })
    return rules


def install_flows_to_controller(flow_rules: list, controller_url: str = DEFAULT_CONTROLLER_URL,
                                apply_changes: bool = False, delete_first: bool = True,
                                verbose: bool = False) -> dict:
    """
    Send or display flow rules, optionally deleting strict matches first to prevent duplicates.
    """
    logger = setup_logger(verbose)
    base_url = controller_url.rstrip("/")
    add_url = f"{base_url}/stats/flowentry/add"
    del_url = f"{base_url}/stats/flowentry/delete_strict"
    results = []

    for rule in flow_rules:
        dpid = rule.get("dpid")
        match = rule.get("match", {})
        prio = rule.get("priority", 100)
        out_port = rule.get("actions", [{}])[0].get("port")

        if not apply_changes:
            results.append({"dpid": dpid, "status": "DRY_RUN", "payload": rule})
            continue

        if delete_first:
            del_payload = {"dpid": dpid, "priority": prio, "match": match}
            try:
                requests.post(del_url, json=del_payload, timeout=DEFAULT_TIMEOUT)
            except Exception as e:
                logger.debug(f"delete_strict failed on dpid {dpid}: {e}")

        try:
            resp = requests.post(add_url, json=rule, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            logger.info(f"Installed flow on DPID {dpid}: match={match} -> port {out_port} (HTTP {resp.status_code})")
            results.append({"dpid": dpid, "status": "SUCCESS", "code": resp.status_code})
        except Exception as e:
            logger.error(f"Failed to install flow on DPID {dpid}: {e}")
            results.append({"dpid": dpid, "status": "ERROR", "error": str(e)})

    return {"applied": apply_changes, "rules_count": len(flow_rules), "results": results}


def install_primary_flows(controller_url: str = DEFAULT_CONTROLLER_URL,
                           priority: int = 100, apply_changes: bool = False,
                           delete_first: bool = True, verbose: bool = False) -> dict:
    """Install static bidirectional primary flows (h1-s1-s2-h2)."""
    rules = build_primary_flow_rules(priority=priority)
    return install_flows_to_controller(rules, controller_url=controller_url,
                                       apply_changes=apply_changes, delete_first=delete_first,
                                       verbose=verbose)


def install_backup_flows(controller_url: str = DEFAULT_CONTROLLER_URL,
                          priority: int = 200, apply_changes: bool = False,
                          delete_first: bool = True, verbose: bool = False) -> dict:
    """Install static bidirectional backup flows (h1-s1-s3-s2-h2)."""
    rules = build_backup_flow_rules(priority=priority)
    return install_flows_to_controller(rules, controller_url=controller_url,
                                       apply_changes=apply_changes, delete_first=delete_first,
                                       verbose=verbose)


def apply_reroute(flow_rules: list, controller_url: str, apply_changes: bool = False,
                  verbose: bool = False) -> dict:
    """
    Push flow entries to controller or display dry-run output.
    """
    logger = setup_logger(verbose)
    api_url = f"{controller_url.rstrip('/')}/stats/flowentry/add"
    results = []

    print("=" * 72)
    print("           SDN AUTOMATED BACKUP PATH REROUTING ASSISTANT")
    print("=" * 72)
    print(f" Target Controller: {api_url}")
    print(f" Execution Mode:    {'*** LIVE APPLY ***' if apply_changes else '[DRY-RUN] (Simulation Only)'}")
    print(f" Total Rules:       {len(flow_rules)}")
    print("-" * 72)

    for idx, rule in enumerate(flow_rules, start=1):
        dpid = rule.get("dpid")
        out_p = rule.get("actions", [{}])[0].get("port")
        match = rule.get("match", {})

        print(f"Rule #{idx}: Switch DPID {dpid} | Match: {match} | Action: OUTPUT port {out_p}")

        if apply_changes:
            try:
                resp = requests.post(api_url, json=rule, timeout=DEFAULT_TIMEOUT)
                resp.raise_for_status()
                logger.info(f"Successfully installed rule #{idx} on DPID {dpid} (HTTP {resp.status_code})")
                results.append({"dpid": dpid, "status": "SUCCESS", "code": resp.status_code})
            except Exception as e:
                logger.error(f"Failed to install rule #{idx} on DPID {dpid}: {e}")
                results.append({"dpid": dpid, "status": "ERROR", "error": str(e)})
        else:
            results.append({"dpid": dpid, "status": "DRY_RUN", "payload": rule})

    print("-" * 72)
    if not apply_changes:
        print("[NOTE] Safe dry-run complete. No flow rules were modified on the controller.")
        print("To push these flow modifications to the live controller, append the --apply flag.")
    else:
        print("[SUCCESS] All rerouting flow modifications dispatched to controller.")
    print("=" * 72)

    return {"applied": apply_changes, "rules_count": len(flow_rules), "results": results}


def main():
    parser = argparse.ArgumentParser(
        description="Install OpenFlow Rules to Reroute Traffic Along Recommended Backup Path."
    )
    parser.add_argument("--mode", choices=["reroute", "primary", "backup"], default="reroute",
                        help="Flow operation mode: reroute (from report), primary (h1-s1-s2-h2), or backup (h1-s1-s3-s2-h2)")
    parser.add_argument("-r", "--report", default=DEFAULT_REPORT_FILE, help=f"Correlation report JSON (default: {DEFAULT_REPORT_FILE})")
    parser.add_argument("-t", "--topo", default=DEFAULT_TOPOLOGY_FILE, help=f"Topology JSON file (default: {DEFAULT_TOPOLOGY_FILE})")
    parser.add_argument("-c", "--controller", default=DEFAULT_CONTROLLER_URL, help=f"SDN controller URL (default: {DEFAULT_CONTROLLER_URL})")
    parser.add_argument("--priority", type=int, default=None, help=f"OpenFlow rule priority (default: 100 for primary, {DEFAULT_PRIORITY} for backup)")
    parser.add_argument("--unidirectional", action="store_true", help="Only install forward flows toward destination")
    parser.add_argument("--no-arp", action="store_true", help="Do not install matching ARP flows")
    parser.add_argument("--apply", action="store_true", help="Explicitly apply flow rules (default: dry-run mode)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    if args.mode == "primary":
        prio = args.priority if args.priority is not None else 100
        install_primary_flows(controller_url=args.controller, priority=prio,
                              apply_changes=args.apply, verbose=args.verbose)
        if not args.apply:
            for rule in build_primary_flow_rules(priority=prio):
                print(json.dumps(rule))
        return

    if args.mode == "backup":
        prio = args.priority if args.priority is not None else DEFAULT_PRIORITY
        install_backup_flows(controller_url=args.controller, priority=prio,
                             apply_changes=args.apply, verbose=args.verbose)
        if not args.apply:
            for rule in build_backup_flow_rules(priority=prio):
                print(json.dumps(rule))
        return

    # Default reroute mode
    prio = args.priority if args.priority is not None else DEFAULT_PRIORITY
    if not os.path.exists(args.report):
        print(f"[ERROR] Correlation report not found: {args.report}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.topo):
        print(f"[ERROR] Topology file not found: {args.topo}", file=sys.stderr)
        sys.exit(1)

    with open(args.report, "r", encoding="utf-8") as f:
        report_data = json.load(f)

    backup_info = report_data.get("recommended_backup_path")
    if not backup_info:
        print("[WARN] No recommended backup path found in report; checking ranked backups...", file=sys.stderr)
        backups = [b for b in report_data.get("ranked_backup_paths", []) if b.get("is_viable")]
        backup_info = backups[0] if backups else None

    if not backup_info:
        print("[ERROR] No viable backup path available in correlation report to reroute.", file=sys.stderr)
        sys.exit(1)

    backup_path = backup_info.get("path", [])
    dst_ip = report_data.get("destination_ip", "10.0.0.2")

    graph = SDNTopologyGraph()
    graph.load_from_file(args.topo)

    src_node = report_data.get("source_node", "h1")
    src_ip = graph.nodes.get(src_node, {}).get("ip")

    rules = generate_flow_entries(
        backup_path,
        graph,
        dst_ip,
        priority=prio,
        bidirectional=not args.unidirectional,
        src_ip=src_ip,
        include_arp=not args.no_arp,
    )
    apply_reroute(rules, controller_url=args.controller, apply_changes=args.apply, verbose=args.verbose)


if __name__ == "__main__":
    main()
