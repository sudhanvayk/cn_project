"""
Unit tests for FlowInspector OpenFlow flow-table path reconstruction,
action port parsing, and fallback shortest-path determination.

Tests use real Ryu ofctl_rest OpenFlow 1.3 legacy match keys:
dl_src, dl_dst, dl_type, in_port (integer), nw_src, nw_dst.
"""

from unittest.mock import MagicMock, patch

from flow_inspector import FlowInspector, is_lldp_flow, is_table_miss_flow, parse_output_port


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


def test_is_lldp_flow():
    """Verify LLDP discovery flow detection."""
    lldp_flow = {
        "priority": 65535,
        "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 35020},
        "actions": ["OUTPUT:CONTROLLER"]
    }
    assert is_lldp_flow(lldp_flow) is True

    # Not LLDP: wrong dl_type
    non_lldp = {
        "priority": 100,
        "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 2048},
        "actions": ["OUTPUT:CONTROLLER"]
    }
    assert is_lldp_flow(non_lldp) is False

    # Not LLDP: wrong dl_dst
    non_lldp2 = {
        "priority": 65535,
        "match": {"dl_dst": "aa:bb:cc:dd:ee:ff", "dl_type": 35020},
        "actions": ["OUTPUT:CONTROLLER"]
    }
    assert is_lldp_flow(non_lldp2) is False

    # Not LLDP: no controller output
    non_lldp3 = {
        "priority": 65535,
        "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 35020},
        "actions": ["OUTPUT:2"]
    }
    assert is_lldp_flow(non_lldp3) is False


def test_is_table_miss_flow():
    """Verify table-miss flow detection (priority 0, empty/all match)."""
    table_miss = {"priority": 0, "match": {}, "actions": ["OUTPUT:CONTROLLER"]}
    assert is_table_miss_flow(table_miss) is True

    # Priority 0 with dl_type match is not table-miss (it's a specific rule)
    not_miss = {"priority": 0, "match": {"dl_type": 2048}, "actions": ["OUTPUT:2"]}
    assert is_table_miss_flow(not_miss) is False

    # Non-zero priority is not table-miss
    not_miss2 = {"priority": 100, "match": {}, "actions": ["OUTPUT:2"]}
    assert is_table_miss_flow(not_miss2) is False


def test_match_flow_rule_legacy_keys():
    """Verify matching rules by IPv4 destination using legacy nw_dst key."""
    inspector = FlowInspector()
    flows = [
        {"priority": 10, "match": {"dl_type": 2048}, "actions": ["OUTPUT:1"]},
        {"priority": 100, "match": {"nw_dst": "10.0.0.2", "dl_type": 2048}, "actions": ["OUTPUT:2"]},
        {"priority": 100, "match": {"nw_dst": "10.0.0.1", "dl_type": 2048}, "actions": ["OUTPUT:3"]}
    ]

    matched = inspector.match_flow_rule(flows, dst_ip="10.0.0.2")
    assert matched is not None
    assert matched["actions"] == ["OUTPUT:2"]

    # Match nonexistent destination returns None
    assert inspector.match_flow_rule(flows, dst_ip="192.168.1.1") is None


def test_match_flow_rule_eth_aliases():
    """Verify eth_dst/eth_type aliases work alongside legacy keys."""
    inspector = FlowInspector()
    flows = [
        {"priority": 100, "match": {"eth_dst": "a6:81:91:d5:30:f9", "eth_type": 2048}, "actions": ["OUTPUT:2"]},
    ]

    matched = inspector.match_flow_rule(flows, dst_mac="a6:81:91:d5:30:f9")
    assert matched is not None
    assert matched["actions"] == ["OUTPUT:2"]


def test_match_flow_rule_skips_lldp_and_table_miss():
    """Verify LLDP discovery and table-miss flows are ignored during matching."""
    inspector = FlowInspector()
    flows = [
        # LLDP discovery flow - should be skipped
        {"priority": 65535, "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 35020}, "actions": ["OUTPUT:CONTROLLER"]},
        # Table-miss flow - should be skipped
        {"priority": 0, "match": {}, "actions": ["OUTPUT:CONTROLLER"]},
        # Real forwarding rule - should be matched
        {"priority": 100, "match": {"nw_dst": "10.0.0.2", "dl_type": 2048, "in_port": 1}, "actions": ["OUTPUT:2"]},
    ]

    matched = inspector.match_flow_rule(flows, dst_ip="10.0.0.2")
    assert matched is not None
    assert matched["priority"] == 100
    assert matched["actions"] == ["OUTPUT:2"]


@patch("requests.get")
def test_reconstruct_active_path_flow_table(mock_get):
    """Verify active path reconstruction from simulated Ryu flow tables (legacy keys)."""
    # Mock responses for DPID 1 (s1) and DPID 2 (s2)
    def mock_requests(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if url.endswith("/flow/1"):
            # Switch 1 forwards 10.0.0.2 to port 2 (s2)
            resp.json.return_value = {
                "1": [
                    {"priority": 65535, "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 35020}, "actions": ["OUTPUT:CONTROLLER"]},
                    {"priority": 0, "match": {}, "actions": ["OUTPUT:CONTROLLER"]},
                    {"priority": 100, "match": {"nw_dst": "10.0.0.2", "dl_type": 2048, "in_port": 1}, "actions": ["OUTPUT:2"]}
                ]
            }
        elif url.endswith("/flow/2"):
            # Switch 2 forwards 10.0.0.2 to port 1 (h2)
            resp.json.return_value = {
                "2": [
                    {"priority": 65535, "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 35020}, "actions": ["OUTPUT:CONTROLLER"]},
                    {"priority": 0, "match": {}, "actions": ["OUTPUT:CONTROLLER"]},
                    {"priority": 100, "match": {"nw_dst": "10.0.0.2", "dl_type": 2048, "in_port": 2}, "actions": ["OUTPUT:1"]}
                ]
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
    # Only LLDP and table-miss flows, no real forwarding rule
    resp.json.return_value = {"1": [
        {"priority": 65535, "match": {"dl_dst": "01:80:c2:00:00:0e", "dl_type": 35020}, "actions": ["OUTPUT:CONTROLLER"]},
        {"priority": 0, "match": {}, "actions": ["OUTPUT:CONTROLLER"]}
    ]}
    mock_get.return_value = resp

    inspector = FlowInspector()
    inspector.graph.load_from_dict(build_mock_topology_dict())

    result = inspector.reconstruct_active_path("h1", "h2")
    assert result["path_source"] == "assumed_shortest"
    assert result["path"] == ["h1", "s1", "s2", "h2"]
    assert "no matching flow entry found" in result["fallback_reason"].lower()


def test_normalize_dpid_import():
    """Verify normalize_dpid and dpid_to_decimal are importable from sdn_topology."""
    from sdn_topology import dpid_to_decimal, normalize_dpid

    assert normalize_dpid("0000000000000002") == "0000000000000002"
    assert normalize_dpid("2") == "0000000000000002"
    assert normalize_dpid("s2") == "0000000000000002"
    assert dpid_to_decimal("0000000000000002") == 2
    assert dpid_to_decimal("2") == 2
    assert dpid_to_decimal("s2") == 2
