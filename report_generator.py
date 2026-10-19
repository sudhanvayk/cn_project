#!/usr/bin/env python3
"""
Diagnostic and Path Analysis Report Generator
Part of the Socket-Based Network Diagnostic and Path Analysis Tool for SDN.

Generates comprehensive human-readable Markdown (report.md) and styled
HTML (report.html) reports from correlation reports and diagnostic results.
Optionally generates latency time-series PNG charts via matplotlib.
"""

import argparse
import json
import logging
import os
import sys
import time

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def setup_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("report_generator")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger


def generate_ascii_path_diagram(active_path: list, suspected_links: list, backup_path: list) -> str:
    """Generate high-clarity ASCII diagram illustrating active, degraded/failed, and backup routes."""
    active_str = " -> ".join(active_path) if active_path else "None"
    backup_str = " -> ".join(backup_path) if backup_path else "None"
    suspect_strs = [s.get("link_str", "") for s in suspected_links]

    diagram = f"""
+---------------------------------------------------------------------------------+
|                       SDN TOPOLOGY AND FORWARDING PATH MAP                      |
+---------------------------------------------------------------------------------+
|                                                                                 |
|  ACTIVE FORWARDING ROUTE:                                                       |
|    [ {active_str} ]                                                             |
|                                                                                 |
|  SUSPECTED BROKEN/DEGRADED LINKS:                                               |
|    {', '.join(suspect_strs) if suspect_strs else 'None (All path links operational)'}
|                                                                                 |
|  RECOMMENDED FAILOVER BACKUP ROUTE:                                             |
|    [ {backup_str} ]                                                             |
|                                                                                 |
+---------------------------------------------------------------------------------+
"""
    return diagram.strip()


def generate_charts(diag_data: dict, output_dir: str) -> str:
    """Generate RTT time-series plot if matplotlib is available."""
    if not HAS_MATPLOTLIB:
        return None

    probes = diag_data.get("probes", [])
    if not probes:
        return None

    seqs = [p.get("seq", idx) for idx, p in enumerate(probes, 1)]
    rtts = [p.get("rtt_ms") if p.get("status") == "SUCCESS" else 0.0 for p in probes]

    os.makedirs(output_dir, exist_ok=True)
    chart_path = os.path.join(output_dir, "rtt_timeseries.png")

    plt.figure(figsize=(9, 4.5))
    plt.plot(seqs, rtts, marker="o", color="#1f77b4", linewidth=2, label="Probe RTT (ms)")
    plt.axhline(y=50.0, color="r", linestyle="--", label="Degraded RTT Threshold (50ms)")
    plt.title(f"UDP Probe Round-Trip Time Time-Series to {diag_data.get('target_ip')}")
    plt.xlabel("Probe Sequence Number")
    plt.ylabel("RTT (ms)")
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(chart_path, dpi=150)
    plt.close()

    return chart_path


def generate_markdown_report(report_data: dict, diag_data: dict = None, chart_file: str = None) -> str:
    """Render full markdown analysis document."""
    status = report_data.get("path_status", "UNKNOWN")
    src = report_data.get("source_node", "h1")
    dst = report_data.get("destination_node", "h2")
    dst_ip = report_data.get("destination_ip", "10.0.0.2")
    metrics = report_data.get("detailed_metrics", {})
    active = report_data.get("active_path", {})
    suspects = report_data.get("suspected_links", [])
    backups = report_data.get("ranked_backup_paths", [])
    rec_backup = report_data.get("recommended_backup_path")

    status_badge = "🟩 **HEALTHY**" if status == "HEALTHY_PATH" else ("🟨 **DEGRADED**" if status == "DEGRADED_PATH" else "🟥 **FAILED**")

    md = f"""# SDN Network Diagnostic and Path Analysis Report

**Timestamp:** `{report_data.get('timestamp')}`  
**Overall Path Health:** {status_badge} (`{status}`)  
**Endpoint Target:** `{src}` -> `{dst}` (`{dst_ip}`)  
**Path Identification Method:** `{active.get('source', 'unknown').upper()}`  

---

## 1. Executive Summary & Diagnostic Notice

> **Primary Path Status:** `{status}`  
> **Diagnostic Finding:** {report_data.get('failed_path_reason')}

### Active Forwarding Route
`{active.get('path_str')}` ({active.get('hop_count')} hops)

```
{generate_ascii_path_diagram(active.get('path', []), suspects, rec_backup.get('path', []) if rec_backup else [])}
```

---

## 2. Quantitative Performance Telemetry

| Performance Metric | Measured Value | Nominal / Threshold Baseline | Health Evaluation |
|---|---|---|---|
| **Probes Sent / Received** | `{metrics.get('probes_sent')}` sent / `{metrics.get('probes_received')}` received | `{metrics.get('probes_sent')}` / `{metrics.get('probes_sent')}` | {'OK' if metrics.get('probes_lost') == 0 else 'Drops Detected'} |
| **Packet Loss Rate** | `{metrics.get('packet_loss_percentage', 0.0):.2f}%` | `<= 0.0%` (Fail: `>= 50.0%`) | {'Normal' if metrics.get('packet_loss_percentage', 0.0) == 0 else 'Threshold Exceeded'} |
| **Mean RTT** | `{metrics.get('mean_rtt_ms', 0.0):.2f} ms` | `<= 50.0 ms` | {'Normal' if (metrics.get('mean_rtt_ms') or 0.0) <= 50.0 else 'High Latency'} |
| **Minimum / Maximum RTT** | `{metrics.get('min_rtt_ms', 0.0):.2f} ms` / `{metrics.get('max_rtt_ms', 0.0):.2f} ms` | N/A | Range Spread |
| **Median RTT** | `{metrics.get('median_rtt_ms', 0.0):.2f} ms` | N/A | Central Tendency |
| **95th Percentile RTT (p95)** | `{metrics.get('p95_rtt_ms', 0.0):.2f} ms` | N/A | Tail Latency Indicator |
| **Standard Deviation Jitter** | `{metrics.get('stddev_rtt_ms', 0.0):.2f} ms` | Low variation | Sample Deviation |
| **RFC 3550 Inter-Arrival Jitter** | `{metrics.get('rfc3550_jitter_ms', 0.0):.2f} ms` | Smoothed $J = J + (|D|-J)/16$ | Statistical Standard |

"""
    if chart_file and os.path.exists(chart_file):
        md += f"\n### RTT Time-Series Chart\n![RTT Time-Series Chart]({chart_file})\n"

    md += """
---

## 3. Failure Localization & Evidence Sources

"""
    if not suspects:
        md += "No links exhibited packet loss, port drop counters, or topology churn.\n"
    else:
        md += "| Rank | Suspected Link | Combined Confidence | Localization Evidence Sources |\n"
        md += "|---|---|---|---|\n"
        for idx, s in enumerate(suspects, 1):
            md += f"| {idx} | `{s['link_str']}` | `{s['confidence']*100:.1f}%` | {'; '.join(s['evidence'])} |\n"

    md += """
---

## 4. Alternative Backup Routes & Failover Recommendation

"""
    if not backups:
        md += "No alternative routes available in current topology.\n"
    else:
        md += "| Rank | Route Status | Hop Count | Hop Penalty | Forwarding Path Route |\n"
        md += "|---|---|---|---|---|\n"
        for b in backups:
            md += f"| {b.get('rank')} | `{b.get('status')}` | {b.get('hop_count')} | +{b.get('extra_hops')} | `{b.get('path_str')}` |\n"

    if rec_backup:
        md += f"""
### Actionable Rerouting Recommendation
> **Recommended Action:** Failover traffic to backup route **`{rec_backup['path_str']}`** (+{rec_backup['extra_hops']} extra hop penalty).  
> **Deployment Command:** `python3 sdnscope.py reroute --apply` (or `python3 reroute_helper.py --apply`)
"""
    return md


