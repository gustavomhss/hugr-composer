"""CONTRACT.md machine enforcer — implementation package.

Public re-export: ``RULES`` + ``main`` from ``_registry``. The
historic public surface remains ``engine.audit.contract_check`` (the
facade in the parent ``engine/audit/`` package); this package is the
new implementation home per WP-16.
"""

from ._registry import RULES, main

__all__ = ["RULES", "main"]
