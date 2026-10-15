#!/usr/bin/env python3
"""
Path Analysis Module
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This module performs network path discovery to a target IP using traceroute
(with graceful fallback to tracepath if traceroute is absent). It executes
the command with numeric output, configurable maximum hop counts, parses
each intermediate hop IP or unreachable hop '*', and outputs a structured
JSON object containing the target, total hop count, and hop sequence.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

DEFAULT_MAX_HOPS = 30
DEFAULT_TIMEOUT_SEC = 20


def parse_traceroute_output(output_text):
    """
    Parse standard numeric traceroute stdout.

    Format expected:
      1  192.168.1.1  1.234 ms  1.123 ms  1.050 ms
      2  * * *
      3  10.0.0.2  3.456 ms  3.234 ms  3.123 ms

    Returns:
        list of dict: [{'hop': 1, 'ip': '192.168.1.1'}, {'hop': 2, 'ip': '*'}]
    """
    hops = []
    ip_regex = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

    for line in output_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Match traceroute line starting with a hop number
        match = re.match(r'^(\d+)\s+(.+)$', line)
        if match:
            hop_num = int(match.group(1))
            remainder = match.group(2)

            ip_match = ip_regex.search(remainder)
            if ip_match:
                hop_ip = ip_match.group(0)
            elif "*" in remainder:
                hop_ip = "*"
            else:
                hop_ip = "*"

            hops.append({
                "hop": hop_num,
                "ip": hop_ip
            })

    return hops


def parse_tracepath_output(output_text):
    """
    Parse tracepath stdout as a graceful fallback.

    Format expected:
      1:  127.0.0.1                     0.226ms reached
      2?: [localhost] pmtu 65535
    """
    hops = []
    ip_regex = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

    for line in output_text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(r'^(\d+):\s+(.+)$', line)
        if match:
            hop_num = int(match.group(1))
            remainder = match.group(2)

            ip_match = ip_regex.search(remainder)
            if ip_match:
                hop_ip = ip_match.group(0)
            elif "*" in remainder or "no reply" in remainder.lower():
                hop_ip = "*"
            else:
                hop_ip = "*"

            hops.append({
                "hop": hop_num,
                "ip": hop_ip
            })

    return hops


def run_path_analysis(target_ip, max_hops=DEFAULT_MAX_HOPS, timeout=DEFAULT_TIMEOUT_SEC):
    """
    Execute traceroute path tracing against target_ip.

    Args:
        target_ip (str): Destination IPv4 address to trace.
        max_hops (int): Maximum Time-To-Live / hop limit.
        timeout (int): Timeout in seconds for command execution.

    Returns:
        dict: Structured path analysis result.
    """
    traceroute_bin = shutil.which("traceroute")
    tracepath_bin = shutil.which("tracepath")

    cmd = None
    use_tracepath = False

    if traceroute_bin:
        # -n: numeric IP addresses (no DNS reverse lookups)
        # -m: maximum number of hops
        # -w: wait time per probe in seconds (1 sec per probe to keep it snappy)
        cmd = [traceroute_bin, "-n", "-m", str(max_hops), "-w", "1", target_ip]
    elif tracepath_bin:
        # Fallback to tracepath if traceroute is not installed
        use_tracepath = True
        cmd = [tracepath_bin, "-n", "-m", str(max_hops), target_ip]
    else:
        err_msg = (
            "Neither 'traceroute' nor 'tracepath' was found in system PATH. "
            "Please install traceroute (e.g., sudo apt install traceroute)."
        )
        print(f"[WARN] {err_msg}", file=sys.stderr)
        return {
            "target": target_ip,
            "hop_count": 0,
            "hop_list": [],
            "status": "UNAVAILABLE",
            "error": err_msg
        }

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        raw_output = proc.stdout

        if use_tracepath:
            hops = parse_tracepath_output(raw_output)
        else:
            hops = parse_traceroute_output(raw_output)

        return {
            "target": target_ip,
            "hop_count": len(hops),
            "hop_list": hops,
            "status": "SUCCESS" if hops else "NO_HOPS_FOUND",
            "raw_output": raw_output.strip()
        }

    except subprocess.TimeoutExpired:
        err_msg = f"Path tracing timed out after {timeout} seconds."
        print(f"[WARN] {err_msg}", file=sys.stderr)
        return {
            "target": target_ip,
            "hop_count": 0,
            "hop_list": [],
            "status": "TIMEOUT",
            "error": err_msg
        }
    except Exception as e:
        err_msg = f"Failed to execute path tracing command: {e}"
        print(f"[ERROR] {err_msg}", file=sys.stderr)
        return {
            "target": target_ip,
            "hop_count": 0,
            "hop_list": [],
            "status": "ERROR",
            "error": str(e)
        }


def print_path_table(result):
    """Display path hops in formatted terminal view."""
    print("=" * 60)
    print("              NETWORK PATH ANALYSIS REPORT")
    print("=" * 60)
    print(f" Target Host:   {result.get('target')}")
    print(f" Status:        {result.get('status')}")
    print(f" Total Hops:    {result.get('hop_count')}")
    if "error" in result:
        print(f" Error:         {result.get('error')}")
    print("-" * 60)
    print(f"{'Hop #':<8} {'IP Address':<30} {'Status':<15}")
    print("-" * 60)

    hops = result.get("hop_list", [])
    if not hops:
        print(" No intermediate hops recorded.")
    else:
        for item in hops:
            hop_num = item.get("hop", "-")
            ip = item.get("ip", "*")
            status = "REACHABLE" if ip != "*" else "UNREACHABLE (*)"
            print(f"{hop_num:<8} {ip:<30} {status:<15}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Network Path Analysis Module using Traceroute/Tracepath."
    )
    parser.add_argument(
        "target_ip",
        nargs="?",
        default="127.0.0.1",
        help="Target IPv4 address to trace (default: 127.0.0.1)"
    )
    parser.add_argument(
        "-t", "--target",
        dest="target_flag",
        help="Target IP address (overrides positional target_ip)"
    )
    parser.add_argument(
        "-m", "--max-hops",
        type=int,
        default=DEFAULT_MAX_HOPS,
        help=f"Maximum hop count (TTL) (default: {DEFAULT_MAX_HOPS})"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"Command timeout in seconds (default: {DEFAULT_TIMEOUT_SEC})"
    )
    parser.add_argument(
        "-o", "--output",
        help="Optional filepath to save output JSON"
    )

    args = parser.parse_args()
    target = args.target_flag if args.target_flag else args.target_ip

    result = run_path_analysis(target, max_hops=args.max_hops, timeout=args.timeout)

    # Print human-readable report to stdout
    print_path_table(result)

    # Print raw JSON object as required:
    # "Return and print a JSON object containing target, hop count, and hop list"
    json_output = {
        "target": result["target"],
        "hop_count": result["hop_count"],
        "hop_list": result["hop_list"]
    }
    if "error" in result:
        json_output["error"] = result["error"]

    print("\n[Structured JSON Output]:")
    print(json.dumps(json_output, indent=2))

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(json_output, f, indent=2)
            print(f"\n[INFO] Path analysis saved to: {args.output}")
        except Exception as e:
            print(f"[ERROR] Failed to save {args.output}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
