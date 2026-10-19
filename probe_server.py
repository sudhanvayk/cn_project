#!/usr/bin/env python3
"""
UDP Diagnostic Probe Server
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

This server listens for UDP probe packets, validates protocol version and magic
header, records arrival and departure timestamps, optionally injects artificial
delay and packet loss for testing, and echoes structured JSON responses.
Supports concurrent client handling.
"""

import argparse
import json
import logging
import os
import random
import socket
import socketserver
import sys
import time

MAGIC_HEADER = "SDN_PROBE"
PROTOCOL_VERSION = "1.0"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9999
BUFFER_SIZE = 65535


def setup_logger(verbose: bool = False) -> logging.Logger:
    """Configure module logger with appropriate log levels."""
    logger = logging.getLogger("probe_server")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s", datefmt="%H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def load_default_config(config_path: str = "config.json") -> int:
    """Load default port from config file if available."""
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return int(cfg.get("udp_port", DEFAULT_PORT))
        except Exception:
            pass
    return DEFAULT_PORT


class ProbeUDPHandler(socketserver.BaseRequestHandler):
    """
    Request handler for incoming UDP probes.
    Processes packets in individual threads for concurrent multi-client support.
    """

    def handle(self):
        server_recv_time = time.time()
        data = self.request[0]
        sock = self.request[1]
        client_ip, client_port = self.client_address
        logger = self.server.logger
        drop_rate = self.server.drop_rate
        delay_ms = self.server.delay_ms

        # Artificial drop simulation
        if drop_rate > 0.0 and random.random() < drop_rate:
            logger.debug(f"Artificially dropped probe from {client_ip}:{client_port} (drop rate: {drop_rate * 100:.1f}%)")
            return

        # Decode payload safely
        try:
            raw_text = data.decode("utf-8")
            payload = json.loads(raw_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            logger.warning(f"Malformed non-JSON packet from {client_ip}:{client_port}: {err}")
            return

        if not isinstance(payload, dict):
            logger.warning(f"Non-dictionary payload from {client_ip}:{client_port}")
            return

        # Magic string & protocol validation
        magic = payload.get("magic")
        version = payload.get("version")
        if magic != MAGIC_HEADER:
            logger.warning(f"Rejected stray packet from {client_ip}:{client_port} (invalid magic: {magic})")
            return
        if version != PROTOCOL_VERSION:
            logger.warning(f"Protocol version mismatch from {client_ip}:{client_port}: {version}")
            return

        probe_id = payload.get("probe_id")
        seq = payload.get("seq", probe_id)
        client_send_time = payload.get("send_time")

        if client_send_time is None:
            logger.warning(f"Missing send_time in probe from {client_ip}:{client_port}")
            return

        # Artificial delay injection
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        server_send_time = time.time()

        reply = {
            "magic": MAGIC_HEADER,
            "version": PROTOCOL_VERSION,
            "probe_id": probe_id,
            "seq": seq,
            "client_send_time": client_send_time,
            "server_recv_time": server_recv_time,
            "server_send_time": server_send_time,
            "status": "OK"
        }

        try:
            reply_bytes = json.dumps(reply).encode("utf-8")
            sock.sendto(reply_bytes, self.client_address)
            self.server.probe_count += 1
            est_1way = max(0.0, (server_recv_time - client_send_time) * 1000.0)
            logger.info(
                f"[PROBE #{seq}] From {client_ip}:{client_port} | "
                f"Size: {len(data)}B | Est. 1-way: {est_1way:6.2f} ms | Echoed"
            )
        except socket.error as e:
            logger.error(f"Socket error replying to {client_ip}:{client_port}: {e}")


class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    """Multi-threaded UDP server allowing concurrent request handling."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, drop_rate=0.0, delay_ms=0.0, verbose=False):
        super().__init__(server_address, RequestHandlerClass)
        self.drop_rate = drop_rate
        self.delay_ms = delay_ms
        self.probe_count = 0
        self.logger = setup_logger(verbose)


def start_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 drop_rate: float = 0.0, delay_ms: float = 0.0, verbose: bool = False):
    """
    Start the multi-threaded UDP diagnostic echo server.
    """
    setup_logger(verbose)
    server = ThreadedUDPServer((host, port), ProbeUDPHandler, drop_rate=drop_rate, delay_ms=delay_ms, verbose=verbose)

    print("=" * 68)
    print("      SDN UDP Diagnostic Probe Server (Concurrent)")
    print("=" * 68)
    print(f" Listening Address:  {host}:{port}")
    print(f" Protocol Version:   {PROTOCOL_VERSION} (Magic: {MAGIC_HEADER})")
    print(f" Artificial Delay:   {delay_ms:.1f} ms")
    print(f" Artificial Drop:    {drop_rate * 100:.1f} %")
    print(f" Started At:         {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(" Waiting for diagnostic probes... (Press Ctrl+C to terminate)")
    print("-" * 68)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n" + "-" * 68)
        print(f" [INFO] Server shutting down. Processed {server.probe_count} probes.")
        print("=" * 68)
    finally:
        server.server_close()


def main():
    default_port = load_default_config()
    parser = argparse.ArgumentParser(
        description="UDP Diagnostic Probe Echo Server with Loss/Delay Injection for SDN."
    )
    parser.add_argument("-p", "--port", type=int, default=default_port, help=f"UDP port to bind (default: {default_port})")
    parser.add_argument("-b", "--bind", default=DEFAULT_HOST, help=f"IP address to bind (default: {DEFAULT_HOST})")
    parser.add_argument("--drop-rate", type=float, default=0.0, help="Artificial packet drop rate (0.0 to 1.0, default: 0.0)")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Artificial delay in milliseconds before reply (default: 0.0)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()
    if not (0.0 <= args.drop_rate <= 1.0):
        print(f"[ERROR] --drop-rate must be between 0.0 and 1.0, got {args.drop_rate}", file=sys.stderr)
        sys.exit(1)
    if args.delay_ms < 0:
        print(f"[ERROR] --delay-ms must be non-negative, got {args.delay_ms}", file=sys.stderr)
        sys.exit(1)

    start_server(host=args.bind, port=args.port, drop_rate=args.drop_rate, delay_ms=args.delay_ms, verbose=args.verbose)


if __name__ == "__main__":
    main()
