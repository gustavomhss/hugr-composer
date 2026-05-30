"""Phase 1 — primitive layer + adapter wiring (CONTRACT.md §B1.0–§B1.8).

CONTRACT.md scope: §B1.0 core.venous distribution, §B1.0.1 adapter
layer + framework-free primitives, §B1.1 primitives_by_concern.yaml
registry, §B1.2 Compose-with coverage, §B1.3 ≥15 tools import primitives,
§B1.5 no hardcoded ``@mcp_app.tool`` decorators, §B1.6 no orphan
generators, §B1.7 fastapi adapter coverage, §B1.8 tier-lite eligibility
(lazy-imports ``engine.promotion.state``).

Cohesion: every rule reads ``core/venous/``, ``engine/primitives_by_concern.yaml``,
or ``engine/index/catalog.json`` and asserts a property of the
primitive layer (registry sync, framework purity, sibling-pairing
coverage, adapter wiring, orphan-generator detection, lite-tier
eligibility).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ._common import REPO_ROOT, SKILL_ROOT, _exists


def _r_registry_exists() -> tuple[bool, str]:
    """B1.1 — registry synced with disk + no half-extracted dirs.

    A "half-extracted" directory is a subdir under a production namespace
    that lacks a matching ``<Name>.md`` (per the strict dir==name contract).
    Historically these were candidate scaffolds abandoned mid-extraction;
    leaving them under a production namespace created the *perception*
    of a ready primitive that B1.1 silently skipped. Reject them outright.
    """
    reg = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
    ok, msg = _exists(reg, min_bytes=500)
    if not ok:
        return ok, msg
    import yaml as _yaml

    data = _yaml.safe_load(reg.read_text()) or {}
    registered = {p["name"] for p in (data.get("primitives") or [])}
    venous = SKILL_ROOT / "core" / "venous"

    on_disk: set[str] = set()
    all_leaf_dirs: set[Path] = set()
    for d in venous.glob("*/*"):
        if not d.is_dir():
            continue
        if any(part in d.parts for part in ("_staging", "_adapters", "_ports", "__pycache__")):
            continue
        all_leaf_dirs.add(d)
        md = d / f"{d.name}.md"
        if md.exists():
            on_disk.add(d.name)

    missing = sorted(on_disk - registered)
    if missing:
        return False, f"{len(missing)} production primitives unregistered: {missing[:5]}"
    extra = sorted(registered - on_disk)
    if extra:
        return False, f"{len(extra)} registered primitives have no .md on disk: {extra[:5]}"
    half_extracted = sorted(
        str(d.relative_to(venous)) for d in all_leaf_dirs if not (d / f"{d.name}.md").exists()
    )
    if half_extracted:
        return False, (
            f"{len(half_extracted)} half-extracted dirs under production namespaces "
            f"(no matching .md) — move to _staging/ or complete them: {half_extracted[:5]}"
        )
    return True, f"registry synced: {len(registered)} entries match disk (no half-extracted dirs)"


def _r_compose_with_coverage() -> tuple[bool, str]:
    """B1.2 — every production primitive has a ≥3-bullet Compose-with section.

    CONTRACT §A5 requires ≥3 sibling pairings per primitive (so recipe
    retrieval has something meaningful to return). This rule checks both:
    section presence AND bullet count. Previously it only checked presence.
    """
    import yaml as _yaml

    reg = _yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
    venous = SKILL_ROOT / "core" / "venous"

    missing_section: list[str] = []
    under_three: list[str] = []
    for entry in reg.get("primitives", []):
        md = venous / entry["namespace"] / entry["name"] / f"{entry['name']}.md"
        if not md.exists():
            missing_section.append(f"{entry['namespace']}/{entry['name']}")
            continue
        body = md.read_text()
        m = re.search(r"## Compose with.*?(?=\n## |\Z)", body, re.DOTALL | re.IGNORECASE)
        if not m:
            missing_section.append(f"{entry['namespace']}/{entry['name']}")
            continue
        bullets = re.findall(r"^\s*-\s", m.group(), re.MULTILINE)
        if len(bullets) < 3:
            under_three.append(f"{entry['namespace']}/{entry['name']} ({len(bullets)})")

    if missing_section:
        return (
            False,
            f"{len(missing_section)} primitives lack 'Compose with:' section: {missing_section[:3]}",
        )
    if under_three:
        return False, (
            f"{len(under_three)} primitives have <3 Compose-with bullets "
            f"(§A5 requires ≥3): {under_three[:3]}"
        )
    return True, f"100% of {len(reg['primitives'])} primitives have ≥3 Compose-with bullets"


def _r_tools_import_primitives() -> tuple[bool, str]:
    """B1.3 — ≥15 extend add_* tools import a registered primitive.

    Authoritative count = catalog.json's `primitives_used` populated via
    the MCP_TOOL.imports_primitives declaration or real import scan. A
    docstring that merely mentions `core.venous.Foo.Bar` does NOT satisfy
    this rule (verified by the tightened scan in
    `engine.index.manifest._extract_primitive_imports`).

    The current floor (22) is a non-regression guarantee: no PR may
    reduce the count below this without updating the CONTRACT.
    """
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog_path.exists():
        return False, "catalog.json missing — run engine.index.manifest build"
    try:
        cat = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json unreadable: {exc}"
    connected = [
        t
        for t in cat.get("tools", [])
        if t.get("verb") == "add"
        and t.get("module_path", "").startswith("adapt/extend/")
        and t.get("primitives_used")
    ]
    floor = 22
    if len(connected) < floor:
        return False, (
            f"only {len(connected)}/100 extend add_* tools import primitives "
            f"(floor={floor}; regression bars PR)"
        )
    return True, (
        f"{len(connected)}/100 extend add_* tools primitive-connected "
        f"(floor={floor}, §B1.3 Rails-style wiring)"
    )


def _r_tier_lite_eligibility() -> tuple[bool, str]:
    """B1.8 — every `tier: "lite"` primitive satisfies §B1.8 eligibility.

    Reads `engine/primitives_by_concern.yaml`; for each entry with
    `tier == "lite"` verifies (all must be true):

    1. `core/venous/<namespace>/<Name>/<Name>.py` exists.
    2. That primary .py has no REPLACE_ME marker.
    3. That primary .py imports no framework modules (fastapi, starlette,
       sqlalchemy, sqlmodel, pydantic, django, flask, tornado, aiohttp),
       and declares no implicit framework tokens (`Mapped[`, `APIRouter(`,
       `Depends(`, `class Base(`).
    4. That primary .py contains no concurrency imports (threading,
       asyncio, multiprocessing) or names (Lock, Semaphore, Queue, etc.).

    Trivially green when zero lite primitives are registered. Satisfies
    CONTRACT §B1.8 and the 0004-tier-lite decision doc.
    """
    reg_path = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
    if not reg_path.exists():
        return False, "primitives_by_concern.yaml missing"
    try:
        import yaml as _yaml

        data = _yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"registry unreadable: {exc}"
    if not isinstance(data, dict):
        return False, "registry malformed"

    lite = [p for p in data.get("primitives", []) if p.get("tier") == "lite"]
    if not lite:
        return True, "§B1.8 vacuously satisfied (0 lite primitives registered)"

    # Lazy-import so contract_check doesn't pay promotion-module cost when
    # no lite primitives exist. The promotion module's AST helpers are the
    # single source of truth for these checks.
    import sys as _sys

    _sys.path.insert(0, str(SKILL_ROOT))
    from engine.promotion.state import (
        _detect_concurrency,
        _detect_framework_imports,
    )

    offenders: list[str] = []
    for p in lite:
        name = p.get("name")
        ns = p.get("namespace", "")
        if not name or not ns:
            offenders.append(f"{name or '?'}: registry entry missing name/namespace")
            continue
        py = SKILL_ROOT / "core" / "venous" / ns / name / f"{name}.py"
        if not py.exists():
            offenders.append(f"{name}: primary .py missing at {py.relative_to(SKILL_ROOT)}")
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            offenders.append(f"{name}: unreadable ({exc})")
            continue
        if "REPLACE_ME" in text:
            offenders.append(f"{name}: REPLACE_ME markers still present")
        fw = _detect_framework_imports(py)
        if fw:
            offenders.append(f"{name}: framework imports {fw}")
        if _detect_concurrency(py):
            offenders.append(
                f"{name}: concurrency imports present (lite forbids; promote at full tier)"
            )

    if offenders:
        joined = "\n    - ".join(offenders)
        return False, (
            f"§B1.8 lite eligibility violations ({len(offenders)}):\n    - {joined}\n"
            "Demote violating primitives to `_staging/` or promote at full tier."
        )
    return True, f"§B1.8 satisfied ({len(lite)} lite primitive(s), all eligible)"


def _r_no_manual_mcp_tool_decorator() -> tuple[bool, str]:
    gen = SKILL_ROOT / "mcp_tools" / "generators.py"
    if not gen.exists():
        return True, "mcp_tools/generators.py absent — auto-discovery only"
    body = gen.read_text()
    count = body.count("@mcp_app.tool")
    if count > 0:
        return False, f"{count} hardcoded @mcp_app.tool decorators in generators.py"
    return True, "no hardcoded @mcp_app.tool decorators"


def _r_adapter_coverage() -> tuple[bool, str]:
    """B1.7 — every FastAPI adapter under _adapters/fastapi/ has a matching
    test + maps to a registered primitive; floor of ≥15 adapters.

    Adapters are the thin framework-specific shims that wire framework-free
    primitives into FastAPI (ADR 0003). Without test coverage, a subtle
    adapter bug breaks every generated app silently — so each adapter must
    have a ``test_<Name>Adapter.py`` beside it, and every adapter must
    reference a primitive that exists in the registry.
    """
    import yaml as _yaml

    adapters_dir = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"
    if not adapters_dir.exists():
        return False, f"missing: {adapters_dir.relative_to(SKILL_ROOT)}"

    reg = _yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
    registered = {p["name"] for p in reg.get("primitives", [])}

    adapters = [f for f in adapters_dir.glob("*.py") if not f.name.startswith(("_", "test_"))]
    if len(adapters) < 15:
        return False, f"only {len(adapters)} fastapi adapters (need ≥15)"

    # Family-tag mapping: adapter filenames use a family prefix (e.g.
    # "Workflow", "OAuth2") that the §A3 naming convention does NOT require
    # to match a primitive name exactly. These families map to one or more
    # registered primitives — maintained here so adding a new adapter that
    # breaks the mapping fails B1.7 in CI.
    family_map = {
        "Workflow": {"WorkflowRun", "ActivityCall", "DurableTimer"},
        "AuditLog": {"AuditEvent", "TamperEvidentAuditLog", "AccessLog"},
        "OAuth2": {"AuthorizationCodeFlow", "TokenIntrospector", "SessionStore"},
        "WebhookReceiver": {"SignatureVerifier", "IdempotentConsumer", "InboxDeduplicator"},
        "Saga": {"SagaOrchestrator", "DomainEvent"},
    }

    missing_test: list[str] = []
    unknown_primitive: list[str] = []
    for a in adapters:
        if not (adapters_dir / f"test_{a.name}").exists():
            missing_test.append(a.stem)
        stem = a.stem
        # Convention: <PrimitiveOrFamily>Adapter.py
        if not stem.endswith("Adapter"):
            unknown_primitive.append(a.stem)
            continue
        prefix = stem[: -len("Adapter")]
        if prefix in registered:
            continue
        if prefix in family_map and family_map[prefix] & registered:
            continue
        if any(rn in stem for rn in registered):
            continue
        unknown_primitive.append(a.stem)

    if missing_test:
        return False, f"{len(missing_test)} adapters lack a test_*.py: {missing_test[:3]}"
    if unknown_primitive:
        return False, (
            f"{len(unknown_primitive)} adapters reference no registered primitive: "
            f"{unknown_primitive[:3]}"
        )
    return True, f"{len(adapters)} fastapi adapters, 100% tested + map to registry"


def _r_core_venous_distribution() -> tuple[bool, str]:
    """B1.0 — generate a sample project, copy a primitive into it, import it."""
    import sys
    import tempfile

    decision = REPO_ROOT / "docs" / "decisions" / "0002-core-venous-distribution.md"
    if not decision.exists():
        return False, "missing ADR: docs/decisions/0002-core-venous-distribution.md"

    scaffold = SKILL_ROOT / "generators" / "scaffold_venous.py"
    if not scaffold.exists():
        return False, "missing generators/scaffold_venous.py"

    # Ensure SKILL_ROOT is importable.
    skill_root_str = str(SKILL_ROOT)
    if skill_root_str not in sys.path:
        sys.path.insert(0, skill_root_str)

    try:
        from generators.orchestrator import generate_project
        from generators.scaffold_venous import ensure_primitives
    except ImportError as exc:
        return False, f"scaffold imports failed: {exc}"

    with tempfile.TemporaryDirectory() as tmp:
        generate_project(
            output_dir=tmp,
            name="contract_check_sample",
            profile="minimal",
            models={"Item": {"title": "str"}},
        )
        manifest = ensure_primitives(
            tmp,
            names=["core.venous.resiliency.GracefulShutdown"],
        )
        prim_file = (
            Path(tmp)
            / "core"
            / "venous"
            / "resiliency"
            / "GracefulShutdown"
            / "GracefulShutdown.py"
        )
        if not prim_file.exists():
            return False, f"primitive not copied into sample: {prim_file}"
        if not any(
            p["qualified_name"] == "core.venous.resiliency.GracefulShutdown"
            for p in manifest.primitives
        ):
            return False, "manifest missing GracefulShutdown entry"

        # Prove `from core.venous.resiliency.GracefulShutdown.GracefulShutdown
        # import GracefulShutdown` resolves inside the generated project.
        cmd = [
            sys.executable,
            "-c",
            "from core.venous.resiliency.GracefulShutdown.GracefulShutdown import GracefulShutdown; print('ok')",
        ]
        out = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, check=False)
        if out.returncode != 0 or "ok" not in out.stdout:
            return False, f"import in generated project failed: {out.stderr.strip()}"

    return True, "sample project imports copied primitive cleanly"


def _r_adapter_layer_invariant() -> tuple[bool, str]:
    """B1.0.1 — decision + reference adapter + zero framework leaks in primitives."""
    decision = REPO_ROOT / "docs" / "decisions" / "0003-adapter-layer.md"
    if not decision.exists():
        return False, "missing ADR: docs/decisions/0003-adapter-layer.md"

    ref = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi" / "GracefulShutdownAdapter.py"
    if not ref.exists():
        return False, f"missing reference adapter: {ref}"

    # grep equivalent — scan primitive .py files for FastAPI / Starlette / SQLAlchemy
    # imports; ignore _adapters/ and _staging/ which are out of scope.
    # Match only real top-of-line imports (not strings / comments).
    pat = re.compile(r"^\s*(?:from|import)\s+(fastapi|starlette|sqlalchemy)\b", re.MULTILINE)
    leaks: list[str] = []
    venous = SKILL_ROOT / "core" / "venous"
    for py in venous.rglob("*.py"):
        parts = py.parts
        if "_adapters" in parts or "_staging" in parts or "__pycache__" in parts:
            continue
        if pat.search(py.read_text(errors="ignore")):
            leaks.append(str(py.relative_to(SKILL_ROOT)))
    if leaks:
        return False, f"framework imports leaked into primitives: {leaks[:3]}..."
    return True, "primitives framework-agnostic; reference adapter present"


def _r_no_orphan_generators() -> tuple[bool, str]:
    """B1.6 — every top-level ``generate_X``/``scaffold_X`` function in
    generators/ and modules/**/tools/ is either MCP_TOOL-wrapped OR
    called by another module (internal helper). Prevents the Phase 2
    drift where generator files quietly shipped as non-discoverable code.

    Implementation: one walk of SKILL_ROOT builds a `{path: contents}`
    map, then each candidate function does an O(1) cached-dict scan
    for callers. Previously spawned one `grep -rl` subprocess per
    candidate (~60 of them), which dominated `_r_*` runtime.
    """
    bases = (
        "generators",
        "core/tools",
        "modules/database/tools",
        "modules/security/tools",
        "benchmark",
    )

    # One-pass corpus of every .py file in the skill tree. Populated
    # lazily — only if the base contains at least one candidate.
    _corpus: dict[Path, str] | None = None

    def _load_corpus() -> dict[Path, str]:
        nonlocal _corpus
        if _corpus is not None:
            return _corpus
        out: dict[Path, str] = {}
        for py in SKILL_ROOT.rglob("*.py"):
            parts = py.parts
            if ".venv" in parts or "__pycache__" in parts:
                continue
            try:
                out[py] = py.read_text(errors="ignore")
            except OSError:
                continue
        _corpus = out
        return out

    orphans: list[str] = []
    for base in bases:
        d = SKILL_ROOT / base
        if not d.exists():
            continue
        for py in d.rglob("*.py"):
            if py.name.startswith("__") or "__pycache__" in py.parts or py.name.startswith("test_"):
                continue
            txt = py.read_text(errors="ignore")
            if "MCP_TOOL" in txt:
                continue
            m = re.search(r"^def\s+(generate_\w+|scaffold_\w+)\s*\(", txt, re.MULTILINE)
            if not m:
                continue
            fn = m.group(1)
            # quick call-graph: ≥1 caller elsewhere in-tree → internal helper
            corpus = _load_corpus()
            callers = [p for p, c in corpus.items() if p != py and fn in c]
            if not callers:
                orphans.append(f"{py.relative_to(SKILL_ROOT)} ({fn})")
    if orphans:
        return False, f"orphan generators: {orphans}"
    return True, "every generate_*/scaffold_* function is either MCP_TOOL or internal helper"
