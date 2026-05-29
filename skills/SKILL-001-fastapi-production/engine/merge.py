#!/usr/bin/env python3
"""
Post-delivery consolidation.

After every builder batch lands in `core/venous/<namespace>/<Name>/`, this
script walks every primitive directory, re-validates each delivery against
the contract, aggregates the per-primitive manifests into a single
`core/venous/MANIFEST.json`, and emits:

- `MANIFEST.json` — catalog-wide roll-up: every primitive with its namespace,
  maturity, source batch, tier-pass summary, llm-cost, and file hashes.
- `REPORT.md` — human-readable summary: coverage by namespace and maturity,
  outliers (missing tier evidence, expensive primitives), drift flags.
- Exit 0 if every primitive in `core/venous/` passes `accept_delivery`; non-zero
  with a specific list of offenders otherwise.

Usage (from repo root):
    python3 -m engine.merge --venous-root skills/SKILL-001-fastapi-production/core/venous
    python3 -m engine.merge --venous-root ... --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    __package__ = "engine"

from engine.contracts import accept_delivery  # noqa: E402


def _iter_primitive_dirs(venous_root: Path) -> list[Path]:
    """A primitive dir is two levels below venous_root and contains a *.manifest.json."""
    out: list[Path] = []
    for ns_dir in sorted(
        p for p in venous_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    ):
        for prim_dir in sorted(
            p for p in ns_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
        ):
            manifest = prim_dir / f"{prim_dir.name}.manifest.json"
            if manifest.exists():
                out.append(prim_dir)
    return out


def _roll_up(venous_root: Path) -> tuple[dict, list[str]]:
    """Return (manifest_dict, offender_list)."""
    entries: list[dict] = []
    offenders: list[str] = []
    total_cost = 0.0
    by_ns: dict[str, int] = {}
    by_maturity: dict[str, int] = {}

    for prim_dir in _iter_primitive_dirs(venous_root):
        manifest_path = prim_dir / f"{prim_dir.name}.manifest.json"
        try:
            raw = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as e:
            offenders.append(f"{prim_dir.name}: manifest not valid JSON ({e})")
            continue

        ok, parsed, errors = accept_delivery(raw)
        if not ok:
            offenders.append(f"{prim_dir.name}: {'; '.join(errors)[:300]}")
            continue

        entries.append(
            {
                "name": parsed.name,
                "namespace": parsed.namespace,
                "maturity": parsed.maturity.value,
                "builder_agent_id": parsed.builder_agent_id,
                "file_count": len(parsed.files),
                "invariant_count": len(parsed.invariant_bindings),
                "tier_summary": [
                    {"tier": r.tier.value, "status": r.status.value} for r in parsed.tier_reports
                ],
                "llm_cost_usd": parsed.llm_cost_usd,
                "build_duration_ms": parsed.build_duration_ms,
                "catalog_entry_sha256": parsed.catalog_entry_sha256,
            }
        )
        total_cost += parsed.llm_cost_usd
        by_ns[parsed.namespace] = by_ns.get(parsed.namespace, 0) + 1
        by_maturity[parsed.maturity.value] = by_maturity.get(parsed.maturity.value, 0) + 1

    manifest = {
        "venous_root": str(venous_root),
        "total_primitives": len(entries),
        "total_llm_cost_usd": round(total_cost, 4),
        "by_namespace": dict(sorted(by_ns.items())),
        "by_maturity": dict(sorted(by_maturity.items())),
        "entries": sorted(entries, key=lambda e: (e["namespace"], e["name"])),
    }
    return manifest, offenders


def _write_report(manifest: dict, offenders: list[str], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Venous System — Consolidated Delivery Report")
    lines.append("")
    lines.append(f"- **Accepted primitives:** {manifest['total_primitives']}")
    lines.append(f"- **Rejected primitives:** {len(offenders)}")
    lines.append(f"- **Total LLM cost:** ${manifest['total_llm_cost_usd']:.2f}")
    lines.append("")
    lines.append("## By namespace")
    lines.append("| Namespace | Count |")
    lines.append("|---|---|")
    for ns, n in manifest["by_namespace"].items():
        lines.append(f"| `{ns}` | {n} |")
    lines.append("")
    lines.append("## By maturity")
    lines.append("| Maturity | Count |")
    lines.append("|---|---|")
    for m, n in manifest["by_maturity"].items():
        lines.append(f"| `{m}` | {n} |")
    lines.append("")
    if offenders:
        lines.append("## Rejections")
        for o in offenders:
            lines.append(f"- {o}")
        lines.append("")
    lines.append("## Accepted primitive index")
    lines.append("| # | Primitive | Namespace | Maturity | LLM $ | Duration ms |")
    lines.append("|---|---|---|---|---|---|")
    for i, e in enumerate(manifest["entries"], 1):
        lines.append(
            f"| {i} | `{e['name']}` | `{e['namespace']}` | `{e['maturity']}` | "
            f"{e['llm_cost_usd']:.4f} | {e['build_duration_ms']} |"
        )
    out_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate per-primitive manifests into a catalog roll-up."
    )
    parser.add_argument("--venous-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.venous_root.is_dir():
        msg = f"venous-root not found: {args.venous_root}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"✗ {msg}")
        return 2

    manifest, offenders = _roll_up(args.venous_root)
    (args.venous_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    _write_report(manifest, offenders, args.venous_root / "REPORT.md")

    ok = len(offenders) == 0
    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "accepted": manifest["total_primitives"],
                    "rejected": len(offenders),
                    "offenders": offenders,
                },
                indent=2,
            )
        )
    else:
        if ok:
            print(f"✓ {manifest['total_primitives']} primitives accepted.")
            print(f"  LLM cost total: ${manifest['total_llm_cost_usd']:.2f}")
            print(f"  Manifest: {args.venous_root / 'MANIFEST.json'}")
            print(f"  Report:   {args.venous_root / 'REPORT.md'}")
        else:
            print(f"✗ {len(offenders)} primitives rejected.")
            for o in offenders:
                print(f"  - {o}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
