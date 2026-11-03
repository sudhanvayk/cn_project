#!/usr/bin/env bash
# One-command validation for evaluators: lint + tests + localhost demo.
set -u
cd "$(dirname "$0")/.."

fail=0
run() {
  local label="$1"; shift
  echo "=== $label"
  if "$@" > /tmp/validate_$$.log 2>&1; then
    echo "PASS: $label"
  else
    echo "FAIL: $label"
    tail -20 /tmp/validate_$$.log
    fail=1
  fi
}

run "Static analysis (ruff)" make lint
run "Test suite (pytest)"    make test
run "Localhost demonstration" make demo
rm -f /tmp/validate_$$.log

echo "----------------------------------------"
if [ $fail -eq 0 ]; then
  echo "ALL CHECKS PASSED"
  exit 0
else
  echo "SOME CHECKS FAILED"
  exit 1
fi
