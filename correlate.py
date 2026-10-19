#!/usr/bin/env python3
"""
Measurement and Topology Correlation Module
(with Multi-Source Failure Localization and Safe Backup Path Re-Ranking)
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Correlates active UDP measurement metrics (RTT and packet loss) with SDN
network topology data and OpenFlow flow tables. Classifies path health,
localizes failure using three distinct evidence sources (port statistics deltas,
per-segment probing, and controller link liveness), pinpoints suspected failed links
with confidence scores, and prunes broken links to rank viable alternative backup paths.
"""

import argparse
import json
import logging
import os
import re
import sys
import time

from topology_graph import SDNTopologyGraph
from flow_inspector import FlowInspector

DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_DIAG_FILE = "diagnostic_result.json"
DEFAULT_TOPO_FILE = "topology.json"
DEFAULT_REPORT_FILE = "correlation_report.json"
DEFAULT_SOURCE = "h1"


def setup_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("correlate")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
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


def classify_path_health(summary: dict, thresholds: dict) -> tuple:
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
    """
    suspects = []
    if not baseline_stats or not current_stats:
        return suspects

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


def analyze_topology_liveness(expected_path_links: list, active_topology_links: list) -> list:
    """
    Evidence Source C: Compare active controller links against expected path links.
    Flags links that have completely disappeared from controller active topology.
    """
    suspects = []
    active_set = {tuple(sorted([l.get("source"), l.get("destination")])) for l in active_topology_links}

    for link in expected_path_links:
        src, dst = link[0], link[1]
        pair = tuple(sorted([src, dst]))
        if pair not in active_set:
            suspects.append({
                "link": [src, dst],
                "link_str": f"{src} <---> {dst}",
                "evidence_type": "topology_liveness",
                "confidence": 1.0,
                "evidence": [f"Link {src} <---> {dst} disappeared from active SDN controller topology"]
            })

    return suspects


def aggregate_suspected_links(all_suspects: list) -> list:
    """Consolidate multiple evidence sources per link and compute combined confidence."""
    grouped = {}
    for item in all_suspects:
        pair_key = tuple(sorted(item["link"]))
        if pair_key not in grouped:
            grouped[pair_key] = {
                "link": list(pair_key),
                "link_str": f"{pair_key[0]} <---> {pair_key[1]}",
                "evidence": [],
                "confidences": []
            }
        grouped[pair_key]["evidence"].extend(item["evidence"])
        grouped[pair_key]["confidences"].append(item["confidence"])

    consolidated = []
    for pair_key, data in grouped.items():
        # Combined confidence: 1 - product(1 - c_i)
        comb_conf = 1.0
        for c in data["confidences"]:
            comb_conf *= (1.0 - c)
        final_conf = round(1.0 - comb_conf, 3)

        consolidated.append({
            "link": data["link"],
            "link_str": data["link_str"],
            "confidence": final_conf,
            "evidence": list(dict.fromkeys(data["evidence"]))
        })

    consolidated.sort(key=lambda x: x["confidence"], reverse=True)
    return consolidated


def filter_and_rank_backups(candidate_paths: list, primary_path: list,
                            suspected_links: list, min_confidence: float = 0.5) -> list:
    """
    Prune candidate paths that traverse suspected-bad links, then rank surviving
    backup paths by hop count.
    """
    bad_pairs = set()
    for s in suspected_links:
        if s["confidence"] >= min_confidence:
            bad_pairs.add(tuple(sorted(s["link"])))

    primary_hops = len(primary_path) - 1 if primary_path else 0
    ranked = []

    for path in candidate_paths:
        if path == primary_path:
            continue

        # Check if path contains any bad link
        has_bad_link = False
        path_links = [tuple(sorted([path[i], path[i + 1]])) for i in range(len(path) - 1)]
        for pl in path_links:
            if pl in bad_pairs:
                has_bad_link = True
                break

        hops = len(path) - 1
        extra_hops = hops - primary_hops
        ranked.append({
            "path": path,
            "path_str": " -> ".join(path),
            "hop_count": hops,
            "extra_hops": extra_hops,
            "status": "EXCLUDED_CORRUPT_LINK" if has_bad_link else "VIABLE_BACKUP",
            "is_viable": not has_bad_link
        })

    # Sort viable paths first, then by hop count
    ranked.sort(key=lambda x: (not x["is_viable"], x["hop_count"]))
    for idx, r in enumerate(ranked, start=1):
        r["rank"] = idx

    return ranked


def correlate(diag_file: str, topo_file: str, source_node: str,
              config_file: str = DEFAULT_CONFIG_PATH,
              output_file: str = DEFAULT_REPORT_FILE,
              controller_url: str = None,
              baseline_stats_file: str = None,
              current_stats_file: str = None,
              override_thresholds: dict = None,
              rank_backups: bool = True) -> dict:
    """
    Correlate diagnostic measurements with SDN topology graph, perform multi-source
    failure localization, and recommend clean backup paths.
    """
    cfg = load_config(config_file)
    thresholds = cfg["thresholds"]
    if override_thresholds:
        thresholds.update({k: v for k, v in override_thresholds.items() if v is not None})

    # 1. Load diagnostic measurements
    if not os.path.exists(diag_file):
        raise FileNotFoundError(f"Diagnostic results file not found: {diag_file}")
    with open(diag_file, "r", encoding="utf-8") as f:
        diag_data = json.load(f)

    target_ip = diag_data.get("target_ip")
    summary = diag_data.get("summary", {})
    loss_pct = summary.get("packet_loss_percent", 100.0)
    mean_rtt = summary.get("mean_rtt_ms")

    # 2. Load topology graph
    if not os.path.exists(topo_file):
        raise FileNotFoundError(f"SDN topology file not found: {topo_file}")
    graph = SDNTopologyGraph()
    graph.load_from_file(topo_file)

    src_canonical = graph.resolve_node(source_node) or source_node
    dst_canonical = graph.resolve_node(target_ip) or target_ip

    # 3. Reconstruct active path (from flow tables or graph fallback)
    c_url = controller_url or f"http://{cfg.get('controller_ip', '127.0.0.1')}:{cfg.get('ryu_port', 8080)}"
    inspector = FlowInspector(controller_url=c_url, topology_file=topo_file)
    path_info = inspector.reconstruct_active_path(src_canonical, dst_canonical)

    active_path = path_info.get("path", [])
    path_source = path_info.get("path_source", "none")

    # Candidate paths for alternatives
    candidate_paths = graph.find_all_simple_paths(src_canonical, dst_canonical)
    comparison_data = graph.compare_paths(candidate_paths)

    # 4. Classify health
    path_status, failed_path_reason = classify_path_health(summary, thresholds)

    # 5. Multi-Source Failure Localization
    suspects_raw = []

    # Evidence A: Port Stats Deltas
    base_stats = {}
    curr_stats = {}
    if baseline_stats_file and os.path.exists(baseline_stats_file):
        with open(baseline_stats_file, "r", encoding="utf-8") as f:
            base_stats = json.load(f)
    if current_stats_file and os.path.exists(current_stats_file):
        with open(current_stats_file, "r", encoding="utf-8") as f:
            curr_stats = json.load(f)

    if base_stats and curr_stats:
        suspects_raw.extend(analyze_port_stats_deltas(base_stats, curr_stats, graph.links))

    # Evidence B: Segment probing
    segment_metrics = diag_data.get("segment_metrics", {})
    if segment_metrics:
        suspects_raw.extend(analyze_segment_probes(segment_metrics, active_path))

    # Evidence C: Topology Liveness
    expected_links = []
    if active_path:
        for i in range(len(active_path) - 1):
            expected_links.append((active_path[i], active_path[i + 1]))
    if path_status in ["FAILED_PATH", "DEGRADED_PATH"] and expected_links:
        with open(topo_file, "r", encoding="utf-8") as f:
            current_topo = json.load(f)
        suspects_raw.extend(analyze_topology_liveness(expected_links, current_topo.get("links", [])))

    suspected_links = aggregate_suspected_links(suspects_raw)

    # If failed/degraded and no specific link was caught by stats, flag primary path intermediate links
    if path_status in ["FAILED_PATH", "DEGRADED_PATH"] and not suspected_links and active_path:
        for i in range(len(active_path) - 1):
            suspected_links.append({
                "link": [active_path[i], active_path[i + 1]],
                "link_str": f"{active_path[i]} <---> {active_path[i + 1]}",
                "confidence": 0.60,
                "evidence": ["Inferred from end-to-end packet loss / latency anomaly across active route"]
            })

    # 6. Rank Backup Paths (excluding suspected bad links)
    ranked_backups = filter_and_rank_backups(candidate_paths, active_path, suspected_links)
    recommended_backup = next((b for b in ranked_backups if b["is_viable"]), None)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path_status": path_status,
        "source_node": src_canonical,
        "destination_node": dst_canonical,
        "destination_ip": target_ip,
        "path_source": path_source,
        "active_path": {
            "path": active_path,
            "path_str": " -> ".join(active_path),
            "hop_count": len(active_path) - 1 if active_path else 0,
            "source": path_source
        },
        "failed_path_reason": failed_path_reason,
        "packet_loss_percentage": loss_pct,
        "mean_rtt": mean_rtt,
        "suspected_links": suspected_links,
        "ranked_backup_paths": ranked_backups,
        "recommended_backup_path": recommended_backup,
        "detailed_metrics": {
            "probes_sent": summary.get("sent"),
            "probes_received": summary.get("received"),
            "probes_lost": summary.get("lost"),
            "packet_loss_percentage": loss_pct,
            "min_rtt_ms": summary.get("min_rtt_ms"),
            "max_rtt_ms": summary.get("max_rtt_ms"),
            "mean_rtt_ms": mean_rtt,
            "median_rtt_ms": summary.get("median_rtt_ms"),
            "stddev_rtt_ms": summary.get("stddev_rtt_ms"),
            "rfc3550_jitter_ms": summary.get("rfc3550_jitter_ms"),
            "p95_rtt_ms": summary.get("p95_rtt_ms")
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


def print_terminal_report(report: dict):
    """Print high-clarity terminal diagnostic report with clear status banner."""
    status = report.get("path_status", "UNKNOWN")
    reason = report.get("failed_path_reason")
    src = report.get("source_node")
    dst = report.get("destination_node")
    dst_ip = report.get("destination_ip")
    loss = report.get("packet_loss_percentage", 0.0)
    mean_rtt = report.get("mean_rtt")
    active = report.get("active_path", {})
    suspects = report.get("suspected_links", [])
    backups = report.get("ranked_backup_paths", [])
    recommended = report.get("recommended_backup_path")

    banner_symbol = "[●]"
    if status == "HEALTHY_PATH":
        banner_symbol = "[✔ HEALTHY]"
    elif status == "DEGRADED_PATH":
        banner_symbol = "[▲ DEGRADED]"
    elif status == "FAILED_PATH":
        banner_symbol = "[✖ FAILED]"

    print("\n" + "=" * 74)
    print(f" {banner_symbol:<14} SDN NETWORK PATH DIAGNOSTIC & CORRELATION REPORT")
    print("=" * 74)
    print(f" PATH STATUS:             {status}")
    print(f" FAILED-PATH REASON:      {reason}")
    print("-" * 74)
    print(f" Source Node:             {src}")
    print(f" Destination Node:        {dst} (IP: {dst_ip})")
    print(f" Packet Loss:             {loss:.2f}%")
    print(f" Mean RTT:                {f'{mean_rtt:.2f} ms' if mean_rtt is not None else 'N/A'}")
    print(f" Active Path:             {active.get('path_str')} ({active.get('hop_count')} hops)")
    print(f" Path Source:             {active.get('source', 'unknown').upper()}")
    print("-" * 74)

    # Suspected Links Table
    if suspects:
        print(" SUSPECTED FAILED / DEGRADED LINKS (Localization Evidence):")
        print(f" {'Rank':<6} {'Suspected Link':<24} {'Confidence':<14} {'Evidence'}")
        print(" " + "-" * 72)
        for idx, s in enumerate(suspects, start=1):
            conf_str = f"{s['confidence'] * 100:.1f}%"
            ev_str = "; ".join(s["evidence"])
            print(f" {idx:<6} {s['link_str']:<24} {conf_str:<14} {ev_str}")
        print("-" * 74)

    # Ranked Backup Paths
    print(f" RANKED BACKUP PATHS (Pruned of Suspected Links):")
    if backups:
        print(f" {'Rank':<6} {'Status':<25} {'Hops':<8} {'Extra':<8} {'Route'}")
        print(" " + "-" * 72)
        for b in backups:
            rank = b.get("rank")
            b_status = b.get("status")
            hops = b.get("hop_count")
            extra = f"+{b.get('extra_hops')}" if b.get('extra_hops') > 0 else "0"
            route = b.get("path_str")
            print(f" {rank:<6} {b_status:<25} {hops:<8} {extra:<8} {route}")
    else:
        print("  No alternative candidate paths available in current topology.")

    print("-" * 74)
    if status in ["FAILED_PATH", "DEGRADED_PATH"]:
        if recommended:
            print(f" [ACTION RECOMMENDED] Failover to Viable Backup Route:")
            print(f" -> Best Backup:  {recommended['path_str']} ({recommended['hop_count']} hops, +{recommended['extra_hops']} extra)")
            print(" -> Next Step:    Deploy backup flow rules via reroute_helper.py or SDN controller.")
        else:
            print(" [CRITICAL] Path is down/degraded and NO viable alternative paths exist in topology!")
    else:
        print(" [OK] Network path operating within nominal parameters. No rerouting needed.")
    print("=" * 74 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Correlate UDP Metrics with SDN Topology, Localize Failures, and Rank Backup Paths."
    )
    parser.add_argument("-d", "--diag", default=DEFAULT_DIAG_FILE, help=f"Diagnostic result JSON file (default: {DEFAULT_DIAG_FILE})")
    parser.add_argument("-t", "--topo", default=DEFAULT_TOPO_FILE, help=f"SDN topology JSON file (default: {DEFAULT_TOPO_FILE})")
    parser.add_argument("-s", "--source", default=DEFAULT_SOURCE, help=f"Source node ID or IPv4 address (default: {DEFAULT_SOURCE})")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH, help=f"Configuration JSON file (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--controller", help="SDN Controller REST base URL (e.g. http://127.0.0.1:8080)")
    parser.add_argument("--baseline-stats", dest="baseline_stats", help="JSON file containing switch port stats before probing")
    parser.add_argument("--current-stats", dest="current_stats", help="JSON file containing switch port stats after probing")
    parser.add_argument("--degraded-loss", type=float, help="Override degraded packet loss percentage threshold")
    parser.add_argument("--failed-loss", type=float, help="Override failed packet loss percentage threshold")
    parser.add_argument("--degraded-rtt", type=float, help="Override degraded mean RTT (ms) threshold")
    parser.add_argument("-o", "--output", default=DEFAULT_REPORT_FILE, help=f"Output correlation JSON file (default: {DEFAULT_REPORT_FILE})")

    args = parser.parse_args()

    override_thresholds = {
        "degraded_packet_loss_percent": args.degraded_loss,
        "failed_packet_loss_percent": args.failed_loss,
        "degraded_rtt_ms": args.degraded_rtt
    }

    try:
        correlate(
            diag_file=args.diag,
            topo_file=args.topo,
            source_node=args.source,
            config_file=args.config,
            output_file=args.output,
            controller_url=args.controller,
            baseline_stats_file=args.baseline_stats,
            current_stats_file=args.current_stats,
            override_thresholds=override_thresholds
        )
    except Exception as e:
        print(f"[ERROR] Correlation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
