#!/usr/bin/env python3
"""
Path Analysis Module
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This module performs network path discovery to a target IP using native raw UDP/ICMP
sockets when permitted, with graceful fallback to system traceroute/tracepath.
Crucially, it provides per-hop RTT and loss statistics, and documents the
fundamental SDN property that OpenFlow L2 switches do not decrement IP TTL.
"""

import argparse
import json
import logging
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time

DEFAULT_MAX_HOPS = 30
DEFAULT_TIMEOUT_SEC = 2.0
DEFAULT_PROBES_PER_HOP = 3
SDN_L2_TTL_NOTE = (
    "In standard OpenFlow/Mininet networks, switches forward packets at Layer 2 without "
    "decrementing the IPv4 TTL field (unless explicit dec_ttl actions exist). "
    "Consequently, standard traceroute only reveals Layer 3 routed hops, not intermediate "
    "OpenFlow switches. Authoritative SDN forwarding paths are determined by querying the "
    "SDN controller flow tables (see flow_inspector.py)."
)


def setup_logger(verbose: bool = False) -> logging.Logger:
    """Configure module logger."""
    logger = logging.getLogger("path_analysis")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def parse_traceroute_output(output_text: str) -> list:
    """
    Parse standard numeric traceroute stdout, extracting per-hop IPs and RTTs.

    Format example:
      1  192.168.1.1  1.234 ms  1.123 ms  1.050 ms
      2  * * *
      3  10.0.0.2  3.456 ms  3.234 ms  *
    """
    hops = []
    ip_regex = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    rtt_regex = re.compile(r'(\d+\.?\d*)\s*ms')

    for line in output_text.splitlines():
        line = line.strip()
        if not line or line.startswith("traceroute to") or line.startswith("traceroute:"):
            continue

        match = re.match(r'^(\d+)\s+(.+)$', line)
        if match:
            hop_num = int(match.group(1))
            remainder = match.group(2)

            ip_match = ip_regex.search(remainder)
            hop_ip = ip_match.group(0) if ip_match else "*"

            rtts = [float(m.group(1)) for m in rtt_regex.finditer(remainder)]
            stars = remainder.count("*")
            total_probes = len(rtts) + stars
            loss_pct = (stars / total_probes * 100.0) if total_probes > 0 else 0.0

            avg_rtt = round(statistics.mean(rtts), 3) if rtts else None
            min_rtt = round(min(rtts), 3) if rtts else None
            max_rtt = round(max(rtts), 3) if rtts else None

            hops.append({
                "hop": hop_num,
                "ip": hop_ip,
                "rtts_ms": rtts,
                "avg_rtt_ms": avg_rtt,
                "min_rtt_ms": min_rtt,
                "max_rtt_ms": max_rtt,
                "loss_percent": round(loss_pct, 1),
                "status": "REACHABLE" if hop_ip != "*" else "TIMEOUT"
            })

    return hops


def parse_tracepath_output(output_text: str) -> list:
    """
    Parse tracepath stdout as a secondary fallback.
    """
    hops = []
    ip_regex = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    rtt_regex = re.compile(r'(\d+\.?\d*)\s*ms')

    for line in output_text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(r'^(\d+):\s+(.+)$', line)
        if match:
            hop_num = int(match.group(1))
            remainder = match.group(2)

            ip_match = ip_regex.search(remainder)
            hop_ip = ip_match.group(0) if ip_match else "*"

            rtts = [float(m.group(1)) for m in rtt_regex.finditer(remainder)]
            avg_rtt = round(statistics.mean(rtts), 3) if rtts else None

            hops.append({
                "hop": hop_num,
                "ip": hop_ip,
                "rtts_ms": rtts,
                "avg_rtt_ms": avg_rtt,
                "min_rtt_ms": avg_rtt,
                "max_rtt_ms": avg_rtt,
                "loss_percent": 0.0 if hop_ip != "*" else 100.0,
                "status": "REACHABLE" if hop_ip != "*" else "TIMEOUT"
            })

    return hops


def run_socket_traceroute(target_ip: str, max_hops: int = DEFAULT_MAX_HOPS,
                          timeout: float = DEFAULT_TIMEOUT_SEC,
                          probes_per_hop: int = DEFAULT_PROBES_PER_HOP) -> list:
    """
    Execute native Python UDP/ICMP traceroute using raw sockets.
    Requires root/CAP_NET_RAW privileges. Raises PermissionError if unprivileged.
    """
    # ICMP socket to capture Time-to-Live Exceeded (Type 11) or Destination Unreachable (Type 3)
    icmp_sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    icmp_sock.settimeout(timeout)
    dest_ip = socket.gethostbyname(target_ip)

    hops = []
    base_port = 33434

    for ttl in range(1, max_hops + 1):
        hop_rtts = []
        hop_ip = "*"
        reached_dest = False

        for probe_idx in range(probes_per_hop):
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            udp_sock.setsockopt(socket.SOL_IP, socket.IP_TTL, ttl)
            udp_sock.settimeout(timeout)

            port = base_port + (ttl * 3) + probe_idx
            payload = b"SDN_TRACEROUTE_PROBE"
            send_t = time.time()

            try:
                udp_sock.sendto(payload, (dest_ip, port))
                data, addr = icmp_sock.recvfrom(512)
                recv_t = time.time()
                rtt = (recv_t - send_t) * 1000.0
                hop_rtts.append(round(rtt, 3))
                hop_ip = addr[0]

                # If the replying host is the destination host
                if hop_ip == dest_ip:
                    reached_dest = True
            except socket.timeout:
                pass
            finally:
                udp_sock.close()

        stars = probes_per_hop - len(hop_rtts)
        loss_pct = (stars / probes_per_hop * 100.0)
        avg_rtt = round(statistics.mean(hop_rtts), 3) if hop_rtts else None

        hops.append({
            "hop": ttl,
            "ip": hop_ip,
            "rtts_ms": hop_rtts,
            "avg_rtt_ms": avg_rtt,
            "min_rtt_ms": min(hop_rtts) if hop_rtts else None,
            "max_rtt_ms": max(hop_rtts) if hop_rtts else None,
            "loss_percent": round(loss_pct, 1),
            "status": "REACHABLE" if hop_ip != "*" else "TIMEOUT"
        })

        if reached_dest:
            break

    icmp_sock.close()
    return hops


