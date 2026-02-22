PYTHON      ?= python3.11
VENV        := backend/venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
MANAGE      := $(PY) backend/manage.py

# ── Setup ─────────────────────────────────────────────────────────────────────

.PHONY: install
install: $(VENV)/bin/activate   ## Create venv and install all dependencies
	@echo "✓ Dependencies installed. Run 'make migrate' next."

$(VENV)/bin/activate: backend/requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip -q
	$(PIP) install -r backend/requirements.txt
	mkdir -p backend/data backend/media backend/staticfiles
	touch $@

.PHONY: migrate
migrate:   ## Apply database migrations
	$(MANAGE) migrate

.PHONY: setup
setup: install migrate   ## Full first-time setup (venv + deps + migrations)

# ── Development ───────────────────────────────────────────────────────────────

.PHONY: run
run:   ## Start the development server at http://localhost:8000
	$(MANAGE) runserver

# ── Tests ─────────────────────────────────────────────────────────────────────

.PHONY: test
test:   ## Run the entire test suite
	$(MANAGE) test files

.PHONY: test-module
test-module:   ## Run one test module  e.g. make test-module MOD=test_repository
	$(MANAGE) test files.tests.$(MOD)

.PHONY: test-class
test-class:   ## Run one test class  e.g. make test-class CLS=test_repository.CreateFileTests
	$(MANAGE) test files.tests.$(CLS)

.PHONY: test-method
test-method:   ## Run one test method  e.g. make test-method M=test_repository.CreateFileTests.test_accepts_zero_size
	$(MANAGE) test files.tests.$(M)

# ── Docker ────────────────────────────────────────────────────────────────────

.PHONY: docker-up
docker-up:   ## Build and start via Docker Compose
	docker-compose up --build

# ── Utilities ─────────────────────────────────────────────────────────────────

.PHONY: clean
clean:   ## Remove venv, compiled files, and runtime artefacts
	rm -rf $(VENV) backend/data/*.sqlite3 backend/staticfiles
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

.PHONY: check
check:   ## Run Django system checks
	$(MANAGE) check

.PHONY: help
help:   ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
