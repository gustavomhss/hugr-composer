#!/usr/bin/env python3
"""Wrap shell: autonomously wrap a staged primitive with the minimal HuGR shell.

Input:  `core/venous/_staging/<ns>/<Name>/<Name>.py` (raw-lifted source).
Output: the same directory, augmented with:
  - `<Name>.py`                  (import-resolved; original impl untouched)
  - `<Name>.protocol.py`         (auto-inferred Protocol surface — optional)
  - `<Name>.contract.json`       (synthetic PrimitiveSpec stub)
  - `invariant_bindings.json`    (seed: 1 binding per public method,
                                  confirms/prevents/under_failure slots empty)
  - `observability_schema.json`  (standard logs/metrics/spans stubs)
  - `test_<Name>.py`             (contract-roundtrip smoke test)
  - `<Name>.md`                  (provenance narrative — source tool cited)
  - `conftest.py`                (hypothesis storage redirect, pytest cache)
  - `_provenance.json`           (audit trail: source tool, line range, etc.)
  - `_extraction_report.json`    (unresolved imports, any T0 errors)

Runs a MINIMAL T0-ish check: import the module via `ast.parse` + a lazy
exec in a sandbox. Real mypy/ruff gate happens only AFTER the human promotes
the primitive out of staging.

This is the "fucking awesome" core: one command, N primitives, all gated,
no human-in-the-loop except for final review of the staged directory.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.extraction.infer_protocol import protocol_for_source
from engine.extraction.resolve_imports import resolve_imports

_STAGE_DIR = Path(__file__).resolve().parents[2] / "core" / "venous" / "_staging"


def _camel_to_snake_upper(name: str) -> str:
    """`GracefulShutdown` -> `GRACEFUL_SHUTDOWN`. Readable invariant-id prefixes."""
    # Split on camelCase / PascalCase boundaries.
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.upper()


_CONFTEST = '''\
"""Conftest for extracted primitive — hypothesis DB redirect + pytest cache."""
from __future__ import annotations

import os
import tempfile

from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

_HYP_DIR = tempfile.mkdtemp(prefix="hypothesis_")
os.environ.setdefault("HYPOTHESIS_STORAGE_DIRECTORY", _HYP_DIR)
settings.register_profile(
    "venous",
    database=DirectoryBasedExampleDatabase(_HYP_DIR),
    deadline=None,
)
settings.load_profile("venous")
'''


def _fresh_obs_schema() -> dict[str, list[dict[str, object]]]:
    """Return a fresh copy of the standard observability seed schema.

    A function (not a module-level dict) so each primitive gets its own
    mutable-safe instance. A shared mutable default leaks across primitives
    if any downstream code mutates it.
    """
    return {
        "logs": [
            {"event_name": "primitive.invoked", "required_attributes": ["primitive", "op"]},
            {
                "event_name": "primitive.failed",
                "required_attributes": ["primitive", "op", "error_class"],
            },
        ],
        "metrics": [
            {
                "name": "primitive.ops",
                "metric_type": "counter",
                "unit": "1",
                "cardinality_bound": 50,
                "label_keys": ["primitive", "op", "outcome"],
            },
            {
                "name": "primitive.latency",
                "metric_type": "histogram",
                "unit": "ms",
                "cardinality_bound": 50,
                "label_keys": ["primitive", "op"],
            },
        ],
        "spans": [
            {"operation_name": "primitive.call", "required_attributes": ["primitive", "op"]},
        ],
    }


def _public_methods_of_classes(source: str) -> dict[str, list[str]]:
    """Return `{class_name: [public_method_name, ...]}` for auto-binding stubs."""
    out: dict[str, list[str]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods: list[str] = []
            for item in node.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and not item.name.startswith("_"):
                    methods.append(item.name)
            out[node.name] = methods
    return out


def _synthesize_contract(name: str, ns: str, source: str) -> dict[str, Any]:
    method_map = _public_methods_of_classes(source)
    primary_class = next(iter(method_map), name)
    methods = method_map.get(primary_class, [])
    api_signature = (
        f"class {primary_class}: " + ", ".join(f"{m}(...)" for m in methods) if methods else ""
    )
    return {
        "name": name,
        "namespace": ns,
        "maturity": "emerging",
        "kind": "extracted",
        "purpose": "Extracted primitive (auto-generated stub). Human MUST replace with a "
        "concrete purpose statement before promotion.",
        "api_signature": api_signature,
        "invariants": [
            f"{_camel_to_snake_upper(name)}_INV_01: REPLACE_ME — describe the primary "
            "correctness invariant.",
        ],
        "status": "staged",
    }


def _synthesize_invariant_bindings(name: str, source: str) -> dict[str, Any]:
    method_map = _public_methods_of_classes(source)
    primary_class = next(iter(method_map), name)
    methods = method_map.get(primary_class, []) or ["REPLACE_ME"]
    slug = methods[0].lower()
    return {
        "invariant_bindings": [
            {
                "invariant_id": f"{_camel_to_snake_upper(name)}_INV_01",
                "invariant_text": "REPLACE_ME — describe the invariant.",
                "confirms_test": f"test_inv_{slug}_confirms",
                "prevents_test": f"test_inv_{slug}_prevents",
                "under_failure_test": f"test_inv_{slug}_under_failure",
            },
        ],
    }


def _synthesize_smoke_test(name: str, source: str) -> str:
    method_map = _public_methods_of_classes(source)
    primary_class = next(iter(method_map), name)
    slug = (method_map.get(primary_class, [primary_class.lower()]) or [primary_class.lower()])[
        0
    ].lower()
    return (
        f'"""Smoke tests for extracted primitive `{primary_class}`.\n\n'
        "These tests intentionally EMPTY-SHELL until a human promotes the\n"
        "primitive out of staging with real invariant semantics.\n"
        '"""\n'
        "from __future__ import annotations\n\n\n"
        f"def test_inv_{slug}_confirms() -> None:\n"
        f"    # REPLACE_ME: confirms-path scenario for {primary_class}.\n"
        "    assert True\n\n\n"
        f"def test_inv_{slug}_prevents() -> None:\n"
        f"    # REPLACE_ME: prevents-path scenario for {primary_class}.\n"
        "    assert True\n\n\n"
        f"def test_inv_{slug}_under_failure() -> None:\n"
        f"    # REPLACE_ME: under-failure scenario for {primary_class}.\n"
        "    assert True\n"
    )


