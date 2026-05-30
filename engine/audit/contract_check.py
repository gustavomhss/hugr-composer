#!/usr/bin/env python3
"""CONTRACT.md machine enforcer (facade).

Implementation moved to ``engine.audit.contract_rules`` (split per WP-16).
This module preserves the historic public surface:

    python -m engine.audit.contract_check              # run all
    python -m engine.audit.contract_check --item B1.1  # one item
    python -m engine.audit.contract_check --phase 0    # whole phase
    from engine.audit.contract_check import main, RULES
"""

from __future__ import annotations

import sys

from engine.audit.contract_rules import RULES, main
from engine.audit.contract_rules._common import REPO_ROOT, SKILL_ROOT
from engine.audit.contract_rules.phase0_identity import _r_agent_memory_pointer

__all__ = ["RULES", "REPO_ROOT", "SKILL_ROOT", "_r_agent_memory_pointer", "main"]

if __name__ == "__main__":
    sys.exit(main())
