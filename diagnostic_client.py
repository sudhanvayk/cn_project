#!/usr/bin/env python3
"""
UDP Diagnostic Client
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This client sends periodic UDP probe packets containing sequence numbers
and high-resolution timestamps to a target server, measures Round-Trip Time (RTT),
tracks packet loss, computes statistical metrics (min, max, mean, median, stddev),
and outputs both a terminal summary table and a structured JSON result file.
"""

import argparse
import json
import os
import socket
import statistics
import sys
import time

DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_TARGET = "127.0.0.1"
DEFAULT_PORT = 9999
DEFAULT_COUNT = 10
DEFAULT_TIMEOUT = 2.0
DEFAULT_PAYLOAD_SIZE = 64
DEFAULT_OUTPUT_FILE = "diagnostic_result.json"


def load_config(config_path=DEFAULT_CONFIG_PATH):
    """Load default network parameters from config.json if present."""
    config = {
        "udp_port": DEFAULT_PORT,
        "probe_count": DEFAULT_COUNT,
        "timeout": DEFAULT_TIMEOUT,
        "payload_size": DEFAULT_PAYLOAD_SIZE,
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config["udp_port"] = data.get("udp_port", DEFAULT_PORT)
                config["probe_count"] = data.get("probe_count", DEFAULT_COUNT)
                config["timeout"] = float(data.get("timeout", DEFAULT_TIMEOUT))
                config["payload_size"] = int(data.get("payload_size", DEFAULT_PAYLOAD_SIZE))
        except Exception as e:
            print(f"[WARN] Could not parse {config_path}: {e}", file=sys.stderr)
    return config


def run_diagnostics(target_ip, port, count, timeout, payload_size, output_file=None, interval=0.1):
    """
    Execute active UDP diagnostic probing against target host.

    Args:
        target_ip (str): Destination IPv4 address.
        port (int): Destination UDP port.
        count (int): Number of probes to transmit.
        timeout (float): Per-probe socket timeout in seconds.
        payload_size (int): Size of probe payload padding in bytes.
        output_file (str): Filepath to save JSON results.
        interval (float): Delay in seconds between probes.

    Returns:
        dict: Complete diagnostic measurement results and statistics.
    """
    print("=" * 70)
    print("       SDN UDP Network Diagnostic Measurement Client")
    print("=" * 70)
    print(f" Target Host:       {target_ip}")
    print(f" Target Port:       {port}")
    print(f" Probe Count:       {count}")
    print(f" Timeout per probe: {timeout:.2f} s")
    print(f" Payload Size:      {payload_size} bytes")
    print(f" Inter-probe Delay: {interval:.2f} s")
    print("-" * 70)
    print(f"{'Seq':<6} {'Status':<12} {'RTT (ms)':<12} {'Client Send Time':<24}")
    print("-" * 70)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    probes = []
    rtts = []

    # Prepare payload padding
    padding = "X" * max(0, payload_size - 64)

    start_wall_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for seq in range(1, count + 1):
        send_time = time.time()
        probe_packet = {
            "probe_id": seq,
            "send_time": send_time,
            "payload_pad": padding
        }
        encoded_data = json.dumps(probe_packet).encode("utf-8")

        probe_record = {
            "probe_id": seq,
            "send_time": send_time,
            "status": "UNKNOWN",
            "rtt_ms": None,
            "server_recv_time": None,
            "server_send_time": None
        }

        try:
            sock.sendto(encoded_data, (target_ip, port))
            recv_data, _ = sock.recvfrom(65535)
            recv_time = time.time()

            rtt_ms = (recv_time - send_time) * 1000.0
            rtts.append(rtt_ms)

            # Parse server echo details
            try:
                resp = json.loads(recv_data.decode("utf-8"))
                probe_record["server_recv_time"] = resp.get("server_recv_time")
                probe_record["server_send_time"] = resp.get("server_send_time")
            except Exception:
                pass

            probe_record["status"] = "SUCCESS"
            probe_record["rtt_ms"] = round(rtt_ms, 3)
            probe_record["recv_time"] = recv_time

            print(f"{seq:<6} {'SUCCESS':<12} {rtt_ms:<12.2f} {time.strftime('%H:%M:%S', time.localtime(send_time))}")

        except socket.timeout:
            probe_record["status"] = "TIMEOUT"
            print(f"{seq:<6} {'TIMEOUT':<12} {'*':<12} {time.strftime('%H:%M:%S', time.localtime(send_time))}")

        except Exception as e:
            probe_record["status"] = f"ERROR: {e}"
            print(f"{seq:<6} {'ERROR':<12} {'*':<12} {time.strftime('%H:%M:%S', time.localtime(send_time))}")

        probes.append(probe_record)

        if seq < count and interval > 0:
            time.sleep(interval)

    sock.close()

    # Compute statistical metrics
    sent = count
    received = len(rtts)
    lost = sent - received
    packet_loss_pct = (lost / sent) * 100.0 if sent > 0 else 0.0

    if received > 0:
        min_rtt = round(min(rtts), 3)
        max_rtt = round(max(rtts), 3)
        mean_rtt = round(statistics.mean(rtts), 3)
        median_rtt = round(statistics.median(rtts), 3)
        stddev_rtt = round(statistics.stdev(rtts), 3) if received > 1 else 0.0
    else:
        min_rtt = None
        max_rtt = None
        mean_rtt = None
        median_rtt = None
        stddev_rtt = None

    summary = {
        "sent": sent,
        "received": received,
        "lost": lost,
        "packet_loss_percent": round(packet_loss_pct, 2),
        "min_rtt_ms": min_rtt,
        "max_rtt_ms": max_rtt,
        "mean_rtt_ms": mean_rtt,
        "median_rtt_ms": median_rtt,
        "stddev_rtt_ms": stddev_rtt
    }

    result = {
        "timestamp": start_wall_time,
        "target_ip": target_ip,
        "destination_port": port,
        "probe_count": count,
        "timeout_seconds": timeout,
        "payload_size_bytes": payload_size,
        "summary": summary,
        "probes": probes
    }

    print_summary_table(target_ip, port, summary)

    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"\n[INFO] Diagnostic results successfully saved to: {output_file}")
        except Exception as e:
            print(f"[ERROR] Failed to write results to {output_file}: {e}", file=sys.stderr)

    return result


