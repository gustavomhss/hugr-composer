#!/usr/bin/env python3
"""Dedupe: cross-check extracted candidates against the already-delivered catalog.

Strategy:
  1. Scan `core/venous/*/*/` for directories containing `<Name>.manifest.json`
     (= accepted catalog-derived primitives).
  2. For each extracted candidate in `primitive_candidates_ranked.json`,
     record the dedupe decision:
       - `exact_name`: a delivered primitive already uses this exact class name.
       - `case_insensitive_name`: collision after lower-casing.
       - `fuzzy_name`: Levenshtein ≤ 2 against any delivered name.
       - `unique`: no collision detected.
  3. For `exact_name` / `case_insensitive_name`: also compare `shape_hash` to
     flag whether it's the SAME implementation or a semantically-different
     one sharing a name (signals worth-merging vs worth-renaming).

Output: `dedupe_report.json` with per-candidate decision. This informs the
next stage (only `unique` + manually-approved `fuzzy`/`exact` candidates go
through the HuGR shell wrapper).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_RANKED_PATH = Path(__file__).resolve().parent / "primitive_candidates_ranked.json"
_VENOUS_DIR = Path(__file__).resolve().parents[2] / "core" / "venous"
_OUT_PATH = Path(__file__).resolve().parent / "dedupe_report.json"


def _delivered_primitives() -> dict[str, dict[str, Any]]:
    """Return `{PrimitiveName: {namespace, manifest_path, shape_hash}}`.

    Skips `_staging/` staging, `__pycache__/`, byproduct dirs.
    """
    out: dict[str, dict[str, Any]] = {}
    if not _VENOUS_DIR.exists():
        return out
    for ns_dir in sorted(_VENOUS_DIR.iterdir()):
        if not ns_dir.is_dir() or ns_dir.name.startswith(("_", ".")):
            continue
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir() or prim_dir.name.startswith((".", "__")):
                continue
            name = prim_dir.name
            manifest = prim_dir / f"{name}.manifest.json"
            if not manifest.exists():
                continue
            impl_file = prim_dir / f"{name}.py"
            shape_hash = _shape_hash_file(impl_file) if impl_file.exists() else None
            out[name] = {
                "namespace": ns_dir.name,
                "manifest_path": str(manifest.relative_to(_VENOUS_DIR.parent.parent)),
                "impl_shape_hash": shape_hash,
            }
    return out


def _shape_hash_file(path: Path) -> str:
    """Content-address hash using the SAME normalization as
    `audit_tools._normalized_body_hash` so cross-side comparisons are valid.

    Order MUST be preserved — sorting lines is catastrophic for this kind of
    hash (two unrelated files with the same line-multiset collide trivially).
    """
    import ast as _ast

    try:
        tree = _ast.parse(path.read_text())
    except SyntaxError:
        return "unparseable"
    canonical = _ast.unparse(tree)
    lines = [ln.strip() for ln in canonical.splitlines() if ln.strip()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[-1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def classify_candidate(
    cand: dict[str, Any],
    delivered: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    name = cand["name"]
    decision: dict[str, Any] = {
        "name": name,
        "tool": cand["tool"],
        "primitive_score": cand["primitive_score"],
        "candidate_shape_hash": cand["shape_hash"],
        "decision": "unique",
        "match": None,
        "shape_differs": None,
    }

    if name in delivered:
        d = delivered[name]
        decision["decision"] = "exact_name"
        decision["match"] = {"name": name, "namespace": d["namespace"]}
        decision["shape_differs"] = d["impl_shape_hash"] != cand["shape_hash"]
        return decision

    lower_map = {n.lower(): n for n in delivered}
    if name.lower() in lower_map:
        matched = lower_map[name.lower()]
        d = delivered[matched]
        decision["decision"] = "case_insensitive_name"
        decision["match"] = {"name": matched, "namespace": d["namespace"]}
        decision["shape_differs"] = d["impl_shape_hash"] != cand["shape_hash"]
        return decision

    best_dist = 99
    best_name = None
    for d_name in delivered:
        dist = _levenshtein(name.lower(), d_name.lower())
        if dist < best_dist:
            best_dist, best_name = dist, d_name
    if best_name is not None and best_dist <= 2:
        d = delivered[best_name]
        decision["decision"] = "fuzzy_name"
        decision["match"] = {"name": best_name, "namespace": d["namespace"], "distance": best_dist}

    return decision


def run() -> dict[str, Any]:
    delivered = _delivered_primitives()
    ranked = json.loads(_RANKED_PATH.read_text())
    qualifying = [r for r in ranked if not r["disqualified"]]

    decisions = [classify_candidate(cand, delivered) for cand in qualifying]

    counts: dict[str, int] = {}
    for d in decisions:
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1

    return {
        "delivered_count": len(delivered),
        "qualifying_count": len(qualifying),
        "decision_counts": counts,
        "decisions": decisions,
    }


def summarize(report: dict[str, Any]) -> None:
    print(f"Delivered catalog primitives: {report['delivered_count']}")
    print(f"Extraction candidates:        {report['qualifying_count']}")
    print("Decision counts:")
    for k, v in sorted(report["decision_counts"].items()):
        print(f"  {k:<24} {v:>4}")
    print("\nExact-name matches (candidates already in catalog):")
    for d in report["decisions"]:
        if d["decision"] == "exact_name":
            marker = "SAME_IMPL" if not d["shape_differs"] else "DIFFERS"
            print(f"  [{marker}] {d['name']:<30} (score {d['primitive_score']:>10}) — {d['tool']}")
    print("\nFuzzy-name matches (possibly re-named):")
    for d in report["decisions"]:
        if d["decision"] == "fuzzy_name":
            m = d["match"]
            print(
                f"  {d['name']:<30} ≈ {m['name']} (ns={m['namespace']}, dist={m['distance']}) — {d['tool']}"
            )


if __name__ == "__main__":
    report = run()
    _OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"Wrote {_OUT_PATH}\n")
    summarize(report)
