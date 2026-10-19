#!/usr/bin/env python3
"""
Mock SDN Controller REST Server
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Provides a lightweight, zero-dependency HTTP server that mimics Ryu's
rest_topology and ofctl_rest REST APIs. Serves canned diamond-topology
data (switches s1, s2, s3, and hosts h1, h2), flow tables, port statistics,
and supports dynamic scenario switching (healthy, degraded, failed).
"""

import argparse
import http.server
import json
import logging
import socketserver
import sys
from urllib.parse import urlparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


def setup_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("mock_controller")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s", datefmt="%H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


class MockSDNState:
    """Maintains simulated SDN network state, flow tables, and port statistics."""

    def __init__(self, scenario: str = "healthy"):
        self.scenario = scenario
        self.installed_rules = []
        self.reset_topology()

    def reset_topology(self):
        self.switches = [
            {
                "dpid": "0000000000000001",
                "ports": [
                    {"port_no": 1, "name": "s1-eth1"},
                    {"port_no": 2, "name": "s1-eth2"},
                    {"port_no": 3, "name": "s1-eth3"}
                ]
            },
            {
                "dpid": "0000000000000002",
                "ports": [
                    {"port_no": 1, "name": "s2-eth1"},
                    {"port_no": 2, "name": "s2-eth2"},
                    {"port_no": 3, "name": "s2-eth3"}
                ]
            },
            {
                "dpid": "0000000000000003",
                "ports": [
                    {"port_no": 1, "name": "s3-eth1"},
                    {"port_no": 2, "name": "s3-eth2"}
                ]
            }
        ]

        self.hosts = [
            {
                "mac": "00:00:00:00:00:01",
                "ipv4": ["10.0.0.1"],
                "port": {"dpid": "0000000000000001", "port_no": 1, "name": "s1-eth1"}
            },
            {
                "mac": "00:00:00:00:00:02",
                "ipv4": ["10.0.0.2"],
                "port": {"dpid": "0000000000000002", "port_no": 1, "name": "s2-eth1"}
            }
        ]

        # In "failed" scenario, the primary s1-s2 link is down
        if self.scenario == "failed":
            self.links = [
                {
                    "src": {"dpid": "0000000000000001", "port_no": 3, "name": "s1-eth3"},
                    "dst": {"dpid": "0000000000000003", "port_no": 1, "name": "s3-eth1"}
                },
                {
                    "src": {"dpid": "0000000000000003", "port_no": 2, "name": "s3-eth2"},
                    "dst": {"dpid": "0000000000000002", "port_no": 3, "name": "s2-eth3"}
                }
            ]
        else:
            self.links = [
                {
                    "src": {"dpid": "0000000000000001", "port_no": 2, "name": "s1-eth2"},
                    "dst": {"dpid": "0000000000000002", "port_no": 2, "name": "s2-eth2"}
                },
                {
                    "src": {"dpid": "0000000000000001", "port_no": 3, "name": "s1-eth3"},
                    "dst": {"dpid": "0000000000000003", "port_no": 1, "name": "s3-eth1"}
                },
                {
                    "src": {"dpid": "0000000000000003", "port_no": 2, "name": "s3-eth2"},
                    "dst": {"dpid": "0000000000000002", "port_no": 3, "name": "s2-eth3"}
                }
            ]

    def get_flow_table(self, dpid_num: int) -> list:
        # Check if an installed rule overrides actions for this dpid
        installed_action = None
        for rule in reversed(self.installed_rules):
            if int(rule.get("dpid", 0)) == dpid_num:
                acts = rule.get("actions", [])
                for a in acts:
                    if isinstance(a, dict) and a.get("type") == "OUTPUT":
                        installed_action = f"OUTPUT:{a.get('port')}"
                    elif isinstance(a, str):
                        installed_action = a
                break

        if dpid_num == 1:
            # Switch 1 forwards 10.0.0.2 out port 2 (s1->s2) by default, or installed backup (s1->s3)
            out_act = [installed_action] if installed_action else ["OUTPUT:2"]
            return [
                {
                    "priority": 100,
                    "match": {"ipv4_dst": "10.0.0.2", "eth_type": 2048},
                    "actions": out_act
                },
                {
                    "priority": 100,
                    "match": {"ipv4_dst": "10.0.0.1", "eth_type": 2048},
                    "actions": ["OUTPUT:1"]
                }
            ]
        elif dpid_num == 2:
            # Switch 2 forwards 10.0.0.2 out port 1 (s2->h2)
            in_port = 3 if (installed_action or self.scenario == "failed") else 2
            return [
                {
                    "priority": 100,
                    "match": {"ipv4_dst": "10.0.0.2", "eth_type": 2048},
                    "actions": ["OUTPUT:1"]
                },
                {
                    "priority": 100,
                    "match": {"ipv4_dst": "10.0.0.1", "eth_type": 2048},
                    "actions": [f"OUTPUT:{in_port}"]
                }
            ]
        elif dpid_num == 3:
            # Switch 3 forwards 10.0.0.2 out port 2 (s3->s2) and 10.0.0.1 out port 1 (s3->s1)
            return [
                {
                    "priority": 100,
                    "match": {"ipv4_dst": "10.0.0.2", "eth_type": 2048},
                    "actions": ["OUTPUT:2"]
                },
                {
                    "priority": 100,
                    "match": {"ipv4_dst": "10.0.0.1", "eth_type": 2048},
                    "actions": ["OUTPUT:1"]
                }
            ]
        return []

    def get_port_stats(self, dpid_num: int) -> list:
        # Simulate normal vs degraded vs dropped stats
        is_degraded = (self.scenario == "degraded")
        is_failed = (self.scenario == "failed")

        if dpid_num == 1:
            port2_drops = 25 if is_degraded else (100 if is_failed else 0)
            port2_errors = 5 if is_degraded else (50 if is_failed else 0)
            return [
                {"port_no": 1, "rx_packets": 1000, "tx_packets": 995, "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0},
                {"port_no": 2, "rx_packets": 1200, "tx_packets": 1150, "rx_dropped": port2_drops, "tx_dropped": port2_drops, "rx_errors": port2_errors, "tx_errors": port2_errors},
                {"port_no": 3, "rx_packets": 200, "tx_packets": 200, "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0}
            ]
        elif dpid_num == 2:
            port2_drops = 25 if is_degraded else (100 if is_failed else 0)
            return [
                {"port_no": 1, "rx_packets": 990, "tx_packets": 1000, "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0},
                {"port_no": 2, "rx_packets": 1150 - port2_drops, "tx_packets": 1200, "rx_dropped": port2_drops, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0},
                {"port_no": 3, "rx_packets": 200, "tx_packets": 200, "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0}
            ]
        elif dpid_num == 3:
            return [
                {"port_no": 1, "rx_packets": 200, "tx_packets": 200, "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0},
                {"port_no": 2, "rx_packets": 200, "tx_packets": 200, "rx_dropped": 0, "tx_dropped": 0, "rx_errors": 0, "tx_errors": 0}
            ]
        return []


class MockControllerHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Handles REST requests imitating Ryu's rest_topology and ofctl_rest."""

    def log_message(self, format, *args):
        # Override standard HTTP access log to use logger
        self.server.logger.debug(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        state = self.server.state

        # 1. Ryu Topology REST Endpoints
        if path == "/v1.0/topology/switches":
            self._send_json(state.switches)
        elif path == "/v1.0/topology/links":
            self._send_json(state.links)
        elif path == "/v1.0/topology/hosts":
            self._send_json(state.hosts)

        # 2. Ryu Ofctl REST Endpoints
        elif path == "/stats/switches":
            self._send_json([1, 2, 3])
        elif path.startswith("/stats/flow/"):
            try:
                dpid_num = int(path.split("/")[-1])
                flows = state.get_flow_table(dpid_num)
                self._send_json({str(dpid_num): flows})
            except ValueError:
                self._send_error(400, "Invalid DPID")
        elif path.startswith("/stats/port/"):
            try:
                dpid_num = int(path.split("/")[-1])
                ports = state.get_port_stats(dpid_num)
                self._send_json({str(dpid_num): ports})
            except ValueError:
                self._send_error(400, "Invalid DPID")

        # 3. Mock Scenario Controls
        elif path == "/mock/scenario":
            self._send_json({"scenario": state.scenario, "installed_rules_count": len(state.installed_rules)})
        elif path.startswith("/mock/set_scenario/"):
            new_scen = path.split("/")[-1]
            state.scenario = new_scen
            state.reset_topology()
            self._send_json({"status": "OK", "new_scenario": new_scen})
        else:
            self._send_error(404, f"Endpoint {path} not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        state = self.server.state

        if path == "/stats/flowentry/add":
            length = int(self.headers.get("content-length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                rule_data = json.loads(body)
                state.installed_rules.append(rule_data)
                self.server.logger.info(f"Installed flow entry via /stats/flowentry/add: {rule_data}")
                self._send_json({"status": "SUCCESS", "message": "Flow entry installed successfully"})
            except Exception as e:
                self._send_error(400, f"Malformed JSON rule: {e}")
        elif path == "/mock/reset":
            state.reset_topology()
            state.installed_rules.clear()
            self._send_json({"status": "RESET_OK"})
        else:
            self._send_error(404, f"Endpoint {path} not found")

    def _send_json(self, data, status_code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code, message):
        self._send_json({"error": message, "code": code}, status_code=code)


class MockSDNServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, scenario="healthy", verbose=False):
        super().__init__(server_address, RequestHandlerClass)
        self.state = MockSDNState(scenario=scenario)
        self.logger = setup_logger(verbose)


def run_mock_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                    scenario: str = "healthy", verbose: bool = False):
    """Run mock controller server."""
    server = MockSDNServer((host, port), MockControllerHTTPHandler, scenario=scenario, verbose=verbose)
    print("=" * 68)
    print("        Mock Ryu SDN Controller REST Server Running")
    print("=" * 68)
    print(f" Listening Address: http://{host}:{port}")
    print(f" Active Scenario:   {scenario.upper()}")
    print(" Emulated APIs:     Ryu rest_topology (/v1.0/topology/*)")
    print("                    Ryu ofctl_rest (/stats/switches, /stats/flow/*, /stats/port/*)")
    print("                    Ryu flow modification (/stats/flowentry/add)")
    print("-" * 68)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Mock controller shutting down.")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(
        description="Mock Ryu SDN Controller REST Server for Offline Testing & Demos."
    )
    parser.add_argument("-b", "--bind", default=DEFAULT_HOST, help=f"IP address to bind (default: {DEFAULT_HOST})")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"REST port (default: {DEFAULT_PORT})")
    parser.add_argument("-s", "--scenario", choices=["healthy", "degraded", "failed"], default="healthy", help="Simulated network scenario (default: healthy)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()
    run_mock_server(host=args.bind, port=args.port, scenario=args.scenario, verbose=args.verbose)


if __name__ == "__main__":
    main()
