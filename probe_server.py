#!/usr/bin/env python3
"""
UDP Diagnostic Probe Server
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This server listens for UDP probe packets sent by diagnostic_client.py,
records timestamps for arrival and departure, and echoes back a structured
JSON response. This allows the client to calculate Round-Trip Time (RTT),
jitter, and packet loss across an SDN network.
"""

import argparse
import json
import os
import socket
import sys
import time

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9999
BUFFER_SIZE = 65535


def load_default_config(config_path="config.json"):
    """Load default port from config file if available."""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return cfg.get("udp_port", DEFAULT_PORT)
        except Exception:
            pass
    return DEFAULT_PORT


def start_server(host=DEFAULT_HOST, port=DEFAULT_PORT):
    """
    Start the UDP diagnostic echo server.

    Args:
        host (str): IP address to bind to (default: 0.0.0.0).
        port (int): UDP port number to listen on.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Enable address reuse where appropriate
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass

    try:
        sock.bind((host, port))
    except OSError as e:
        print(f"[ERROR] Failed to bind to {host}:{port} - {e}", file=sys.stderr)
        sys.exit(1)

    print("=" * 65)
    print("      SDN UDP Diagnostic Probe Server Running")
    print("=" * 65)
    print(f" Listening on UDP: {host}:{port}")
    print(f" Buffer size:     {BUFFER_SIZE} bytes")
    print(f" Started at:      {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(" Waiting for diagnostic probes... (Press Ctrl+C to terminate)")
    print("-" * 65)

    probe_count = 0

    try:
        while True:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                server_recv_time = time.time()
                client_ip, client_port = addr

                # Decode payload safely
                try:
                    raw_text = data.decode("utf-8")
                    payload = json.loads(raw_text)
                except (UnicodeDecodeError, json.JSONDecodeError) as err:
                    print(f"[WARN] Received malformed/non-JSON packet from {client_ip}:{client_port}: {err}")
                    continue

                if not isinstance(payload, dict):
                    print(f"[WARN] Non-dictionary JSON payload from {client_ip}:{client_port}")
                    continue

                probe_id = payload.get("probe_id")
                client_send_time = payload.get("send_time")

                if probe_id is None or client_send_time is None:
                    print(f"[WARN] Missing probe_id or send_time in packet from {client_ip}:{client_port}")
                    continue

                probe_count += 1
                server_send_time = time.time()

                # Build standardized JSON response
                reply = {
                    "probe_id": probe_id,
                    "client_send_time": client_send_time,
                    "server_recv_time": server_recv_time,
                    "server_send_time": server_send_time,
                    "status": "OK"
                }

                reply_bytes = json.dumps(reply).encode("utf-8")
                sock.sendto(reply_bytes, addr)

                one_way_delay_estimate_ms = max(0.0, (server_recv_time - client_send_time) * 1000.0)

                print(f"[PROBE #{probe_id:04d}] From {client_ip}:{client_port} | "
                      f"Payload: {len(data)}B | "
                      f"Est. 1-way: {one_way_delay_estimate_ms:6.2f} ms | "
                      f"Echoed successfully")

            except socket.error as sock_err:
                print(f"[ERROR] Socket error while receiving: {sock_err}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n" + "-" * 65)
        print(f" [INFO] Server shutting down. Processed {probe_count} probes.")
        print("=" * 65)
    finally:
        sock.close()


def main():
    default_port = load_default_config()
    parser = argparse.ArgumentParser(
        description="UDP Diagnostic Probe Echo Server for SDN Network Monitoring."
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=default_port,
        help=f"UDP port to bind (default: {default_port})"
    )
    parser.add_argument(
        "-b", "--bind",
        type=str,
        default=DEFAULT_HOST,
        help=f"IP address to bind (default: {DEFAULT_HOST})"
    )

    args = parser.parse_args()
    start_server(host=args.bind, port=args.port)


if __name__ == "__main__":
    main()
