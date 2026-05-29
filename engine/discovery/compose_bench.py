"""Quality gate for CONTRACT §B2.2 — suggest_composition retrieval.

Runs the curated intent set through `suggest_composition` and reports
top-1 accuracy + P@3 against expected primitive sets. Exit non-zero if
top-1 < --min-top-1 (default 0.70) or P@3 < --min-p-at-3 (default 0.90).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.discovery import suggest_composition

_DEFAULT_SET = Path(__file__).resolve().parents[2] / "benchmarks" / "composition_test_set.json"


def _matches(hit: dict, expected: list[str]) -> bool:
    got = set(hit["primitives"])
    return set(expected).issubset(got)


def run(path: Path) -> tuple[float, float, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    intents = data["intents"]
    top1, p3 = 0, 0
    rows: list[dict] = []
    for it in intents:
        hits = suggest_composition(it["intent"], limit=5)
        expected = it["expected_primitives"]
        got_top1 = bool(hits) and _matches(hits[0], expected)
        got_p3 = any(_matches(h, expected) for h in hits[:3])
        top1 += int(got_top1)
        p3 += int(got_p3)
        rows.append(
            {
                "id": it["id"],
                "intent": it["intent"],
                "expected": expected,
                "top_1": hits[0]["primitives"] if hits else None,
                "top_1_source": hits[0].get("source") if hits else None,
                "pass_top1": got_top1,
                "pass_p3": got_p3,
            }
        )
    n = len(intents) or 1
    return top1 / n, p3 / n, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", type=Path, default=_DEFAULT_SET)
    parser.add_argument("--min-top-1", type=float, default=0.70)
    parser.add_argument("--min-p-at-3", type=float, default=0.90)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    top1, p3, rows = run(args.set)

    if args.json:
        print(json.dumps({"top_1": top1, "p_at_3": p3, "rows": rows}, indent=2))
    else:
        print(f"composition quality: top-1 {top1:.0%}, P@3 {p3:.0%} over {len(rows)} intents")
        if args.verbose or top1 < args.min_top_1 or p3 < args.min_p_at_3:
            for r in rows:
                mark = "OK " if r["pass_top1"] else ("P3 " if r["pass_p3"] else "MISS")
                print(
                    f"  {mark} {r['id']}: '{r['intent'][:50]}...' -> {r['top_1']} (expected ⊇ {r['expected']})"
                )

    if top1 < args.min_top_1:
        print(f"FAIL: top-1 {top1:.2%} < {args.min_top_1:.2%}", file=sys.stderr)
        return 1
    if p3 < args.min_p_at_3:
        print(f"FAIL: P@3 {p3:.2%} < {args.min_p_at_3:.2%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
