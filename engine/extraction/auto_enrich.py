#!/usr/bin/env python3
"""Programmatic enrichment: harvest REAL invariants from extracted source.

This is the assertive half of the extraction pipeline. For every primitive
under `_extracted/<ns>/<Name>/` it does three things — each driven by
objective AST signal, not LLM judgment:

1. **Invariant mining from raise sites.** Scans every `raise <E>("<ID>: msg")`
   literal where `<ID>` looks like an invariant anchor (e.g. `RATE_INV_05`,
   `CBREAK-INV-03`). Those IDs are ground truth — the code already commits
   to the invariant by citing the ID on the failure path. Harvests unique
   IDs + the human-readable message after the `:`.

2. **Domain-coupling detection.** Walks the AST for `import X` / `from X import`
   where `X` matches a forbidden top-level module (SQLAlchemy ORM, Stripe SDK,
   Celery, etc.). Flags the primitive as `domain_coupled` and moves it to a
   quarantine staging area (`_extracted/_quarantine/`) so the promoter skips
   it without needing LLM review.

3. **Purpose mining from docstrings.** The primitive class's first docstring
   paragraph becomes the `purpose` string in contract.json. Missing docstring
   → fallback to `<Name>: reusable primitive extracted from <tool>`.

For each staged primitive this replaces `REPLACE_ME` in `<Name>.contract.json`
and `invariant_bindings.json` with the mined content — OR marks the primitive
`needs_llm_review` if we found fewer than 2 invariants (ambiguous case).

Deterministic, idempotent, zero LLM. The ambiguous residue (fewer than 2
invariants mined AND not quarantined) is written to a small JSON list for a
cheap follow-up Opus triage batch.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

_STAGE_DIR = Path(__file__).resolve().parents[2] / "core" / "venous" / "_extracted"
_QUARANTINE = _STAGE_DIR / "_quarantine"
_AMBIGUOUS_PATH = Path(__file__).resolve().parent / "ambiguous_primitives.json"


# Top-level module names whose presence indicates tool-specific coupling.
_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    # ORM / storage coupling — primitives MUST delegate storage to adapters.
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "pymongo",
    "redis",
    # Payment / e-commerce SDK coupling — marks code as domain-specific.
    "stripe",
    "shopify",
    "paypalrestsdk",
    # Task queue coupling — `WorkflowRun` etc. are the right abstraction.
    "celery",
    "rq",
    "dramatiq",
    # Framework-specific middleware that wraps FastAPI/Starlette directly —
    # primitives should be framework-agnostic.
    "starlette",
})


# Invariant-ID shapes seen across the catalog + extracted source. Match any of:
#   RATE_INV_05, CBREAK-INV-03, UOW.INV.01, LH_INV_02, SESSION-INV-06.
_INV_ID_RE = re.compile(r"\b[A-Z][A-Z_]{0,30}[-_.]INV[-_.][0-9]{1,3}\b")


def _is_domain_coupled(source: str) -> tuple[bool, list[str]]:
    """Return (is_coupled, hit_modules)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False, []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top in _FORBIDDEN_MODULES:
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top = node.module.split(".", 1)[0]
            if top in _FORBIDDEN_MODULES:
                hits.append(node.module)
    return (len(hits) > 0, sorted(set(hits)))


