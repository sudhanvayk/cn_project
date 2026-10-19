"""
Unit tests for packet parsing, magic headers, protocol validation,
and malformed-packet handling.
"""

import json
import logging
from probe_server import MAGIC_HEADER, PROTOCOL_VERSION, ProbeUDPHandler


class MockUDPServer:
    """Mock socketserver for testing handler logic."""
    def __init__(self, drop_rate=0.0, delay_ms=0.0):
        self.drop_rate = drop_rate
        self.delay_ms = delay_ms
        self.probe_count = 0
        self.logger = logging.getLogger("test_probe_handler")


class MockUDPSocket:
    """Mock socket capturing replies."""
    def __init__(self):
        self.sent_packets = []

    def sendto(self, data, address):
        self.sent_packets.append((data, address))


def simulate_packet(raw_bytes: bytes, drop_rate: float = 0.0, delay_ms: float = 0.0) -> list:
    """Helper to run ProbeUDPHandler against raw bytes."""
    mock_socket = MockUDPSocket()
    mock_server = MockUDPServer(drop_rate=drop_rate, delay_ms=delay_ms)
    
    # Instantiate handler without calling BaseRequestHandler.__init__
    handler = ProbeUDPHandler.__new__(ProbeUDPHandler)
    handler.server = mock_server
    handler.request = (raw_bytes, mock_socket)
    handler.client_address = ("127.0.0.1", 54321)
    
    handler.handle()
    return mock_socket.sent_packets


def test_valid_packet_parsing():
    """Verify standard valid probe generates a valid matching response."""
    valid_payload = {
        "magic": MAGIC_HEADER,
        "version": PROTOCOL_VERSION,
        "probe_id": "test-probe-1",
        "seq": 1,
        "send_time": 1700000000.123,
        "payload_pad": "XXXX"
    }
    raw_data = json.dumps(valid_payload).encode("utf-8")
    replies = simulate_packet(raw_data)

    assert len(replies) == 1
    resp_bytes, client_addr = replies[0]
    assert client_addr == ("127.0.0.1", 54321)

    resp_json = json.loads(resp_bytes.decode("utf-8"))
    assert resp_json["magic"] == MAGIC_HEADER
    assert resp_json["version"] == PROTOCOL_VERSION
    assert resp_json["probe_id"] == "test-probe-1"
    assert resp_json["seq"] == 1
    assert resp_json["client_send_time"] == 1700000000.123
    assert "server_recv_time" in resp_json
    assert "server_send_time" in resp_json
    assert resp_json["status"] == "OK"


def test_reject_invalid_magic():
    """Verify packet with invalid magic string is discarded."""
    payload = {
        "magic": "STRAY_PACKET",
        "version": PROTOCOL_VERSION,
        "probe_id": "p-1",
        "seq": 1,
        "send_time": 1700000000.0
    }
    replies = simulate_packet(json.dumps(payload).encode("utf-8"))
    assert len(replies) == 0


def test_reject_malformed_json():
    """Verify non-JSON garbage data is discarded safely without unhandled exceptions."""
    garbage = b"\x00\xff\xfeNot Valid JSON!#$@%"
    replies = simulate_packet(garbage)
    assert len(replies) == 0


def test_reject_non_dict_json():
    """Verify JSON array or scalar is rejected."""
    replies = simulate_packet(b"[1, 2, 3]")
    assert len(replies) == 0

    replies = simulate_packet(b'"just a string"')
    assert len(replies) == 0


def test_reject_missing_send_time():
    """Verify packet missing client timestamp is dropped."""
    payload = {
        "magic": MAGIC_HEADER,
        "version": PROTOCOL_VERSION,
        "probe_id": "p-1",
        "seq": 1
    }
    replies = simulate_packet(json.dumps(payload).encode("utf-8"))
    assert len(replies) == 0


def test_artificial_drop_rate_100_percent():
    """Verify drop rate of 1.0 discards all packets."""
    valid_payload = {
        "magic": MAGIC_HEADER,
        "version": PROTOCOL_VERSION,
        "probe_id": "p-1",
        "seq": 1,
        "send_time": 1700000000.0
    }
    replies = simulate_packet(json.dumps(valid_payload).encode("utf-8"), drop_rate=1.0)
    assert len(replies) == 0
