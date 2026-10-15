#!/usr/bin/env python3
"""
Measurement and Topology Correlation Module
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This module correlates active UDP measurement metrics (RTT and packet loss)
with discovered SDN network topology data. It resolves end-hosts, finds all
candidate forwarding paths in the SDN fabric, classifies path health status
(HEALTHY_PATH, DEGRADED_PATH, FAILED_PATH), analyzes alternative routes,
and produces a structured correlation report.
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
        tuple (str, str): (classification_label, reason_description)
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
        f"Optimal network conditions: 0% loss and mean RTT ({mean_rtt if mean_rtt else 0.0:.2f} ms) within nominal limits."
    )


def correlate(diag_file, topo_file, source_node, config_file=DEFAULT_CONFIG_PATH, output_file=DEFAULT_REPORT_FILE):
    """
    Correlate diagnostic measurements with SDN topology graph.
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

    # Load SDN topology graph
    if not os.path.exists(topo_file):
        raise FileNotFoundError(f"SDN topology file not found: {topo_file}")
    graph = SDNTopologyGraph()
    graph.load_from_file(topo_file)

    # Resolve nodes
    src_canonical = graph.resolve_node(source_node)
    dst_canonical = graph.resolve_node(target_ip)

    if not src_canonical:
        src_canonical = source_node

    if not dst_canonical:
        # Check if there's any host matching IP or default to h2
        print(f"[WARN] Destination IP {target_ip} not directly listed in topology nodes. Using as endpoint.", file=sys.stderr)
        dst_canonical = target_ip

    # Find candidate paths in SDN topology
    candidate_paths = graph.find_all_simple_paths(src_canonical, dst_canonical)
    path_comparison = graph.compare_paths(candidate_paths)

    # Classify health status
    classification, reason = classify_path_health(summary, thresholds)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": src_canonical,
        "destination_ip": target_ip,
        "destination_node": dst_canonical,
        "path_status": classification,
        "reason": reason,
        "metrics": {
            "probes_sent": summary.get("sent"),
            "probes_received": summary.get("received"),
            "probes_lost": summary.get("lost"),
            "packet_loss_percent": summary.get("packet_loss_percent"),
            "min_rtt_ms": summary.get("min_rtt_ms"),
            "max_rtt_ms": summary.get("max_rtt_ms"),
            "mean_rtt_ms": summary.get("mean_rtt_ms"),
            "median_rtt_ms": summary.get("median_rtt_ms"),
            "stddev_rtt_ms": summary.get("stddev_rtt_ms")
        },
        "thresholds_used": thresholds,
        "candidate_paths": candidate_paths,
        "path_comparison": path_comparison
    }

    print_correlation_report(report)

    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"\n[INFO] Correlation report saved to: {output_file}")
        except Exception as e:
            print(f"[ERROR] Failed to save {output_file}: {e}", file=sys.stderr)

    return report


def print_correlation_report(report):
    """Print readable diagnostic and correlation report to terminal."""
    status = report.get("path_status", "UNKNOWN")
    metrics = report.get("metrics", {})
    comparison = report.get("path_comparison", {})

    print("\n" + "=" * 70)
    print("               SDN PATH & MEASUREMENT CORRELATION REPORT")
    print("=" * 70)
    print(f" Source Node:        {report.get('source')}")
    print(f" Destination Node:   {report.get('destination_node')} ({report.get('destination_ip')})")
    print(f" Path Status:        {status}")
    print(f" Status Reason:      {report.get('reason')}")
    print("-" * 70)
    print(" Diagnostic Metrics:")
    print(f"   Packet Loss:      {metrics.get('packet_loss_percent', 0.0):.2f}% "
          f"({metrics.get('probes_lost', 0)}/{metrics.get('probes_sent', 0)} probes lost)")
    mean_rtt = metrics.get('mean_rtt_ms')
    print(f"   Mean Latency:     {f'{mean_rtt:.2f} ms' if mean_rtt is not None else 'N/A'}")
    jitter = metrics.get('stddev_rtt_ms')
    print(f"   Jitter (StdDev):  {f'{jitter:.2f} ms' if jitter is not None else 'N/A'}")
    print("-" * 70)

    total_paths = comparison.get("total_paths", 0)
    print(f" SDN Candidate Paths Discovered: {total_paths}")

    if total_paths > 0:
        primary = comparison.get("primary_path", {})
        print(f"   Primary Route:    {primary.get('path_str')} ({primary.get('hop_count')} hops)")

        alts = comparison.get("alternative_paths", [])
        if alts:
            print("\n Alternative Routes Available:")
            for alt in alts:
                print(f"   [Rank {alt['rank']}] {alt['path_str']} ({alt['hop_count']} hops, +{alt['extra_hops']} extra)")
        else:
            print("   No alternate topology paths available between these nodes.")
    else:
        print("   No path found in current SDN topology between source and destination.")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Correlate UDP Diagnostic Metrics with SDN Topology Paths."
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
