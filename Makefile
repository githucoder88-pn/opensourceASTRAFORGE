.DEFAULT_GOAL := help
PY ?= python

.PHONY: help install lint format typecheck test test-fast cov check demo clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	 awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev extras
	$(PY) -m pip install -e ".[dev]"

lint: ## Run ruff
	ruff check src tests

format: ## Auto-fix lint issues
	ruff check --fix src tests

typecheck: ## Run mypy in strict mode
	mypy

test: ## Run the full test suite
	pytest

test-fast: ## Run everything except subprocess-heavy tests
	pytest -m "not slow"

cov: ## Run tests with a coverage report
	pytest --cov --cov-report=term-missing

check: lint typecheck test ## Lint, typecheck and test

demo: ## Run the flagship example end to end
	@rm -rf .demo && mkdir -p .demo
	cd .demo && astraforge init . >/dev/null && \
	 astraforge run "Fix the failing statistics module" \
	   --plan ../examples/software_engineering/plan.yaml -y
	@echo "\nInspect it with:  cd .demo && astraforge inspect latest"

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov \
	       dist build .demo *.egg-info src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
