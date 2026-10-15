#!/usr/bin/env python3
"""
Measurement and Topology Correlation Module (with Failure Detection & Path Comparison)
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This module correlates active UDP measurement metrics (RTT and packet loss)
with discovered SDN network topology data. It classifies path health
(HEALTHY_PATH, DEGRADED_PATH, FAILED_PATH), identifies failure reasons,
determines the selected shortest path, ranks alternative candidate paths
by hop count, and produces actionable rerouting recommendations.
"""

import argparse
import json
import os
import sys
import time

from topology_graph import SDNTopologyGraph

DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_DIAG_FILE = "diagnostic_result.json"
DEFAULT_TOPO_FILE = "topology.json"
DEFAULT_REPORT_FILE = "correlation_report.json"
DEFAULT_SOURCE = "h1"


def load_config(config_path=DEFAULT_CONFIG_PATH):
    """Load performance thresholds from config.json."""
    defaults = {
        "thresholds": {
            "degraded_rtt_ms": 50.0,
            "degraded_packet_loss_percent": 0.0,
            "failed_packet_loss_percent": 50.0
        }
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "thresholds" in data:
                    defaults["thresholds"].update(data["thresholds"])
        except Exception as e:
            print(f"[WARN] Failed to load config from {config_path}: {e}", file=sys.stderr)
    return defaults


def classify_path_health(summary, thresholds):
    """
    Classify path health based on network metrics against configured thresholds.

    Rules:
    - FAILED_PATH: Packet loss >= failed_loss_percent (default: >= 50%)
    - DEGRADED_PATH: Packet loss > degraded_loss_percent (e.g. > 0%) OR mean RTT > degraded_rtt_ms
    - HEALTHY_PATH: Packet loss <= 0% and mean RTT <= degraded_rtt_ms

    Returns:
        tuple (str, str): (path_status, failed_path_reason)
    """
    loss_pct = summary.get("packet_loss_percent", 100.0)
    mean_rtt = summary.get("mean_rtt_ms")

    failed_thresh = thresholds.get("failed_packet_loss_percent", 50.0)
    degraded_loss_thresh = thresholds.get("degraded_packet_loss_percent", 0.0)
    degraded_rtt_thresh = thresholds.get("degraded_rtt_ms", 50.0)

    if loss_pct >= failed_thresh:
        return (
            "FAILED_PATH",
            f"Severe packet loss ({loss_pct:.2f}%) meets or exceeds failure threshold ({failed_thresh:.1f}%)."
        )

    is_loss_degraded = loss_pct > degraded_loss_thresh
    is_rtt_degraded = (mean_rtt is not None) and (mean_rtt > degraded_rtt_thresh)

    if is_loss_degraded or is_rtt_degraded:
        reasons = []
        if is_loss_degraded:
            reasons.append(f"packet loss of {loss_pct:.2f}% detected")
        if is_rtt_degraded:
            reasons.append(f"mean RTT ({mean_rtt:.2f} ms) exceeds latency limit ({degraded_rtt_thresh:.2f} ms)")
        return (
            "DEGRADED_PATH",
            "Path degradation detected: " + " and ".join(reasons) + "."
        )

    return (
        "HEALTHY_PATH",
        "None (Path is healthy and operating within nominal thresholds)"
    )


def correlate(diag_file, topo_file, source_node, config_file=DEFAULT_CONFIG_PATH, output_file=DEFAULT_REPORT_FILE):
    """
    Correlate diagnostic measurements with SDN topology graph, perform failure
    detection, and rank alternative routes.
    """
    cfg = load_config(config_file)
    thresholds = cfg["thresholds"]

    # Load diagnostic measurements
    if not os.path.exists(diag_file):
        raise FileNotFoundError(f"Diagnostic results file not found: {diag_file}")
    with open(diag_file, "r", encoding="utf-8") as f:
        diag_data = json.load(f)

    target_ip = diag_data.get("target_ip")
    summary = diag_data.get("summary", {})
    loss_pct = summary.get("packet_loss_percent", 100.0)
    mean_rtt = summary.get("mean_rtt_ms")

    # Load SDN topology graph
    if not os.path.exists(topo_file):
        raise FileNotFoundError(f"SDN topology file not found: {topo_file}")
    graph = SDNTopologyGraph()
    graph.load_from_file(topo_file)

    # Resolve canonical nodes
    src_canonical = graph.resolve_node(source_node) or source_node
    dst_canonical = graph.resolve_node(target_ip) or target_ip

    # Find candidate paths in SDN topology
    candidate_paths = graph.find_all_simple_paths(src_canonical, dst_canonical)
    comparison_data = graph.compare_paths(candidate_paths)

    selected_shortest = comparison_data.get("selected_shortest_path")
    alternative_paths = comparison_data.get("alternative_paths", [])
    path_comparison_ranking = comparison_data.get("comparison", [])

    # Classify health status and failed-path reason
    path_status, failed_path_reason = classify_path_health(summary, thresholds)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path_status": path_status,
        "source_node": src_canonical,
        "destination_node": dst_canonical,
        "destination_ip": target_ip,
        "candidate_paths": candidate_paths,
        "selected_shortest_path": selected_shortest,
        "failed_path_reason": failed_path_reason,
        "packet_loss_percentage": loss_pct,
        "mean_rtt": mean_rtt,
        "alternative_paths": alternative_paths,
        "path_comparison": path_comparison_ranking,
        "detailed_metrics": {
            "probes_sent": summary.get("sent"),
            "probes_received": summary.get("received"),
            "probes_lost": summary.get("lost"),
            "packet_loss_percentage": loss_pct,
            "min_rtt_ms": summary.get("min_rtt_ms"),
            "max_rtt_ms": summary.get("max_rtt_ms"),
            "mean_rtt_ms": mean_rtt,
            "median_rtt_ms": summary.get("median_rtt_ms"),
            "stddev_rtt_ms": summary.get("stddev_rtt_ms")
        },
        "thresholds": thresholds
    }

    print_terminal_report(report)

    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"[INFO] Final correlation report saved to: {output_file}")
        except Exception as e:
            print(f"[ERROR] Failed to save {output_file}: {e}", file=sys.stderr)

    return report


