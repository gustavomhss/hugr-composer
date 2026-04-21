"""Human-facing Markdown ledger generator.

Reads `engine/promotion/ledger.json` (machine-readable) and emits
`engine/promotion/LEDGER.md` (human-readable) grouped by verdict bucket.
Every entry carries one approve/reject checkbox and a one-line command
Gustavo can copy-paste to execute.

The Markdown ledger is the artefact Gustavo reviews to approve/reject
each primitive individually.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.promotion.schemas import Ledger, LedgerEntry, Verdict
from engine.promotion.state import SKILL_ROOT

_LEDGER_JSON = SKILL_ROOT / "engine" / "promotion" / "ledger.json"
_LEDGER_MD = SKILL_ROOT / "engine" / "promotion" / "LEDGER.md"


def _bucket_header(verdict: Verdict, count: int) -> str:
    titles = {
        Verdict.PROMOTE_AS_ADAPTER: "Promote as FastAPI adapter",
        Verdict.PROMOTE_AS_PRIMITIVE: "Promote as registered primitive",
        Verdict.EXTRACT_MOTOR_PAIR: "Extract motor+adapter pair (re-factor required)",
        Verdict.FILL_AND_PROMOTE: "Fill shell, then promote",
        Verdict.REDUNDANT: "Redundant (motor+adapter already ship)",
        Verdict.NEEDS_CALLER: "Wait for §A12(b) caller signal",
        Verdict.NEEDS_REVIEW: "Needs human review (ambiguous state)",
    }
    return f"## {titles[verdict]} — {count} primitive(s)"


def _bucket_preamble(verdict: Verdict) -> str:
    preambles = {
        Verdict.PROMOTE_AS_ADAPTER: (
            "Each item's motor is already registered under "
            "`core/venous/<ns>/<Motor>/` but the matching "
            "`_adapters/fastapi/<Motor>Adapter.py` is missing. The staged "
            "code can become that adapter. `promotion_target` gives the "
            "exact destination path. Approve to run:\n\n"
            "```\nPYTHONPATH=. .venv/bin/python -m engine.promotion.promote "
            "--from-ledger <NAME>\n```"
        ),
        Verdict.PROMOTE_AS_PRIMITIVE: (
            "Each item has a §A12(b) signal, clean shell, and fits either "
            "lite or full tier (see `tier` field). Lite promotion requires "
            "§B1.8 ratification first (see `docs/decisions/0004-tier-lite.md`). "
            "`promotion_target` gives the exact destination path. Approve:\n\n"
            "```\nPYTHONPATH=. .venv/bin/python -m engine.promotion.promote "
            "--from-ledger <NAME>\n```"
        ),
        Verdict.EXTRACT_MOTOR_PAIR: (
            "Framework-coupled with no motor registered. Cannot be "
            "promoted as-is (§B1.0.1 bars framework imports in registered "
            "primitives). Required work per item: split into "
            "(framework-free motor primitive under `core/venous/<ns>/<Motor>/`) "
            "+ (FastAPI adapter under `_adapters/fastapi/<Motor>Adapter.py`). "
            "~2-4h per item depending on complexity. No one-shot command — "
            "this is a refactoring sprint, not an executor call."
        ),
        Verdict.FILL_AND_PROMOTE: (
            "Has §A12(b) signal but shell is incomplete (REPLACE_ME markers "
            "or stub invariant tests). Work required: fill placeholders + "
            "implement the three invariant tests (confirms / prevents / "
            "under_failure) with real assertions. After that the classifier "
            "re-evaluates to PROMOTE_AS_ADAPTER or PROMOTE_AS_PRIMITIVE."
        ),
        Verdict.REDUNDANT: (
            "Motor and adapter (or the registered primitive itself) "
            "already ship. Staged copy adds no unique value. Default: "
            "leave in place as reference. If you want to remove, run:\n\n"
            "```\nPYTHONPATH=. .venv/bin/python -m engine.promotion.promote "
            "--delete <NAME>\n```\n\n"
            "Delete is opt-in, never automatic."
        ),
        Verdict.NEEDS_CALLER: (
            "No current §A12(b) signal — no registered tool, module, or "
            "benchmark spec references this primitive. §A12 discipline "
            "says: wait for a caller to appear before promoting. Leave "
            "in `_extracted/` with the recorded staging_reason."
        ),
        Verdict.NEEDS_REVIEW: (
            "Classifier heuristics disagreed or quarantine reason unclear. "
            "Each entry lists what the reviewer must adjudicate. Not "
            "executable until manually reclassified."
        ),
    }
    return preambles.get(verdict, "")


def _signal_line(entry: LedgerEntry) -> str:
    if not entry.signals:
        return "_No signals._"
    parts: list[str] = []
    for s in entry.signals[:5]:
        parts.append(f"`{s.kind.value}`: `{s.source}`")
    more = ""
    if len(entry.signals) > 5:
        more = f" (+{len(entry.signals) - 5} more)"
    return " · ".join(parts) + more


def _blocker_block(entry: LedgerEntry) -> str:
    if not entry.blockers:
        return ""
    lines = ["  - Blockers:"]
    for b in entry.blockers:
        lines.append(f"    - {b}")
    return "\n".join(lines)


def _state_line(entry: LedgerEntry) -> str:
    s = entry.state
    bits = [
        f"REPLACE_ME={s.replace_me_count}",
        f"loc={s.loc}",
        f"tla={'y' if s.has_tla else 'n'}",
        f"concurrency={'y' if s.has_concurrency else 'n'}",
        f"mutable={'y' if s.has_mutable_class_state else 'n'}",
        f"tests={'y' if s.test_file_present else 'n'}",
    ]
    if s.is_quarantined:
        bits.append("quarantined")
    if s.duplicate_of_registered:
        bits.append(f"dup_of={s.duplicate_of_registered}")
    if s.primitive_score:
        bits.append(f"score={s.primitive_score}")
    return " · ".join(bits)


def _entry_md(entry: LedgerEntry, n: int) -> str:
    lines = [
        f"### {n}. [ ] `{entry.primitive}` ({entry.namespace})",
        "",
        f"  - **Rationale:** {entry.rationale}",
        f"  - **State:** {_state_line(entry)}",
        f"  - **Signals:** {_signal_line(entry)}",
    ]
    if entry.staging_reason:
        lines.append(f"  - **Staging reason:** {entry.staging_reason}")
    if entry.delete_reason:
        lines.append(f"  - **Delete reason:** {entry.delete_reason}")
    blockers = _blocker_block(entry)
    if blockers:
        lines.append(blockers)
    if entry.promotion_target:
        lines.append(f"  - **Target:** `{entry.promotion_target}`")
    if entry.verdict == Verdict.REDUNDANT:
        lines.append(
            f"  - **Run (opt-in):** "
            f"`python -m engine.promotion.promote --delete {entry.primitive}`"
        )
    elif entry.verdict in (
        Verdict.PROMOTE_AS_ADAPTER,
        Verdict.PROMOTE_AS_PRIMITIVE,
    ):
        lines.append(
            f"  - **Run:** `python -m engine.promotion.promote "
            f"--from-ledger {entry.primitive}`"
        )
    lines.append("")
    return "\n".join(lines)


def render(ledger: Ledger) -> str:
    """Full Markdown ledger string."""
    head = [
        "# Promotion Ledger",
        "",
        f"**Generated:** {ledger.generated_at} · "
        f"**Classifier:** v{ledger.classifier_version} · "
        f"**Total:** {len(ledger.entries)} "
        f"({ledger.total_staged} staged + {ledger.total_quarantined} quarantined)",
        "",
        "> **How to use this ledger.** Each entry proposes a path to",
        "> functionality. Tick the checkbox to mark it approved; un-ticked =",
        "> not yet approved. PROMOTE_* entries have a copy-paste `Run:`",
        "> command. Default stance is **make it work, not delete** —",
        "> REDUNDANT entries stay in place unless you explicitly opt-in to",
        "> remove them. §A12 discipline is intact.",
        "",
        "## Summary",
        "",
        "| Verdict | Count | Gustavo's next step |",
        "|---|---:|---|",
    ]
    next_steps = {
        Verdict.PROMOTE_AS_ADAPTER: "Review + approve individually; executor ships each.",
        Verdict.PROMOTE_AS_PRIMITIVE: "Ratify §B1.8 (for lite) → review + approve.",
        Verdict.EXTRACT_MOTOR_PAIR: "Refactoring sprint — ~2-4h per item.",
        Verdict.FILL_AND_PROMOTE: "Fill REPLACE_ME + invariant tests; reclassify.",
        Verdict.REDUNDANT: "Leave in place, or opt-in delete for cleanup.",
        Verdict.NEEDS_CALLER: "No action. Revisit when a caller appears.",
        Verdict.NEEDS_REVIEW: "Adjudicate manually; reclassify.",
    }
    bucket_order = (
        Verdict.PROMOTE_AS_ADAPTER,
        Verdict.PROMOTE_AS_PRIMITIVE,
        Verdict.FILL_AND_PROMOTE,
        Verdict.EXTRACT_MOTOR_PAIR,
        Verdict.NEEDS_REVIEW,
        Verdict.REDUNDANT,
        Verdict.NEEDS_CALLER,
    )
    for v in bucket_order:
        cnt = len(ledger.by_verdict(v))
        head.append(f"| {v.value} | {cnt} | {next_steps[v]} |")
    head.append("")

    body: list[str] = []
    for verdict in bucket_order:
        bucket = ledger.by_verdict(verdict)
        if not bucket:
            continue
        body.append(_bucket_header(verdict, len(bucket)))
        body.append("")
        preamble = _bucket_preamble(verdict)
        if preamble:
            body.append(preamble)
            body.append("")
        # Sort within bucket: primitives with signals first, then by name.
        bucket_sorted = sorted(
            bucket, key=lambda e: (-len(e.signals), e.namespace, e.primitive)
        )
        for i, entry in enumerate(bucket_sorted, 1):
            body.append(_entry_md(entry, i))
        body.append("---")
        body.append("")

    return "\n".join(head + body).rstrip() + "\n"


def main() -> int:
    if not _LEDGER_JSON.exists():
        raise SystemExit("ledger.json missing — run `engine.promotion.classify` first.")
    data = json.loads(_LEDGER_JSON.read_text(encoding="utf-8"))
    ledger = Ledger.model_validate(data)
    _LEDGER_MD.write_text(render(ledger), encoding="utf-8")
    rel = _LEDGER_MD.relative_to(SKILL_ROOT)
    print(f"Wrote {rel} ({len(ledger.entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