def print_summary_table(target_ip, port, summary):
    """Print a clean, structured diagnostic report table in the terminal."""
    print("\n" + "=" * 70)
    print("                     DIAGNOSTIC SUMMARY REPORT")
    print("=" * 70)
    print(f" Target Endpoint:             {target_ip}:{port}")
    print(f" Probes Transmitted:          {summary['sent']}")
    print(f" Probes Received:             {summary['received']}")
    print(f" Probes Lost:                 {summary['lost']}")
    print(f" Packet Loss:                 {summary['packet_loss_percent']:.2f}%")
    print("-" * 70)

    if summary["received"] > 0:
        print(f" Minimum RTT:                 {summary['min_rtt_ms']:.2f} ms")
        print(f" Maximum RTT:                 {summary['max_rtt_ms']:.2f} ms")
        print(f" Mean RTT:                    {summary['mean_rtt_ms']:.2f} ms")
        print(f" Median RTT:                  {summary['median_rtt_ms']:.2f} ms")
        print(f" Standard Deviation (Jitter): {summary['stddev_rtt_ms']:.2f} ms")
    else:
        print(" All probes timed out. No RTT metrics available.")
    print("=" * 70)


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(
        description="UDP Diagnostic Probe Client for RTT and Packet Loss Measurement."
    )
    parser.add_argument(
        "target_ip",
        nargs="?",
        default=DEFAULT_TARGET,
        help=f"Target IPv4 address to probe (default: {DEFAULT_TARGET})"
    )
    parser.add_argument(
        "-t", "--target",
        dest="target_flag",
        help="Optional flag specifying target IP (overrides positional target_ip)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=cfg["udp_port"],
        help=f"Destination UDP port (default: {cfg['udp_port']})"
    )
    parser.add_argument(
        "-c", "--count",
        type=int,
        default=cfg["probe_count"],
        help=f"Number of UDP probes to send (default: {cfg['probe_count']})"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=cfg["timeout"],
        help=f"Socket timeout in seconds per probe (default: {cfg['timeout']})"
    )
    parser.add_argument(
        "-s", "--payload-size",
        type=int,
        default=cfg["payload_size"],
        help=f"Probe payload size in bytes (default: {cfg['payload_size']})"
    )
    parser.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output JSON file for results (default: {DEFAULT_OUTPUT_FILE})"
    )

    args = parser.parse_args()
    target = args.target_flag if args.target_flag else args.target_ip

    run_diagnostics(
        target_ip=target,
        port=args.port,
        count=args.count,
        timeout=args.timeout,
        payload_size=args.payload_size,
        output_file=args.output
    )


if __name__ == "__main__":
    main()
