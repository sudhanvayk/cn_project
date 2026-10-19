"""
Unit tests for FlowInspector OpenFlow flow-table path reconstruction,
action port parsing, and fallback shortest-path determination.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from flow_inspector import FlowInspector, parse_output_port


def build_mock_topology_dict():
    return {
        "nodes": [
            {"id": "h1", "type": "host", "ip": "10.0.0.1", "connected_to": "s1"},
            {"id": "h2", "type": "host", "ip": "10.0.0.2", "connected_to": "s2"},
            {"id": "s1", "type": "switch", "dpid": "0000000000000001"},
            {"id": "s2", "type": "switch", "dpid": "0000000000000002"},
            {"id": "s3", "type": "switch", "dpid": "0000000000000003"}
        ],
        "links": [
            {"source": "h1", "destination": "s1", "type": "host-to-switch"},
            {"source": "s1", "destination": "s2", "type": "switch-to-switch", "src_port": 2, "dst_port": 2},
            {"source": "s1", "destination": "s3", "type": "switch-to-switch", "src_port": 3, "dst_port": 1},
            {"source": "s3", "destination": "s2", "type": "switch-to-switch", "src_port": 2, "dst_port": 3},
            {"source": "s2", "destination": "h2", "type": "host-to-switch", "src_port": 1}
        ]
    }


def test_parse_output_port():
    """Verify regex extraction of output ports from OpenFlow actions."""
    assert parse_output_port("OUTPUT:2") == 2
    assert parse_output_port("OUTPUT:10") == 10
    assert parse_output_port("OUTPUT:FLOOD") == "FLOOD"
    assert parse_output_port("OUTPUT:IN_PORT") == "IN_PORT"
    assert parse_output_port("SET_FIELD: eth_dst") is None
    assert parse_output_port("DROP") is None


def test_match_flow_rule():
    """Verify matching rules by IPv4 destination address."""
    inspector = FlowInspector()
    flows = [
        {"priority": 10, "match": {"eth_type": 2048}, "actions": ["OUTPUT:1"]},
        {"priority": 100, "match": {"ipv4_dst": "10.0.0.2", "eth_type": 2048}, "actions": ["OUTPUT:2"]},
        {"priority": 100, "match": {"ipv4_dst": "10.0.0.1", "eth_type": 2048}, "actions": ["OUTPUT:3"]}
    ]

    matched = inspector.match_flow_rule(flows, dst_ip="10.0.0.2")
    assert matched is not None
    assert matched["actions"] == ["OUTPUT:2"]

    # Match nonexistent destination returns None
    assert inspector.match_flow_rule(flows, dst_ip="192.168.1.1") is None


@patch("requests.get")
def test_reconstruct_active_path_flow_table(mock_get):
    """Verify active path reconstruction from simulated Ryu flow tables."""
    # Mock responses for DPID 1 (s1) and DPID 2 (s2)
    def mock_requests(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if url.endswith("/flow/1"):
            # Switch 1 forwards 10.0.0.2 to port 2 (s2)
            resp.json.return_value = {
                "1": [{"priority": 100, "match": {"ipv4_dst": "10.0.0.2"}, "actions": ["OUTPUT:2"]}]
            }
        elif url.endswith("/flow/2"):
            # Switch 2 forwards 10.0.0.2 to port 1 (h2)
            resp.json.return_value = {
                "2": [{"priority": 100, "match": {"ipv4_dst": "10.0.0.2"}, "actions": ["OUTPUT:1"]}]
            }
        else:
            resp.json.return_value = {}
        return resp

    mock_get.side_effect = mock_requests

    inspector = FlowInspector()
    inspector.graph.load_from_dict(build_mock_topology_dict())

    result = inspector.reconstruct_active_path("h1", "h2")
    assert result["path_source"] == "flow_table"
    assert result["path"] == ["h1", "s1", "s2", "h2"]
    assert result["hop_count"] == 3
    assert len(result["flow_chain"]) == 2


@patch("requests.get")
def test_reconstruct_active_path_controller_down_fallback(mock_get):
    """Verify graceful fallback to assumed_shortest path when controller is unreachable."""
    mock_get.side_effect = ConnectionError("Controller unreachable")

    inspector = FlowInspector()
    inspector.graph.load_from_dict(build_mock_topology_dict())

    result = inspector.reconstruct_active_path("h1", "h2")
    assert result["path_source"] == "assumed_shortest"
    assert result["path"] == ["h1", "s1", "s2", "h2"]
    assert "fallback_reason" in result
    assert "unreachable" in result["fallback_reason"].lower() or "no matching" in result["fallback_reason"].lower()


@patch("requests.get")
def test_reconstruct_active_path_missing_flow_fallback(mock_get):
    """Verify fallback to assumed_shortest when no matching flow rule exists."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"1": []}  # empty flow table
    mock_get.return_value = resp

    inspector = FlowInspector()
    inspector.graph.load_from_dict(build_mock_topology_dict())

    result = inspector.reconstruct_active_path("h1", "h2")
    assert result["path_source"] == "assumed_shortest"
    assert result["path"] == ["h1", "s1", "s2", "h2"]
    assert "no matching flow entry found" in result["fallback_reason"].lower()
