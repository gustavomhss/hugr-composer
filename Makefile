# HuGR Arsenal — single entrypoint for the local loop.
# See docs/contributing.md for the tiered model.

SHELL := /bin/bash
KIT := skills/SKILL-001-fastapi-production
PY := $(KIT)/.venv/bin/python

.PHONY: help verify verify-tier0 verify-tier1 verify-tier2 lint fmt checks clean install

help:
	@echo "Targets:"
	@echo "  make verify         # auto-tier from git diff (recommended)"
	@echo "  make verify-tier0   # touched tools only (~30s)"
	@echo "  make verify-tier1   # composition gates (~5min)"
	@echo "  make verify-tier2   # full unit suite + composition (~6min)"
	@echo "  make lint           # ruff lint + format check + repo checks"
	@echo "  make fmt            # ruff format (writes)"
	@echo "  make checks         # the 3 local repo-rule checks (scan mode)"
	@echo "  make clean          # remove caches + scratch tempdirs"
	@echo "  make install        # pre-commit + venv prep hints"

verify:
	@$(KIT)/scripts/verify.sh

verify-tier0:
	@$(KIT)/scripts/verify.sh tier0

verify-tier1:
	@$(KIT)/scripts/verify.sh tier1

verify-tier2:
	@$(KIT)/scripts/verify.sh tier2

lint:
	@$(PY) -m ruff check $(KIT) hugr_auth scripts
	@$(PY) -m ruff format --check $(KIT) hugr_auth scripts
	@$(MAKE) -s checks

fmt:
	@$(PY) -m ruff check --fix $(KIT) hugr_auth scripts
	@$(PY) -m ruff format $(KIT) hugr_auth scripts

checks:
	@python3 scripts/checks/no_committed_venv.py
	@python3 scripts/checks/md_location.py
	@python3 scripts/checks/file_size.py

clean:
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ caches cleaned"

install:
	@echo "1) pre-commit install        # local hygiene"
	@echo "2) (kit venv)  python3.12 -m venv $(KIT)/.venv && \\"
	@echo "                $(PY) -m pip install -r $(KIT)/requirements-mcp.txt"
	@echo "3) start local Postgres on :5432 (user/pass/db = skill/skill/skill_e2e)"