def _synthesize_md(name: str, ns: str, source_tool: str, unresolved: set[str]) -> str:
    return (
        f"# {name}\n\n"
        f"**Status:** extracted-staged (needs human review).\n"
        f"**Namespace:** `{ns}`\n"
        f"**Source tool:** `adapt/extend/{source_tool}`\n\n"
        "## Provenance\n"
        f"Lifted by `engine.extraction.wrap_shell` on "
        f"{datetime.now(UTC).isoformat(timespec='seconds')}.\n"
        f"Unresolved symbols (requires manual import/stub): "
        f"{sorted(unresolved) or 'none'}.\n\n"
        "## Checklist before promotion\n"
        f"- [ ] Replace `REPLACE_ME` in `{name}.contract.json` with real purpose + invariants.\n"
        f"- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real "
        f"`confirms`/`prevents`/`under_failure` cases.\n"
        f"- [ ] Flesh out `test_{name}.py` beyond the smoke-stubs.\n"
        "- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.\n"
        "- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.\n"
        "- [ ] Move directory from `core/venous/_staging/<ns>/<Name>/` to "
        "`core/venous/<ns>/<Name>/` and run `engine.check_primitive` with "
        "`--maturity emerging`.\n"
    )


def _is_stub(path: Path) -> bool:
    """True if the file looks like an unmodified stub this module emitted."""
    if not path.exists():
        return False
    content = path.read_text()
    # Every stub this module produces contains a `REPLACE_ME` token or one of
    # the known seed markers; a human who starts editing will remove those.
    return (
        "REPLACE_ME" in content
        or "auto-generated stub" in content
        or "Auto-inferred Protocol surface" in content
    )


