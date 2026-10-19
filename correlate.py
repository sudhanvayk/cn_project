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
import re
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


def analyze_port_stats_deltas(baseline_stats: dict, current_stats: dict, links: list) -> list:
    """
    Evidence Source A: Analyze per-port tx/rx counters and drop/error deltas.
    Flags links where tx/rx packets mismatch or drops/errors occur.

    Args:
        baseline_stats: Dict of {dpid_str: [port_dict, ...]} before probing.
        current_stats: Dict of {dpid_str: [port_dict, ...]} after probing.
        links: List of topology link dicts.

    Returns:
        list of dict: Suspected links identified via port statistics.
    """
    suspects = []
    if not baseline_stats or not current_stats:
        return suspects

    # Helper to index port stats by (dpid, port_no)
    def index_stats(stats_dict):
        indexed = {}
        for dpid, ports in stats_dict.items():
            for p in ports:
                p_no = p.get("port_no")
                if p_no is not None:
                    indexed[(str(dpid), int(p_no))] = p
        return indexed

    base_idx = index_stats(baseline_stats)
    curr_idx = index_stats(current_stats)

    for link in links:
        src = link.get("source")
        dst = link.get("destination")
        src_port = link.get("src_port")
        dst_port = link.get("dst_port")

        if not src_port or not dst_port:
            continue

        # Extract numeric dpid if needed
        s_dpid = re.search(r'\d+', src)
        d_dpid = re.search(r'\d+', dst)
        if not s_dpid or not d_dpid:
            continue

        s_key = (s_dpid.group(0), int(src_port))
        d_key = (d_dpid.group(0), int(dst_port))

        s_base = base_idx.get(s_key, {})
        s_curr = curr_idx.get(s_key, {})
        d_base = base_idx.get(d_key, {})
        d_curr = curr_idx.get(d_key, {})

        s_tx_delta = max(0, s_curr.get("tx_packets", 0) - s_base.get("tx_packets", 0))
        d_rx_delta = max(0, d_curr.get("rx_packets", 0) - d_base.get("rx_packets", 0))
        s_drop_delta = max(0, s_curr.get("tx_dropped", 0) - s_base.get("tx_dropped", 0))
        d_drop_delta = max(0, d_curr.get("rx_dropped", 0) - d_base.get("rx_dropped", 0))
        s_err_delta = max(0, s_curr.get("tx_errors", 0) - s_base.get("tx_errors", 0))
        d_err_delta = max(0, d_curr.get("rx_errors", 0) - d_base.get("rx_errors", 0))

        evidence = []
        confidence = 0.0

        if s_drop_delta > 0 or d_drop_delta > 0:
            total_drops = s_drop_delta + d_drop_delta
            evidence.append(f"Port drop counters incremented: {total_drops} dropped packets on link {src}:{src_port} <-> {dst}:{dst_port}")
            confidence = max(confidence, 0.85)

        if s_err_delta > 0 or d_err_delta > 0:
            total_errors = s_err_delta + d_err_delta
            evidence.append(f"Port error counters incremented: {total_errors} errors on link {src}:{src_port} <-> {dst}:{dst_port}")
            confidence = max(confidence, 0.80)

        # Transmit mismatch
        if s_tx_delta > 0 and s_tx_delta > d_rx_delta:
            diff = s_tx_delta - d_rx_delta
            evidence.append(f"Packet mismatch across link: {src} TX delta ({s_tx_delta}) exceeds {dst} RX delta ({d_rx_delta}) by {diff} pkts")
            confidence = max(confidence, 0.90)

        if evidence:
            suspects.append({
                "link": [src, dst],
                "link_str": f"{src} <---> {dst}",
                "evidence_type": "port_statistics",
                "confidence": confidence,
                "evidence": evidence
            })

    return suspects


def analyze_segment_probes(segment_metrics: dict, active_path: list) -> list:
    """
    Evidence Source B: Per-segment probing anomaly detector.
    Analyzes measurements to intermediate targets along the path to find
    where packet loss or RTT first spikes.

    Args:
        segment_metrics: Dict mapping node_id or IP to diagnostic summary dict.
                         e.g. {'s1': {'packet_loss_percent': 0.0, 'mean_rtt_ms': 1.2},
                               's2': {'packet_loss_percent': 60.0, 'mean_rtt_ms': 75.0}}
        active_path: Ordered list of nodes in active forwarding path.

    Returns:
        list of dict: Suspected links identified via per-segment probe jumps.
    """
    suspects = []
    if not segment_metrics or not active_path or len(active_path) < 2:
        return suspects

    prev_node = active_path[0]
    prev_loss = segment_metrics.get(prev_node, {}).get("packet_loss_percent", 0.0)
    prev_rtt = segment_metrics.get(prev_node, {}).get("mean_rtt_ms", 0.0) or 0.0

    for i in range(1, len(active_path)):
        curr_node = active_path[i]
        curr_metric = segment_metrics.get(curr_node)
        if not curr_metric:
            prev_node = curr_node
            continue

        curr_loss = curr_metric.get("packet_loss_percent", 0.0)
        curr_rtt = curr_metric.get("mean_rtt_ms", 0.0) or 0.0

        loss_jump = curr_loss - prev_loss
        rtt_jump = curr_rtt - prev_rtt

        evidence = []
        confidence = 0.0

        if loss_jump >= 30.0 or (prev_loss < 10.0 and curr_loss >= 50.0):
            evidence.append(f"Packet loss spiked by +{loss_jump:.1f}% across segment ({prev_node} -> {curr_node})")
            confidence = max(confidence, 0.90)
        elif loss_jump >= 10.0:
            evidence.append(f"Packet loss increased by +{loss_jump:.1f}% across segment ({prev_node} -> {curr_node})")
            confidence = max(confidence, 0.75)

        if rtt_jump >= 40.0:
            evidence.append(f"Mean RTT jumped by +{rtt_jump:.2f} ms across segment ({prev_node} -> {curr_node})")
            confidence = max(confidence, 0.80)

        if evidence:
            suspects.append({
                "link": [prev_node, curr_node],
                "link_str": f"{prev_node} <---> {curr_node}",
                "evidence_type": "segment_probing",
                "confidence": confidence,
                "evidence": evidence
            })

        prev_node = curr_node
        prev_loss = curr_loss
        prev_rtt = curr_rtt

    return suspects




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
