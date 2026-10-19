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

from diagnostic_client import run_diagnostics_single, run_diagnostics_multi, load_config as load_client_config

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
            verbose=args.verbose
        )


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
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
