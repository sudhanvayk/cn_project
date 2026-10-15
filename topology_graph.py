#!/usr/bin/env python3
"""
SDN Topology Graph and Path-Finding Engine
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This module loads the common nodes-and-links JSON representation generated
by sdn_topology.py, constructs an undirected graph, finds all simple paths
between a source and destination, ranks paths by hop count, and provides
an analytical comparison between primary and alternative paths.
"""

import argparse
import collections
import json
import os
import sys

DEFAULT_TOPOLOGY_FILE = "topology.json"
DEFAULT_MAX_PATHS = 10


class SDNTopologyGraph:
    """
    Undirected graph representation of an SDN network topology.
    """

    def __init__(self):
        self.adj = collections.defaultdict(set)
        self.nodes = {}
        self.links = []
        self.ip_to_node = {}

    def load_from_dict(self, data):
        """Build graph from parsed dictionary."""
        self.adj.clear()
        self.nodes.clear()
        self.links = []
        self.ip_to_node.clear()

        # Load nodes
        for node in data.get("nodes", []):
            nid = node.get("id")
            if not nid:
                continue
            self.nodes[nid] = node
            # Index by IP if available
            ip = node.get("ip")
            if ip and ip != "*":
                self.ip_to_node[ip] = nid

        # Load links
        for link in data.get("links", []):
            src = link.get("source")
            dst = link.get("destination")
            if src and dst and src != dst:
                self.adj[src].add(dst)
                self.adj[dst].add(src)
                self.links.append(link)

                # Ensure endpoints are recorded as nodes if missing
                if src not in self.nodes:
                    self.nodes[src] = {"id": src, "type": "unknown"}
                if dst not in self.nodes:
                    self.nodes[dst] = {"id": dst, "type": "unknown"}

    def load_from_file(self, filepath):
        """Load topology from JSON file."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Topology file not found: {filepath}")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.load_from_dict(data)

    def resolve_node(self, identifier):
        """
        Resolve an identifier (Node ID or IPv4 address) to a canonical node ID.

        Returns:
            str or None: Node ID if found, else None.
        """
        if not identifier:
            return None
        # Check direct node ID match
        if identifier in self.nodes:
            return identifier
        # Check IP lookup
        if identifier in self.ip_to_node:
            return self.ip_to_node[identifier]
        # Check case-insensitive node match
        for nid in self.nodes:
            if nid.lower() == identifier.lower():
                return nid
        return None

    def find_all_simple_paths(self, src_id, dst_id, max_paths=DEFAULT_MAX_PATHS):
        """
        Find all loop-free simple paths between source and destination using BFS.
        Breadth-first search guarantees paths are naturally discovered in increasing order
        of hop count.

        Args:
            src_id (str): Source node identifier.
            dst_id (str): Destination node identifier.
            max_paths (int): Maximum number of paths to collect.

        Returns:
            list of list of str: List of paths sorted by hop count.
        """
        src = self.resolve_node(src_id)
        dst = self.resolve_node(dst_id)

        if not src or not dst:
            return []
        if src == dst:
            return [[src]]

        found_paths = []
        queue = collections.deque([[src]])

        while queue:
            path = queue.popleft()
            current = path[-1]

            if current == dst:
                found_paths.append(path)
                if max_paths and len(found_paths) >= max_paths:
                    break
                continue

            # Visit unvisited neighbors
            for neighbor in sorted(self.adj.get(current, [])):
                if neighbor not in path:
                    queue.append(path + [neighbor])

        # Sort paths primarily by hop count (length - 1), then lexicographically
        found_paths.sort(key=lambda p: (len(p) - 1, "->".join(p)))
        if max_paths:
            found_paths = found_paths[:max_paths]

        return found_paths

    def compare_paths(self, paths):
        """
        Compare alternative paths against the primary (shortest) path by hop count.

        Args:
            paths (list of list of str): Sorted list of simple paths.

        Returns:
            dict: Detailed comparison metrics including selected shortest path and alternative routes.
        """
        if not paths:
            return {
                "total_paths": 0,
                "selected_shortest_path": None,
                "alternative_paths": [],
                "comparison": []
            }

        primary = paths[0]
        primary_hops = len(primary) - 1

        alternatives = []
        for rank, p in enumerate(paths[1:], start=2):
            hops = len(p) - 1
            alternatives.append({
                "rank": rank,
                "path": p,
                "path_str": " -> ".join(p),
                "hop_count": hops,
                "extra_hops": hops - primary_hops
            })

        comparison_table = [{
            "rank": 1,
            "role": "SELECTED_SHORTEST",
            "path": primary,
            "path_str": " -> ".join(primary),
            "hop_count": primary_hops,
            "extra_hops": 0
        }]
        for alt in alternatives:
            comparison_table.append({
                "rank": alt["rank"],
                "role": "ALTERNATIVE",
                "path": alt["path"],
                "path_str": alt["path_str"],
                "hop_count": alt["hop_count"],
                "extra_hops": alt["extra_hops"]
            })

        return {
            "total_paths": len(paths),
            "selected_shortest_path": {
                "path": primary,
                "path_str": " -> ".join(primary),
                "hop_count": primary_hops
            },
            "alternative_paths": alternatives,
            "comparison": comparison_table
        }


def print_path_comparison(src, dst, comparison_result):
    """Print path analysis and alternative comparison in formatted terminal view."""
    print("=" * 70)
    print("               SDN PATH DISCOVERY AND COMPARISON REPORT")
    print("=" * 70)
    print(f" Source:            {src}")
    print(f" Destination:       {dst}")
    print(f" Total Paths Found: {comparison_result['total_paths']}")
    print("-" * 70)

    if comparison_result["total_paths"] == 0:
        print("[WARN] No simple paths exist between the specified nodes.")
        print("=" * 70)
        return

    print(f"{'Rank':<6} {'Role':<22} {'Hops':<8} {'Extra':<8} {'Path Route'}")
    print("-" * 70)

    for entry in comparison_result["comparison"]:
        rank = entry["rank"]
        role = entry["role"]
        hops = entry["hop_count"]
        extra = f"+{entry['extra_hops']}" if entry['extra_hops'] > 0 else "0"
        route = entry["path_str"]
        print(f"{rank:<6} {role:<22} {hops:<8} {extra:<8} {route}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="SDN Topology Graph Engine and Alternative Path Finder."
    )
    parser.add_argument(
        "-f", "--file",
        default=DEFAULT_TOPOLOGY_FILE,
        help=f"Path to SDN topology JSON file (default: {DEFAULT_TOPOLOGY_FILE})"
    )
    parser.add_argument(
        "-s", "--source",
        required=True,
        help="Source node ID or IPv4 address (e.g., h1 or 10.0.0.1)"
    )
    parser.add_argument(
        "-d", "--dest",
        required=True,
        help="Destination node ID or IPv4 address (e.g., h2 or 10.0.0.2)"
    )
    parser.add_argument(
        "-m", "--max-paths",
        type=int,
        default=DEFAULT_MAX_PATHS,
        help=f"Maximum number of paths to find (default: {DEFAULT_MAX_PATHS})"
    )
    parser.add_argument(
        "-o", "--output",
        help="Optional filepath to save path comparison JSON"
    )

    args = parser.parse_args()

    graph = SDNTopologyGraph()
    try:
        graph.load_from_file(args.file)
    except Exception as e:
        print(f"[ERROR] Failed to load topology file '{args.file}': {e}", file=sys.stderr)
        sys.exit(1)

    src_node = graph.resolve_node(args.source)
    dst_node = graph.resolve_node(args.dest)

    if not src_node:
        print(f"[ERROR] Source '{args.source}' could not be resolved in topology.", file=sys.stderr)
        sys.exit(1)
    if not dst_node:
        print(f"[ERROR] Destination '{args.dest}' could not be resolved in topology.", file=sys.stderr)
        sys.exit(1)

    paths = graph.find_all_simple_paths(src_node, dst_node, max_paths=args.max_paths)
    comparison = graph.compare_paths(paths)

    print_path_comparison(src_node, dst_node, comparison)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({
                    "source": src_node,
                    "destination": dst_node,
                    "comparison": comparison
                }, f, indent=2)
            print(f"\n[INFO] Path comparison written to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to write {args.output}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