def run_path_analysis(target_ip: str, max_hops: int = DEFAULT_MAX_HOPS,
                      timeout: float = DEFAULT_TIMEOUT_SEC,
                      try_raw_socket: bool = True,
                      verbose: bool = False) -> dict:
    """
    Execute path tracing against target_ip, attempting native socket traceroute first,
    and falling back to system traceroute/tracepath gracefully.
    """
    logger = setup_logger(verbose)
    method_used = "system_traceroute"
    hops = []
    error = None

    # 1. Attempt native socket traceroute
    if try_raw_socket:
        try:
            logger.debug("Attempting native socket UDP/ICMP traceroute...")
            hops = run_socket_traceroute(target_ip, max_hops=max_hops, timeout=timeout)
            method_used = "native_raw_socket"
        except (PermissionError, OSError) as e:
            logger.info(f"Native raw socket traceroute unavailable (non-root: {e}); falling back to system utility.")

    # 2. Fall back to system utilities if native socket was skipped or failed
    if not hops:
        traceroute_bin = shutil.which("traceroute")
        tracepath_bin = shutil.which("tracepath")

        if traceroute_bin:
            cmd = [traceroute_bin, "-n", "-m", str(max_hops), "-w", "1", target_ip]
            method_used = "system_traceroute"
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout * max_hops)
                hops = parse_traceroute_output(proc.stdout)
            except Exception as e:
                error = f"Traceroute execution error: {e}"
        elif tracepath_bin:
            cmd = [tracepath_bin, "-n", "-m", str(max_hops), target_ip]
            method_used = "system_tracepath"
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout * max_hops)
                hops = parse_tracepath_output(proc.stdout)
            except Exception as e:
                error = f"Tracepath execution error: {e}"
        else:
            error = "Neither native socket (requires root), 'traceroute', nor 'tracepath' was available."

    return {
        "target": target_ip,
        "method": method_used,
        "sdn_note": SDN_L2_TTL_NOTE,
        "hop_count": len(hops),
        "hop_list": hops,
        "status": "SUCCESS" if hops else ("ERROR" if error else "NO_HOPS_FOUND"),
        "error": error
    }


def print_path_table(result: dict):
    """Display comprehensive path report in terminal."""
    print("=" * 72)
    print("              NETWORK PATH ANALYSIS REPORT (IP Layer)")
    print("=" * 72)
    print(f" Target Host:       {result.get('target')}")
    print(f" Tracing Method:    {result.get('method')}")
    print(f" Total Hops Found:  {result.get('hop_count')}")
    if result.get("error"):
        print(f" Diagnostic Notice: {result.get('error')}")
    print("-" * 72)
    print(f"{'Hop':<5} {'IP Address':<22} {'Loss %':<10} {'Avg RTT':<12} {'Status':<12}")
    print("-" * 72)

    hops = result.get("hop_list", [])
    if not hops:
        print(" No intermediate hops recorded.")
    else:
        for item in hops:
            hop_num = item.get("hop", "-")
            ip = item.get("ip", "*")
            loss = f"{item.get('loss_percent', 0.0):.1f}%"
            avg_rtt = f"{item.get('avg_rtt_ms', 0.0):.2f} ms" if item.get("avg_rtt_ms") is not None else "-"
            status = item.get("status", "UNKNOWN")
            print(f"{hop_num:<5} {ip:<22} {loss:<10} {avg_rtt:<12} {status:<12}")

    print("-" * 72)
    print("[SDN PATH TRANSPARENCY NOTICE]:")
    print(result.get("sdn_note", ""))
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="Network Path Analysis Module (Raw Socket & System Traceroute with SDN L2 Notice)."
    )
    parser.add_argument("target_ip", nargs="?", default="127.0.0.1", help="Target IPv4 address to trace (default: 127.0.0.1)")
    parser.add_argument("-t", "--target", dest="target_flag", help="Target IP address (overrides positional target_ip)")
    parser.add_argument("-m", "--max-hops", type=int, default=DEFAULT_MAX_HOPS, help=f"Maximum hop count (TTL) (default: {DEFAULT_MAX_HOPS})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SEC, help=f"Timeout in seconds per probe (default: {DEFAULT_TIMEOUT_SEC})")
    parser.add_argument("-o", "--output", help="Optional filepath to save output JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()
    target = args.target_flag if args.target_flag else args.target_ip

    result = run_path_analysis(target, max_hops=args.max_hops, timeout=args.timeout, verbose=args.verbose)
    print_path_table(result)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"\n[INFO] Path analysis saved to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to save {args.output}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