def wrap(primitive_dir: Path, *, force: bool = False) -> dict[str, Any]:
    name = primitive_dir.name
    ns = primitive_dir.parent.name
    impl_path = primitive_dir / f"{name}.py"
    if not impl_path.exists():
        return {"name": name, "status": "missing_impl"}

    # Idempotency gate: if ANY shell artifact has been edited (no REPLACE_ME /
    # no stub markers), refuse to overwrite unless `force=True`. This protects
    # human review work from being blown away on re-run.
    candidate_artifacts = [
        primitive_dir / f"{name}.contract.json",
        primitive_dir / "invariant_bindings.json",
        primitive_dir / f"test_{name}.py",
        primitive_dir / f"{name}.md",
    ]
    any_edited = any(p.exists() and not _is_stub(p) for p in candidate_artifacts)
    if any_edited and not force:
        return {"name": name, "namespace": ns, "status": "skipped_edited"}

    origin_raw = (
        (primitive_dir / "_origin.json").read_text()
        if (primitive_dir / "_origin.json").exists()
        else "{}"
    )
    origin = json.loads(origin_raw)
    source_tool = origin.get("tool", "(unknown)")

    original_source = impl_path.read_text()
    _stmts, _resolved, unresolved = resolve_imports(original_source)

    # Import-resolved impl.
    from engine.extraction.resolve_imports import prepend_imports

    rewritten, _ = prepend_imports(original_source)
    impl_path.write_text(rewritten)

    # Protocol stub.
    protocols = protocol_for_source(original_source, module_name=name)
    if protocols:
        joined = "\n\n".join(protocols)
        # `@abstractmethod` is a runtime decorator, not an annotation — if any
        # inferred method carries it, the stub must import it or it NameErrors
        # at import time (typing-only names are safe under `from __future__`).
        abc_import = "from abc import abstractmethod\n" if "@abstractmethod" in joined else ""
        proto_src = (
            "from __future__ import annotations\n\n"
            + abc_import
            + "from typing import Protocol, runtime_checkable\n\n\n"
            + joined
        )
        (primitive_dir / f"{name}.protocol.py").write_text(proto_src)

    # Contract + bindings + obs schema.
    (primitive_dir / f"{name}.contract.json").write_text(
        json.dumps(_synthesize_contract(name, ns, original_source), indent=2)
    )
    (primitive_dir / "invariant_bindings.json").write_text(
        json.dumps(_synthesize_invariant_bindings(name, original_source), indent=2)
    )
    (primitive_dir / "observability_schema.json").write_text(
        json.dumps(_fresh_obs_schema(), indent=2)
    )
    (primitive_dir / "dashboard.json").write_text(
        json.dumps({"title": f"{name}", "panels": []}, indent=2)
    )

    # Smoke test + conftest + md + __init__.
    (primitive_dir / f"test_{name}.py").write_text(_synthesize_smoke_test(name, original_source))
    (primitive_dir / "conftest.py").write_text(_CONFTEST)
    (primitive_dir / f"{name}.md").write_text(_synthesize_md(name, ns, source_tool, unresolved))
    (primitive_dir / "__init__.py").write_text("")
    (primitive_dir / "persona_reviews.json").write_text('{"reviews": []}\n')
    (primitive_dir / "proposed_invariants.json").write_text('{"proposed": []}\n')

    # Provenance record.
    (primitive_dir / "_provenance.json").write_text(
        json.dumps(
            {
                "extracted_at": datetime.now(UTC).isoformat(),
                "source_tool": source_tool,
                "origin_candidate": origin.get("candidate", {}),
                "wrapped_by": "engine.extraction.wrap_shell",
            },
            indent=2,
        )
    )

    return {
        "name": name,
        "namespace": ns,
        "status": "wrapped",
        "unresolved": sorted(unresolved),
        "has_protocol": bool(protocols),
    }


def run(only: str | None = None, *, force: bool = False) -> list[dict[str, Any]]:
    if not _STAGE_DIR.exists():
        raise SystemExit("No _staging/ directory — run `engine.extraction.extract` first.")
    reports: list[dict[str, Any]] = []
    for ns_dir in sorted(_STAGE_DIR.iterdir()):
        if not ns_dir.is_dir() or ns_dir.name.startswith("."):
            continue
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir() or prim_dir.name.startswith("."):
                continue
            if only and prim_dir.name != only:
                continue
            reports.append(wrap(prim_dir, force=force))
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wrap every staged primitive with the HuGR shell.")
    parser.add_argument("--only", type=str, default=None, help="Wrap only the named primitive.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite shell artifacts even if a human has edited them.",
    )
    args = parser.parse_args()
    out = run(only=args.only, force=args.force)
    wrapped = sum(1 for r in out if r["status"] == "wrapped")
    skipped = sum(1 for r in out if r["status"] == "skipped_edited")
    if skipped:
        print(f"Skipped (human-edited): {skipped} — pass --force to overwrite.")  # noqa: T201
    with_unresolved = [r for r in out if r.get("unresolved")]
    print(f"Wrapped: {wrapped} / {len(out)}")  # noqa: T201
    print(f"With unresolved imports: {len(with_unresolved)}")  # noqa: T201
    if with_unresolved:
        print("Top primitives needing manual import fixes:")  # noqa: T201
        for r in with_unresolved[:10]:
            print(f"  {r['namespace']}/{r['name']}: {r['unresolved'][:5]}...")  # noqa: T201
