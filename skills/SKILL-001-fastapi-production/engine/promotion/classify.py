"""Classify every staged primitive into an action-focused verdict.

Default stance: **make it work, don't delete**. Every verdict except
REDUNDANT points to a concrete path-to-functionality (promote it, fill
its shell, extract the motor/adapter pair, or wait for a caller).
REDUNDANT is reserved for items where both motor and adapter already
ship — the user may still choose to keep them as reference copies.

Decision tree (evaluated in order — first match wins):

1. `duplicate_of_registered` set → REDUNDANT
   (same name as a registered primitive; staged copy adds no value).

2. Framework-coupled AND motor registered AND adapter exists
       → REDUNDANT.

3. Framework-coupled AND motor registered AND adapter missing
       → PROMOTE_AS_ADAPTER
       (the staged item can become `_adapters/fastapi/<Motor>Adapter.py`).

4. Framework-coupled AND motor NOT registered
       → EXTRACT_MOTOR_PAIR
       (needs splitting into framework-free primitive + adapter).

5. Physically quarantined (non-framework-coupled)
       → NEEDS_REVIEW (the extraction gate rejected it for a non-framework
       reason; a human must inspect before any signal-driven path can apply).
       Quarantined items short-circuit the signal/shell flow on purpose:
       silently routing them through FILL_AND_PROMOTE or NEEDS_CALLER would
       paper over the underlying rejection rationale.

6. No §A12(b) signal → NEEDS_CALLER.

7. Signal + shell incomplete (REPLACE_ME or stub tests)
       → FILL_AND_PROMOTE (with blockers listing what to fill).

8. Signal + clean shell + (concurrency OR mutable state)
       → PROMOTE_AS_PRIMITIVE (tier=full; requires .tla spec).

9. Signal + clean shell + lite-eligible
       → PROMOTE_AS_PRIMITIVE (tier=lite; requires §B1.7 ratification).

10. Fallthrough → NEEDS_REVIEW.

Every verdict carries a `blockers` list: preconditions the executor must
see resolved before it runs. Non-empty blockers = documentation, not yet
executable.
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
from engine.promotion.signals import _load_catalog, collect_signals
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

# Framework-specific suffixes that, stripped from a staged primitive name,
# reveal the "motor" (framework-free core) it wraps. Order matters: longer
# suffixes first so `AuthBackend` → `Auth` wins over `Backend` → `` noise.
_FRAMEWORK_SUFFIXES = (
    "Middleware",
    "Adapter",
    "Dispatcher",
    "Interceptor",
    "Backend",
    "Handler",
    "Router",
    "Service",
    "Endpoint",
    "Controller",
    "Responder",
)


def _motor_name(staged_name: str) -> str | None:
    """Return the likely framework-free motor name, or None if no suffix matches.

    `BulkheadMiddleware` → `Bulkhead`; `AdminAuthBackend` → `AdminAuth`;
    `CORSConfigMiddleware` → `CORSConfig`; `Foo` → None (no suffix to strip).
    """
    for suffix in _FRAMEWORK_SUFFIXES:
        if staged_name.endswith(suffix) and len(staged_name) > len(suffix):
            return staged_name[: -len(suffix)]
    return None


def _motor_is_registered(staged_name: str, registered: set[str]) -> str | None:
    """If stripping a framework suffix yields a registered primitive, return it."""
    motor = _motor_name(staged_name)
    if motor is None:
        return None
    if motor in registered:
        return motor
    return None


def _adapter_exists(motor: str) -> bool:
    """True if `core/venous/_adapters/fastapi/<Motor>Adapter.py` exists."""
    return (
        SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi" / f"{motor}Adapter.py"
    ).exists()


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
    state: StateFlags,
    signals: list[Signal],
    registered_names: set[str] | None = None,
) -> tuple[Verdict, str, str, str | None, str | None, str | None]:
    """Return (verdict, tier, rationale, staging_reason, delete_reason, promotion_target)."""
    strong = _strong(signals)
    registered_names = registered_names or set()

    # Rule 1: duplicate of a registered primitive.
    if state.duplicate_of_registered:
        return (
            Verdict.REDUNDANT,
            "none",
            (
                f"Duplicate of registered primitive "
                f"`{state.duplicate_of_registered}`. Staged copy adds no "
                "value; registered canonical version already ships. "
                "User may keep as reference or remove — not automatic."
            ),
            None,
            (
                f"Same name as core/venous/*/{state.duplicate_of_registered}/ "
                "(registered version is canonical)."
            ),
            None,
        )

    # Rule 2: framework-coupled AND motor registered AND adapter exists.
    if state.framework_imports:
        motor = _motor_is_registered(state.name, registered_names)
        if motor is not None and _adapter_exists(motor):
            mods = ", ".join(state.framework_imports)
            return (
                Verdict.REDUNDANT,
                "none",
                (
                    f"Framework-coupled ({mods}). Motor `{motor}` registered, "
                    f"AND `{motor}Adapter.py` already ships under "
                    "_adapters/fastapi/. Both halves of the pair exist — "
                    "staged copy is pure redundancy."
                ),
                None,
                (
                    f"Motor `{motor}` + `{motor}Adapter.py` both registered. "
                    f"Staged `{state.name}` duplicates shipped code."
                ),
                None,
            )

    # Rule 3: framework-coupled + motor registered but adapter MISSING.
    # This is a PROMOTE opportunity: the staged item can become the
    # missing adapter.
    if state.framework_imports:
        motor = _motor_is_registered(state.name, registered_names)
        if motor is not None and not _adapter_exists(motor):
            mods = ", ".join(state.framework_imports)
            target = f"core/venous/_adapters/fastapi/{motor}Adapter.py"
            return (
                Verdict.PROMOTE_AS_ADAPTER,
                "adapter",
                (
                    f"Framework-coupled ({mods}). Motor `{motor}` registered "
                    f"but `{motor}Adapter.py` is MISSING. Promote this staged "
                    f"item as `{target}` — completes the motor+adapter pair."
                ),
                None,
                None,
                target,
            )

    # Rule 4: framework-coupled with no motor registered — split required.
    if state.framework_imports:
        mods = ", ".join(state.framework_imports)
        motor_hint = _motor_name(state.name)
        hint_line = (
            f" Suggested motor name: `{motor_hint}`."
            if motor_hint
            else " No common framework suffix; motor name must be chosen manually."
        )
        return (
            Verdict.EXTRACT_MOTOR_PAIR,
            "none",
            (
                f"Framework-coupled ({mods}) with no registered motor. "
                f"Requires re-extraction into (framework-free motor primitive "
                f"+ FastAPI adapter) per §B1.0.1.{hint_line}"
            ),
            None,
            None,
            None,
        )

    # Rule 5: physically quarantined (no framework imports detected).
    # Not a duplicate, not framework-coupled — still rejected by extraction
    # gate for some other reason. Defer to signal-based classification.
    if state.is_quarantined:
        reason_text = state.quarantine_reason or (
            "extraction gate rejected it for an unrecorded reason"
        )
        return (
            Verdict.NEEDS_REVIEW,
            "none",
            (
                f"Quarantined ({reason_text}) but no framework coupling "
                "detected. Needs human inspection: either waive the "
                "rejection reason, re-extract, or mark as keep-with-reason."
            ),
            (
                "Physically quarantined with non-framework reason. Human "
                "inspection needed before any promotion path can be chosen."
            ),
            None,
            None,
        )

    # Rule 6: no §A12(b) signal — wait for caller.
    if not strong:
        return (
            Verdict.NEEDS_CALLER,
            "none",
            (
                "No registered tool / module / benchmark spec currently "
                "imports or references this primitive. §A12(b) gate not "
                "met; leave staged until a caller appears."
            ),
            (
                "No §A12(b) signal yet. Primitive was extracted from "
                f"`{state.origin_tool}` but no current caller declares it. "
                "Re-evaluate on the next triage pass."
            ),
            None,
            None,
        )

    # Rule 7: signal present but shell incomplete.
    if state.replace_me_count > 0 or state.invariants_stubbed:
        return (
            Verdict.FILL_AND_PROMOTE,
            "none",
            (
                f"Caller exists ({len(strong)} signal(s)), shell incomplete: "
                f"{state.replace_me_count} REPLACE_ME marker(s)"
                + (" + stubbed invariants" if state.invariants_stubbed else "")
                + ". Fill placeholders + implement invariant tests, then "
                "promote (primitive or adapter depending on coupling)."
            ),
            None,
            None,
            None,
        )

    # Rule 8: signal + clean shell + concurrency/mutable → promote full tier.
    if _tla_required_reason(state):
        ns = state.namespace or "extras"
        target = f"core/venous/{ns}/{state.name}/"
        return (
            Verdict.PROMOTE_AS_PRIMITIVE,
            "full",
            (
                f"{len(strong)} §A12(b) signal(s) + clean shell + "
                "concurrent/mutable state. Promote at full tier (TLA+ "
                f"required) to `{target}`."
            ),
            None,
            None,
            target,
        )

    # Rule 9: signal + clean shell + lite-eligible.
    if _lite_eligible(state):
        ns = state.namespace or "extras"
        target = f"core/venous/{ns}/{state.name}/"
        return (
            Verdict.PROMOTE_AS_PRIMITIVE,
            "lite",
            (
                f"{len(strong)} §A12(b) signal(s) + clean shell + stateless. "
                f"Eligible for lite tier. Target: `{target}` "
                "(requires §B1.7 ratification)."
            ),
            None,
            None,
            target,
        )

    # Rule 10: fallthrough.
    return (
        Verdict.NEEDS_REVIEW,
        "none",
        (
            "Signals present and shell complete, but eligibility heuristics "
            "disagreed. Human must adjudicate tier."
        ),
        None,
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
    (
        verdict,
        tier,
        rationale,
        staging_reason,
        delete_reason,
        promotion_target,
    ) = _classify_single(state, signals, registered_names)
    # Adapter promotions only copy the primary `.py` to the adapters tree;
    # REPLACE_ME markers in invariant_bindings.json / tests do NOT block an
    # adapter copy (they only matter for full primitive promotion).
    if verdict == Verdict.PROMOTE_AS_ADAPTER:
        blockers: list[str] = []
    elif verdict in (
        Verdict.PROMOTE_AS_PRIMITIVE,
        Verdict.FILL_AND_PROMOTE,
        Verdict.NEEDS_REVIEW,
    ):
        blockers = _describe_blockers(state)
    else:
        blockers = []
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
        promotion_target=promotion_target,
        classifier_version=_CLASSIFIER_VERSION,
    )


def classify_all() -> Ledger:
    root = SKILL_ROOT / "core" / "venous" / "_staging"
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
        json.dumps(ledger.model_dump(mode="json"), indent=2, sort_keys=False) + "\n",
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
