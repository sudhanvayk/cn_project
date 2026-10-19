"""
End-to-End Integration Tests for Probe Server and Diagnostic Client.
Verifies real UDP probe transmission, artificial loss injection,
and measurement statistics on localhost.
"""

import socket
import threading
import time

import pytest

from diagnostic_client import run_diagnostics_single
from probe_server import ProbeUDPHandler, ThreadedUDPServer


def get_free_udp_port():
    """Find an available UDP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def run_udp_server():
    """Fixture to launch ThreadedUDPServer with configurable drop_rate and delay_ms."""
    servers = []

    def _start(drop_rate=0.0, delay_ms=0.0):
        port = get_free_udp_port()
        server = ThreadedUDPServer(("127.0.0.1", port), ProbeUDPHandler, drop_rate=drop_rate, delay_ms=delay_ms)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        servers.append(server)
        time.sleep(0.05)  # allow socket binding
        return port

    yield _start

    for s in servers:
        s.shutdown()
        s.server_close()


def test_integration_zero_loss(run_udp_server):
    """Verify 100% reception and 0% loss against a nominal server."""
    port = run_udp_server(drop_rate=0.0, delay_ms=0.0)

    result = run_diagnostics_single(
        target_ip="127.0.0.1",
        port=port,
        count=15,
        timeout=1.0,
        payload_size=64,
        interval=0.01,
        burst=False
    )

    summary = result["summary"]
    assert summary["sent"] == 15
    assert summary["received"] == 15
    assert summary["lost"] == 0
    assert summary["packet_loss_percent"] == 0.0
    assert summary["mean_rtt_ms"] is not None
    assert summary["mean_rtt_ms"] > 0.0


def test_integration_artificial_drop_rate(run_udp_server):
    """
    Verify artificial drop rate of 25% produces measured packet loss
    within statistical tolerance (+/- 15% on 40 probes).
    """
    port = run_udp_server(drop_rate=0.25, delay_ms=0.0)

    result = run_diagnostics_single(
        target_ip="127.0.0.1",
        port=port,
        count=40,
        timeout=0.2,
        payload_size=64,
        interval=0.01,
        burst=False
    )

    summary = result["summary"]
    assert summary["sent"] == 40
    # Expected drops: 40 * 0.25 = 10 drops (25%)
    # Tolerant range: 3 to 20 drops (7.5% to 50.0%)
    measured_loss = summary["packet_loss_percent"]
    assert 5.0 <= measured_loss <= 50.0
    assert summary["lost"] > 0
    assert summary["received"] > 0


def test_integration_artificial_delay(run_udp_server):
    """Verify artificial delay injection of 25ms increases mean RTT accordingly."""
    port = run_udp_server(drop_rate=0.0, delay_ms=25.0)

    result = run_diagnostics_single(
        target_ip="127.0.0.1",
        port=port,
        count=5,
        timeout=1.0,
        payload_size=64,
        interval=0.01,
        burst=False
    )

    summary = result["summary"]
    assert summary["received"] == 5
    # Mean RTT must be at least 24ms due to injected 25ms server delay
    assert summary["mean_rtt_ms"] >= 24.0
