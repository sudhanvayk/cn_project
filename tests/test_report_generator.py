"""
Unit tests for report_generator.py
"""

import os
import tempfile

from report_generator import (
    generate_ascii_path_diagram,
    generate_charts,
    generate_html_report,
    generate_markdown_report,
)


def test_generate_ascii_path_diagram():
    active = ["h1", "s1", "s2", "h2"]
    suspects = [{"link": ["s1", "s2"], "link_str": "s1 <-> s2", "confidence": 0.95}]
    backup = ["h1", "s1", "s3", "s2", "h2"]

    diagram = generate_ascii_path_diagram(active, suspects, backup)
    assert "h1 -> s1 -> s2 -> h2" in diagram
    assert "s1 <-> s2" in diagram
    assert "h1 -> s1 -> s3 -> s2 -> h2" in diagram


def test_generate_markdown_and_html_report():
    report_data = {
        "path_status": "DEGRADED_PATH",
        "source_node": "h1",
        "destination_node": "h2",
        "destination_ip": "10.0.0.2",
        "timestamp": "2026-10-19T22:00:00Z",
        "detailed_metrics": {
            "probes_sent": 10,
            "probes_received": 9,
            "packet_loss_pct": 10.0,
            "min_rtt_ms": 61.2,
            "avg_rtt_ms": 64.5,
            "max_rtt_ms": 70.1,
            "median_rtt_ms": 63.8,
            "p95_rtt_ms": 69.5,
            "rfc3550_jitter_ms": 2.1,
            "stddev_jitter_ms": 2.8,
        },
        "active_path": {
            "path": ["h1", "s1", "s2", "h2"],
            "hop_count": 3,
            "path_source": "flow_table",
        },
        "suspected_links": [
            {
                "link": ["s1", "s2"],
                "link_str": "s1 <-> s2",
                "confidence": 0.85,
                "reasons": ["Core link with 10% packet drop"],
            }
        ],
        "ranked_backup_paths": [
            {
                "rank": 1,
                "path": ["h1", "s1", "s3", "s2", "h2"],
                "path_str": "h1 -> s1 -> s3 -> s2 -> h2",
                "hop_count": 4,
                "status": "OPERATIONAL",
                "has_suspect_link": False,
            }
        ],
        "recommended_backup_path": {
            "rank": 1,
            "path": ["h1", "s1", "s3", "s2", "h2"],
            "path_str": "h1 -> s1 -> s3 -> s2 -> h2",
            "hop_count": 4,
        },
    }

    diag_data = {
        "target_ip": "10.0.0.2",
        "probes": [
            {"seq": 1, "status": "SUCCESS", "rtt_ms": 62.0},
            {"seq": 2, "status": "SUCCESS", "rtt_ms": 65.0},
            {"seq": 3, "status": "LOST", "rtt_ms": None},
        ],
    }

    md = generate_markdown_report(report_data, diag_data)
    assert "# SDN Network Diagnostic and Path Analysis Report" in md
    assert "DEGRADED_PATH" in md
    assert "s1 <-> s2" in md
    assert "h1 -> s1 -> s3 -> s2 -> h2" in md

    html = generate_html_report(md)
    assert "<!DOCTYPE html>" in html
    assert "SDN Diagnostic Report" in html
    assert "DEGRADED_PATH" in html
    assert "s1 <-> s2" in html


def test_generate_charts():
    diag_data = {
        "target_ip": "10.0.0.2",
        "probes": [
            {"seq": 1, "status": "SUCCESS", "rtt_ms": 10.0},
            {"seq": 2, "status": "SUCCESS", "rtt_ms": 12.0},
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        chart_path = generate_charts(diag_data, tmpdir)
        if chart_path:
            assert os.path.exists(chart_path)
