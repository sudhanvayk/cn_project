"""
Unit tests for sdn_topology.py
"""

from sdn_topology import (
    diff_topologies,
    dpid_to_decimal,
    dpid_to_switch_id,
    ip_to_host_id,
    load_config,
    normalize_dpid,
    parse_opendaylight_topology,
    parse_ryu_hosts,
    parse_ryu_links,
    parse_ryu_switches,
)


def test_dpid_and_host_normalization():
    assert dpid_to_switch_id("1") == "s1"
    assert dpid_to_switch_id("0000000000000002") == "s2"
    assert dpid_to_switch_id("s3") == "s3"

    assert ip_to_host_id("10.0.0.1") == "h1"
    assert ip_to_host_id("192.168.1.15") == "h15"
    assert ip_to_host_id("*", 4) == "h4"


def test_parse_ryu_switches_and_links():
    raw_switches = ["0000000000000001", "0000000000000002"]
    switches = parse_ryu_switches(raw_switches)
    assert len(switches) == 2
    assert switches[0]["id"] == "s1"
    assert switches[1]["id"] == "s2"

    raw_links = [
        {
            "src": {"dpid": "0000000000000001", "port_no": "00000002"},
            "dst": {"dpid": "0000000000000002", "port_no": "00000001"},
        },
        # Reverse duplicate link
        {
            "src": {"dpid": "0000000000000002", "port_no": "00000001"},
            "dst": {"dpid": "0000000000000001", "port_no": "00000002"},
        },
    ]
    links = parse_ryu_links(raw_links)
    assert len(links) == 1
    assert links[0]["source"] == "s1"
    assert links[0]["destination"] == "s2"


def test_parse_opendaylight_topology():
    odl_raw = {
        "network-topology": {
            "topology": [
                {
                    "topology-id": "flow:1",
                    "node": [
                        {"node-id": "openflow:1"},
                        {
                            "node-id": "host:10.0.0.1",
                            "host-tracker-service:addresses": [{"ip": "10.0.0.1", "mac": "00:00:00:00:00:01"}],
                            "host-tracker-service:attachment-points": [{"tp-id": "openflow:1:1"}],
                        },
                    ],
                    "link": [
                        {
                            "link-id": "link:1",
                            "source": {"source-node": "openflow:1"},
                            "destination": {"dest-node": "openflow:2"},
                        }
                    ],
                }
            ]
        }
    }

    parsed = parse_opendaylight_topology(odl_raw, "http://127.0.0.1:8181")
    assert parsed["controller_type"] == "opendaylight"
    node_ids = [n["id"] for n in parsed["nodes"]]
    assert "s1" in node_ids
    assert "h1" in node_ids
    assert len(parsed["links"]) >= 1


def test_diff_topologies():
    old_topo = {
        "nodes": [{"id": "s1", "type": "switch"}, {"id": "s2", "type": "switch"}],
        "links": [{"source": "s1", "destination": "s2"}],
    }
    new_topo = {
        "nodes": [
            {"id": "s1", "type": "switch"},
            {"id": "s2", "type": "switch"},
            {"id": "s3", "type": "switch"},
        ],
        "links": [
            {"source": "s1", "destination": "s2"},
            {"source": "s1", "destination": "s3"},
        ],
    }

    diffs = diff_topologies(old_topo, new_topo)
    assert any("NODE ADDED: s3" in d for d in diffs)
    assert any("LINK UP: s1 <---> s3" in d for d in diffs)


def test_load_config():
    config = load_config("config.json")
    assert "sdn_controller_type" in config
    assert "controller_ip" in config


def test_parse_ryu_hosts_prefers_ipv4_ignores_colon_colon():
    """Verify IPv4 preference and '::' IPv6 handling in host parsing."""
    hosts_data = [
        {
            "mac": "16:fe:2d:6a:16:99",
            "ipv4": ["10.0.0.2"],
            "ipv6": ["::", "fe80::14fe:2dff:fe6a:1699"],
            "port": {"dpid": "0000000000000002", "port_no": "00000001", "name": "s2-eth1"}
        },
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "ipv4": [],
            "ipv6": ["::", "fe80::aaaa"],
            "port": {"dpid": "0000000000000003", "port_no": "00000001", "name": "s3-eth1"}
        },
    ]
    nodes, links = parse_ryu_hosts(hosts_data)

    # Only h1 with IPv4 10.0.0.2 should be parsed; host with only :: should be skipped
    assert len(nodes) == 1
    assert nodes[0]["id"] == "h2"
    assert nodes[0]["ip"] == "10.0.0.2"


def test_parse_ryu_hosts_empty_list():
    """Verify empty hosts list returns empty nodes/links (fresh controller)."""
    nodes, links = parse_ryu_hosts([])
    assert nodes == []
    assert links == []


def test_normalize_dpid_and_decimal():
    """Verify DPID normalization between 16-char hex and decimal forms."""
    assert normalize_dpid("0000000000000001") == "0000000000000001"
    assert normalize_dpid("1") == "0000000000000001"
    assert normalize_dpid("s1") == "0000000000000001"
    assert normalize_dpid("0000000000000003") == "0000000000000003"
    assert normalize_dpid("3") == "0000000000000003"

    assert dpid_to_decimal("0000000000000001") == 1
    assert dpid_to_decimal("1") == 1
    assert dpid_to_decimal("s1") == 1
    assert dpid_to_decimal("0000000000000003") == 3
