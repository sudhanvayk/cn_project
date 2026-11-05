# Makefile for SDNScope - SDN Network Diagnostic and Path Analysis Suite
#
# Quick start:
#   make run     # set up the venv (first time) and run the full localhost demo
#   make help    # list every available target

.DEFAULT_GOAL := help
.PHONY: all help install setup venv run demo test lint format scenarios real-scenarios real-check clean

PYTHON      ?= python3
VENV        ?= .venv
PIP         := $(VENV)/bin/pip
PY_BIN      := $(VENV)/bin/python
PYTEST_BIN  := $(VENV)/bin/pytest
RUFF_BIN    := $(VENV)/bin/ruff
STAMP       := $(VENV)/.installed
REQ         := requirements.txt
REQ_DEV     := requirements-dev.txt

# Reinstall automatically whenever either requirements file changes.
$(STAMP): $(REQ) $(REQ_DEV) | $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(REQ) -r $(REQ_DEV)
	@touch $(STAMP)

$(VENV):
	@echo "[INFO] Creating virtual environment in $(VENV)..."
	@if $(PYTHON) -m venv $(VENV); then \
		echo "[INFO] venv created."; \
	else \
		echo "[WARN] ensurepip unavailable; creating venv without pip and bootstrapping from system pip."; \
		rm -rf $(VENV); \
		$(PYTHON) -m venv --without-pip $(VENV); \
		$(PYTHON) -m pip --python $(VENV)/bin/python install --upgrade pip; \
	fi

.PHONY: venv
venv: $(VENV) ## Create the project virtualenv only

.PHONY: install setup
install setup: $(STAMP) ## Create the venv and install all dependencies

all: install run ## Install dependencies and run the localhost demo

run: install demo ## One command: install dependencies, then run the full demo

demo: install ## Run the full localhost demonstration (no Mininet required)
	./scripts/demo_localhost.sh

test: install ## Run the pytest suite with coverage
	$(PYTEST_BIN) --cov=. --cov-report=term-missing tests/

lint: install ## Run ruff static analysis
	$(RUFF_BIN) check .

format: install ## Auto-format the code with ruff
	$(RUFF_BIN) format .

scenarios real-scenarios: install ## Run all live Mininet + Ryu scenarios (needs sudo)
	./scripts/run_all_scenarios.sh

real-check: install ## Verify sudo, tools, ports, and run pre-flight gates
	./scripts/preflight_check.sh

clean: ## Remove caches, coverage data, and the local demo artifacts
	rm -rf .pytest_cache .coverage htmlcov results/demo_localhost
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

help: ## Show this help message
	@echo "SDNScope - available make targets:"
	@echo "  make run              Install dependencies, then run the full localhost demo"
	@echo "  make all              Same as 'make run'"
	@echo "  make install          Create .venv and install requirements"
	@echo "  make venv             Create the project virtualenv only"
	@echo "  make demo             Run the localhost demo (no Mininet required)"
	@echo "  make test             Run the pytest suite with coverage"
	@echo "  make lint             Run ruff static analysis"
	@echo "  make format           Auto-format the code with ruff"
	@echo "  make real-check       Verify sudo, tools, ports, and pre-flight gates"
	@echo "  make real-scenarios   Run all live Mininet + Ryu scenarios (needs sudo)"
	@echo "  make scenarios        Alias for 'make real-scenarios'"
	@echo "  make clean            Remove caches, coverage data, and demo artifacts"
	@echo "  make help             Show this help message"
	@echo ""
	@echo "First time? Run 'make run' for the self-contained localhost demo."
	@echo "Live testbed? Run 'make real-check' then 'make real-scenarios'."

.PHONY: validate
validate: ## Run lint, tests and the localhost demo with a pass/fail summary
	bash scripts/validate.sh
