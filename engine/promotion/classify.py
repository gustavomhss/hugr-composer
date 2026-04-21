"""Classify every staged primitive into a verdict.

Decision tree (evaluated in order — first match wins):

1. `duplicate_of_registered` is set
       → DELETE (redundant with an already-registered primitive).
2. `is_quarantined` AND `forbidden_modules` non-empty AND quarantine
   reason is non-fixable (domain_coupled on framework modules)
       → DELETE (or KEEP_STAGED if the fix path is obvious).
3. `is_quarantined` with a fixable reason (e.g. REPLACE_ME-only)
       → KEEP_STAGED with reason.
4. No strong signal (TOOL_IMPORT / MODULE_REF / BENCHMARK_REF)
       → KEEP_STAGED with reason ("no registered caller yet —
         awaiting benchmark signal per §A12").
5. Strong signal + REPLACE_ME > 0 + invariants stubbed
       → NEEDS_REVIEW (caller exists but shell incomplete).
6. Strong signal + REPLACE_ME == 0 + eligibility fails (concurrency,
   mutable state, etc.) → PROMOTE_FULL.
7. Strong signal + REPLACE_ME == 0 + lite-eligible
       → PROMOTE_LITE (awaiting ratification of 0004-tier-lite).
8. Anything else → NEEDS_REVIEW.

Every verdict carries a `blockers` list: preconditions the executor must
see resolved before it runs. A non-empty blockers list means the verdict
is documentation, not an executable instruction.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from engine.promotion.schemas import (
    Ledger,
    LedgerEntry,
    Signal,
    SignalKind,
    StateFlags,
    Verdict,
)
from engine.promotion.signals import collect_signals, _load_catalog
from engine.promotion.state import (
    SKILL_ROOT,
    _registered_primitive_names,
    measure,
)

_CLASSIFIER_VERSION = "1.0"

_STRONG_KINDS = {
    SignalKind.TOOL_IMPORT,
    SignalKind.MODULE_REF,
    SignalKind.BENCHMARK_REF,
}


def _strong(signals: list[Signal]) -> list[Signal]:
    return [s for s in signals if s.kind in _STRONG_KINDS]


def _lite_eligible(state: StateFlags) -> bool:
    """All seven conditions from docs/decisions/0004-tier-lite.md §2.1."""
    return (
        state.replace_me_count == 0
        and not state.has_concurrency
        and not state.has_mutable_class_state
        and state.test_file_present
        and not state.invariants_stubbed
        and not state.duplicate_of_registered
        and not state.is_quarantined
    )


def _describe_blockers(state: StateFlags) -> list[str]:
    """Enumerate what would have to change before this primitive can ship."""
    out: list[str] = []
    if state.replace_me_count > 0:
        out.append(
            f"Resolve {state.replace_me_count} REPLACE_ME marker(s) across "
            "the primitive tree (invariant text, stub tests)."
        )
    if state.invariants_stubbed:
        out.append(
            "Implement the three invariant tests (confirms / prevents / "
            "under_failure) with real assertions."
        )
    if state.is_quarantined and state.forbidden_modules:
        mods = ", ".join(sorted(set(state.forbidden_modules)))
        out.append(
            f"Remove framework coupling: primitive imports {mods}; "
            "registered primitives may not import framework modules."
        )
    if state.has_concurrency and _tla_required_reason(state):
        out.append(
            "Concurrency present — full-tier promotion requires a .tla spec "
            "(no lite path for concurrent primitives)."
        )
    return out


def _tla_required_reason(state: StateFlags) -> bool:
    return state.has_concurrency or state.has_mutable_class_state


def _classify_single(
    state: StateFlags, signals: list[Signal]
) -> tuple[Verdict, str, str, str | None, str | None]:
    """Return (verdict, tier, rationale, staging_reason, delete_reason)."""
    strong = _strong(signals)

    # Rule 1: duplicate of a registered primitive.
    if state.duplicate_of_registered:
        return (
            Verdict.DELETE,
            "none",
            (
                f"Duplicate of registered primitive "
                f"`{state.duplicate_of_registered}`. Staged copy adds no "
                "value; registered canonical version already ships."
            ),
            None,
            (
                f"Redundant with core/venous/*/{state.duplicate_of_registered}/ "
                "(same name; registered version is canonical)."
            ),
        )

    # Rule 2a: quarantined with framework coupling — delete unless fixable.
    if state.is_quarantined and state.forbidden_modules:
        mods = sorted(set(state.forbidden_modules))
        framework_mods = any(
            m.startswith(("fastapi", "starlette", "sqlalchemy", "pydantic"))
            for m in mods
        )
        if framework_mods:
            return (
                Verdict.DELETE,
                "none",
                (
                    f"Quarantined for framework coupling ({', '.join(mods)}). "
                    "Registered primitives may not import framework modules "
                    "(CONTRACT §B1.0.1); fixing means re-extracting from the "
                    "tool, not shipping as-is."
                ),
                None,
                (
                    f"Quarantined + forbidden_modules={mods}. Not salvageable "
                    "as a registered primitive without re-extraction."
                ),
            )

    # Rule 2b: AST-detected framework imports in the primary .py.
    # CONTRACT §B1.0.1 forbids framework imports in registered primitives.
    # This catches items the extraction gate missed.
    if state.framework_imports:
        mods = ", ".join(state.framework_imports)
        return (
            Verdict.KEEP_STAGED,
            "none",
            (
                f"Primary .py imports framework module(s) ({mods}). "
                "CONTRACT §B1.0.1 bars framework imports from registered "
                "primitives. Must be re-extracted as a framework-free "
                "primitive (with adapter under _adapters/fastapi/ if the "
                "FastAPI surface is needed) before promotion."
            ),
            (
                f"Framework-coupled: imports {mods}. Requires re-extraction "
                "with adapter pattern (CONTRACT §B1.0.1) before promotion."
            ),
            None,
        )

    # Rule 3: quarantined (physically in _quarantine/) — keep staged with reason.
    if state.is_quarantined:
        reason_text = state.quarantine_reason or (
            "no explicit reason recorded; physical location in _quarantine/ "
            "indicates extraction-gate rejection"
        )
        return (
            Verdict.KEEP_STAGED,
            "none",
            (
                f"Quarantined ({reason_text}). Not immediately promotable; "
                "requires re-extraction from the origin tool OR an explicit "
                "extraction-gate rule waiver before it can advance."
            ),
            (
                f"Physically quarantined under _extracted/_quarantine/. "
                f"Extracted from `{state.origin_tool or 'unknown tool'}`. "
                "Re-extract or waive the gate rule that rejected it."
            ),
            None,
        )

    # Rule 4: no strong signal at all — keep staged per §A12(b) discipline.
    if not strong:
        return (
            Verdict.KEEP_STAGED,
            "none",
            (
                "No registered tool / module / benchmark spec currently "
                "imports or references this primitive. §A12(b) gate not met; "
                "leave staged until a caller appears."
            ),
            (
                "No §A12(b) signal yet. Primitive was extracted from a tool "
                f"(`{state.origin_tool}`) but no current caller declares it "
                "in imports_primitives or imports from core.venous. Will re-"
                "evaluate on the next triage pass."
            ),
            None,
        )

    # Rule 5: signal present but shell incomplete.
    if state.replace_me_count > 0 or state.invariants_stubbed:
        return (
            Verdict.NEEDS_REVIEW,
            "none",
            (
                f"Caller exists ({len(strong)} signal(s)), but shell "
                f"incomplete: {state.replace_me_count} REPLACE_ME marker(s) + "
                f"{'stubbed' if state.invariants_stubbed else 'complete'} "
                "invariants. Fill placeholders and write real invariant tests "
                "before promotion."
            ),
            None,
            None,
        )

    # Rule 6/7: signal + clean shell — pick tier.
    if _tla_required_reason(state):
        return (
            Verdict.PROMOTE_FULL,
            "full",
            (
                f"{len(strong)} §A12(b) signal(s) + REPLACE_ME=0 + concurrent "
                "or mutable state requires formal TLA+ verification. Promote "
                "at full tier; ship .tla spec with the promotion PR."
            ),
            None,
            None,
        )

    if _lite_eligible(state):
        return (
            Verdict.PROMOTE_LITE,
            "lite",
            (
                f"{len(strong)} §A12(b) signal(s) + REPLACE_ME=0 + stateless + "
                "no concurrency + no ordering invariants. Eligible for lite "
                "tier per 0004-tier-lite.md §2.1 (awaiting ratification)."
            ),
            None,
            None,
        )

    # Rule 8: fallthrough.
    return (
        Verdict.NEEDS_REVIEW,
        "none",
        (
            "Signals present and shell complete, but eligibility heuristics "
            "disagreed. Human must adjudicate tier."
        ),
        None,
        None,
    )


def classify_primitive(
    primitive_dir: Path,
    name: str,
    namespace: str,
    is_quarantined: bool,
    registered_names: set[str],
    catalog: dict,
) -> LedgerEntry:
    state = measure(primitive_dir, name, namespace, is_quarantined, registered_names)
    signals = collect_signals(name, primitive_dir, catalog)
    verdict, tier, rationale, staging_reason, delete_reason = _classify_single(
        state, signals
    )
    blockers = (
        _describe_blockers(state)
        if verdict in (Verdict.PROMOTE_FULL, Verdict.PROMOTE_LITE, Verdict.NEEDS_REVIEW)
        else []
    )
    return LedgerEntry(
        primitive=name,
        namespace=namespace,
        verdict=verdict,
        tier=tier,  # type: ignore[arg-type]
        rationale=rationale,
        signals=signals,
        blockers=blockers,
        state=state,
        staging_reason=staging_reason,
        delete_reason=delete_reason,
        classifier_version=_CLASSIFIER_VERSION,
    )


def classify_all() -> Ledger:
    root = SKILL_ROOT / "core" / "venous" / "_extracted"
    registered_names = _registered_primitive_names()
    catalog = _load_catalog()
    entries: list[LedgerEntry] = []
    staged_total = 0
    quarantined_total = 0

    for ns_dir in sorted(root.iterdir()):
        if not ns_dir.is_dir():
            continue
        is_quarantined = ns_dir.name == "_quarantine"
        for p in sorted(ns_dir.iterdir()):
            if not p.is_dir() or not re.match(r"^[A-Z]", p.name):
                continue
            namespace = ns_dir.name if not is_quarantined else _guess_ns_from_quarantine(p)
            entry = classify_primitive(
                p, p.name, namespace, is_quarantined, registered_names, catalog
            )
            entries.append(entry)
            if is_quarantined:
                quarantined_total += 1
            else:
                staged_total += 1

    return Ledger(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        classifier_version=_CLASSIFIER_VERSION,
        total_staged=staged_total,
        total_quarantined=quarantined_total,
        entries=entries,
    )


def _guess_ns_from_quarantine(primitive_dir: Path) -> str:
    """Quarantine primitives live at `_quarantine/<Name>/` without namespace.

    Use `_origin.json.tool` path's first segment as a best-guess namespace.
    """
    origin = primitive_dir / "_origin.json"
    if not origin.exists():
        return "extras"
    try:
        import json

        data = json.loads(origin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "extras"
    tool_path = data.get("tool", "")
    if not tool_path:
        return "extras"
    first = tool_path.split("/")[0].strip()
    # Map common extract tool prefixes to registry namespaces.
    mapping = {
        "api_design": "api",
        "auth_access": "auth",
        "crud_data": "data",
        "infrastructure": "resiliency",
        "realtime": "api",
        "testing_tools": "extras",
    }
    return mapping.get(first, first or "extras")


def main() -> int:
    import json

    ledger = classify_all()
    out_json = SKILL_ROOT / "engine" / "promotion" / "ledger.json"
    out_json.write_text(
        json.dumps(ledger.model_dump(mode="json"), indent=2, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )
    # Brief stdout summary.
    from collections import Counter

    buckets = Counter(e.verdict.value for e in ledger.entries)
    ready = len(ledger.ready_to_execute())
    print(f"Ledger written to {out_json.relative_to(SKILL_ROOT)}")
    print(f"  total entries: {len(ledger.entries)}")
    print(f"  staged: {ledger.total_staged}  quarantined: {ledger.total_quarantined}")
    for verdict, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:15s} {n:>4}")
    print(f"  ready_to_execute (no blockers): {ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