def print_terminal_report(report):
    """Print high-clarity terminal diagnostic report with clear status banner."""
    status = report.get("path_status", "UNKNOWN")
    reason = report.get("failed_path_reason")
    src = report.get("source_node")
    dst = report.get("destination_node")
    dst_ip = report.get("destination_ip")
    loss = report.get("packet_loss_percentage", 0.0)
    mean_rtt = report.get("mean_rtt")
    shortest = report.get("selected_shortest_path")
    alternatives = report.get("alternative_paths", [])
    ranking = report.get("path_comparison", [])

    banner_symbol = "[●]"
    status_label = f"*** {status} ***"
    if status == "HEALTHY_PATH":
        banner_symbol = "[✔ HEALTHY]"
    elif status == "DEGRADED_PATH":
        banner_symbol = "[▲ DEGRADED]"
    elif status == "FAILED_PATH":
        banner_symbol = "[✖ FAILED]"

    print("\n" + "=" * 72)
    print(f" {banner_symbol:<14} SDN NETWORK PATH DIAGNOSTIC & CORRELATION REPORT")
    print("=" * 72)
    print(f" PATH STATUS:             {status}")
    print(f" FAILED-PATH REASON:      {reason}")
    print("-" * 72)
    print(f" Source Node:             {src}")
    print(f" Destination Node:        {dst} (IP: {dst_ip})")
    print(f" Packet Loss:             {loss:.2f}%")
    print(f" Mean RTT:                {f'{mean_rtt:.2f} ms' if mean_rtt is not None else 'N/A'}")
    if shortest:
        print(f" Selected Shortest Path:  {shortest.get('path_str')} ({shortest.get('hop_count')} hops)")
    else:
        print(" Selected Shortest Path:  No path discovered")
    print("-" * 72)

    # Path comparison ranked by hop count
    print(f" PATH COMPARISON RANKED BY HOP COUNT ({len(ranking)} total):")
    if ranking:
        print(f" {'Rank':<6} {'Role':<20} {'Hops':<8} {'Extra':<8} {'Route'}")
        print(" " + "-" * 70)
        for row in ranking:
            rank = row.get("rank")
            role = row.get("role")
            hops = row.get("hop_count")
            extra = f"+{row.get('extra_hops')}" if row.get('extra_hops') > 0 else "0"
            route = row.get("path_str")
            print(f" {rank:<6} {role:<20} {hops:<8} {extra:<8} {route}")
    else:
        print("  No candidate paths discovered in current topology.")

    # Alternative paths & recommendations
    print("-" * 72)
    if status == "FAILED_PATH":
        if alternatives:
            best_alt = alternatives[0]
            print(f" [ACTION REQUIRED] Primary path has failed!")
            print(f" -> Recommended Alternative: Rank {best_alt['rank']} ({best_alt['path_str']})")
            print(f" -> Cost Penalty: +{best_alt['extra_hops']} extra hop(s)")
            print(" -> Suggested Action: Direct SDN Controller to update OpenFlow flow rules to alternative route.")
        else:
            print(" [CRITICAL] Primary path failed and NO alternative topology paths exist.")
            print(" -> Suggested Action: Check physical links or controller flow tables.")
    elif status == "DEGRADED_PATH":
        if alternatives:
            best_alt = alternatives[0]
            print(f" [WARNING] Primary path is degraded (latency/loss threshold exceeded).")
            print(f" -> Feasible Failover: Rank {best_alt['rank']} ({best_alt['path_str']}) (+{best_alt['extra_hops']} hops)")
            print(" -> Suggested Action: Shift delay-sensitive traffic to alternative route.")
        else:
            print(" [WARNING] Primary path is degraded. No alternative topology paths available.")
    else:
        print(" [OK] Network path operating within nominal parameters. No rerouting needed.")
    print("=" * 72 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Correlate UDP Diagnostic Metrics with SDN Topology and Analyze Alternative Paths."
    )
    parser.add_argument(
        "-d", "--diag",
        default=DEFAULT_DIAG_FILE,
        help=f"Diagnostic result JSON file (default: {DEFAULT_DIAG_FILE})"
    )
    parser.add_argument(
        "-t", "--topo",
        default=DEFAULT_TOPO_FILE,
        help=f"SDN topology JSON file (default: {DEFAULT_TOPO_FILE})"
    )
    parser.add_argument(
        "-s", "--source",
        default=DEFAULT_SOURCE,
        help=f"Source node ID or IPv4 address (default: {DEFAULT_SOURCE})"
    )
    parser.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Configuration JSON file (default: {DEFAULT_CONFIG_PATH})"
    )
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_REPORT_FILE,
        help=f"Output correlation JSON file (default: {DEFAULT_REPORT_FILE})"
    )

    args = parser.parse_args()

    try:
        correlate(
            diag_file=args.diag,
            topo_file=args.topo,
            source_node=args.source,
            config_file=args.config,
            output_file=args.output
        )
    except Exception as e:
        print(f"[ERROR] Correlation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
