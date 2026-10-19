#!/usr/bin/env python3
"""
UDP Diagnostic Client
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This client transmits active UDP probes with protocol versioning, sequence tracking,
and nanosecond timestamps. It measures Round-Trip Time (RTT), packet loss,
duplicate replies, out-of-order packets, RFC 3550 jitter, standard deviation jitter,
and p95 latency. Supports single or multi-target parallel probing, and burst mode.
"""

import argparse
import concurrent.futures
import json
import logging
import math
import os
import socket
import statistics
import sys
import time
import uuid

MAGIC_HEADER = "SDN_PROBE"
PROTOCOL_VERSION = "1.0"
DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_TARGET = "127.0.0.1"
DEFAULT_PORT = 9999
DEFAULT_COUNT = 10
DEFAULT_TIMEOUT = 2.0
DEFAULT_PAYLOAD_SIZE = 64
DEFAULT_INTERVAL = 0.1
DEFAULT_OUTPUT_FILE = "diagnostic_result.json"


def setup_logger(verbose: bool = False) -> logging.Logger:
    """Configure client logger."""
    logger = logging.getLogger("diagnostic_client")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load default network parameters from config.json if present."""
    config = {
        "udp_port": DEFAULT_PORT,
        "probe_count": DEFAULT_COUNT,
        "timeout": DEFAULT_TIMEOUT,
        "payload_size": DEFAULT_PAYLOAD_SIZE,
        "interval": DEFAULT_INTERVAL,
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config["udp_port"] = int(data.get("udp_port", DEFAULT_PORT))
                config["probe_count"] = int(data.get("probe_count", DEFAULT_COUNT))
                config["timeout"] = float(data.get("timeout", DEFAULT_TIMEOUT))
                config["payload_size"] = int(data.get("payload_size", DEFAULT_PAYLOAD_SIZE))
                config["interval"] = float(data.get("interval", DEFAULT_INTERVAL))
        except Exception as e:
            print(f"[WARN] Could not parse {config_path}: {e}", file=sys.stderr)
    return config


def calculate_percentile(data: list, percentile: float) -> float:
    """
    Compute arbitrary percentile (0-100) using linear interpolation.
    """
    if not data:
        return 0.0
    sorted_data = sorted(data)
    if len(sorted_data) == 1:
        return sorted_data[0]
    index = (len(sorted_data) - 1) * (percentile / 100.0)
    lower = math.floor(index)
    upper = math.ceil(index)
    weight = index - lower
    return sorted_data[lower] * (1.0 - weight) + sorted_data[upper] * weight


def compute_probe_statistics(probes: list, sent_count: int) -> dict:
    """
    Compute rigorous statistical metrics across collected probe measurements.

    Args:
        probes: List of probe record dictionaries.
        sent_count: Total number of probes dispatched.

    Returns:
        dict: Complete statistical summary including RTT, loss, RFC 3550 jitter,
              stddev jitter, and p95.
    """
    valid_probes = [p for p in probes if p.get("status") == "SUCCESS" and p.get("rtt_ms") is not None]
    received_count = len(valid_probes)
    lost_count = max(0, sent_count - received_count)
    packet_loss_pct = (lost_count / sent_count * 100.0) if sent_count > 0 else 0.0

    duplicate_count = sum(1 for p in probes if p.get("is_duplicate"))
    out_of_order_count = sum(1 for p in probes if p.get("is_out_of_order"))

    rtts = [p["rtt_ms"] for p in valid_probes]

    if received_count > 0:
        min_rtt = round(min(rtts), 3)
        max_rtt = round(max(rtts), 3)
        mean_rtt = round(statistics.mean(rtts), 3)
        median_rtt = round(statistics.median(rtts), 3)
        stddev_rtt = round(statistics.stdev(rtts), 3) if received_count > 1 else 0.0
        p95_rtt = round(calculate_percentile(rtts, 95.0), 3)

        # RFC 3550 inter-arrival jitter smoothing
        # J = J + (|D(i-1, i)| - J) / 16.0
        rfc3550_jitter = 0.0
        for i in range(1, len(valid_probes)):
            p_prev = valid_probes[i - 1]
            p_curr = valid_probes[i]
            s_prev, r_prev = p_prev["send_time"], p_prev["recv_time"]
            s_curr, r_curr = p_curr["send_time"], p_curr["recv_time"]
            d = abs((r_curr - s_curr) - (r_prev - s_prev)) * 1000.0
            rfc3550_jitter += (d - rfc3550_jitter) / 16.0
        rfc3550_jitter = round(rfc3550_jitter, 3)

        # One-way delay estimates
        fwd_delays = [p["est_forward_delay_ms"] for p in valid_probes if p.get("est_forward_delay_ms") is not None]
        rev_delays = [p["est_reverse_delay_ms"] for p in valid_probes if p.get("est_reverse_delay_ms") is not None]
        mean_fwd = round(statistics.mean(fwd_delays), 3) if fwd_delays else None
        mean_rev = round(statistics.mean(rev_delays), 3) if rev_delays else None
    else:
        min_rtt = max_rtt = mean_rtt = median_rtt = stddev_rtt = p95_rtt = None
        rfc3550_jitter = None
        mean_fwd = mean_rev = None

    return {
        "sent": sent_count,
        "received": received_count,
        "lost": lost_count,
        "packet_loss_percent": round(packet_loss_pct, 2),
        "duplicates": duplicate_count,
        "out_of_order": out_of_order_count,
        "min_rtt_ms": min_rtt,
        "max_rtt_ms": max_rtt,
        "mean_rtt_ms": mean_rtt,
        "median_rtt_ms": median_rtt,
        "stddev_rtt_ms": stddev_rtt,
        "rfc3550_jitter_ms": rfc3550_jitter,
        "p95_rtt_ms": p95_rtt,
        "mean_forward_delay_ms": mean_fwd,
        "mean_reverse_delay_ms": mean_rev,
        "clock_sync_note": "One-way delays are estimates; precision depends on NTP/PTP synchronization between client and server."
    }


def run_diagnostics_single(target_ip: str, port: int, count: int, timeout: float,
                           payload_size: int, output_file: str = None,
                           interval: float = DEFAULT_INTERVAL, burst: bool = False,
                           verbose: bool = False) -> dict:
    """
    Execute active UDP diagnostic probing against a single target.
    """
    logger = setup_logger(verbose)
    actual_interval = 0.0 if burst else interval

    print("=" * 72)
    print("       SDN UDP Network Diagnostic Measurement Client")
    print("=" * 72)
    print(f" Target Endpoint:   {target_ip}:{port}")
    print(f" Mode:              {'BURST (back-to-back)' if burst else f'Standard ({actual_interval:.2f}s interval)'}")
    print(f" Probe Count:       {count}")
    print(f" Timeout per probe: {timeout:.2f} s")
    print(f" Payload Size:      {payload_size} bytes")
    print(f" Protocol Version:  {PROTOCOL_VERSION} (Magic: {MAGIC_HEADER})")
    print("-" * 72)
    print(f"{'Seq':<6} {'Status':<10} {'RTT (ms)':<10} {'RFC Jitter':<12} {'1-Way (ms)':<12} {'Order':<8}")
    print("-" * 72)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    probes = []
    seen_seqs = set()
    highest_seq_received = 0
    padding = "X" * max(0, payload_size - 96)
    start_wall_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    running_rfc_jitter = 0.0
    prev_probe = None

    for seq in range(1, count + 1):
        probe_uuid = f"p-{uuid.uuid4().hex[:8]}"
        send_time = time.time()
        packet = {
            "magic": MAGIC_HEADER,
            "version": PROTOCOL_VERSION,
            "probe_id": probe_uuid,
            "seq": seq,
            "send_time": send_time,
            "payload_pad": padding
        }
        encoded_data = json.dumps(packet).encode("utf-8")

        record = {
            "probe_id": probe_uuid,
            "seq": seq,
            "send_time": send_time,
            "recv_time": None,
            "status": "TIMEOUT",
            "rtt_ms": None,
            "is_duplicate": False,
            "is_out_of_order": False,
            "est_forward_delay_ms": None,
            "est_reverse_delay_ms": None
        }

        try:
            sock.sendto(encoded_data, (target_ip, port))
            recv_data, _ = sock.recvfrom(65535)
            recv_time = time.time()
            record["recv_time"] = recv_time

            # Validate response
            try:
                resp = json.loads(recv_data.decode("utf-8"))
            except Exception:
                resp = {}

            if resp.get("magic") != MAGIC_HEADER:
                logger.warning(f"Ignored reply with invalid magic from {target_ip}")
                record["status"] = "INVALID_MAGIC"
            else:
                resp_seq = resp.get("seq", seq)
                record["status"] = "SUCCESS"
                rtt_ms = (recv_time - send_time) * 1000.0
                record["rtt_ms"] = round(rtt_ms, 3)

                # Duplicate & Out-of-order detection
                if resp_seq in seen_seqs:
                    record["is_duplicate"] = True
                seen_seqs.add(resp_seq)

                if resp_seq < highest_seq_received:
                    record["is_out_of_order"] = True
                else:
                    highest_seq_received = max(highest_seq_received, resp_seq)

                # One-way delay estimates
                srv_recv = resp.get("server_recv_time")
                srv_send = resp.get("server_send_time")
                if srv_recv is not None:
                    record["est_forward_delay_ms"] = round((srv_recv - send_time) * 1000.0, 3)
                if srv_send is not None:
                    record["est_reverse_delay_ms"] = round((recv_time - srv_send) * 1000.0, 3)

                # Update live RFC 3550 jitter
                if prev_probe and prev_probe.get("recv_time"):
                    d = abs((recv_time - send_time) - (prev_probe["recv_time"] - prev_probe["send_time"])) * 1000.0
                    running_rfc_jitter += (d - running_rfc_jitter) / 16.0
                prev_probe = record

                order_tag = "DUP" if record["is_duplicate"] else ("OOO" if record["is_out_of_order"] else "OK")
                fwd_str = f"{record['est_forward_delay_ms']:.2f}" if record['est_forward_delay_ms'] is not None else "-"
                print(f"{seq:<6} {'SUCCESS':<10} {rtt_ms:<10.2f} {running_rfc_jitter:<12.2f} {fwd_str:<12} {order_tag:<8}")

        except socket.timeout:
            record["status"] = "TIMEOUT"
            print(f"{seq:<6} {'TIMEOUT':<10} {'*':<10} {'*':<12} {'*':<12} {'LOST':<8}")
        except Exception as e:
            record["status"] = f"ERROR: {e}"
            print(f"{seq:<6} {'ERROR':<10} {'*':<10} {'*':<12} {'*':<12} {'ERR':<8}")

        probes.append(record)

        if seq < count and actual_interval > 0:
            time.sleep(actual_interval)

    sock.close()

    summary = compute_probe_statistics(probes, count)
    result = {
        "timestamp": start_wall_time,
        "target_ip": target_ip,
        "destination_port": port,
        "probe_count": count,
        "timeout_seconds": timeout,
        "payload_size_bytes": payload_size,
        "interval_seconds": actual_interval,
        "burst_mode": burst,
        "summary": summary,
        "probes": probes
    }

    print_summary_table(target_ip, port, summary, burst)

    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"\n[INFO] Diagnostic results successfully saved to: {output_file}")
        except Exception as e:
            print(f"[ERROR] Failed to write results to {output_file}: {e}", file=sys.stderr)

    return result


def print_summary_table(target_ip: str, port: int, summary: dict, burst: bool = False):
    """Print formatted diagnostic summary table in terminal."""
    print("\n" + "=" * 72)
    print("                     DIAGNOSTIC SUMMARY REPORT")
    print("=" * 72)
    print(f" Target Endpoint:             {target_ip}:{port}")
    print(f" Probing Mode:                {'BURST' if burst else 'Standard'}")
    print(f" Probes Transmitted:          {summary['sent']}")
    print(f" Probes Received:             {summary['received']}")
    print(f" Probes Lost:                 {summary['lost']}")
    print(f" Packet Loss Rate:            {summary['packet_loss_percent']:.2f}%")
    print(f" Duplicates Detected:         {summary['duplicates']}")
    print(f" Out-of-Order Packets:        {summary['out_of_order']}")
    print("-" * 72)

    if summary["received"] > 0:
        print(f" Minimum RTT:                 {summary['min_rtt_ms']:.2f} ms")
        print(f" Maximum RTT:                 {summary['max_rtt_ms']:.2f} ms")
        print(f" Mean RTT:                    {summary['mean_rtt_ms']:.2f} ms")
        print(f" Median RTT:                  {summary['median_rtt_ms']:.2f} ms")
        print(f" 95th Percentile RTT (p95):   {summary['p95_rtt_ms']:.2f} ms")
        print(f" Standard Deviation Jitter:   {summary['stddev_rtt_ms']:.2f} ms")
        print(f" RFC 3550 Inter-Arrival Jitter:{summary['rfc3550_jitter_ms']:.2f} ms")
        if summary.get("mean_forward_delay_ms") is not None:
            print(f" Est. Mean Forward Delay:     {summary['mean_forward_delay_ms']:.2f} ms (clock-dependent)")
            print(f" Est. Mean Reverse Delay:     {summary['mean_reverse_delay_ms']:.2f} ms (clock-dependent)")
    else:
        print(" All probes timed out. No latency metrics available.")
    print("=" * 72)


def run_diagnostics_multi(targets: list, port: int, count: int, timeout: float,
                          payload_size: int, output_prefix: str = "diagnostic_result",
                          interval: float = DEFAULT_INTERVAL, burst: bool = False,
                          verbose: bool = False) -> dict:
    """
    Probe multiple target hosts concurrently using a thread pool.
    """
    print(f"[INFO] Initiating parallel diagnostics across {len(targets)} targets: {', '.join(targets)}")
    results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(targets))) as executor:
        future_map = {}
        for target in targets:
            out_file = f"{output_prefix}_{target.replace('.', '_')}.json"
            future = executor.submit(
                run_diagnostics_single,
                target_ip=target,
                port=port,
                count=count,
                timeout=timeout,
                payload_size=payload_size,
                output_file=out_file,
                interval=interval,
                burst=burst,
                verbose=verbose
            )
            future_map[future] = target

        for future in concurrent.futures.as_completed(future_map):
            target = future_map[future]
            try:
                res = future.result()
                results[target] = res
            except Exception as e:
                print(f"[ERROR] Probing failed for target {target}: {e}", file=sys.stderr)

    return results


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(
        description="UDP Diagnostic Probe Client with RFC 3550 Jitter, p95, Burst, and Multi-Target Probing."
    )
    parser.add_argument("target_ip", nargs="?", default=DEFAULT_TARGET, help=f"Target IPv4 address to probe (default: {DEFAULT_TARGET})")
    parser.add_argument("-t", "--target", dest="target_flag", help="Optional target IP or comma-separated list of IPs")
    parser.add_argument("-p", "--port", type=int, default=cfg["udp_port"], help=f"Destination UDP port (default: {cfg['udp_port']})")
    parser.add_argument("-c", "--count", type=int, default=cfg["probe_count"], help=f"Number of UDP probes to send (default: {cfg['probe_count']})")
    parser.add_argument("-s", "--size", "--payload-size", dest="payload_size", type=int, default=cfg["payload_size"], help=f"Probe payload size in bytes (default: {cfg['payload_size']})")
    parser.add_argument("--timeout", type=float, default=cfg["timeout"], help=f"Socket timeout in seconds per probe (default: {cfg['timeout']})")
    parser.add_argument("--interval", type=float, default=cfg["interval"], help=f"Delay between probes in seconds (default: {cfg['interval']})")
    parser.add_argument("--burst", action="store_true", help="Send probes back-to-back with zero delay to expose queueing/microbursts")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_FILE, help=f"Output JSON file or prefix (default: {DEFAULT_OUTPUT_FILE})")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    # Determine targets
    target_str = args.target_flag if args.target_flag else args.target_ip
    targets = [t.strip() for t in target_str.split(",") if t.strip()]

    if len(targets) > 1:
        run_diagnostics_multi(
            targets=targets,
            port=args.port,
            count=args.count,
            timeout=args.timeout,
            payload_size=args.payload_size,
            output_prefix=args.output.replace(".json", ""),
            interval=args.interval,
            burst=args.burst,
            verbose=args.verbose
        )
    else:
        run_diagnostics_single(
            target_ip=targets[0],
            port=args.port,
            count=args.count,
            timeout=args.timeout,
            payload_size=args.payload_size,
            output_file=args.output,
            interval=args.interval,
            burst=args.burst,
            verbose=args.verbose
        )


if __name__ == "__main__":
    main()
