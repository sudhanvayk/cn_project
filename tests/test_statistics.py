"""
Unit tests for RTT statistics, jitter calculations, and percentiles.
"""

import math
import pytest
from diagnostic_client import calculate_percentile, compute_probe_statistics


def test_percentile_single_value():
    assert calculate_percentile([42.0], 95.0) == 42.0
    assert calculate_percentile([42.0], 50.0) == 42.0
    assert calculate_percentile([], 95.0) == 0.0


def test_percentile_linear_interpolation():
    # Values: 10, 20, 30, 40, 50
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    # 50th percentile (median) is 30.0
    assert math.isclose(calculate_percentile(data, 50.0), 30.0, rel_tol=1e-5)
    # 0th percentile is 10.0
    assert math.isclose(calculate_percentile(data, 0.0), 10.0, rel_tol=1e-5)
    # 100th percentile is 50.0
    assert math.isclose(calculate_percentile(data, 100.0), 50.0, rel_tol=1e-5)
    # 95th percentile: index = 4 * 0.95 = 3.8 -> 40*0.2 + 50*0.8 = 48.0
    assert math.isclose(calculate_percentile(data, 95.0), 48.0, rel_tol=1e-5)


def test_compute_probe_statistics_all_success():
    probes = [
        {"status": "SUCCESS", "rtt_ms": 10.0, "send_time": 100.0, "recv_time": 100.010, "is_duplicate": False, "is_out_of_order": False, "est_forward_delay_ms": 5.0, "est_reverse_delay_ms": 5.0},
        {"status": "SUCCESS", "rtt_ms": 20.0, "send_time": 100.1, "recv_time": 100.120, "is_duplicate": False, "is_out_of_order": False, "est_forward_delay_ms": 10.0, "est_reverse_delay_ms": 10.0},
        {"status": "SUCCESS", "rtt_ms": 30.0, "send_time": 100.2, "recv_time": 100.230, "is_duplicate": False, "is_out_of_order": False, "est_forward_delay_ms": 15.0, "est_reverse_delay_ms": 15.0},
    ]
    stats = compute_probe_statistics(probes, sent_count=3)

    assert stats["sent"] == 3
    assert stats["received"] == 3
    assert stats["lost"] == 0
    assert stats["packet_loss_percent"] == 0.0
    assert stats["min_rtt_ms"] == 10.0
    assert stats["max_rtt_ms"] == 30.0
    assert stats["mean_rtt_ms"] == 20.0
    assert stats["median_rtt_ms"] == 20.0
    assert stats["duplicates"] == 0
    assert stats["out_of_order"] == 0
    assert stats["stddev_rtt_ms"] == 10.0


def test_compute_probe_statistics_with_loss_and_anomalies():
    probes = [
        {"status": "SUCCESS", "rtt_ms": 12.0, "send_time": 1.0, "recv_time": 1.012, "is_duplicate": False, "is_out_of_order": False, "est_forward_delay_ms": 6.0, "est_reverse_delay_ms": 6.0},
        {"status": "TIMEOUT", "rtt_ms": None, "send_time": 1.1, "recv_time": None, "is_duplicate": False, "is_out_of_order": False, "est_forward_delay_ms": None, "est_reverse_delay_ms": None},
        {"status": "SUCCESS", "rtt_ms": 14.0, "send_time": 1.2, "recv_time": 1.214, "is_duplicate": True, "is_out_of_order": True, "est_forward_delay_ms": 7.0, "est_reverse_delay_ms": 7.0},
        {"status": "TIMEOUT", "rtt_ms": None, "send_time": 1.3, "recv_time": None, "is_duplicate": False, "is_out_of_order": False, "est_forward_delay_ms": None, "est_reverse_delay_ms": None},
    ]
    stats = compute_probe_statistics(probes, sent_count=4)

    assert stats["sent"] == 4
    assert stats["received"] == 2
    assert stats["lost"] == 2
    assert stats["packet_loss_percent"] == 50.0
    assert stats["duplicates"] == 1
    assert stats["out_of_order"] == 1
    assert stats["min_rtt_ms"] == 12.0
    assert stats["max_rtt_ms"] == 14.0


def test_compute_probe_statistics_100_percent_loss():
    probes = [
        {"status": "TIMEOUT", "rtt_ms": None, "send_time": 1.0, "recv_time": None, "is_duplicate": False, "is_out_of_order": False},
        {"status": "TIMEOUT", "rtt_ms": None, "send_time": 2.0, "recv_time": None, "is_duplicate": False, "is_out_of_order": False},
    ]
    stats = compute_probe_statistics(probes, sent_count=2)

    assert stats["sent"] == 2
    assert stats["received"] == 0
    assert stats["lost"] == 2
    assert stats["packet_loss_percent"] == 100.0
    assert stats["min_rtt_ms"] is None
    assert stats["rfc3550_jitter_ms"] is None


def test_rfc3550_jitter_smoothing_formula():
    # Check RFC 3550 formula step-by-step
    # J = J + (|D| - J) / 16.0
    # Probe 1: RTT = 10ms (transit = 0.010)
    # Probe 2: RTT = 26ms (transit = 0.026) -> |D| = 16ms
    # J = 0 + (16 - 0)/16 = 1.0 ms
    probes = [
        {"status": "SUCCESS", "rtt_ms": 10.0, "send_time": 1.0, "recv_time": 1.010, "is_duplicate": False, "is_out_of_order": False},
        {"status": "SUCCESS", "rtt_ms": 26.0, "send_time": 2.0, "recv_time": 2.026, "is_duplicate": False, "is_out_of_order": False},
    ]
    stats = compute_probe_statistics(probes, sent_count=2)
    assert math.isclose(stats["rfc3550_jitter_ms"], 1.0, rel_tol=1e-3)