def _mine_invariants(source: str, primitive_name: str) -> list[dict[str, str]]:
    """Extract invariants from raise sites.

    Two passes:
      Pass 1 — formal: if the raise message embeds an `XXX_INV_NN` id, trust it.
               These are carry-overs from catalog-style code where the author
               already committed to an invariant anchor.
      Pass 2 — synthetic: for raise sites WITHOUT a formal ID (the common case
               in tool-extracted code), synthesize `<NAME>_INV_<NN>` with the
               raise message as the invariant text. Messages are deduped so
               repeated identical raises collapse to one invariant.

    The synthetic IDs are still reliable signal: they describe REAL code paths
    that reject REAL invalid inputs. They need naming review before catalog
    promotion, but the semantic content is harvested faithfully from source.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    formal: dict[str, str] = {}
    messages: list[str] = []  # ordered, for deterministic synthetic numbering
    seen_messages: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        call = node.exc
        if not isinstance(call, ast.Call):
            continue
        for arg in call.args:
            literal = _extract_literal(arg)
            if literal is None:
                continue
            match = _INV_ID_RE.search(literal)
            if match:
                inv_id = match.group(0)
                tail = literal.split(inv_id, 1)[1]
                msg = tail.split(":", 1)[-1].strip() if ":" in tail else tail.strip()
                msg = msg or f"invariant {inv_id} enforced at raise site."
                formal.setdefault(inv_id, msg[:240])
            else:
                # Synthetic candidate: the raise message itself. De-dupe by
                # lowercased normalized message so `raise X("x too short")` in
                # two methods collapses to one invariant.
                norm = " ".join(literal.split()).lower()[:120]
                if norm and norm not in seen_messages:
                    seen_messages.add(norm)
                    messages.append(literal.strip()[:240])
            break  # one literal per raise

    # Assemble: formal ones keep their citation ID; synthetic ones get
    # `<PRIMITIVE>_INV_NN` where PRIMITIVE is the camelCase→SNAKE form.
    name_upper = _camel_to_snake_upper(primitive_name)
    invariants: list[dict[str, str]] = [
        {"invariant_id": iid, "invariant_text": formal[iid]}
        for iid in sorted(formal)
    ]
    next_n = 1
    for msg in messages:
        # Skip messages that are just framework exception wrappers with no
        # meaningful content (e.g. HTTPException passthroughs).
        if len(msg) < 15:
            continue
        invariants.append({
            "invariant_id": f"{name_upper}_INV_{next_n:02d}",
            "invariant_text": msg,
        })
        next_n += 1
    return invariants


def _camel_to_snake_upper(name: str) -> str:
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.upper()


def _extract_literal(node: ast.AST) -> str | None:
    """Collect the string content of a literal or simple f-string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for seg in node.values:
            if isinstance(seg, ast.Constant) and isinstance(seg.value, str):
                parts.append(seg.value)
            elif isinstance(seg, ast.FormattedValue):
                parts.append("{?}")  # Placeholder — we only need the fixed text.
        return "".join(parts)
    return None


