# Makefile for SDN Network Diagnostic and Path Analysis Suite

.PHONY: all test lint format demo scenarios clean help real-check

PYTHON ?= python3
VENV ?= .venv

ifeq ($(wildcard $(VENV)/bin/python3),)
    PY_BIN = $(PYTHON)
    PYTEST_BIN = pytest
    RUFF_BIN = ruff
else
    PY_BIN = $(VENV)/bin/python3
    PYTEST_BIN = $(VENV)/bin/pytest
    RUFF_BIN = $(VENV)/bin/ruff
endif

help:
	@echo "Available commands:"
	@echo "  make test       - Execute full pytest test suite with coverage report"
	@echo "  make lint       - Run ruff static code analysis and linter"
	@echo "  make format     - Automatically format code using ruff"
	@echo "  make demo       - Execute standalone localhost demonstration (no Mininet required)"
	@echo "  make scenarios  - Automatically run all 3 SDN scenarios (healthy, degraded, failed)"
	@echo "  make real-check - Verify sudo, tools, ports, and pre-flight gates for real Mininet"
	@echo "  make clean      - Remove build artifacts, pycache, and coverage databases"

test:
	$(PYTEST_BIN) --cov=. --cov-report=term-missing tests/

lint:
	$(RUFF_BIN) check .

format:
	$(RUFF_BIN) format .

demo:
	./scripts/demo_localhost.sh

scenarios:
	./scripts/run_all_scenarios.sh

real-check:
	./scripts/preflight_check.sh

clean:
	rm -rf .pytest_cache .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
