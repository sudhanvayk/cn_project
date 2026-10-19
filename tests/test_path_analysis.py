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
