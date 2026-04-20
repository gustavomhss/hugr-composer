"""Quality gate for CONTRACT §B2.1.

Runs the curated query set at benchmarks/discovery_test_set.json through
`find_primitive` and reports top-1 accuracy + P@3. Exit non-zero if the
top-1 rate is below --min-top-1 (default 0.80, per CONTRACT §B2.1).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.discovery import find_primitive

_DEFAULT_SET = Path(__file__).resolve().parents[2] / "benchmarks" / "discovery_test_set.json"


def run(path: Path, verbose: bool = False) -> tuple[float, float, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    queries = data["queries"]
    top1 = 0
    p_at_3 = 0
    rows: list[dict] = []
    for q in queries:
        hits = find_primitive(q.get("concern", ""), q["query"], limit=10)
        top_names = [h["name"] for h in hits]
        expected = q["expected_top_1"]
        got_top1 = bool(top_names) and top_names[0] == expected
        got_p3 = expected in top_names[:3]
        top1 += int(got_top1)
        p_at_3 += int(got_p3)
        rows.append({
            "id": q["id"],
            "query": q["query"],
            "expected": expected,
            "top_1": top_names[0] if top_names else None,
            "top_3": top_names[:3],
            "pass_top1": got_top1,
            "pass_p3": got_p3,
        })
    n = len(queries) or 1
    return top1 / n, p_at_3 / n, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", type=Path, default=_DEFAULT_SET)
    parser.add_argument("--min-top-1", type=float, default=0.80)
    parser.add_argument("--min-p-at-3", type=float, default=0.90)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    top1, p3, rows = run(args.set, verbose=args.verbose)

    if args.json:
        print(json.dumps({"top_1": top1, "p_at_3": p3, "rows": rows}, indent=2))
    else:
        print(f"discovery quality: top-1 {top1:.0%}, P@3 {p3:.0%} over {len(rows)} queries")
        if args.verbose or top1 < args.min_top_1 or p3 < args.min_p_at_3:
            for r in rows:
                status = "OK " if r["pass_top1"] else "MISS"
                print(f"  {status} {r['id']}: '{r['query']}' -> {r['top_1']} (expected {r['expected']}); top3={r['top_3']}")

    if top1 < args.min_top_1:
        print(f"FAIL: top-1 {top1:.2%} < required {args.min_top_1:.2%}", file=sys.stderr)
        return 1
    if p3 < args.min_p_at_3:
        print(f"FAIL: P@3 {p3:.2%} < required {args.min_p_at_3:.2%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
