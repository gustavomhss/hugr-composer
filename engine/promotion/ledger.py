"""Human-facing Markdown ledger — skill shim over hugr_core.promotion.ledger.

The rendering lives in the shared core; this shim binds skill-001's ledger.json
/ LEDGER.md paths and preserves the ``render`` re-export + the ``python -m
engine.promotion.ledger`` CLI.
"""

from __future__ import annotations

from hugr_core.promotion.ledger import main as _core_main
from hugr_core.promotion.ledger import render

from engine.promotion.config import build_config

__all__ = ["render", "main"]


def main() -> int:
    return _core_main(build_config())


if __name__ == "__main__":
    raise SystemExit(main())
