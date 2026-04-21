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
        Verdict.PROMOTE_FULL: "Promote at full tier (TLA+ required)",
        Verdict.PROMOTE_LITE: "Promote at lite tier (no TLA+)",
        Verdict.DELETE: "Delete (redundant or not salvageable)",
        Verdict.KEEP_STAGED: "Keep staged (awaiting signal or re-extraction)",
        Verdict.NEEDS_DECISION: "Needs decision — re-extract or delete as boilerplate",
        Verdict.NEEDS_REVIEW: "Needs human review (ambiguous state)",
    }
    return f"## {titles[verdict]} — {count} primitive(s)"


def _bucket_preamble(verdict: Verdict) -> str:
    preambles = {
        Verdict.PROMOTE_FULL: (
            "These primitives have a §A12(b) signal (registered tool / "
            "module / benchmark references them), a complete shell "
            "(REPLACE_ME=0, invariants implemented), and require full-"
            "tier promotion because they carry concurrent state, "
            "ordering invariants, or mutable behaviour that only TLA+ "
            "can verify exhaustively. Approve to run:\n\n"
            "```\nPYTHONPATH=. .venv/bin/python -m engine.promotion.promote "
            "--from-ledger <NAME>\n```"
        ),
        Verdict.PROMOTE_LITE: (
            "Stateless, no concurrent invariants, shell complete. "
            "**Blocked on ratification of §B1.7 in CONTRACT.md §E** "
            "(see `docs/decisions/0004-tier-lite.md`). Once ratified:"
            "\n\n"
            "```\nPYTHONPATH=. .venv/bin/python -m engine.promotion.promote "
            "--from-ledger <NAME>\n```"
        ),
        Verdict.DELETE: (
            "Either duplicates of a registered primitive (registered "
            "version is canonical), or quarantined with non-fixable "
            "framework coupling. Approve to run:\n\n"
            "```\nPYTHONPATH=. .venv/bin/python -m engine.promotion.promote "
            "--delete <NAME>\n```"
        ),
        Verdict.KEEP_STAGED: (
            "No current §A12(b) signal, OR signal present but the shell "
            "requires re-extraction. Leave in `_extracted/` with the "
            "recorded staging_reason. Each entry's `staging_reason` "
            "line documents why the primitive stays put."
        ),
        Verdict.NEEDS_DECISION: (
            "Framework-coupled primitives whose motor (framework-free core) "
            "is NOT yet registered. For each, decide:\n"
            "- (a) **re-extract** into (framework-free primitive + "
            "FastAPI adapter under `_adapters/fastapi/`) per §B1.0.1, or\n"
            "- (b) **delete** as boilerplate (trivial wiring, one-off "
            "middleware, no reusable logic).\n\n"
            "The rationale lines include a hint at the likely motor name "
            "if the suffix is recognisable (Middleware/Adapter/Backend/…).\n"
            "There is no one-shot command — these are judgment calls."
        ),
        Verdict.NEEDS_REVIEW: (
            "Classifier found strong signals but the shell is "
            "incomplete (REPLACE_ME markers or stub tests). Each entry "
            "lists blockers that a human must resolve before the "
            "classifier can upgrade the verdict to PROMOTE_*."
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
    if entry.verdict == Verdict.DELETE:
        lines.append(
            f"  - **Run:** `python -m engine.promotion.promote --delete {entry.primitive}`"
        )
    elif entry.verdict in (Verdict.PROMOTE_FULL, Verdict.PROMOTE_LITE):
        lines.append(
            f"  - **Run:** `python -m engine.promotion.promote --from-ledger {entry.primitive}`"
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
        "> **How to use this ledger.** Each entry is a proposed verdict, not a",
        "> decided action. Tick the checkbox of an entry to mark it approved;",
        "> un-ticked = not yet approved. The `Run:` line gives the exact",
        "> command to execute an approved entry. §A12 discipline is intact —",
        "> the executor refuses any entry whose verdict isn't PROMOTE_* or",
        "> DELETE, or which still has unresolved blockers.",
        "",
        "## Summary",
        "",
        "| Verdict | Count | Gustavo's next step |",
        "|---|---:|---|",
    ]
    next_steps = {
        Verdict.PROMOTE_FULL: "Review + approve individually; executor runs each.",
        Verdict.PROMOTE_LITE: "Ratify §B1.7 first; then review + approve.",
        Verdict.DELETE: "Review + approve individually; executor removes each.",
        Verdict.KEEP_STAGED: "No action required. Revisit on next triage pass.",
        Verdict.NEEDS_DECISION: "Human call: re-extract as motor+adapter, or delete.",
        Verdict.NEEDS_REVIEW: "Resolve blockers, then re-run classifier.",
    }
    for v in (
        Verdict.DELETE,
        Verdict.PROMOTE_FULL,
        Verdict.PROMOTE_LITE,
        Verdict.NEEDS_DECISION,
        Verdict.NEEDS_REVIEW,
        Verdict.KEEP_STAGED,
    ):
        cnt = len(ledger.by_verdict(v))
        head.append(f"| {v.value} | {cnt} | {next_steps[v]} |")
    head.append("")

    body: list[str] = []
    for verdict in (
        Verdict.DELETE,
        Verdict.PROMOTE_FULL,
        Verdict.PROMOTE_LITE,
        Verdict.NEEDS_REVIEW,
        Verdict.KEEP_STAGED,
    ):
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
