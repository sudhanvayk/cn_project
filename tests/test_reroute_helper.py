"""
Unit tests for SDN Backup Path Flow Rerouting Assistant.
"""

from unittest.mock import MagicMock, patch

from reroute_helper import (
    apply_reroute,
    build_backup_flow_rules,
    build_primary_flow_rules,
    extract_dpid_num,
    generate_flow_entries,
    install_backup_flows,
    install_primary_flows,
)
from topology_graph import SDNTopologyGraph


def build_test_graph():
    graph = SDNTopologyGraph()
    topo_data = {
        "nodes": [
            {"id": "h1", "type": "host", "ip": "10.0.0.1"},
            {"id": "h2", "type": "host", "ip": "10.0.0.2"},
            {"id": "s1", "type": "switch", "dpid": "0000000000000001"},
            {"id": "s2", "type": "switch", "dpid": "0000000000000002"},
            {"id": "s3", "type": "switch", "dpid": "0000000000000003"}
        ],
        "links": [
            {"source": "h1", "destination": "s1", "src_port": 1, "dst_port": 1},
            {"source": "s1", "destination": "s3", "src_port": 3, "dst_port": 1},
            {"source": "s3", "destination": "s2", "src_port": 2, "dst_port": 3},
            {"source": "s2", "destination": "h2", "src_port": 1, "dst_port": 1}
        ]
    }
    graph.load_from_dict(topo_data)
    return graph


def test_extract_dpid_num():
    assert extract_dpid_num("s1") == 1
    assert extract_dpid_num("s12") == 12
    assert extract_dpid_num("openflow:3") == 3
    assert extract_dpid_num("switch") is None


def test_generate_flow_entries():
    graph = build_test_graph()
    path = ["h1", "s1", "s3", "s2", "h2"]
    rules = generate_flow_entries(path, graph, dst_ip="10.0.0.2", priority=250)

    # 3 switches in path: s1, s3, s2
    assert len(rules) == 3

    # Switch 1 outputs to port 3 (towards s3)
    assert rules[0]["dpid"] == 1
    assert rules[0]["priority"] == 250
    assert rules[0]["match"]["ipv4_dst"] == "10.0.0.2"
    assert rules[0]["actions"][0]["port"] == 3

    # Switch 3 outputs to port 2 (towards s2)
    assert rules[1]["dpid"] == 3
    assert rules[1]["actions"][0]["port"] == 2

    # Switch 2 outputs to port 1 (towards h2)
    assert rules[2]["dpid"] == 2
    assert rules[2]["actions"][0]["port"] == 1


@patch("requests.post")
def test_apply_reroute_live(mock_post):
    resp = MagicMock()
    resp.status_code = 200
    mock_post.return_value = resp

    rules = [{"dpid": 1, "match": {"ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 3}]}]
    res = apply_reroute(rules, "http://127.0.0.1:8080", apply_changes=True)
    assert res["applied"] is True
    assert res["rules_count"] == 1
    assert res["results"][0]["status"] == "SUCCESS"
    mock_post.assert_called_once()


def test_apply_reroute_dry_run():
    rules = [{"dpid": 1, "match": {"ipv4_dst": "10.0.0.2"}, "actions": [{"type": "OUTPUT", "port": 3}]}]
    # Dry run should not make any HTTP requests
    res = apply_reroute(rules, "http://127.0.0.1:8080", apply_changes=False)
    assert res["applied"] is False
    assert res["rules_count"] == 1
    assert res["results"][0]["status"] == "DRY_RUN"


def test_build_primary_flow_rules():
    rules = build_primary_flow_rules(priority=100)
    # 4 specs * 2 (IPv4 + ARP) = 8 rules
    assert len(rules) == 8
    # Check s1 rules
    s1_rules = [r for r in rules if r["dpid"] == 1]
    assert len(s1_rules) == 4
    # Check s1 forward to 10.0.0.2 via port 2
    s1_fwd_ipv4 = [r for r in s1_rules if r["match"].get("ipv4_dst") == "10.0.0.2"][0]
    assert s1_fwd_ipv4["actions"][0]["port"] == 2
    assert s1_fwd_ipv4["priority"] == 100


def test_build_backup_flow_rules():
    rules = build_backup_flow_rules(priority=200)
    # 4 specs * 2 (IPv4 + ARP) = 8 rules
    assert len(rules) == 8
    # s1 to 10.0.0.2 should now output to port 3
    s1_fwd = [r for r in rules if r["dpid"] == 1 and r["match"].get("ipv4_dst") == "10.0.0.2"][0]
    assert s1_fwd["actions"][0]["port"] == 3
    assert s1_fwd["priority"] == 200
    # s3 rules present
    s3_rules = [r for r in rules if r["dpid"] == 3]
    assert len(s3_rules) == 4


@patch("requests.post")
def test_install_primary_flows_live(mock_post):
    resp = MagicMock()
    resp.status_code = 200
    mock_post.return_value = resp

    res = install_primary_flows("http://127.0.0.1:8080", priority=100, apply_changes=True, delete_first=True)
    assert res["applied"] is True
    assert res["rules_count"] == 8
    # delete_strict + add for each of 8 rules = 16 calls
    assert mock_post.call_count == 16


def test_install_backup_flows_dry_run():
    res = install_backup_flows("http://127.0.0.1:8080", priority=200, apply_changes=False)
    assert res["applied"] is False
    assert res["rules_count"] == 8
    assert all(r["status"] == "DRY_RUN" for r in res["results"])
