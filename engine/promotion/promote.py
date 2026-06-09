"""Execute an approved promotion verdict — atomic, rollback on failure.

Usage:
    python -m engine.promotion.promote --from-ledger NAME [--dry-run]
    python -m engine.promotion.promote --delete NAME [--dry-run]

Thin per-skill shim over :mod:`hugr_core.promotion.promote` (M2.5 lift): the
generic, vocabulary- and path-free executor lives in core; this module binds
this skill's :class:`PromotionConfig` (via :func:`build_config`) on every call
and keeps the ``python -m`` CLI (``main()`` / argparse) skill-side.

Invariants:
    - Refuses to promote unless the ledger entry carries an actionable
      verdict (PROMOTE_AS_ADAPTER or PROMOTE_AS_PRIMITIVE) AND has zero
      blockers. FILL_AND_PROMOTE is reclassify-only: the contributor must
      fill the shell, re-run `engine.promotion.classify`, and let that
      flip the verdict to PROMOTE_AS_PRIMITIVE before the executor will
      touch it. The executor never writes through an incomplete shell.
    - Lite-tier promotions (PROMOTE_AS_PRIMITIVE with registry
      `tier: "lite"`) require the ratification token "§B1.8 ratified"
      in CONTRACT.md §E. Without it, the executor refuses (§A12 intact).
    - Every action is fully reversible: a pre-flight copy of the
      affected trees is written to a temp dir; on any failure, the
      original state is restored.
    - Contract must stay green. A post-flight contract_check failure
      triggers automatic rollback.
    - Every promotion is one atomic commit — never batched.
"""

from __future__ import annotations

import argparse

from hugr_core.promotion.promote import (
    PromotionPlan,
    _resolve_match,
)
from hugr_core.promotion.promote import (
    execute as _core_execute,
)
from hugr_core.promotion.promote import (
    execute_delete as _core_execute_delete,
)
from hugr_core.promotion.promote import (
    plan as _core_plan,
)

from engine.promotion.config import build_config

__all__ = [
    "PromotionPlan",
    "plan",
    "execute",
    "execute_delete",
    "_resolve_match",
    "main",
]


def plan(name: str, is_quarantined: bool | None = None) -> PromotionPlan:
    """Load ledger, validate, and return a concrete promotion plan."""
    return _core_plan(build_config(), name, is_quarantined=is_quarantined)


def execute(
    name: str,
    *,
    dry_run: bool = False,
    is_quarantined: bool | None = None,
) -> int:
    """Execute the promotion — with automatic rollback on any failure."""
    return _core_execute(build_config(), name, dry_run=dry_run, is_quarantined=is_quarantined)


def execute_delete(
    name: str,
    *,
    dry_run: bool = False,
    is_quarantined: bool | None = None,
) -> int:
    """Remove a staged primitive marked REDUNDANT in the ledger."""
    return _core_execute_delete(
        build_config(), name, dry_run=dry_run, is_quarantined=is_quarantined
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Execute an approved ledger entry (promote or delete)."
    )
    ap.add_argument("--from-ledger", metavar="NAME", help="Promote primitive NAME.")
    ap.add_argument("--delete", metavar="NAME", help="Delete staged primitive NAME.")
    ap.add_argument("--dry-run", action="store_true")
    # Disambiguators for primitives that appear in BOTH the staged
    # namespace folder AND the _quarantine/ folder (same name, two
    # locations). Without one of these flags, the executor refuses to
    # pick — explicit is better than implicit.
    group = ap.add_mutually_exclusive_group()
    group.add_argument(
        "--staged",
        action="store_true",
        help="Target the copy under _staging/<ns>/, not _quarantine/.",
    )
    group.add_argument(
        "--quarantined",
        action="store_true",
        help="Target the copy under _staging/_quarantine/.",
    )
    args = ap.parse_args()

    if args.from_ledger and args.delete:
        ap.error("Specify either --from-ledger or --delete, not both.")
    if not args.from_ledger and not args.delete:
        ap.error("Specify one of --from-ledger or --delete.")

    is_q: bool | None = None
    if args.quarantined:
        is_q = True
    elif args.staged:
        is_q = False

    if args.from_ledger:
        return execute(args.from_ledger, dry_run=args.dry_run, is_quarantined=is_q)
    return execute_delete(args.delete, dry_run=args.dry_run, is_quarantined=is_q)


if __name__ == "__main__":
    raise SystemExit(main())
