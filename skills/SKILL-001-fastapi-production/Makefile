SKILL_ROOT := $(shell pwd)
PYTHON     := PYTHONPATH=$(SKILL_ROOT) python3
AUDIT_DIR  := $(SKILL_ROOT)/audit

.PHONY: help test audit audit-l1 audit-l2 audit-security audit-quality e2e clean

help:  ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

test:  ## Run all 1020+ adapt tool tests
	@echo "==> Running all adapt tool tests …"
	@$(PYTHON) $(AUDIT_DIR)/audit_l1.py --tests-only
	@echo "==> Done."

audit-l1:  ## L1 correctness, parse+tests+orchestrator smoke
	@echo "==> L1 Correctness audit …"
	@$(PYTHON) $(AUDIT_DIR)/audit_l1.py

audit-l2:  ## L2 brutal, coverage ratio+long fns+stub detection
	@echo "==> L2 Brutal audit …"
	@$(PYTHON) $(AUDIT_DIR)/audit_l2.py

audit-security:  ## Security audit, secret detection+env+gitignore
	@echo "==> Security audit …"
	@$(PYTHON) $(AUDIT_DIR)/audit_security.py

audit-quality:  ## Code quality, docstrings+duplicates+function size
	@echo "==> Quality audit …"
	@$(PYTHON) $(AUDIT_DIR)/audit_quality.py

audit:  ## Run full audit (L1+L2+security+quality+e2e)
	@echo "==> Full audit — all layers …"
	@$(PYTHON) $(AUDIT_DIR)/audit_everything.py

e2e:  ## Full E2E chain (generate+adapt tools+validate)
	@echo "==> E2E chain …"
	@$(PYTHON) $(AUDIT_DIR)/audit_everything.py --e2e-only

clean:  ## Clean temp files and __pycache__
	@echo "==> Cleaning …"
	@find $(SKILL_ROOT) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find $(SKILL_ROOT) -name "*.pyc" -delete 2>/dev/null || true
	@find $(SKILL_ROOT) -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf /tmp/_skill001_audit_* 2>/dev/null || true
	@echo "==> Clean done."