def _first_paragraph_docstring(source: str, class_name: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            docstring = ast.get_docstring(node) or ""
            para = docstring.split("\n\n", 1)[0].strip()
            return para.replace("\n", " ") if para else None
    return None


def _primary_class_name(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            return node.name
    return None


def _enrich_one(primitive_dir: Path) -> dict[str, Any]:
    name = primitive_dir.name
    ns = primitive_dir.parent.name
    impl = primitive_dir / f"{name}.py"
    contract_path = primitive_dir / f"{name}.contract.json"
    bindings_path = primitive_dir / "invariant_bindings.json"
    if not impl.exists() or not contract_path.exists():
        return {"name": name, "status": "missing_files"}

    source = impl.read_text()

    # 1. Domain coupling — move to quarantine if forbidden imports present.
    coupled, modules = _is_domain_coupled(source)
    if coupled:
        _QUARANTINE.mkdir(parents=True, exist_ok=True)
        (_QUARANTINE / name).mkdir(exist_ok=True)
        for f in primitive_dir.iterdir():
            dest = _QUARANTINE / name / f.name
            if f.is_file():
                dest.write_bytes(f.read_bytes())
        # Leave a breadcrumb in the original dir describing why.
        breadcrumb = primitive_dir / "_quarantined.json"
        breadcrumb.write_text(json.dumps({
            "reason": "domain_coupled",
            "forbidden_modules": modules,
        }, indent=2))
        return {"name": name, "status": "quarantined", "modules": modules}

    # 2. Invariants from raise sites.
    invariants = _mine_invariants(source, name)

    # 3. Purpose from docstring.
    primary = _primary_class_name(source)
    purpose = None
    if primary is not None:
        purpose = _first_paragraph_docstring(source, primary)
    if not purpose:
        purpose = (
            f"{name}: primitive extracted from the HuGR EXTEND tool corpus. "
            "Docstring absent from source; human review MUST replace this "
            "line with a concrete purpose statement."
        )

    # Decide whether to flag for LLM review — we need ≥2 invariants to be
    # confident the primitive carries real contract (<2 = weak signal).
    ambiguous = len(invariants) < 2
    if ambiguous:
        _flag_ambiguous(primitive_dir, reason=f"only {len(invariants)} invariant(s) mined")

    # Patch contract.json with mined content.
    contract = json.loads(contract_path.read_text())
    contract["purpose"] = purpose
    contract["invariants"] = [
        f"{inv['invariant_id']}: {inv['invariant_text']}"
        for inv in invariants
    ] or contract.get("invariants", [])
    contract["enrichment"] = {
        "invariants_mined": len(invariants),
        "ambiguous": ambiguous,
        "source": "engine.extraction.auto_enrich",
    }
    contract_path.write_text(json.dumps(contract, indent=2))

    # Patch invariant_bindings.json with real IDs + slug-matched test names.
    if invariants:
        bindings = {
            "invariant_bindings": [
                {
                    "invariant_id": inv["invariant_id"],
                    "invariant_text": inv["invariant_text"],
                    "confirms_test": f"test_{_slugify(inv['invariant_id'])}_confirms",
                    "prevents_test": f"test_{_slugify(inv['invariant_id'])}_prevents",
                    "under_failure_test": f"test_{_slugify(inv['invariant_id'])}_under_failure",
                }
                for inv in invariants
            ],
        }
        bindings_path.write_text(json.dumps(bindings, indent=2))

    return {
        "name": name,
        "namespace": ns,
        "status": "enriched",
        "invariants_mined": len(invariants),
        "ambiguous": ambiguous,
        "purpose_from_docstring": primary is not None and not purpose.startswith(f"{name}: primitive extracted"),
    }


def _slugify(inv_id: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", inv_id.lower()).strip("_")


def _flag_ambiguous(primitive_dir: Path, *, reason: str) -> None:
    existing: list[dict[str, str]] = []
    if _AMBIGUOUS_PATH.exists():
        existing = json.loads(_AMBIGUOUS_PATH.read_text())
    existing.append({
        "primitive_dir": str(primitive_dir.relative_to(_STAGE_DIR.parent.parent.parent)),
        "reason": reason,
    })
    _AMBIGUOUS_PATH.write_text(json.dumps(existing, indent=2))


def run() -> dict[str, Any]:
    if _AMBIGUOUS_PATH.exists():
        _AMBIGUOUS_PATH.unlink()
    if not _STAGE_DIR.exists():
        raise SystemExit("No _extracted/ directory.")
    totals: dict[str, int] = {"enriched": 0, "quarantined": 0, "ambiguous": 0, "missing_files": 0}
    results: list[dict[str, Any]] = []
    for ns_dir in sorted(_STAGE_DIR.iterdir()):
        if not ns_dir.is_dir() or ns_dir.name.startswith("_"):
            continue
        for prim_dir in sorted(ns_dir.iterdir()):
            if not prim_dir.is_dir() or prim_dir.name.startswith("_"):
                continue
            r = _enrich_one(prim_dir)
            totals[r["status"]] = totals.get(r["status"], 0) + 1
            if r.get("ambiguous"):
                totals["ambiguous"] += 1
            results.append(r)
    return {"totals": totals, "results": results}


if __name__ == "__main__":
    report = run()
    print("Auto-enrichment complete:")
    for k, v in sorted(report["totals"].items()):
        print(f"  {k:<16} {v:>5}")
    avg_inv = 0
    enriched_only = [r for r in report["results"] if r["status"] == "enriched"]
    if enriched_only:
        avg_inv = sum(r["invariants_mined"] for r in enriched_only) / len(enriched_only)
    print(f"\n  Mean invariants mined per enriched primitive: {avg_inv:.2f}")
    non_ambig = [r for r in enriched_only if not r.get("ambiguous", True)]
    print(f"  Primitives with ≥2 invariants (production-ready stub): {len(non_ambig)}")
    print(f"  Ambiguous residue (for mini-Opus triage): {report['totals']['ambiguous']}")
    if _AMBIGUOUS_PATH.exists():
        print(f"  Ambiguous list written to: {_AMBIGUOUS_PATH}")
