#!/usr/bin/env bash
# Run all three diagnostic scenarios automatically and generate full reports
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if [ -f "$ROOT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python3"
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
RUN_DIR="results/$TIMESTAMP"
mkdir -p "$RUN_DIR"

echo "======================================================================"
echo "          AUTOMATED EXECUTION OF ALL 3 SDN DIAGNOSTIC SCENARIOS       "
echo "======================================================================"
echo " Results Directory: $RUN_DIR"
echo "----------------------------------------------------------------------"

# 1. Healthy
echo -e "\n>>> EXECUTING SCENARIO A: HEALTHY PATH <<<"
"$SCRIPT_DIR/scenario_healthy.sh" "$RUN_DIR/scenario_healthy"

# 2. Degraded
echo -e "\n>>> EXECUTING SCENARIO B: DEGRADED / CONGESTED PATH <<<"
"$SCRIPT_DIR/scenario_degraded.sh" "$RUN_DIR/scenario_degraded"

# 3. Failed
echo -e "\n>>> EXECUTING SCENARIO C: FAILED PATH & REROUTE <<<"
"$SCRIPT_DIR/scenario_failed.sh" "$RUN_DIR/scenario_failed"

# 4. Generate Comprehensive Report from Degraded or Latest Result
echo -e "\n>>> GENERATING EXECUTIVE REPORT (MARKDOWN, HTML, CHARTS) <<<"
$PYTHON_BIN report_generator.py \
    -r "$RUN_DIR/scenario_degraded/correlation_report.json" \
    -d "$RUN_DIR/scenario_degraded/diagnostic_result.json" \
    -m "$RUN_DIR/report.md" \
    -H "$RUN_DIR/report.html" \
    --dir "$RUN_DIR"

# Link as latest
rm -f results/latest
ln -sf "$TIMESTAMP" results/latest

echo "======================================================================"
echo " All scenarios executed successfully!"
echo " Reports available at:"
echo "   - Markdown: $RUN_DIR/report.md"
echo "   - HTML:     $RUN_DIR/report.html"
echo "   - Charts:   $RUN_DIR/rtt_timeseries.png"
echo "======================================================================"
