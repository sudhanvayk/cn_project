"""
Unit tests for path_analysis module: traceroute and tracepath parsing.
"""

from path_analysis import parse_tracepath_output, parse_traceroute_output


def test_parse_traceroute_output_nominal():
    sample = """
traceroute to 10.0.0.2 (10.0.0.2), 30 hops max, 60 byte packets
 1  192.168.1.1  1.234 ms  1.123 ms  1.050 ms
 2  * * *
 3  10.0.0.2  3.456 ms  3.234 ms  3.123 ms
"""
    hops = parse_traceroute_output(sample)
    assert len(hops) == 3

    assert hops[0]["hop"] == 1
    assert hops[0]["ip"] == "192.168.1.1"
    assert hops[0]["status"] == "REACHABLE"
    assert hops[0]["loss_percent"] == 0.0
    assert len(hops[0]["rtts_ms"]) == 3
    assert hops[0]["avg_rtt_ms"] == 1.136

    assert hops[1]["hop"] == 2
    assert hops[1]["ip"] == "*"
    assert hops[1]["status"] == "TIMEOUT"
    assert hops[1]["loss_percent"] == 100.0

    assert hops[2]["hop"] == 3
    assert hops[2]["ip"] == "10.0.0.2"
    assert hops[2]["status"] == "REACHABLE"
    assert hops[2]["loss_percent"] == 0.0


def test_parse_traceroute_partial_loss():
    sample = """
 1  10.0.1.1  2.100 ms  *  2.300 ms
"""
    hops = parse_traceroute_output(sample)
    assert len(hops) == 1
    assert hops[0]["ip"] == "10.0.1.1"
    assert len(hops[0]["rtts_ms"]) == 2
    # 1 star out of 3 probes = 33.3% loss
    assert hops[0]["loss_percent"] == 33.3


def test_parse_tracepath_output():
    sample = """
 1?: [LOCALHOST]     pmtu 1500
 1:  192.168.1.1                                           0.450ms
 2:  10.0.0.2                                              1.230ms reached
"""
    hops = parse_tracepath_output(sample)
    assert len(hops) == 2
    assert hops[0]["hop"] == 1
    assert hops[0]["ip"] == "192.168.1.1"
    assert hops[1]["hop"] == 2
    assert hops[1]["ip"] == "10.0.0.2"
    assert hops[1]["status"] == "REACHABLE"


from unittest.mock import MagicMock, patch

from path_analysis import run_path_analysis


@patch("path_analysis.run_socket_traceroute")
def test_run_path_analysis_hop1_reachable(mock_socket_trace):
    mock_socket_trace.return_value = [
        {
            "hop": 1,
            "ip": "10.0.0.2",
            "rtts_ms": [11.36, 11.20, 11.45],
            "avg_rtt_ms": 11.337,
            "min_rtt_ms": 11.20,
            "max_rtt_ms": 11.45,
            "loss_percent": 0.0,
            "status": "REACHABLE"
        }
    ]
    res = run_path_analysis("10.0.0.2", max_hops=5, try_raw_socket=True)
    assert res["status"] == "SUCCESS"
    assert res["hop_count"] == 1
    assert res["method"] == "native_raw_socket"
    assert res["hop_list"][0]["ip"] == "10.0.0.2"
    assert res["hop_list"][0]["status"] == "REACHABLE"
    assert "ICMP Port Unreachable" in res["sdn_note"]


@patch("path_analysis.shutil.which")
@patch("path_analysis.subprocess.run")
@patch("path_analysis.run_socket_traceroute")
def test_run_path_analysis_fallback_traceroute(mock_socket_trace, mock_subproc, mock_which):
    mock_socket_trace.side_effect = PermissionError("Need root")
    mock_which.side_effect = lambda cmd: "/usr/bin/traceroute" if cmd == "traceroute" else None

    proc = MagicMock()
    proc.stdout = " 1  10.0.0.2  10.500 ms  10.600 ms  10.400 ms\n"
    mock_subproc.return_value = proc

    res = run_path_analysis("10.0.0.2", max_hops=5, try_raw_socket=True)
    assert res["status"] == "SUCCESS"
    assert res["hop_count"] == 1
    assert res["method"] == "system_traceroute"
    assert res["hop_list"][0]["ip"] == "10.0.0.2"
