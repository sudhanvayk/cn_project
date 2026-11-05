"""
Unit tests for Linux kernel qdisc (tc/netem) telemetry parsing and its use as
a direct degraded-link localization evidence source.
"""

import json

from correlate import (
    aggregate_suspected_links,
    analyze_qdisc_deltas,
    load_qdisc_stats,
    parse_qdisc_stats,
)

QDISC_CAPTURE = """s1-eth2:
qdisc netem 10: root refcnt 5 limit 1000 delay 30ms loss 5%
 Sent 16427 bytes 99 pkt (dropped 9, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0

s2-eth2:
qdisc netem 10: root refcnt 5 limit 1000 delay 30ms loss 5%
 Sent 23436 bytes 97 pkt (dropped 3, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
"""

LINKS = [
    {"source": "s1", "destination": "s2", "src_port": 2, "dst_port": 2},
    {"source": "s1", "destination": "s3", "src_port": 3, "dst_port": 1},
]


def test_parse_qdisc_stats_multi_section():
    stats = parse_qdisc_stats(QDISC_CAPTURE)
    assert stats["s1-eth2"] == {"sent_packets": 99, "dropped": 9}
    assert stats["s2-eth2"] == {"sent_packets": 97, "dropped": 3}


def test_parse_qdisc_stats_single_output():
    raw = (
        "qdisc netem 10: root refcnt 5 limit 1000 delay 30ms loss 5%\n"
        " Sent 100 bytes 2 pkt (dropped 1, overlimits 0 requeues 0)\n"
    )
    stats = parse_qdisc_stats(raw)
    assert list(stats.values()) == [{"sent_packets": 2, "dropped": 1}]


def test_load_qdisc_stats_json(tmp_path):
    path = tmp_path / "qdisc.json"
    path.write_text(json.dumps({"s1-eth2": {"dropped": 5}, "s2-eth2": 2}))
    stats = load_qdisc_stats(str(path))
    assert stats["s1-eth2"]["dropped"] == 5
    assert stats["s2-eth2"]["dropped"] == 2


def test_load_qdisc_stats_missing_file_returns_empty():
    assert load_qdisc_stats("/nonexistent/qdisc.txt") == {}


def test_analyze_qdisc_deltas_flags_impaired_link():
    baseline = {
        "s1-eth2": {"dropped": 0},
        "s2-eth2": {"dropped": 0},
        "s1-eth3": {"dropped": 0},
    }
    current = {
        "s1-eth2": {"dropped": 9},
        "s2-eth2": {"dropped": 3},
        "s1-eth3": {"dropped": 0},
    }
    suspects = analyze_qdisc_deltas(baseline, current, LINKS)

    assert len(suspects) == 1
    assert suspects[0]["link"] == ["s1", "s2"]
    assert suspects[0]["confidence"] == 0.95
    assert suspects[0]["drop_delta"] == 12
    assert "Kernel qdisc drop counters incremented: 12" in suspects[0]["evidence"][0]


def test_analyze_qdisc_deltas_ignores_zero_and_missing_counters():
    baseline = {"s1-eth2": {"dropped": 4}, "s2-eth2": {"dropped": 0}}
    current = {"s1-eth2": {"dropped": 4}, "s2-eth2": {"dropped": 0}}
    assert analyze_qdisc_deltas(baseline, current, LINKS) == []


def test_analyze_qdisc_deltas_requires_ports():
    links = [{"source": "s1", "destination": "s2"}]
    stats = {"s1-eth2": {"dropped": 1}}
    assert analyze_qdisc_deltas(stats, stats, links) == []


def test_qdisc_evidence_combines_with_port_statistics():
    qdisc_suspect = {
        "link": ["s1", "s2"],
        "confidence": 0.95,
        "evidence": ["qdisc drops"],
    }
    port_suspect = {
        "link": ["s1", "s2"],
        "confidence": 0.85,
        "evidence": ["port drops"],
    }
    combined = aggregate_suspected_links([qdisc_suspect, port_suspect])
    assert len(combined) == 1
    # noisy-OR: 1 - (1 - 0.95) * (1 - 0.85) = 0.9925
    assert combined[0]["confidence"] >= 0.99


def test_correlate_uses_qdisc_deltas_for_degraded_path(tmp_path):
    from correlate import correlate

    diag_file = tmp_path / "diag.json"
    topo_file = tmp_path / "topo.json"
    qdisc_before = tmp_path / "qdisc_before.txt"
    qdisc_after = tmp_path / "qdisc_after.txt"
    out_file = tmp_path / "corr.json"

    diag = {
        "target_ip": "10.0.0.2",
        "summary": {
            "sent": 100,
            "received": 89,
            "lost": 11,
            "packet_loss_percent": 11.0,
            "mean_rtt_ms": 75.8,
        },
    }
    topo = {
        "nodes": [
            {"id": "h1", "type": "host", "ip": "10.0.0.1"},
            {"id": "h2", "type": "host", "ip": "10.0.0.2"},
            {"id": "s1", "type": "switch"},
            {"id": "s2", "type": "switch"},
            {"id": "s3", "type": "switch"},
        ],
        "links": [
            {"source": "h1", "destination": "s1"},
            {"source": "s1", "destination": "s2", "src_port": 2, "dst_port": 2},
            {"source": "s1", "destination": "s3", "src_port": 3, "dst_port": 1},
            {"source": "s3", "destination": "s2", "src_port": 2, "dst_port": 3},
            {"source": "s2", "destination": "h2"},
        ],
    }

    diag_file.write_text(json.dumps(diag))
    topo_file.write_text(json.dumps(topo))
    qdisc_before.write_text(
        "s1-eth2:\n Sent 0 bytes 0 pkt (dropped 0, overlimits 0 requeues 0)\n"
        "s2-eth2:\n Sent 0 bytes 0 pkt (dropped 0, overlimits 0 requeues 0)\n"
    )
    qdisc_after.write_text(QDISC_CAPTURE)

    report = correlate(
        diag_file=str(diag_file),
        topo_file=str(topo_file),
        source_node="h1",
        dest_node="h2",
        output_file=str(out_file),
        baseline_qdisc_file=str(qdisc_before),
        current_qdisc_file=str(qdisc_after),
    )

    assert report["path_status"] == "DEGRADED_PATH"
    assert report["qdisc_drop_delta"] == 12
    suspects = {tuple(sorted(s["link"])): s for s in report["suspected_links"]}
    assert ("s1", "s2") in suspects
    assert suspects[("s1", "s2")]["confidence"] == 0.95
