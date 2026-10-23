#!/usr/bin/env python3
"""
SDNScope: Unified Command-Line Interface for SDN Diagnostics and Path Analysis
Topic 13: Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Provides unified subcommands:
  - probe:     Run UDP active probing client
  - serve:     Start UDP diagnostic probe server
  - trace:     Execute hop-by-hop network path tracing
  - topo:      Discover SDN switches, links, and hosts
  - paths:     Find and compare topological paths in graph
  - correlate: Correlate measurements with SDN topology
  - watch:     Monitor live topology events (link up/down)
  - localize:  Multi-source failure localization
  - reroute:   Deploy OpenFlow flow modifications along backup paths
  - report:    Generate comprehensive Markdown and HTML reports
"""

import argparse
import ipaddress
import json
import logging
import os
import sys

from correlate import (
    aggregate_suspected_links,
    analyze_port_stats_deltas,
    analyze_segment_probes,
    analyze_topology_liveness,
    correlate as run_correlation,
)
from diagnostic_client import load_config as load_client_config, run_diagnostics_multi, run_diagnostics_single
from path_analysis import print_path_table, run_path_analysis
from probe_server import load_default_config as load_server_config, start_server
from report_generator import build_report
from reroute_helper import apply_reroute, generate_flow_entries
from sdn_topology import discover_topology, load_config as load_topo_config, print_topology_summary, watch_topology
from topology_graph import SDNTopologyGraph, print_path_comparison

VERSION = "1.0.0"


def setup_logger(verbose: bool = False, quiet: bool = False) -> logging.Logger:
    logger = logging.getLogger("sdnscope")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    if quiet:
        logger.setLevel(logging.ERROR)
    elif verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    return logger


def validate_ip(ip_str: str) -> str:
    """Validate IPv4 address string."""
    try:
        ipaddress.IPv4Address(ip_str.strip())
        return ip_str.strip()
    except ValueError:
        print(f"[ERROR] Invalid IPv4 address: '{ip_str}'", file=sys.stderr)
        sys.exit(1)


def validate_port(port_val: int) -> int:
    """Validate TCP/UDP port range."""
    if not (1 <= port_val <= 65535):
        print(f"[ERROR] Port number out of range (1-65535): {port_val}", file=sys.stderr)
        sys.exit(1)
    return port_val


def validate_file_exists(filepath: str, desc: str = "File") -> str:
    """Validate that required file exists on disk."""
    if not os.path.exists(filepath):
        print(f"[ERROR] {desc} not found: '{filepath}'", file=sys.stderr)
        sys.exit(1)
    return filepath


def cmd_probe(args):
    """Execute UDP active diagnostic probing."""
    cfg = load_client_config()
    port = validate_port(args.port or cfg.get("udp_port", 9999))
    count = args.count or cfg.get("probe_count", 10)
    timeout = args.timeout or cfg.get("timeout", 2.0)
    size = args.size or cfg.get("payload_size", 64)
    interval = args.interval or cfg.get("interval", 0.1)

    targets = [t.strip() for t in args.target.split(",") if t.strip()]
    for t in targets:
        validate_ip(t)

    if len(targets) > 1:
        run_diagnostics_multi(
            targets=targets,
            port=port,
            count=count,
            timeout=timeout,
            payload_size=size,
            output_prefix=args.output.replace(".json", ""),
            interval=interval,
            burst=args.burst,
            verbose=args.verbose
        )
    else:
        run_diagnostics_single(
            target_ip=targets[0],
            port=port,
            count=count,
            timeout=timeout,
            payload_size=size,
            output_file=args.output,
            interval=interval,
            burst=args.burst,
            verbose=args.verbose,
            dest_node=args.dest_node
        )


def cmd_serve(args):
    """Start UDP diagnostic probe server."""
    port = validate_port(args.port or load_server_config())
    bind_ip = validate_ip(args.bind) if args.bind != "0.0.0.0" else args.bind
    drop_rate = args.drop_rate
    delay_ms = args.delay_ms

    if not (0.0 <= drop_rate <= 1.0):
        print(f"[ERROR] --drop-rate must be between 0.0 and 1.0, got {drop_rate}", file=sys.stderr)
        sys.exit(1)
    if delay_ms < 0:
        print(f"[ERROR] --delay-ms must be non-negative, got {delay_ms}", file=sys.stderr)
        sys.exit(1)

    start_server(host=bind_ip, port=port, drop_rate=drop_rate, delay_ms=delay_ms, verbose=args.verbose)


