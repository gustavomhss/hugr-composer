#!/usr/bin/env python3
"""
check_primitive — aggregate all 9 tier gates for a single primitive delivery.

Usage:
    python3 -m engine.check_primitive \\
        --primitive-dir core/venous/obs/HealthProbe \\
        --catalog-entry docs/research/outputs/AGENT_1_FRAMEWORKS.json \\
        --maturity battle_tested \\
        --builder-agent 1

Exits 0 iff every required tier PASSED (or legitimately SKIPPED). Emits a
`<Name>.manifest.json` file inside the primitive dir summarizing every tier
outcome, tool version, and evidence path. If `--sign` is given and `cosign`
is on PATH, the manifest is signed in place.

Never soft-accepts. Every rejection names the failing tier + IDs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

# Support running either as `python -m engine.check_primitive` or
# `python engine/check_primitive.py ...` by adjusting the path.
if __package__ is None or __package__ == "":
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    __package__ = "engine"

from engine.contracts import (  # noqa: E402
    Maturity,
    PrimitiveDelivery,
    Tier,
    accept_delivery,
    compute_sha256,
)
from engine.gates import (  # noqa: E402
    GateContext,
    run_t0_static,
    run_t1_behavioral,
    run_t2_formal,
    run_t3_state_machine,
    run_t4_metamorphic,
    run_t5_concurrency,
    run_t6_adversarial,
    run_t7_observability,
    run_t8_chaos,
    run_t9_meta,
)
from engine.llm import TransportPool  # noqa: E402


def _catalog_lookup(catalog_entry_file: Path, primitive_name: str) -> dict:
    """Load one PrimitiveSpec dict from an agent deliverable JSON."""
    raw = json.loads(catalog_entry_file.read_text())
    for p in raw.get("primitives", []):
        if p.get("name") == primitive_name:
            return p
    raise SystemExit(f"Primitive '{primitive_name}' not found in {catalog_entry_file}.")


def _spec_sha256(spec: dict) -> str:
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _file_artefacts(primitive_dir: Path, namespace: str, primitive_name: str) -> list[dict]:
    # Byproduct directories created by gate runners (not primitive artefacts).
    _BYPRODUCT_DIRS = {
        "_evidence",          # per-tier JUnit XML / T6 / T9 evidence
        "__pycache__",        # Python bytecode
        ".hypothesis",        # hypothesis example DB (T3)
        "states",             # TLC model-checker output dir (T2)
        ".pytest_cache",      # pytest cache
        ".ruff_cache",        # ruff cache
        ".mypy_cache",        # mypy cache
    }
    out: list[dict] = []
    for p in sorted(primitive_dir.rglob("*")):
        if p.is_dir():
            continue
        if any(part in _BYPRODUCT_DIRS for part in p.parts):
            continue
        # __init__.py / conftest.py are package hygiene files, not primitive artefacts.
        if p.name in ("__init__.py", "conftest.py"):
            continue
        rel = f"{namespace}/{primitive_name}/" + str(p.relative_to(primitive_dir))
        out.append({
            "path": rel,
            "sha256": compute_sha256(p.read_bytes()),
            "size_bytes": p.stat().st_size,
            "kind": _infer_kind(p.name, primitive_name),
        })
    return out


def _infer_kind(filename: str, primitive_name: str) -> str:
    base = filename
    n = primitive_name
    mapping = [
        (f"behavioral_{n}.py", "behavioral"),
        (f"state_machine_{n}.py", "state_machine"),
        (f"metamorphic_{n}.py", "metamorphic"),
        (f"concurrent_{n}.py", "concurrent"),
        (f"chaos_{n}.py", "chaos"),
        (f"observability_{n}.py", "observability"),
        (f"test_{n}.py", "test"),
        (f"{n}.py", "impl"),
        (f"{n}.md", "spec_md"),
        (f"{n}.tla", "formal_tla"),
        (f"{n}.als", "formal_alloy"),
        (f"{n}.contract.json", "contract_json"),
        (f"{n}.manifest.json", "manifest"),
        ("observability_schema.json", "observability"),
        ("dashboard.json", "dashboard"),
        ("sbom.cdx.json", "sbom"),
        ("persona_reviews.json", "persona_reviews"),
        ("proposed_invariants.json", "proposed_invariants"),
    ]
    for needle, kind in mapping:
        if base == needle:
            return kind
    if base.startswith("adversarial_") and base.endswith(".json"):
        return "adversarial"
    return "test"  # generic default


async def _run_all_tiers(ctx: GateContext, tiers_needed: frozenset[Tier]) -> list:
    reports = []
    if Tier.T0_STATIC in tiers_needed:
        reports.append(run_t0_static(ctx))
    if Tier.T1_BEHAVIORAL in tiers_needed:
        reports.append(run_t1_behavioral(ctx))
    if Tier.T2_FORMAL in tiers_needed:
        reports.append(run_t2_formal(ctx))
    if Tier.T3_STATE_MACHINE in tiers_needed:
        reports.append(run_t3_state_machine(ctx))
    if Tier.T4_METAMORPHIC in tiers_needed:
        reports.append(run_t4_metamorphic(ctx))
    if Tier.T5_CONCURRENCY in tiers_needed:
        reports.append(run_t5_concurrency(ctx))
    if Tier.T6_ADVERSARIAL in tiers_needed:
        reports.append(await run_t6_adversarial(ctx))
    if Tier.T7_OBSERVABILITY in tiers_needed:
        reports.append(run_t7_observability(ctx))
    if Tier.T8_CHAOS in tiers_needed:
        reports.append(run_t8_chaos(ctx))
    if Tier.T9_META in tiers_needed:
        reports.append(await run_t9_meta(ctx))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a primitive delivery against all 9 tiers.")
    parser.add_argument("--primitive-dir", type=Path, required=True)
    parser.add_argument("--catalog-entry", type=Path, required=True,
                        help="JSON file containing `primitives: [...]` (one agent deliverable).")
    parser.add_argument("--maturity", choices=[m.value for m in Maturity], required=True)
    parser.add_argument("--builder-agent", type=int, required=True)
    parser.add_argument("--invariant-bindings", type=Path, required=True,
                        help="JSON file: {'invariant_bindings': [{invariant_id, invariant_text, confirms_test, prevents_test, under_failure_test}, ...]}")
    parser.add_argument("--is-stateful", action="store_true",
                        help="Primitive carries shared/in-memory state; enables T2 / T3 / T5.")
    parser.add_argument("--max-concurrent-llm", type=int, default=6)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    pdir: Path = args.primitive_dir
    if not pdir.is_dir():
        _emit(args.json, False, [f"primitive_dir not found: {pdir}"])
        return 2

    primitive_name = pdir.name
    namespace = pdir.parent.name
    spec = _catalog_lookup(args.catalog_entry, primitive_name)

    if namespace != spec["namespace"]:
        _emit(args.json, False, [
            f"namespace mismatch: directory says '{namespace}', catalog says '{spec['namespace']}'."
        ])
        return 3

    maturity = Maturity(args.maturity)
    required = _required_tiers(maturity)
    pool = TransportPool(max_concurrent=args.max_concurrent_llm) if (
        Tier.T6_ADVERSARIAL in required or Tier.T9_META in required
    ) else None

    ctx = GateContext(
        primitive_dir=pdir,
        primitive_name=primitive_name,
        namespace=namespace,
        is_stateful=args.is_stateful,
        catalog_spec=spec,
        pool=pool,
    )

    started = time.monotonic()
    reports = asyncio.run(_run_all_tiers(ctx, required))

    # Write a placeholder manifest up-front so the file scan includes `kind=manifest`.
    manifest_path_early = pdir / f"{primitive_name}.manifest.json"
    if not manifest_path_early.exists():
        manifest_path_early.write_text(json.dumps({"status": "building"}, indent=2))

    files = _file_artefacts(pdir, namespace, primitive_name)
    bindings_raw = json.loads(args.invariant_bindings.read_text())["invariant_bindings"]

    llm_cost = sum(
        (pool._COST_HINT_PER_CALL.get(r.tool_version or "", 0.0) if pool else 0.0)
        for r in reports
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    delivery_raw = {
        "name": primitive_name,
        "namespace": namespace,
        "maturity": maturity.value,
        "builder_agent_id": args.builder_agent,
        "catalog_entry_sha256": _spec_sha256(spec),
        "files": files,
        "invariant_bindings": bindings_raw,
        "tier_reports": [r.model_dump() for r in reports],
        "build_duration_ms": duration_ms,
        "llm_cost_usd": round(llm_cost, 4),
    }

    # Sub-reports derive from the tier runs
    for r in reports:
        if r.evidence_path and r.tier == Tier.T6_ADVERSARIAL and r.status.value == "passed":
            delivery_raw["adversarial"] = json.loads((pdir / r.evidence_path).read_text())
        if r.evidence_path and r.tier == Tier.T9_META and r.status.value == "passed":
            ev = json.loads((pdir / r.evidence_path).read_text())
            delivery_raw["judge"] = ev["judge"]
            delivery_raw["personas"] = ev["personas"]
        if r.evidence_path and r.tier == Tier.T7_OBSERVABILITY and r.status.value == "passed":
            schema_path = pdir / "observability_schema.json"
            if schema_path.exists():
                delivery_raw["observability"] = json.loads(schema_path.read_text())

    ok, parsed, errors = accept_delivery(delivery_raw)

    manifest_path = pdir / f"{primitive_name}.manifest.json"
    manifest_path.write_text(json.dumps(delivery_raw, indent=2))

    if ok:
        _emit(args.json, True, [], parsed, manifest_path)
        return 0
    _emit(args.json, False, errors, None, manifest_path)
    return 1


def _required_tiers(maturity: Maturity) -> frozenset[Tier]:
    from engine.contracts import MATURITY_REQUIRED_TIERS
    return MATURITY_REQUIRED_TIERS[maturity]


def _emit(as_json: bool, ok: bool, errors: list[str], parsed=None, manifest: Path | None = None) -> None:
    payload = {
        "ok": ok,
        "errors": errors,
        "manifest": str(manifest) if manifest else None,
    }
    if parsed is not None:
        payload["tier_summary"] = [
            {"tier": r.tier.value, "status": r.status.value, "duration_ms": r.duration_ms}
            for r in parsed.tier_reports
        ]

    if as_json:
        print(json.dumps(payload, indent=2))
        return

    if ok:
        print("✓ PRIMITIVE DELIVERY ACCEPTED")
        if parsed is not None:
            for r in parsed.tier_reports:
                print(f"  {r.tier.value:22s}  {r.status.value:7s}  {r.duration_ms:>7d} ms")
        print(f"  manifest: {manifest}")
    else:
        print("✗ PRIMITIVE DELIVERY REJECTED")
        for i, err in enumerate(errors, 1):
            print(f"  [{i}] {err}")
        if manifest:
            print(f"  partial manifest: {manifest}")


if __name__ == "__main__":
    sys.exit(main())
