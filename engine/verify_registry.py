#!/usr/bin/env python3
"""
verify_registry — run the T0 static gate across every registered primitive.

The catalog-conformant verification surface for the SKILL KIT registry
(`fastapi_meta_verify`). Unlike `engine.check_primitive` — which validates a
*single delivery* and therefore demands a catalog entry, invariant bindings
and a builder agent id — this runner iterates the primitive registry and
executes the tiers that apply to already-merged primitives:

  - T0 static (mypy --strict + ruff curated + suppression audit)
  - T1 behavioral (pytest on `behavioral_<Name>.py`, when present)

Usage:
    python -m engine.verify_registry [--name VALUEOBJECT] [--json]

Exit 0 iff every evaluated primitive passes T0 and T1. Never soft-accepts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))
    __package__ = "engine"

from engine.gates.runners import GateContext, run_t0_static, run_t1_behavioral

SKILL_ROOT = Path(__file__).resolve().parent.parent


def _run_pytest_in(cwd: Path, target: Path, py: str) -> tuple[int, str, str]:
    """Run pytest against a single test file with cwd set to its dir.

    Primitives' conftest.py redirects the pytest cache out of the primitive
    dir; running from inside the dir keeps the import path and cache policy
    identical to a manual `pytest core/venous/.../`.
    """
    import subprocess

    p = subprocess.run(
        [py, "-m", "pytest", "-q", "--no-header", "--disable-warnings", str(target)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=600,
    )
    return p.returncode, p.stdout, p.stderr


def _registered_primitives() -> list[tuple[str, str, Path]]:
    """Yield (namespace, name, dir) for every registered core.venous primitive."""
    out: list[tuple[str, str, Path]] = []
    root = SKILL_ROOT / "core" / "venous"
    for ns_dir in sorted(root.iterdir()):
        if not ns_dir.is_dir():
            continue
        if ns_dir.name.startswith("_") or ns_dir.name == "__pycache__":
            continue
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir():
                continue
            impl = prim_dir / f"{prim_dir.name}.py"
            if not impl.exists():
                continue
            if not (prim_dir / "__init__.py").exists():
                continue
            out.append((ns_dir.name, prim_dir.name, prim_dir))
    return out


def _evaluate(prim_dir: Path, name: str, ns: str) -> dict:
    ctx = GateContext(
        primitive_dir=prim_dir,
        primitive_name=name,
        namespace=ns,
        is_stateful=(prim_dir / f"behavioral_{name}.py").exists(),
        catalog_spec={},
        pool=None,
    )
    reports: dict[str, dict] = {}

    t0 = run_t0_static(ctx)
    reports["t0"] = {
        "status": t0.status.value,
        "duration_ms": t0.duration_ms,
        "summary": t0.summary,
        "error": t0.error_details[:600] if t0.error_details else None,
    }

    behavioral = prim_dir / f"behavioral_{name}.py"
    invariant_test = prim_dir / f"test_{name}.py"
    if behavioral.exists():
        t1 = run_t1_behavioral(ctx)
        reports["t1"] = {
            "status": t1.status.value,
            "duration_ms": t1.duration_ms,
            "summary": t1.summary,
            "error": t1.error_details[:600] if t1.error_details else None,
        }
    elif invariant_test.exists():
        # Registry primitives carry their invariant tests in test_<Name>.py;
        # run those as the behavioral tier (contract pattern test_inv_*).

        started = time.monotonic()
        py = "python3"
        try:
            import sys as _sys

            py = _sys.executable
        except Exception:  # noqa: BLE001  # pragma: no cover - defensive; sys.executable is always present in a running interpreter
            pass
        code, out, err = _run_pytest_in(prim_dir, invariant_test, py)
        ok = code == 0
        reports["t1"] = {
            "status": "passed" if ok else "failed",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "summary": "invariant test suite" if ok else "invariant test failures",
            "error": (out + err)[-1200:] if not ok else None,
        }
    else:
        reports["t1"] = {
            "status": "errored",
            "duration_ms": 0,
            "summary": "no behavioral harness / invariant test — registry primitive MUST ship one",
            "error": None,
        }

    return {"name": name, "namespace": ns, "path": str(prim_dir), "reports": reports}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the primitive registry (T0 static + T1 behavioral)."
    )
    parser.add_argument(
        "--name", type=str, default=None, help="Verify a single primitive (default: all)."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--skip-t1", action="store_true", help="Skip T1 behavioral (faster; T0 only)."
    )
    args = parser.parse_args()

    started = time.monotonic()
    prims = _registered_primitives()
    if args.name:
        prims = [(ns, n, d) for ns, n, d in prims if n.lower() == args.name.lower()]
        if not prims:
            print(f"Primitive '{args.name}' not found in registry.")  # noqa: T201 — CLI verbatim output; gate runs headless via exit code
            return 2

    results = [_evaluate(d, n, ns) for ns, n, d in prims]
    if args.skip_t1:
        for res in results:
            res["reports"].pop("t1", None)

    failed = [
        r
        for r in results
        if any(rep["status"] in ("failed", "errored", "error") for rep in r["reports"].values())
    ]
    duration_ms = int((time.monotonic() - started) * 1000)

    if args.json:
        print(  # noqa: T201 — JSON report is the primary CLI contract; JSON flag consumers parse stdout
            json.dumps(
                {
                    "ok": not failed,
                    "total": len(results),
                    "failed": [f["name"] for f in failed],
                    "duration_ms": duration_ms,
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        print(  # noqa: T201 — human-readable summary is the non-JSON CLI contract
            f"Registry verify: {len(results)} primitives, {len(failed)} failing in {duration_ms} ms"
        )
        for r in results:
            marks = " ".join(f"{t}={rep['status']}" for t, rep in sorted(r["reports"].items()))
            print(f"  {r['namespace']}/{r['name']:32s} {marks}")  # noqa: T201 — per-primitive status line in the human summary
        for f in failed:
            for t, rep in sorted(f["reports"].items()):
                if rep["status"] in ("failed", "errored", "error"):
                    print(f"\n=== {f['namespace']}/{f['name']} [{t}] ===")  # noqa: T201 — failure block header in the human summary
                    print((rep.get("error") or rep.get("summary") or "")[:1200])  # noqa: T201 — failure detail block

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