def cmd_trace(args):
    """Execute network path analysis."""
    target = validate_ip(args.target)
    max_hops = args.max_hops
    if max_hops <= 0 or max_hops > 255:
        print(f"[ERROR] --max-hops must be between 1 and 255, got {max_hops}", file=sys.stderr)
        sys.exit(1)

    result = run_path_analysis(target_ip=target, max_hops=max_hops, timeout=args.timeout, verbose=args.verbose)
    print_path_table(result)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"\n[INFO] Path trace saved to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to save {args.output}: {e}", file=sys.stderr)


def cmd_topo(args):
    """Discover SDN switches, hosts, and links."""
    cfg = load_topo_config()
    ctl_type = args.controller or cfg.get("sdn_controller_type", "ryu")
    ip = validate_ip(args.ip or cfg.get("controller_ip", "127.0.0.1"))
    port = args.port
    if port is None:
        port = cfg.get("opendaylight_port", 8181) if ctl_type in ["odl", "opendaylight"] else cfg.get("ryu_port", 8080)
    port = validate_port(port)

    username = args.username or cfg.get("username", "admin")
    password = args.password or cfg.get("password", "")

    try:
        hosts_file = getattr(args, "hosts_file", None)
        topo = discover_topology(ctl_type, ip, port, username, password, verbose=args.verbose, hosts_file=hosts_file)
        print_topology_summary(topo)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(topo, f, indent=2)
            print(f"\n[INFO] Topology written to: {args.output}")
    except ConnectionError as ce:
        print(f"[ERROR] Connection failed: {ce}", file=sys.stderr)
        print("[HINT] Ensure SDN controller is active, or use mock_controller.py for offline tests.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Topology discovery failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_paths(args):
    """Find and compare simple loop-free paths in SDN graph."""
    topo_file = validate_file_exists(args.file, "Topology file")
    graph = SDNTopologyGraph()
    try:
        graph.load_from_file(topo_file)
    except Exception as e:
        print(f"[ERROR] Failed to load topology file '{topo_file}': {e}", file=sys.stderr)
        sys.exit(1)

    src_node = graph.resolve_node(args.source)
    dst_node = graph.resolve_node(args.dest)

    if not src_node:
        print(f"[ERROR] Source node or IP '{args.source}' not resolved in topology.", file=sys.stderr)
        sys.exit(1)
    if not dst_node:
        print(f"[ERROR] Destination node or IP '{args.dest}' not resolved in topology.", file=sys.stderr)
        sys.exit(1)

    paths = graph.find_all_simple_paths(src_node, dst_node, max_paths=args.max_paths)
    comparison = graph.compare_paths(paths)
    print_path_comparison(src_node, dst_node, comparison)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({"source": src_node, "destination": dst_node, "comparison": comparison}, f, indent=2)
            print(f"\n[INFO] Path comparison written to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to save {args.output}: {e}", file=sys.stderr)


def cmd_correlate(args):
    """Correlate telemetry with topology, localize failures, and rank backups."""
    diag_file = validate_file_exists(args.diag, "Diagnostic result file")
    topo_file = validate_file_exists(args.topo, "Topology file")
    config_file = args.config if os.path.exists(args.config) else "config.json"

    override_thresholds = {
        "degraded_packet_loss_percent": args.degraded_loss,
        "failed_packet_loss_percent": args.failed_loss,
        "degraded_rtt_ms": args.degraded_rtt
    }

    try:
        run_correlation(
            diag_file=diag_file,
            topo_file=topo_file,
            source_node=args.source,
            dest_node=args.dest_node,
            config_file=config_file,
            output_file=args.output,
            controller_url=args.controller,
            current_topo_file=args.current_topo,
            baseline_stats_file=args.baseline_stats,
            current_stats_file=args.current_stats,
            override_thresholds=override_thresholds
        )
    except Exception as e:
        print(f"[ERROR] Correlation failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_watch(args):
    """Monitor live topology changes (link up/down, switches)."""
    cfg = load_topo_config()
    ctl_type = args.controller or cfg.get("sdn_controller_type", "ryu")
    ip = validate_ip(args.ip or cfg.get("controller_ip", "127.0.0.1"))
    port = args.port
    if port is None:
        port = cfg.get("opendaylight_port", 8181) if ctl_type in ["odl", "opendaylight"] else cfg.get("ryu_port", 8080)
    port = validate_port(port)

    username = args.username or cfg.get("username", "admin")
    password = args.password or cfg.get("password", "")
    interval = args.interval
    if interval <= 0:
        print(f"[ERROR] --interval must be positive, got {interval}", file=sys.stderr)
        sys.exit(1)

    watch_topology(
        controller_type=ctl_type,
        ip=ip,
        port=port,
        interval=interval,
        username=username,
        password=password,
        output_file=args.output,
        verbose=args.verbose
    )


def cmd_localize(args):
    """Execute dedicated multi-source failure localization."""
    topo_file = validate_file_exists(args.topo, "Topology file")
    with open(topo_file, "r", encoding="utf-8") as f:
        topo_data = json.load(f)

    suspects_raw = []

    # 1. Port statistics
    if args.baseline_stats and args.current_stats:
        b_file = validate_file_exists(args.baseline_stats, "Baseline port stats file")
        c_file = validate_file_exists(args.current_stats, "Current port stats file")
        with open(b_file, "r", encoding="utf-8") as f:
            base_stats = json.load(f)
        with open(c_file, "r", encoding="utf-8") as f:
            curr_stats = json.load(f)
        suspects_raw.extend(analyze_port_stats_deltas(base_stats, curr_stats, topo_data.get("links", [])))

    # 2. Segment probing from diag file
    if args.diag and os.path.exists(args.diag):
        with open(args.diag, "r", encoding="utf-8") as f:
            diag_data = json.load(f)
        seg_metrics = diag_data.get("segment_metrics", {})
        active_path = args.path.split("->") if args.path else []
        active_path = [n.strip() for n in active_path if n.strip()]
        if seg_metrics and active_path:
            suspects_raw.extend(analyze_segment_probes(seg_metrics, active_path))

    # 3. Topology liveness
    if args.expected_links:
        pairs = [p.strip().split(":") for p in args.expected_links.split(",") if ":" in p]
        suspects_raw.extend(analyze_topology_liveness(pairs, topo_data.get("links", [])))

    suspects = aggregate_suspected_links(suspects_raw)

    print("=" * 74)
    print("             SDN MULTI-SOURCE FAILURE LOCALIZATION REPORT")
    print("=" * 74)
    print(f" Analyzed Topology: {topo_file}")
    print(f" Suspected Links:   {len(suspects)}")
    print("-" * 74)

    if not suspects:
        print(" [OK] No failed or degraded links identified from provided telemetry.")
    else:
        print(f" {'Rank':<6} {'Suspected Link':<24} {'Confidence':<14} {'Evidence'}")
        print(" " + "-" * 72)
        for idx, s in enumerate(suspects, start=1):
            conf_str = f"{s['confidence'] * 100:.1f}%"
            ev_str = "; ".join(s["evidence"])
            print(f" {idx:<6} {s['link_str']:<24} {conf_str:<14} {ev_str}")

    print("=" * 74)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump({"suspected_links": suspects}, f, indent=2)
            print(f"[INFO] Localization report saved to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to save {args.output}: {e}", file=sys.stderr)


def cmd_reroute(args):
    """Deploy backup flow rules via SDN controller."""
    report_file = validate_file_exists(args.report, "Correlation report file")
    topo_file = validate_file_exists(args.topo, "Topology file")

    with open(report_file, "r", encoding="utf-8") as f:
        report_data = json.load(f)

    backup_info = report_data.get("recommended_backup_path")
    if not backup_info:
        backups = [b for b in report_data.get("ranked_backup_paths", []) if b.get("is_viable")]
        backup_info = backups[0] if backups else None

    if not backup_info:
        print("[ERROR] No viable backup route found in correlation report to deploy.", file=sys.stderr)
        sys.exit(1)

    backup_path = backup_info.get("path", [])
    dst_ip = report_data.get("destination_ip", "10.0.0.2")

    graph = SDNTopologyGraph()
    graph.load_from_file(topo_file)

    rules = generate_flow_entries(backup_path, graph, dst_ip, priority=args.priority)
    apply_reroute(rules, controller_url=args.controller, apply_changes=args.apply, verbose=args.verbose)


def cmd_report(args):
    """Generate Markdown and HTML reports from diagnosis JSON."""
    report_file = validate_file_exists(args.report, "Correlation report file")
    diag_file = args.diag if (args.diag and os.path.exists(args.diag)) else "diagnostic_result.json"

    md_out, html_out, chart = build_report(
        report_file=report_file,
        diag_file=diag_file,
        output_md=args.md,
        output_html=args.html,
        output_dir=args.dir
    )
    print(f"[SUCCESS] Markdown report generated: {md_out}")
    print(f"[SUCCESS] HTML report generated:     {html_out}")
    if chart:
        print(f"[SUCCESS] Latency chart saved:       {chart}")


def main():
    parser = argparse.ArgumentParser(
        prog="sdnscope",
        description=f"SDNScope (v{VERSION}): Unified SDN Network Diagnostics & Path Analysis Suite."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug output")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error logs")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    subparsers = parser.add_subparsers(dest="subcommand", title="subcommands", required=True)

    # 1. Subcommand: probe
    p_probe = subparsers.add_parser("probe", help="Run active UDP diagnostic client")
    p_probe.add_argument("target", help="Target IP or comma-separated IPs (e.g. 10.0.0.2 or 10.0.0.2,10.0.0.3)")
    p_probe.add_argument("-p", "--port", type=int, help="Destination UDP port (default: from config.json or 9999)")
    p_probe.add_argument("-c", "--count", type=int, help="Number of probes to send (default: 10)")
    p_probe.add_argument("-s", "--size", type=int, help="Probe payload size in bytes (default: 64)")
    p_probe.add_argument("--timeout", type=float, help="Timeout in seconds per probe (default: 2.0)")
    p_probe.add_argument("--interval", type=float, help="Delay between probes in seconds (default: 0.1)")
    p_probe.add_argument("--burst", action="store_true", help="Send probes back-to-back with zero delay")
    p_probe.add_argument("-o", "--output", default="diagnostic_result.json", help="Output JSON filepath")
    p_probe.add_argument("-n", "--dest-node", dest="dest_node", default=None, help="Destination node ID (e.g. h2) to associate with telemetry")
    p_probe.set_defaults(func=cmd_probe)

    # 2. Subcommand: serve
    p_serve = subparsers.add_parser("serve", help="Start UDP diagnostic probe server")
    p_serve.add_argument("-p", "--port", type=int, help="UDP port to bind (default: 9999)")
    p_serve.add_argument("-b", "--bind", default="0.0.0.0", help="IP address to bind (default: 0.0.0.0)")
    p_serve.add_argument("--drop-rate", type=float, default=0.0, help="Artificial packet drop rate (0.0 to 1.0)")
    p_serve.add_argument("--delay-ms", type=float, default=0.0, help="Artificial delay in milliseconds")
    p_serve.set_defaults(func=cmd_serve)

    # 3. Subcommand: trace
    p_trace = subparsers.add_parser("trace", help="Execute hop-by-hop path tracing")
    p_trace.add_argument("target", help="Target IP address to trace")
    p_trace.add_argument("-m", "--max-hops", type=int, default=30, help="Maximum hop limit (default: 30)")
    p_trace.add_argument("--timeout", type=float, default=2.0, help="Timeout in seconds per probe (default: 2.0)")
    p_trace.add_argument("-o", "--output", help="Optional output JSON filepath")
    p_trace.set_defaults(func=cmd_trace)

    # 4. Subcommand: topo
    p_topo = subparsers.add_parser("topo", help="Discover SDN switches, links, and hosts")
    p_topo.add_argument("-c", "--controller", choices=["ryu", "opendaylight", "odl"], help="Controller type (default: ryu)")
    p_topo.add_argument("-i", "--ip", help="Controller IP address (default: 127.0.0.1)")
    p_topo.add_argument("-p", "--port", type=int, help="Controller REST port")
    p_topo.add_argument("-u", "--username", help="Controller REST username")
    p_topo.add_argument("-P", "--password", help="Controller REST password")
    p_topo.add_argument("--hosts-file", dest="hosts_file", help="Path to hosts JSON file to merge if controller hosts API is empty")
    p_topo.add_argument("-o", "--output", default="topology.json", help="Output JSON filepath (default: topology.json)")
    p_topo.set_defaults(func=cmd_topo)

    # 5. Subcommand: paths
    p_paths = subparsers.add_parser("paths", help="Find and compare topological paths in SDN graph")
    p_paths.add_argument("-s", "--source", required=True, help="Source node ID or IP (e.g. h1 or 10.0.0.1)")
    p_paths.add_argument("-d", "--dest", required=True, help="Destination node ID or IP (e.g. h2 or 10.0.0.2)")
    p_paths.add_argument("-f", "--file", default="topology.json", help="Topology JSON file (default: topology.json)")
    p_paths.add_argument("-m", "--max-paths", type=int, default=10, help="Maximum number of paths to find (default: 10)")
    p_paths.add_argument("-o", "--output", help="Optional output JSON filepath")
    p_paths.set_defaults(func=cmd_paths)

    # 6. Subcommand: correlate
    p_corr = subparsers.add_parser("correlate", help="Correlate UDP telemetry with topology and localize failure")
    p_corr.add_argument("-d", "--diag", default="diagnostic_result.json", help="Diagnostic result JSON (default: diagnostic_result.json)")
    p_corr.add_argument("-t", "--topo", default="topology.json", help="Topology JSON (default: topology.json)")
    p_corr.add_argument("-s", "--source", default="h1", help="Source node ID or IP (default: h1)")
    p_corr.add_argument("-e", "--dest", "--destination", dest="dest_node", default=None, help="Destination node ID (e.g. h2) if target is localhost or not directly mapped")
    p_corr.add_argument("-c", "--config", default="config.json", help="Config JSON filepath (default: config.json)")
    p_corr.add_argument("--controller", help="SDN Controller REST base URL")
    p_corr.add_argument("--current-topo", dest="current_topo", help="Current active topology JSON file (if link has failed)")
    p_corr.add_argument("--baseline-stats", dest="baseline_stats", help="Port stats before probing JSON")
    p_corr.add_argument("--current-stats", dest="current_stats", help="Port stats after probing JSON")
    p_corr.add_argument("--degraded-loss", type=float, help="Override degraded packet loss percentage threshold")
    p_corr.add_argument("--failed-loss", type=float, help="Override failed packet loss percentage threshold")
    p_corr.add_argument("--degraded-rtt", type=float, help="Override degraded mean RTT (ms) threshold")
    p_corr.add_argument("-o", "--output", default="correlation_report.json", help="Output correlation JSON filepath")
    p_corr.set_defaults(func=cmd_correlate)

    # 7. Subcommand: watch
    p_watch = subparsers.add_parser("watch", help="Continuously monitor topology changes and link state events")
    p_watch.add_argument("-w", "--interval", type=int, default=5, help="Polling interval in seconds (default: 5)")
    p_watch.add_argument("-c", "--controller", choices=["ryu", "opendaylight", "odl"], help="Controller type (default: ryu)")
    p_watch.add_argument("-i", "--ip", help="Controller IP address (default: 127.0.0.1)")
    p_watch.add_argument("-p", "--port", type=int, help="Controller REST port")
    p_watch.add_argument("-u", "--username", help="Controller REST username")
    p_watch.add_argument("-P", "--password", help="Controller REST password")
    p_watch.add_argument("-o", "--output", default="topology.json", help="Output JSON filepath (default: topology.json)")
    p_watch.set_defaults(func=cmd_watch)

    # 8. Subcommand: localize
    p_loc = subparsers.add_parser("localize", help="Localize failures using port stats, segment probes, and topology liveness")
    p_loc.add_argument("-t", "--topo", default="topology.json", help="SDN topology JSON file (default: topology.json)")
    p_loc.add_argument("--baseline-stats", dest="baseline_stats", help="Port stats before probing JSON")
    p_loc.add_argument("--current-stats", dest="current_stats", help="Port stats after probing JSON")
    p_loc.add_argument("-d", "--diag", help="Diagnostic results JSON with segment metrics")
    p_loc.add_argument("--path", help="Active forwarding path (e.g. h1->s1->s2->h2)")
    p_loc.add_argument("--expected-links", help="Comma-separated expected links (e.g. s1:s2,s2:h2)")
    p_loc.add_argument("-o", "--output", help="Optional output JSON filepath")
    p_loc.set_defaults(func=cmd_localize)

    # 9. Subcommand: reroute
    p_re = subparsers.add_parser("reroute", help="Deploy backup flow rules via SDN controller")
    p_re.add_argument("-r", "--report", default="correlation_report.json", help="Correlation report JSON (default: correlation_report.json)")
    p_re.add_argument("-t", "--topo", default="topology.json", help="Topology JSON file (default: topology.json)")
    p_re.add_argument("-c", "--controller", default="http://127.0.0.1:8080", help="SDN controller URL")
    p_re.add_argument("--priority", type=int, default=200, help="OpenFlow rule priority (default: 200)")
    p_re.add_argument("--apply", action="store_true", help="Explicitly apply rules to controller (default: dry-run)")
    p_re.set_defaults(func=cmd_reroute)

    # 10. Subcommand: report
    p_rep = subparsers.add_parser("report", help="Generate Markdown and HTML reports from diagnosis results")
    p_rep.add_argument("-r", "--report", default="correlation_report.json", help="Correlation report JSON (default: correlation_report.json)")
    p_rep.add_argument("-d", "--diag", default="diagnostic_result.json", help="Diagnostic results JSON (default: diagnostic_result.json)")
    p_rep.add_argument("-m", "--md", default="report.md", help="Output Markdown filepath (default: report.md)")
    p_rep.add_argument("-H", "--html", default="report.html", help="Output HTML filepath (default: report.html)")
    p_rep.add_argument("--dir", default="results", help="Directory for charts and artifacts")
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
