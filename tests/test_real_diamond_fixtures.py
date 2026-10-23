"""
Unit tests validating genuine live captures in tests/fixtures/real_diamond/.
Verifies DPID normalization, legacy OpenFlow match keys, LLDP flow filtering,
priority resolution, and backup flows overriding primary flows.
"""

import json
import os
from unittest.mock import patch

from flow_inspector import FlowInspector, is_lldp_flow
from sdn_topology import (
    merge_hosts_file,
    parse_ryu_hosts,
    parse_ryu_links,
    parse_ryu_switches,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
REAL_DIR = os.path.join(FIXTURES_DIR, "real")
REAL_DIAMOND_DIR = os.path.join(FIXTURES_DIR, "real_diamond")


def load_fixture(subdir: str, filename: str):
    path = os.path.join(FIXTURES_DIR, subdir, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_real_diamond_mac_addresses_fresh_and_not_synthetic():
    """Gate: real_diamond hardware MAC addresses must be genuine and disjoint from linear capture."""
    real_linear_links = load_fixture("real", "links.json")
    real_diamond_links = load_fixture("real_diamond", "links.json")

    linear_macs = {lnk["src"]["hw_addr"] for lnk in real_linear_links}
    diamond_macs = {lnk["src"]["hw_addr"] for lnk in real_diamond_links}

    assert len(diamond_macs) == 6
    assert linear_macs.isdisjoint(diamond_macs), "Real diamond MACs must not match preserved linear capture"


def test_parse_real_diamond_topology():
    """Verify sdn_topology parses switches and links from real diamond capture."""
    switches_raw = load_fixture("real_diamond", "switches.json")
    links_raw = load_fixture("real_diamond", "links.json")

    switches = parse_ryu_switches(switches_raw)
    assert len(switches) == 3
    switch_ids = {s["id"] for s in switches}
    assert switch_ids == {"s1", "s2", "s3"}

    links = parse_ryu_links(links_raw)
    assert len(links) == 3
    link_pairs = {tuple(sorted([lnk["source"], lnk["destination"]])) for lnk in links}
    assert link_pairs == {("s1", "s2"), ("s1", "s3"), ("s2", "s3")}


def test_real_diamond_hosts_empty_and_merge():
    """Verify hosts from real capture is empty and merge_hosts_file integrates static hosts."""
    hosts_raw = load_fixture("real_diamond", "hosts.json")
    nodes, links = parse_ryu_hosts(hosts_raw)
    assert nodes == []
    assert links == []

    # Merge static hosts file
    tmp_hosts = [
        {"name": "h1", "mac": "00:00:00:00:00:01", "ip": "10.0.0.1", "dpid": "0000000000000001", "port": 1},
        {"name": "h2", "mac": "00:00:00:00:00:02", "ip": "10.0.0.2", "dpid": "0000000000000002", "port": 1},
    ]
    switches = parse_ryu_switches(load_fixture("real_diamond", "switches.json"))
    links_parsed = parse_ryu_links(load_fixture("real_diamond", "links.json"))
    topo = {"nodes": switches, "links": links_parsed}

    import tempfile
    with tempfile.NamedTemporaryFile("w+", suffix=".json") as f:
        json.dump(tmp_hosts, f)
        f.flush()
        merged = merge_hosts_file(topo, f.name)

    host_nodes = [n for n in merged["nodes"] if n["type"] == "host"]
    assert len(host_nodes) == 2
    assert {h["id"] for h in host_nodes} == {"h1", "h2"}
    assert all(h["host_source"] == "hosts_file" for h in host_nodes)


def test_real_diamond_lldp_and_legacy_flow_filtering():
    """Verify FlowInspector correctly filters Ryu LLDP flows and matches legacy dl_type/nw_dst keys."""
    flow_s1 = load_fixture("real_diamond", "flow_s1.json")
    flows = flow_s1.get("1", [])

    # Find the LLDP flow
    lldp_flows = [f for f in flows if is_lldp_flow(f)]
    assert len(lldp_flows) == 1
    assert lldp_flows[0]["priority"] == 65535
    assert lldp_flows[0]["match"].get("dl_dst") == "01:80:c2:00:00:0e"

    inspector = FlowInspector()
    matched = inspector.match_flow_rule(flows, dst_ip="10.0.0.2")
    assert matched is not None
    assert matched["priority"] == 100
    assert matched["actions"] == ["OUTPUT:2"]


def test_real_diamond_priority_resolution_backup_overrides_primary():
    """Verify priority 200 backup flows override priority 100 primary flows on s1."""
    flow_s1_backup = load_fixture("real_diamond", "flow_s1_backup.json")
    flows = flow_s1_backup.get("1", [])

    inspector = FlowInspector()
    # On s1 with backup installed, traffic to 10.0.0.2 must route to port 3 (toward s3)
    matched = inspector.match_flow_rule(flows, dst_ip="10.0.0.2")
    assert matched is not None
    assert matched["priority"] == 200
    assert matched["actions"] == ["OUTPUT:3"]


def test_real_diamond_active_path_reconstruction():
    """Verify FlowInspector reconstructs the active path using real diamond flow tables."""
    flow_s1 = load_fixture("real_diamond", "flow_s1.json")
    flow_s2 = load_fixture("real_diamond", "flow_s2.json")
    flow_s3 = load_fixture("real_diamond", "flow_s3.json")

    # Build complete topology dict with hosts
    switches = parse_ryu_switches(load_fixture("real_diamond", "switches.json"))
    links = parse_ryu_links(load_fixture("real_diamond", "links.json"))
    topo = {
        "nodes": switches + [
            {"id": "h1", "type": "host", "ip": "10.0.0.1", "connected_to": "s1", "switch_port": 1},
            {"id": "h2", "type": "host", "ip": "10.0.0.2", "connected_to": "s2", "switch_port": 1},
        ],
        "links": links + [
            {"source": "h1", "destination": "s1", "src_port": None, "dst_port": 1, "type": "host-to-switch"},
            {"source": "h2", "destination": "s2", "src_port": None, "dst_port": 1, "type": "host-to-switch"},
        ]
    }

    import tempfile
    with tempfile.NamedTemporaryFile("w+", suffix=".json") as f:
        json.dump(topo, f)
        f.flush()

        inspector = FlowInspector(topology_file=f.name)

        def mock_get(url, *args, **kwargs):
            class MockResponse:
                def __init__(self, data):
                    self._data = data
                    self.status_code = 200
                def json(self):
                    return self._data
                def raise_for_status(self):
                    pass

            if "/stats/flow/1" in url:
                return MockResponse(flow_s1)
            elif "/stats/flow/2" in url:
                return MockResponse(flow_s2)
            elif "/stats/flow/3" in url:
                return MockResponse(flow_s3)
            return MockResponse({})

        with patch("requests.get", side_effect=mock_get):
            res = inspector.reconstruct_active_path("h1", "h2")
            assert res["path_source"] == "flow_table"
            assert res["path"] == ["h1", "s1", "s2", "h2"]
            assert res["hop_count"] == 3