def generate_html_report(md_content: str, title: str = "SDN Diagnostic Report") -> str:
    """Wrap content in clean, modern CSS styled HTML page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #24292e; max-width: 960px; margin: 40px auto; padding: 0 20px; }}
  h1, h2, h3 {{ border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
  th, td {{ border: 1px solid #dfe2e5; padding: 8px 12px; text-align: left; }}
  th {{ background-color: #f6f8fa; font-weight: 600; }}
  tr:nth-child(even) {{ background-color: #fbfbfb; }}
  pre {{ background-color: #f6f8fa; padding: 16px; border-radius: 6px; overflow-x: auto; font-family: "SFMono-Regular", Consolas, monospace; font-size: 85%; }}
  code {{ background-color: rgba(27,31,35,0.05); padding: 0.2em 0.4em; border-radius: 3px; font-family: monospace; }}
  blockquote {{ border-left: 4px solid #0366d6; color: #444; margin: 0; padding: 0 16px; background: #f1f8ff; }}
  img {{ max-width: 100%; height: auto; }}
</style>
</head>
<body>
<div id="content">
<pre style="white-space: pre-wrap; font-family: inherit;">
{md_content}
</pre>
</div>
</body>
</html>
"""
    return html


def build_report(report_file: str, diag_file: str, output_md: str = "report.md",
                 output_html: str = "report.html", output_dir: str = "results") -> tuple:
    """Build both Markdown and HTML report files."""
    with open(report_file, "r", encoding="utf-8") as f:
        report_data = json.load(f)

    diag_data = {}
    if os.path.exists(diag_file):
        with open(diag_file, "r", encoding="utf-8") as f:
            diag_data = json.load(f)

    chart_file = generate_charts(diag_data, output_dir)
    md_text = generate_markdown_report(report_data, diag_data, chart_file)
    html_text = generate_html_report(md_text)

    with open(output_md, "w", encoding="utf-8") as f:
        f.write(md_text)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_text)

    return output_md, output_html, chart_file


def main():
    parser = argparse.ArgumentParser(description="Generate Comprehensive Markdown and HTML SDN Diagnostic Reports.")
    parser.add_argument("-r", "--report", default="correlation_report.json", help="Correlation report JSON")
    parser.add_argument("-d", "--diag", default="diagnostic_result.json", help="Diagnostic results JSON")
    parser.add_argument("-m", "--md", default="report.md", help="Output Markdown filepath (default: report.md)")
    parser.add_argument("-H", "--html", default="report.html", help="Output HTML filepath (default: report.html)")
    parser.add_argument("--dir", default="results", help="Directory for charts and artifacts")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    md_out, html_out, chart = build_report(
        report_file=args.report,
        diag_file=args.diag,
        output_md=args.md,
        output_html=args.html,
        output_dir=args.dir
    )
    print(f"[SUCCESS] Markdown report generated: {md_out}")
    print(f"[SUCCESS] HTML report generated:     {html_out}")
    if chart:
        print(f"[SUCCESS] Telemetry chart saved:     {chart}")


if __name__ == "__main__":
    main()
