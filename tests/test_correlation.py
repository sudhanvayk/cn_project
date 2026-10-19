"""
Unit tests for correlation module, health classification boundary conditions,
failure localization evidence sources, and backup path re-ranking.
"""

from correlate import (
    classify_path_health,
    analyze_port_stats_deltas,
    analyze_segment_probes,
    analyze_topology_liveness,
    aggregate_suspected_links,
    filter_and_rank_backups
)

THRESHOLDS = {
    "degraded_rtt_ms": 50.0,
    "degraded_packet_loss_percent": 0.0,
    "failed_packet_loss_percent": 50.0
}


def test_classify_path_health_boundaries():
    # Exactly 0% loss, 50.0 ms RTT -> HEALTHY
    status, reason = classify_path_health({"packet_loss_percent": 0.0, "mean_rtt_ms": 50.0}, THRESHOLDS)
    assert status == "HEALTHY_PATH"

    # 0.01% loss (> 0%) -> DEGRADED
    status, reason = classify_path_health({"packet_loss_percent": 0.01, "mean_rtt_ms": 20.0}, THRESHOLDS)
    assert status == "DEGRADED_PATH"
    assert "packet loss" in reason

    # 0% loss, 50.1 ms RTT (> 50.0 ms) -> DEGRADED
    status, reason = classify_path_health({"packet_loss_percent": 0.0, "mean_rtt_ms": 50.1}, THRESHOLDS)
    assert status == "DEGRADED_PATH"
    assert "mean RTT" in reason

    # 49.99% loss -> DEGRADED (< 50%)
    status, reason = classify_path_health({"packet_loss_percent": 49.99, "mean_rtt_ms": 10.0}, THRESHOLDS)
    assert status == "DEGRADED_PATH"

    # Exactly 50.0% loss -> FAILED
    status, reason = classify_path_health({"packet_loss_percent": 50.0, "mean_rtt_ms": None}, THRESHOLDS)
    assert status == "FAILED_PATH"
    assert "Severe packet loss" in reason

    # 100.0% loss -> FAILED
    status, reason = classify_path_health({"packet_loss_percent": 100.0, "mean_rtt_ms": None}, THRESHOLDS)
    assert status == "FAILED_PATH"


def test_analyze_port_stats_deltas_packet_drop():
    baseline = {
        "1": [{"port_no": 2, "tx_packets": 100, "rx_packets": 100, "tx_dropped": 0, "rx_dropped": 0, "tx_errors": 0, "rx_errors": 0}],
        "2": [{"port_no": 2, "tx_packets": 100, "rx_packets": 100, "tx_dropped": 0, "rx_dropped": 0, "tx_errors": 0, "rx_errors": 0}],
    }
    current = {
        "1": [{"port_no": 2, "tx_packets": 200, "rx_packets": 100, "tx_dropped": 20, "rx_dropped": 0, "tx_errors": 0, "rx_errors": 0}],
        "2": [{"port_no": 2, "tx_packets": 100, "rx_packets": 180, "tx_dropped": 0, "rx_dropped": 0, "tx_errors": 0, "rx_errors": 0}],
    }
    links = [
        {"source": "s1", "destination": "s2", "src_port": 2, "dst_port": 2}
    ]

    suspects = analyze_port_stats_deltas(baseline, current, links)
    assert len(suspects) == 1
    assert suspects[0]["link"] == ["s1", "s2"]
    assert suspects[0]["confidence"] >= 0.85
    assert any("drop" in ev.lower() for ev in suspects[0]["evidence"])


def test_analyze_segment_probes_loss_spike():
    active_path = ["h1", "s1", "s2", "h2"]
    segment_metrics = {
        "h1": {"packet_loss_percent": 0.0, "mean_rtt_ms": 1.0},
        "s1": {"packet_loss_percent": 0.0, "mean_rtt_ms": 1.5},
        "s2": {"packet_loss_percent": 60.0, "mean_rtt_ms": 80.0},
        "h2": {"packet_loss_percent": 60.0, "mean_rtt_ms": 82.0},
    }

    suspects = analyze_segment_probes(segment_metrics, active_path)
    assert len(suspects) == 1
    assert suspects[0]["link"] == ["s1", "s2"]
    assert suspects[0]["confidence"] >= 0.90
    assert any("spiked" in ev.lower() for ev in suspects[0]["evidence"])


def test_analyze_topology_liveness_link_down():
    expected_links = [("h1", "s1"), ("s1", "s2"), ("s2", "h2")]
    active_links = [
        {"source": "h1", "destination": "s1"},
        {"source": "s1", "destination": "s3"},
        {"source": "s3", "destination": "s2"},
        {"source": "s2", "destination": "h2"}
    ]

    suspects = analyze_topology_liveness(expected_links, active_links)
    assert len(suspects) == 1
    assert suspects[0]["link"] == ["s1", "s2"]
    assert suspects[0]["confidence"] == 1.0
    assert any("disappeared" in ev.lower() for ev in suspects[0]["evidence"])


def test_filter_and_rank_backups():
    primary_path = ["h1", "s1", "s2", "h2"]
    candidates = [
        ["h1", "s1", "s2", "h2"],
        ["h1", "s1", "s4", "s2", "h2"], # contains s1-s4
        ["h1", "s1", "s3", "s2", "h2"], # viable backup
    ]
    # Suppose s1-s4 is suspected bad
    suspected_links = [
        {"link": ["s1", "s4"], "confidence": 0.90, "evidence": ["link down"]}
    ]

    ranked = filter_and_rank_backups(candidates, primary_path, suspected_links)
    assert len(ranked) == 2

    # First ranked path should be viable backup s1-s3-s2
    assert ranked[0]["path"] == ["h1", "s1", "s3", "s2", "h2"]
    assert ranked[0]["is_viable"] is True
    assert ranked[0]["status"] == "VIABLE_BACKUP"

    # Second path should be flagged as excluded
    assert ranked[1]["path"] == ["h1", "s1", "s4", "s2", "h2"]
    assert ranked[1]["is_viable"] is False
    assert ranked[1]["status"] == "EXCLUDED_CORRUPT_LINK"
