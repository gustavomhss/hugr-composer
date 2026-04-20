#!/usr/bin/env python3
"""
Pre-submission self-check CLI for research agents.

An agent runs this against its deliverable JSON BEFORE submitting.
Exits 0 if the deliverable satisfies the full contract + briefing.
Exits non-zero with structured errors otherwise.

Usage:
    python3 docs/research/contracts/check_deliverable.py \\
        --agent 1 \\
        --deliverable path/to/output.json

    # Or read from stdin:
    cat output.json | python3 docs/research/contracts/check_deliverable.py --agent 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "briefings"))

from briefing_contract import validate_deliverable  # noqa: E402
from briefings import BRIEFINGS  # noqa: E402


def _briefing_for(agent_id: int):
    for b in BRIEFINGS:
        if b.agent_id == agent_id:
            return b
    raise SystemExit(f"ERROR: no briefing found for agent_id={agent_id}. Valid: 1..8.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-check a research deliverable.")
    parser.add_argument("--agent", type=int, required=True, help="Agent id (1..8).")
    parser.add_argument("--deliverable", type=Path, help="Path to deliverable JSON. Omit to read stdin.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    briefing = _briefing_for(args.agent)

    if args.deliverable:
        try:
            raw_text = args.deliverable.read_text(encoding="utf-8")
        except FileNotFoundError:
            _emit(args.json, False, [f"Deliverable file not found: {args.deliverable}"])
            return 2
        except PermissionError:
            _emit(args.json, False, [f"Permission denied reading: {args.deliverable}"])
            return 2
    else:
        raw_text = sys.stdin.read()

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        _emit(args.json, False, [f"Invalid JSON: {e}"])
        return 2

    ok, deliverable, errors = validate_deliverable(raw, briefing)

    summary: dict = {
        "ok": ok,
        "agent_id": args.agent,
        "codename": briefing.codename,
        "errors": errors,
    }
    if deliverable is not None:
        summary.update({
            "primitives_count": len(deliverable.primitives),
            "unique_sources": len(deliverable.source_coverage),
            "insights_count": len(deliverable.cross_cutting_insights),
            "gaps_count": len(deliverable.gaps_observed),
        })
        summary["min_primitives_required"] = briefing.min_primitives
        summary["min_sources_required"] = briefing.min_sources_cited

    _emit(args.json, ok, errors, summary)
    return 0 if ok else 1


def _emit(as_json: bool, ok: bool, errors: list[str], summary: dict | None = None) -> None:
    if as_json:
        print(json.dumps(summary or {"ok": ok, "errors": errors}, indent=2))
        return

    if ok:
        print("✓ DELIVERABLE VALID")
        if summary:
            print(f"  Agent {summary['agent_id']} ({summary['codename']})")
            print(f"  Primitives: {summary.get('primitives_count', '?')} "
                  f"(min {summary.get('min_primitives_required', '?')})")
            print(f"  Unique sources: {summary.get('unique_sources', '?')} "
                  f"(min {summary.get('min_sources_required', '?')})")
            print(f"  Insights: {summary.get('insights_count', '?')}")
            print(f"  Gaps observed: {summary.get('gaps_count', 0)}")
    else:
        print("✗ DELIVERABLE REJECTED")
        for i, err in enumerate(errors, 1):
            print(f"  [{i}] {err}")


if __name__ == "__main__":
    sys.exit(main())
