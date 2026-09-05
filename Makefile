.DEFAULT_GOAL := help

# Resolve tools through the active interpreter so every target works whether or
# not a virtualenv is activated. Override with `make PY=/path/to/python`.
PY ?= $(shell command -v python3 2>/dev/null || command -v python)
# Absolute, so targets that cd into a subdirectory still resolve the interpreter.
PYABS := $(abspath $(PY))
RUN := $(PYABS) -m

.PHONY: help install lint format typecheck test test-fast cov check demo clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	 awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras
	$(RUN) pip install -e ".[dev]"

lint: ## Run ruff
	$(RUN) ruff check src tests

format: ## Auto-fix lint issues
	$(RUN) ruff check --fix src tests

typecheck: ## Run mypy in strict mode
	$(RUN) mypy

test: ## Run the full test suite
	$(RUN) pytest

test-fast: ## Run everything except subprocess-heavy tests
	$(RUN) pytest -m "not slow"

cov: ## Run tests with a coverage report
	$(RUN) pytest --cov --cov-report=term-missing

check: lint typecheck test ## Lint, typecheck and test

demo: ## Run the flagship example end to end
	@$(RUN) astraforge --version >/dev/null 2>&1 || { \
	  echo "astraforge is not importable by $(PY)."; \
	  echo "Run 'make install' first, or set PY=/path/to/venv/bin/python."; \
	  exit 1; }
	@rm -rf .demo && mkdir -p .demo
	cd .demo && $(RUN) astraforge init . >/dev/null && \
	 $(RUN) astraforge run "Fix the failing statistics module" \
	   --plan ../examples/software_engineering/plan.yaml -y
	@echo ""
	@echo "Inspect it with:  cd .demo && astraforge inspect latest"

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov \
	       dist build .demo *.egg-info src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
