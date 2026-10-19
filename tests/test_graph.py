"""
Unit tests for SDNTopologyGraph BFS path enumeration, loop handling,
disconnected graphs, and topology node resolution.
"""

from topology_graph import SDNTopologyGraph


def build_diamond_topology():
    """Construct standard diamond topology with h1, h2, s1, s2, s3."""
    return {
        "nodes": [
            {"id": "h1", "type": "host", "ip": "10.0.0.1"},
            {"id": "h2", "type": "host", "ip": "10.0.0.2"},
            {"id": "s1", "type": "switch", "dpid": "0000000000000001"},
            {"id": "s2", "type": "switch", "dpid": "0000000000000002"},
            {"id": "s3", "type": "switch", "dpid": "0000000000000003"}
        ],
        "links": [
            {"source": "h1", "destination": "s1", "type": "host-to-switch"},
            {"source": "s1", "destination": "s2", "type": "switch-to-switch"},
            {"source": "s1", "destination": "s3", "type": "switch-to-switch"},
            {"source": "s3", "destination": "s2", "type": "switch-to-switch"},
            {"source": "s2", "destination": "h2", "type": "host-to-switch"}
        ]
    }


def test_diamond_path_enumeration():
    """Verify diamond topology produces primary (3 hops) and backup (4 hops) in order."""
    graph = SDNTopologyGraph()
    graph.load_from_dict(build_diamond_topology())

    paths = graph.find_all_simple_paths("h1", "h2")
    assert len(paths) == 2
    assert paths[0] == ["h1", "s1", "s2", "h2"]
    assert paths[1] == ["h1", "s1", "s3", "s2", "h2"]

    comp_dict = graph.compare_paths(paths)
    assert comp_dict["total_paths"] == 2
    assert comp_dict["selected_shortest_path"]["path"] == ["h1", "s1", "s2", "h2"]
    assert len(comp_dict["alternative_paths"]) == 1

    table = comp_dict["comparison"]
    assert len(table) == 2
    assert table[0]["role"] == "SELECTED_SHORTEST"
    assert table[0]["hop_count"] == 3
    assert table[0]["extra_hops"] == 0

    assert table[1]["role"] == "ALTERNATIVE"
    assert table[1]["hop_count"] == 4
    assert table[1]["extra_hops"] == 1


def test_ip_and_case_insensitive_resolution():
    """Verify nodes resolve by Node ID, IPv4, or case-insensitive string."""
    graph = SDNTopologyGraph()
    graph.load_from_dict(build_diamond_topology())

    assert graph.resolve_node("h1") == "h1"
    assert graph.resolve_node("H1") == "h1"
    assert graph.resolve_node("10.0.0.1") == "h1"
    assert graph.resolve_node("10.0.0.2") == "h2"
    assert graph.resolve_node("S2") == "s2"
    assert graph.resolve_node("nonexistent") is None


def test_disconnected_graph():
    """Verify disconnected components return empty path list."""
    disconnected_topo = {
        "nodes": [
            {"id": "h1", "type": "host", "ip": "10.0.0.1"},
            {"id": "s1", "type": "switch"},
            {"id": "h2", "type": "host", "ip": "10.0.0.2"},
            {"id": "s2", "type": "switch"}
        ],
        "links": [
            {"source": "h1", "destination": "s1"},
            {"source": "s2", "destination": "h2"}
            # Notice no link between s1 and s2!
        ]
    }
    graph = SDNTopologyGraph()
    graph.load_from_dict(disconnected_topo)

    paths = graph.find_all_simple_paths("h1", "h2")
    assert paths == []

    comp_dict = graph.compare_paths(paths)
    assert comp_dict["total_paths"] == 0
    assert comp_dict["selected_shortest_path"] is None
    assert comp_dict["comparison"] == []


def test_cyclic_graph_loop_handling():
    """Verify cyclic mesh topology finds paths without entering infinite loops."""
    cyclic_topo = {
        "nodes": [
            {"id": "A", "type": "switch"},
            {"id": "B", "type": "switch"},
            {"id": "C", "type": "switch"},
            {"id": "D", "type": "switch"}
        ],
        "links": [
            {"source": "A", "destination": "B"},
            {"source": "B", "destination": "C"},
            {"source": "C", "destination": "A"},  # Cycle A-B-C-A
            {"source": "C", "destination": "D"},
            {"source": "B", "destination": "D"}   # Alternate to D
        ]
    }
    graph = SDNTopologyGraph()
    graph.load_from_dict(cyclic_topo)

    paths = graph.find_all_simple_paths("A", "D")
    # Loop-free paths:
    # 1. A -> B -> D (2 hops)
    # 2. A -> C -> D (2 hops)
    # 3. A -> B -> C -> D (3 hops)
    # 4. A -> C -> B -> D (3 hops)
    assert len(paths) == 4
    for p in paths:
        assert len(p) == len(set(p))  # All paths must be simple (no repeated nodes)
        assert p[0] == "A"
        assert p[-1] == "D"


def test_source_equals_destination():
    """Verify finding path from node to itself returns single-node path."""
    graph = SDNTopologyGraph()
    graph.load_from_dict(build_diamond_topology())

    paths = graph.find_all_simple_paths("s1", "s1")
    assert paths == [["s1"]]
