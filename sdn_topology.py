#!/usr/bin/env python3
"""
SDN Topology Discovery and Watcher Module
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Discovers switches, links, and hosts from Ryu (rest_topology + ofctl_rest)
and OpenDaylight RESTCONF APIs into a unified common nodes-and-links schema.
Includes continuous topology monitoring (--watch) to detect live link/switch
state changes (additions/deletions/flaps) in real-time.

Recommended Ryu Launch Command:
  ryu-manager ryu.app.rest_topology ryu.app.ofctl_rest ryu.app.simple_switch_13 --observe-links
"""

import argparse
import json
import logging
import os
import sys
import time

import requests
from requests.auth import HTTPBasicAuth

DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_LOCAL_CONFIG = "config.local.json"
DEFAULT_CONTROLLER_TYPE = "ryu"
DEFAULT_CONTROLLER_IP = "127.0.0.1"
DEFAULT_RYU_PORT = 8080
DEFAULT_ODL_PORT = 8181
DEFAULT_USERNAME = "admin"
DEFAULT_OUTPUT_FILE = "topology.json"
REQUEST_TIMEOUT = 5.0


def setup_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("sdn_topology")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s", datefmt="%H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load configuration from config.json, config.local.json, and environment."""
    config = {
        "sdn_controller_type": DEFAULT_CONTROLLER_TYPE,
        "controller_ip": DEFAULT_CONTROLLER_IP,
        "ryu_port": DEFAULT_RYU_PORT,
        "opendaylight_port": DEFAULT_ODL_PORT,
        "username": DEFAULT_USERNAME,
        "password": os.environ.get("CONTROLLER_PASSWORD", ""),
    }

    # Base config
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config.update(data)
        except Exception as e:
            print(f"[WARN] Failed to load config from {config_path}: {e}", file=sys.stderr)

    # Local overrides (untracked secrets)
    if os.path.exists(DEFAULT_LOCAL_CONFIG):
        try:
            with open(DEFAULT_LOCAL_CONFIG, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                config.update(local_data)
        except Exception as e:
            print(f"[WARN] Failed to load {DEFAULT_LOCAL_CONFIG}: {e}", file=sys.stderr)

    # Environment variable override takes ultimate precedence
    env_pwd = os.environ.get("CONTROLLER_PASSWORD")
    if env_pwd:
        config["password"] = env_pwd

    return config


def dpid_to_switch_id(dpid_str: str) -> str:
    """Normalize switch DPID into clean identifier like 's1'."""
    try:
        val = int(str(dpid_str), 16)
        return f"s{val}"
    except (ValueError, TypeError):
        return str(dpid_str)


def ip_to_host_id(ip_str: str, index: int = 1) -> str:
    """Generate canonical host ID like 'h1' or 'host:10.0.0.1'."""
    if not ip_str or ip_str == "*":
        return f"h{index}"
    parts = ip_str.split(".")
    if len(parts) == 4 and parts[-1].isdigit():
        return f"h{parts[-1]}"
    return f"host:{ip_str}"


def discover_ryu_topology(ip: str, port: int, logger: logging.Logger) -> dict:
    """
    Query Ryu REST Topology API endpoints:
    - /v1.0/topology/switches
    - /v1.0/topology/links
    - /v1.0/topology/hosts
    """
    base_url = f"http://{ip}:{port}"
    logger.info(f"Connecting to Ryu REST API at {base_url}...")

    nodes = []
    links = []
    seen_nodes = set()
    seen_links = set()

    # 1. Query Switches
    switches_url = f"{base_url}/v1.0/topology/switches"
    try:
        resp = requests.get(switches_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        switches_data = resp.json()
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Failed to query Ryu switches from {switches_url}: {e}")

    for sw in switches_data:
        raw_dpid = sw.get("dpid", "")
        sw_id = dpid_to_switch_id(raw_dpid)
        seen_nodes.add(sw_id)
        nodes.append({
            "id": sw_id,
            "type": "switch",
            "dpid": raw_dpid,
            "ports": sw.get("ports", [])
        })

    # 2. Query Inter-Switch Links
    links_url = f"{base_url}/v1.0/topology/links"
    try:
        resp = requests.get(links_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        links_data = resp.json()
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Failed to query Ryu links from {links_url}: {e}")

    for link_item in links_data:
        src_raw = link_item.get("src", {}).get("dpid", "")
        dst_raw = link_item.get("dst", {}).get("dpid", "")
        src_id = dpid_to_switch_id(src_raw)
        dst_id = dpid_to_switch_id(dst_raw)

        pair_key = tuple(sorted([src_id, dst_id]))
        if pair_key not in seen_links and src_id != dst_id:
            seen_links.add(pair_key)
            links.append({
                "source": src_id,
                "destination": dst_id,
                "src_port": link_item.get("src", {}).get("port_no"),
                "dst_port": link_item.get("dst", {}).get("port_no"),
                "type": "switch-to-switch"
            })

    # 3. Query Hosts
    hosts_url = f"{base_url}/v1.0/topology/hosts"
    try:
        resp = requests.get(hosts_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        hosts_data = resp.json()
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Failed to query Ryu hosts from {hosts_url}: {e}")

    for idx, host_item in enumerate(hosts_data, start=1):
        ipv4_list = host_item.get("ipv4", [])
        ip = ipv4_list[0] if ipv4_list else None
        mac = host_item.get("mac", "")
        host_id = ip_to_host_id(ip, idx)

        port_info = host_item.get("port", {})
        connected_dpid = port_info.get("dpid")
        connected_sw_id = dpid_to_switch_id(connected_dpid) if connected_dpid else None

        if host_id not in seen_nodes:
            seen_nodes.add(host_id)
            nodes.append({
                "id": host_id,
                "type": "host",
                "ip": ip,
                "mac": mac,
                "connected_to": connected_sw_id,
                "switch_port": port_info.get("port_no")
            })

        if connected_sw_id:
            pair_key = tuple(sorted([host_id, connected_sw_id]))
            if pair_key not in seen_links:
                seen_links.add(pair_key)
                links.append({
                    "source": host_id,
                    "destination": connected_sw_id,
                    "src_port": None,
                    "dst_port": port_info.get("port_no"),
                    "type": "host-to-switch"
                })

    return {
        "controller_type": "ryu",
        "controller_url": base_url,
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "nodes": nodes,
        "links": links
    }


def discover_opendaylight_topology(ip: str, port: int, username: str, password: str, logger: logging.Logger) -> dict:
    """Query OpenDaylight RESTCONF operational network-topology endpoint."""
    base_url = f"http://{ip}:{port}"
    logger.info(f"Connecting to OpenDaylight RESTCONF at {base_url}...")

    topology_url = f"{base_url}/restconf/operational/network-topology:network-topology"
    auth = HTTPBasicAuth(username, password)
    headers = {"Accept": "application/json"}

    try:
        resp = requests.get(topology_url, headers=headers, auth=auth, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw_json = resp.json()
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Failed to query OpenDaylight network-topology: {e}")

    topologies = raw_json.get("network-topology", {}).get("topology", [])
    if not topologies:
        raise ValueError("No topology found in OpenDaylight RESTCONF response.")

    nodes = []
    links = []
    seen_nodes = set()
    seen_links = set()

    for topo in topologies:
        topo_nodes = topo.get("node", [])
        topo_links = topo.get("link", [])

        for node in topo_nodes:
            node_id = str(node.get("node-id", ""))
            if node_id.startswith("host:"):
                host_addrs = node.get("host-tracker-service:addresses", [])
                ip_addr = host_addrs[0].get("ip") if host_addrs else None
                mac = host_addrs[0].get("mac") if host_addrs else node_id.replace("host:", "")
                h_id = ip_to_host_id(ip_addr)

                attachment_pts = node.get("host-tracker-service:attachment-points", [])
                connected_sw = None
                sw_port = None
                if attachment_pts:
                    tp_id = attachment_pts[0].get("tp-id", "")
                    if ":" in tp_id:
                        sw_part, port_str = tp_id.rsplit(":", 1)
                        sw_num = sw_part.split(":")[-1]
                        connected_sw = f"s{sw_num}"
                        sw_port = int(port_str) if port_str.isdigit() else None

                if h_id not in seen_nodes:
                    seen_nodes.add(h_id)
                    nodes.append({
                        "id": h_id,
                        "type": "host",
                        "ip": ip_addr,
                        "mac": mac,
                        "connected_to": connected_sw,
                        "switch_port": sw_port
                    })

                if connected_sw:
                    pair_key = tuple(sorted([h_id, connected_sw]))
                    if pair_key not in seen_links:
                        seen_links.add(pair_key)
                        links.append({
                            "source": h_id,
                            "destination": connected_sw,
                            "src_port": None,
                            "dst_port": sw_port,
                            "type": "host-to-switch"
                        })
            elif node_id.startswith("openflow:"):
                sw_num = node_id.split(":")[-1]
                sw_id = f"s{sw_num}"
                if sw_id not in seen_nodes:
                    seen_nodes.add(sw_id)
                    nodes.append({
                        "id": sw_id,
                        "type": "switch",
                        "dpid": node_id,
                        "termination_points": node.get("termination-point", [])
                    })

        for link in topo_links:
            src_node = link.get("source", {}).get("source-node", "")
            dst_node = link.get("destination", {}).get("dest-node", "")
            src_id = f"s{src_node.split(':')[-1]}" if src_node.startswith("openflow:") else src_node
            dst_id = f"s{dst_node.split(':')[-1]}" if dst_node.startswith("openflow:") else dst_node

            pair_key = tuple(sorted([src_id, dst_id]))
            if pair_key not in seen_links and src_id != dst_id:
                seen_links.add(pair_key)
                links.append({
                    "source": src_id,
                    "destination": dst_id,
                    "type": "switch-to-switch"
                })

    return {
        "controller_type": "opendaylight",
        "controller_url": base_url,
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "nodes": nodes,
        "links": links
    }


def discover_topology(controller_type: str, ip: str, port: int,
                      username: str = DEFAULT_USERNAME, password: str = "",
                      verbose: bool = False) -> dict:
    """Main dispatch function for SDN topology discovery."""
    logger = setup_logger(verbose)
    ctl_type = controller_type.lower()
    if ctl_type == "ryu":
        return discover_ryu_topology(ip, port, logger)
    elif ctl_type in ["opendaylight", "odl"]:
        return discover_opendaylight_topology(ip, port, username, password, logger)
    else:
        raise ValueError(f"Unsupported controller type '{controller_type}'. Use 'ryu' or 'opendaylight'.")


def diff_topologies(old_topo: dict, new_topo: dict) -> list:
    """Identify switches and links added or removed between snapshots."""
    changes = []
    old_node_ids = {n["id"]: n for n in old_topo.get("nodes", [])}
    new_node_ids = {n["id"]: n for n in new_topo.get("nodes", [])}

    for nid in new_node_ids:
        if nid not in old_node_ids:
            changes.append(f"NODE ADDED: {nid} ({new_node_ids[nid].get('type')})")
    for nid in old_node_ids:
        if nid not in new_node_ids:
            changes.append(f"NODE REMOVED: {nid} ({old_node_ids[nid].get('type')})")

    old_links = {tuple(sorted([lnk["source"], lnk["destination"]])) for lnk in old_topo.get("links", [])}
    new_links = {tuple(sorted([lnk["source"], lnk["destination"]])) for lnk in new_topo.get("links", [])}

    for link in new_links - old_links:
        changes.append(f"LINK UP: {link[0]} <---> {link[1]}")
    for link in old_links - new_links:
        changes.append(f"LINK DOWN: {link[0]} <---> {link[1]}")

    return changes


def watch_topology(controller_type: str, ip: str, port: int, interval: int = 5,
                   username: str = DEFAULT_USERNAME, password: str = "",
                   output_file: str = DEFAULT_OUTPUT_FILE, verbose: bool = False):
    """Continuously monitor SDN topology and report link/switch events."""
    logger = setup_logger(verbose)
    print("=" * 68)
    print(f"       SDN Topology Live Watcher Running (Interval: {interval}s)")
    print("=" * 68)
    print(" Press Ctrl+C to terminate watcher.")
    print("-" * 68)

    previous_topo = None

    try:
        while True:
            try:
                current_topo = discover_topology(controller_type, ip, port, username, password, verbose)
                if previous_topo:
                    events = diff_topologies(previous_topo, current_topo)
                    if events:
                        print(f"\n[EVENT DETECTED @ {time.strftime('%H:%M:%S')}]:")
                        for ev in events:
                            print(f"  ● {ev}")
                    else:
                        logger.debug("Topology check: no changes detected.")
                else:
                    logger.info(f"Initial baseline: {len(current_topo['nodes'])} nodes, {len(current_topo['links'])} links.")

                previous_topo = current_topo
                if output_file:
                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(current_topo, f, indent=2)

            except Exception as e:
                logger.error(f"Error querying controller: {e}")

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[INFO] Topology watcher stopped by user.")


def print_topology_summary(topology: dict):
    """Print discovered SDN nodes and links in a formatted terminal table."""
    print("\n" + "=" * 68)
    print("                 SDN TOPOLOGY DISCOVERY REPORT")
    print("=" * 68)
    print(f" Controller Type:   {topology.get('controller_type', 'unknown').upper()}")
    print(f" Controller URL:    {topology.get('controller_url')}")
    print(f" Discovered At:     {topology.get('discovered_at')}")
    print(f" Total Nodes:       {len(topology.get('nodes', []))}")
    print(f" Total Links:       {len(topology.get('links', []))}")
    print("-" * 68)

    print("\n[Discovered Nodes]:")
    print(f"{'Node ID':<12} {'Type':<12} {'IP / DPID':<25} {'Connected To':<15}")
    print("-" * 68)
    for node in topology.get("nodes", []):
        node_id = node.get("id", "")
        ntype = node.get("type", "")
        detail = node.get("ip") or node.get("dpid") or "-"
        conn = node.get("connected_to") or "-"
        print(f"{node_id:<12} {ntype:<12} {detail:<25} {conn:<15}")

    print("\n[Discovered Links]:")
    print(f"{'Source':<15} {'<--->':<8} {'Destination':<15} {'Link Type':<20}")
    print("-" * 68)
    for link in topology.get("links", []):
        src = link.get("source", "")
        dst = link.get("destination", "")
        ltype = link.get("type", "inter-connect")
        print(f"{src:<15} {'<--->':<8} {dst:<15} {ltype:<20}")
    print("=" * 68)


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(
        description="SDN Topology Discovery and Watcher for Ryu and OpenDaylight Controllers."
    )
    parser.add_argument("-c", "--controller", choices=["ryu", "opendaylight", "odl"], default=cfg["sdn_controller_type"], help=f"SDN controller type (default: {cfg['sdn_controller_type']})")
    parser.add_argument("-i", "--ip", default=cfg["controller_ip"], help=f"Controller IP address (default: {cfg['controller_ip']})")
    parser.add_argument("-p", "--port", type=int, help="Controller REST port (default: 8080 for Ryu, 8181 for ODL)")
    parser.add_argument("-u", "--username", default=cfg["username"], help=f"Controller REST username (default: {cfg['username']})")
    parser.add_argument("-P", "--password", default=cfg.get("password", ""), help="Controller REST password (default: read from config/env)")
    parser.add_argument("-w", "--watch", type=int, nargs="?", const=5, help="Monitor topology continuously every N seconds (default: 5s)")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_FILE, help=f"Output topology JSON filepath (default: {DEFAULT_OUTPUT_FILE})")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    port = args.port
    if port is None:
        port = cfg["opendaylight_port"] if args.controller.lower() in ["opendaylight", "odl"] else cfg["ryu_port"]

    if args.watch:
        watch_topology(
            controller_type=args.controller,
            ip=args.ip,
            port=port,
            interval=args.watch,
            username=args.username,
            password=args.password,
            output_file=args.output,
            verbose=args.verbose
        )
    else:
        try:
            topo = discover_topology(
                controller_type=args.controller,
                ip=args.ip,
                port=port,
                username=args.username,
                password=args.password,
                verbose=args.verbose
            )
            print_topology_summary(topo)

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(topo, f, indent=2)
                print(f"\n[INFO] Topology successfully written to: {args.output}")

        except ConnectionError as ce:
            print(f"\n[ERROR] Connection failed: {ce}", file=sys.stderr)
            print("[HINT] Ensure your SDN controller (Ryu/OpenDaylight) is running, or launch mock_controller.py for offline testing.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n[ERROR] Topology discovery error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
