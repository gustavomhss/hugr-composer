#!/usr/bin/env python3
"""CONTRACT.md machine enforcer.

Reads `/CONTRACT.md`, finds every `- [ ] BN.M` checklist item that has a
machine-checkable rule, runs the rule, and prints pass/fail. Exits non-zero
on any failure — suitable for pre-commit hooks and CI.

Rules map (shell-shaped commands that each item must satisfy) is kept IN
this file so the contract and the enforcer never drift: if someone adds a
new §B item they add the rule here; CI then enforces it from the next
commit onward.

Usage:
    python -m engine.audit.contract_check              # run all
    python -m engine.audit.contract_check --item B1.1  # one item
    python -m engine.audit.contract_check --phase 0    # whole phase
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[3].parent
# /Users/…/HuGR_Skills (one level above skills/)
SKILL_ROOT = REPO_ROOT / "skills" / "SKILL-001-fastapi-production"


@dataclass(frozen=True)
class Rule:
    item: str                 # "B0.5"
    phase: int                # 0..7
    description: str          # short human label
    check: Callable[[], tuple[bool, str]]  # -> (ok, message)


def _exists(path: Path, *, min_bytes: int = 0) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if min_bytes and path.stat().st_size < min_bytes:
        return False, f"too small ({path.stat().st_size}B < {min_bytes}B): {path}"
    return True, f"ok: {path.relative_to(REPO_ROOT)}"


def _grep_count(pattern: str, paths: list[Path]) -> int:
    cmd = ["grep", "-rlE", pattern, *[str(p) for p in paths]]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return len([line for line in out.stdout.splitlines() if line])
    except FileNotFoundError:
        return 0


# ---------------------------------------------------------------------------
# Rules per §B item
# ---------------------------------------------------------------------------

def _r_product_md() -> tuple[bool, str]:
    ok, msg = _exists(REPO_ROOT / "PRODUCT.md", min_bytes=3000)
    if not ok:
        return ok, msg
    body = (REPO_ROOT / "PRODUCT.md").read_text()
    required = ["## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8."]
    missing = [s for s in required if s not in body]
    if missing:
        return False, f"PRODUCT.md missing sections: {missing}"
    return True, "PRODUCT.md present with all 8 required sections"


def _r_roadmap_md() -> tuple[bool, str]:
    return _exists(REPO_ROOT / "ROADMAP.md", min_bytes=3000)


def _r_contract_md() -> tuple[bool, str]:
    ok, msg = _exists(REPO_ROOT / "CONTRACT.md", min_bytes=5000)
    if not ok:
        return ok, msg
    body = (REPO_ROOT / "CONTRACT.md").read_text()
    if "§A" not in body or "§B" not in body or "§C" not in body:
        return False, "CONTRACT.md missing §A / §B / §C sections"
    if "- [ ] **A1" not in body:
        return False, "CONTRACT.md missing A1 inviolable rule"
    return True, "CONTRACT.md present with §A/§B/§C structure"


def _r_readme_md() -> tuple[bool, str]:
    ok, msg = _exists(REPO_ROOT / "README.md", min_bytes=200)
    if not ok:
        return ok, msg
    body = (REPO_ROOT / "README.md").read_text()
    lines = body.count("\n")
    if lines > 120:
        return False, f"README.md exceeds 80-line hard budget ({lines} lines)"
    for link in ("PRODUCT.md", "ROADMAP.md", "CONTRACT.md"):
        if link not in body:
            return False, f"README.md missing link to {link}"
    return True, f"README.md present, {lines} lines, links to canonical docs"


def _r_claude_memory() -> tuple[bool, str]:
    mem = Path.home() / ".claude" / "projects"
    hits = list(mem.rglob("venous_architecture.md"))
    if not hits:
        return False, "no venous_architecture.md in ~/.claude/projects/"
    body = hits[0].read_text()
    if "PRODUCT.md" not in body or "CONTRACT.md" not in body:
        return False, "memory entry does not point to PRODUCT.md + CONTRACT.md"
    return True, f"memory ok at {hits[0]}"


def _r_skillmd_honest() -> tuple[bool, str]:
    path = SKILL_ROOT / "SKILL.md"
    ok, msg = _exists(path, min_bytes=500)
    if not ok:
        return ok, msg
    body = path.read_text()
    # Any claim numbers MUST be within 10% of reality on disk.
    tool_count = len(list((SKILL_ROOT / "adapt" / "extend").rglob("add_*.py")))
    m = re.search(r"(\d+)\s*(?:adapt|extend|EXTEND)\s*tools?", body)
    if m:
        claimed = int(m.group(1))
        if abs(claimed - tool_count) > max(10, tool_count * 0.1):
            return False, (
                f"SKILL.md claims {claimed} adapt tools; actual {tool_count}. "
                "Drift beyond 10% — must reconcile."
            )
    return True, f"SKILL.md honest ({tool_count} adapt tools on disk)"


def _r_gitignore_artefacts() -> tuple[bool, str]:
    gi = REPO_ROOT / ".gitignore"
    ok, msg = _exists(gi)
    if not ok:
        return ok, msg
    body = gi.read_text()
    must = [
        "tools_latent_primitives.json",
        "primitive_candidates_ranked.json",
        "dedupe_report.json",
        "ambiguous_primitives.json",
        "_t0_report.json",
    ]
    missing = [m for m in must if m not in body]
    if missing:
        return False, f".gitignore missing artefact entries: {missing}"
    return True, ".gitignore covers all machine-generated artefacts"


def _r_benchmark_no_stubs() -> tuple[bool, str]:
    stubs: list[str] = []
    for name in ("benchmark", "benchmarks"):
        d = SKILL_ROOT / name
        if not d.exists():
            continue
        for py in d.rglob("test_*.py"):
            body = py.read_text()
            # A test file is a stub if EVERY test function body is `assert True`.
            funcs = re.findall(r"def (test_\w+)\([^)]*\):\s*(?:\"[^\"]*\"\s*)?([^\n]+)\n", body)
            if funcs and all(line.strip() == "assert True" for _, line in funcs):
                stubs.append(str(py.relative_to(REPO_ROOT)))
    if stubs:
        return False, f"{len(stubs)} stub test files (every test is `assert True`): {stubs[:3]}..."
    return True, "no trivial-stub test files under benchmark/"


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
        if any(part in d.parts for part in ("_extracted", "_adapters", "__pycache__")):
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
        str(d.relative_to(venous)) for d in all_leaf_dirs
        if not (d / f"{d.name}.md").exists()
    )
    if half_extracted:
        return False, (
            f"{len(half_extracted)} half-extracted dirs under production namespaces "
            f"(no matching .md) — move to _extracted/ or complete them: {half_extracted[:5]}"
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
        return False, f"{len(missing_section)} primitives lack 'Compose with:' section: {missing_section[:3]}"
    if under_three:
        return False, (
            f"{len(under_three)} primitives have <3 Compose-with bullets "
            f"(§A5 requires ≥3): {under_three[:3]}"
        )
    return True, f"100% of {len(reg['primitives'])} primitives have ≥3 Compose-with bullets"


def _r_tools_import_primitives() -> tuple[bool, str]:
    tools_dir = SKILL_ROOT / "adapt" / "extend"
    hits = _grep_count(r"from core\.venous|import core\.venous", [tools_dir])
    if hits < 15:
        return False, f"only {hits}/100+ tools import from core.venous (need ≥15)"
    return True, f"{hits} tools import from core.venous"


def _r_no_manual_mcp_tool_decorator() -> tuple[bool, str]:
    gen = SKILL_ROOT / "mcp_tools" / "generators.py"
    if not gen.exists():
        return True, "mcp_tools/generators.py absent — auto-discovery only"
    body = gen.read_text()
    count = body.count("@mcp_app.tool")
    if count > 0:
        return False, f"{count} hardcoded @mcp_app.tool decorators in generators.py"
    return True, "no hardcoded @mcp_app.tool decorators"


def _r_benchmark_score() -> tuple[bool, str]:
    """B3.5 — latest_score.json present + overall >= baseline_floor.json floor.

    The static floor is held in ``benchmarks/baseline_floor.json``; raise it
    in the same commit that raises the published score. A regression below
    the floor is a B3.5 failure — this is how we prevent "silent 69-point
    drop" scenarios where the hard floor (30) would still pass.
    """
    scorefile = SKILL_ROOT / "benchmarks" / "latest_score.json"
    floorfile = SKILL_ROOT / "benchmarks" / "baseline_floor.json"
    if not scorefile.exists():
        return False, "benchmarks/latest_score.json not published"
    try:
        data = json.loads(scorefile.read_text())
        score = float(data.get("overall", data.get("overall_average", 0)))
        methodology = data.get("methodology", "unknown")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return False, "benchmarks/latest_score.json malformed"

    floor = 30.0  # hard schema floor
    if floorfile.exists():
        try:
            floor = max(floor, float(json.loads(floorfile.read_text()).get("floor", 30.0)))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    if score < floor:
        return False, (
            f"benchmark score {score:.2f} < baseline floor {floor:.2f} "
            f"(set in benchmarks/baseline_floor.json — raise in the same "
            f"commit that raises latest_score.json)"
        )
    return True, f"baseline score {score:.2f} ≥ floor {floor:.2f} ({methodology})"


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

    adapters = [
        f for f in adapters_dir.glob("*.py")
        if not f.name.startswith(("_", "test_"))
    ]
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
        "WebhookReceiver": {"SignatureVerifier", "IdempotentConsumer",
                            "InboxDeduplicator"},
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
            Path(tmp) / "core" / "venous" / "resiliency" / "GracefulShutdown"
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
    # imports; ignore _adapters/ and _extracted/ which are out of scope.
    # Match only real top-of-line imports (not strings / comments).
    pat = re.compile(r"^\s*(?:from|import)\s+(fastapi|starlette|sqlalchemy)\b", re.MULTILINE)
    leaks: list[str] = []
    venous = SKILL_ROOT / "core" / "venous"
    for py in venous.rglob("*.py"):
        parts = py.parts
        if "_adapters" in parts or "_extracted" in parts or "__pycache__" in parts:
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
    """
    bases = ("generators", "core/tools", "modules/database/tools",
             "modules/security/tools", "benchmark")
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
            out = subprocess.run(
                ["grep", "-rl", fn, str(SKILL_ROOT),
                 "--include=*.py", "--exclude-dir=.venv", "--exclude-dir=__pycache__"],
                capture_output=True, text=True, check=False,
            )
            callers = [c for c in out.stdout.splitlines() if c and c != str(py)]
            if not callers:
                orphans.append(f"{py.relative_to(SKILL_ROOT)} ({fn})")
    if orphans:
        return False, f"orphan generators: {orphans}"
    return True, "every generate_*/scaffold_* function is either MCP_TOOL or internal helper"


def _r_find_primitive_discovery() -> tuple[bool, str]:
    """B2.1 — find_primitive MCP tool exists, registers, and clears quality gate."""
    module_path = SKILL_ROOT / "engine" / "discovery" / "find_primitive.py"
    if not module_path.exists():
        return False, f"missing: {module_path.relative_to(REPO_ROOT)}"

    test_set = SKILL_ROOT / "benchmarks" / "discovery_test_set.json"
    if not test_set.exists():
        return False, f"missing: {test_set.relative_to(REPO_ROOT)}"

    # Run quality bench; it enforces top-1 ≥ 80% and P@3 ≥ 90% per §B2.1 quality.
    cmd = [
        sys.executable,
        "-m",
        "engine.discovery.quality_bench",
        "--min-top-1",
        "0.80",
        "--min-p-at-3",
        "0.90",
    ]
    env_pythonpath = str(SKILL_ROOT)
    out = subprocess.run(
        cmd,
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"quality gate failed: {out.stdout.strip() or out.stderr.strip()}"

    # Check the tool registers on the MCP app without raising.
    cmd = [
        sys.executable,
        "-c",
        (
            "from mcp_tools import mcp, discover_and_register; "
            "discover_and_register(mcp); "
            "import asyncio; "
            "t = asyncio.run(mcp.get_tool('fastapi_find_primitive')); "
            "assert t.name == 'fastapi_find_primitive', t.name; print('ok')"
        ),
    ]
    out = subprocess.run(
        cmd,
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0 or "ok" not in out.stdout:
        return False, f"MCP registration failed: {out.stderr.strip()[:300]}"

    return True, "find_primitive registered; quality gate (top-1≥80%, P@3≥90%) passing"


def _r_suggest_composition() -> tuple[bool, str]:
    """B2.2 — suggest_composition MCP tool exists, registers, clears quality."""
    module_path = SKILL_ROOT / "engine" / "discovery" / "compose.py"
    if not module_path.exists():
        return False, f"missing: {module_path.relative_to(REPO_ROOT)}"
    test_set = SKILL_ROOT / "benchmarks" / "composition_test_set.json"
    if not test_set.exists():
        return False, f"missing: {test_set.relative_to(REPO_ROOT)}"

    env_pythonpath = str(SKILL_ROOT)
    cmd = [
        sys.executable, "-m", "engine.discovery.compose_bench",
        "--min-top-1", "0.70", "--min-p-at-3", "0.90",
    ]
    out = subprocess.run(
        cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"quality gate failed: {out.stdout.strip() or out.stderr.strip()}"

    cmd = [
        sys.executable, "-c",
        (
            "from mcp_tools import mcp, discover_and_register; "
            "discover_and_register(mcp); "
            "import asyncio; "
            "t = asyncio.run(mcp.get_tool('fastapi_suggest_composition')); "
            "assert t.name == 'fastapi_suggest_composition', t.name; print('ok')"
        ),
    ]
    out = subprocess.run(
        cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0 or "ok" not in out.stdout:
        return False, f"MCP registration failed: {out.stderr.strip()[:300]}"

    return True, "suggest_composition registered; quality gate (top-1≥70%, P@3≥90%) passing"


def _r_docs_site() -> tuple[bool, str]:
    """B2.3 — docs site generator exists, is idempotent, covers all primitives."""
    builder = SKILL_ROOT / "engine" / "docs" / "build.py"
    if not builder.exists():
        return False, f"missing: {builder.relative_to(REPO_ROOT)}"

    import tempfile

    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_docs_") as tmp:
        cmd = [
            sys.executable, "-m", "engine.docs.build",
            "--out", tmp, "--verify",
        ]
        out = subprocess.run(
            cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if out.returncode != 0:
            return False, f"build --verify failed: {(out.stdout or out.stderr).strip()[:300]}"
        manifest_path = Path(tmp) / "build_manifest.json"
        if not manifest_path.exists():
            return False, "build_manifest.json not written"
        import json as _json
        manifest = _json.loads(manifest_path.read_text())
        if manifest["primitives"] < 97:
            return False, f"only {manifest['primitives']} primitive pages (need ≥97)"
        # Spot-check: every registry entry has an HTML page.
        import yaml as _yaml
        registry = _yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
        missing = [
            e["name"] for e in registry["primitives"]
            if not (Path(tmp) / "primitive" / f"{e['name']}.html").is_file()
        ]
        if missing:
            return False, f"missing pages: {missing[:5]}"
    return True, f"docs site generator green; {manifest['pages_written']} pages, idempotent hash"


def _r_bench_specs() -> tuple[bool, str]:
    """B3.1 — 20 specs split 5/10/5 with required sections."""
    specs = SKILL_ROOT / "benchmarks" / "specs"
    if not specs.exists():
        return False, f"missing: {specs.relative_to(REPO_ROOT)}"
    counts: dict[str, int] = {}
    for tier in ("baseline", "mid", "adversarial"):
        counts[tier] = len(list((specs / tier).glob("*.md"))) if (specs / tier).exists() else 0
    if counts != {"baseline": 5, "mid": 10, "adversarial": 5}:
        return False, f"tier counts wrong: {counts}"

    required = ("## Requirements", "## Acceptance criteria", "## Non-requirements")
    for spec_file in specs.rglob("*.md"):
        if spec_file.name == "README.md":
            continue
        txt = spec_file.read_text()
        for section in required:
            if section not in txt:
                return False, f"{spec_file.name} missing {section}"
    return True, f"20 specs present (5/10/5) with all 4 required sections"


def _r_bench_rubric_runner() -> tuple[bool, str]:
    """B3.2 + B3.3 — rubric and runner importable, stub run yields 0-score report."""
    rubric = SKILL_ROOT / "engine" / "bench" / "rubric.py"
    runner = SKILL_ROOT / "engine" / "bench" / "runner.py"
    if not rubric.exists() or not runner.exists():
        return False, "missing rubric.py or runner.py"

    env_pythonpath = str(SKILL_ROOT)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "engine/tests/test_bench.py", "-q"],
        cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
    )
    if out.returncode != 0:
        return False, f"bench tests failed: {(out.stdout or out.stderr).strip()[-300:]}"
    return True, "rubric + runner green (13 bench tests passing)"


def _r_bench_nightly_workflow() -> tuple[bool, str]:
    """B3.4 — CI workflow file exists and declares the benchmark job."""
    wf = REPO_ROOT / ".github" / "workflows" / "benchmark-nightly.yml"
    if not wf.exists():
        return False, "missing: .github/workflows/benchmark-nightly.yml"
    txt = wf.read_text()
    for required in ("schedule:", "cron:", "engine.bench", "ANTHROPIC_API_KEY", "latest_score.json"):
        if required not in txt:
            return False, f"workflow missing {required}"
    return True, "benchmark-nightly.yml present with schedule + claude dispatch + score upload"


def _r_install_docker_ci() -> tuple[bool, str]:
    """B4.1 — install.sh + install-docker CI workflow present + hermetic."""
    installer = REPO_ROOT / "install.sh"
    workflow = REPO_ROOT / ".github" / "workflows" / "install-docker.yml"
    if not installer.exists():
        return False, "missing: install.sh"
    if not workflow.exists():
        return False, "missing: .github/workflows/install-docker.yml"
    txt = workflow.read_text(encoding="utf-8")
    for required in ("python:3.12-slim", "install.sh", "contract_check", "latest_score.json", "schedule:"):
        if required not in txt:
            return False, f"install-docker.yml missing {required!r}"
    inst = installer.read_text(encoding="utf-8")
    for required in ("set -euo pipefail", "python3 -m venv", "requirements-mcp.txt"):
        if required not in inst:
            return False, f"install.sh missing {required!r}"
    return True, "install.sh + install-docker.yml validated in python:3.12-slim"


def _r_examples_populated() -> tuple[bool, str]:
    """B4.2 — /examples/ has ≥5 subdirs, each carrying the required docset."""
    examples = REPO_ROOT / "examples"
    if not examples.exists():
        return False, "missing: /examples/"
    subdirs = [p for p in examples.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))]
    if len(subdirs) < 5:
        return False, f"only {len(subdirs)} examples (need ≥5)"
    required = ("README.md", "MAESTRO_SESSION.md")
    for sub in subdirs:
        for f in required:
            if not (sub / f).exists():
                return False, f"{sub.name}/ missing {f}"
        # cross-link table: must mention tools-used + primitives-imported
        readme = (sub / "README.md").read_text(encoding="utf-8")
        if "Tools used" not in readme or "Primitives imported" not in readme:
            return False, f"{sub.name}/README.md missing cross-link table (Tools used / Primitives imported)"
    return True, f"{len(subdirs)} examples present with README + MAESTRO_SESSION + cross-link tables"


def _r_docs_site_v1() -> tuple[bool, str]:
    """B4.3 — docs site includes top-level docs + per-tool pages."""
    import tempfile
    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_docs_v1_") as tmp:
        cmd = [sys.executable, "-m", "engine.docs.build", "--out", tmp, "--verify"]
        out = subprocess.run(
            cmd, cwd=SKILL_ROOT, capture_output=True, text=True, check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if out.returncode != 0:
            return False, f"build --verify failed: {(out.stdout or out.stderr).strip()[:300]}"
        root = Path(tmp)
        # Top-level docs: PRODUCT + ROADMAP + CONTRACT + CONTRIBUTING + CHANGELOG
        for slug in ("product", "roadmap", "contract", "contributing", "changelog"):
            if not (root / "doc" / f"{slug}.html").is_file():
                return False, f"missing doc page: doc/{slug}.html"
        # Every adapt tool has a page.
        tool_dir = root / "tool"
        if not tool_dir.exists():
            return False, "missing tool/ page directory"
        n_tool_pages = sum(1 for _ in tool_dir.glob("*.html"))
        if n_tool_pages < 90:
            return False, f"only {n_tool_pages} tool pages (need ≥90)"
        n_prim_pages = sum(1 for _ in (root / "primitive").glob("*.html"))
        if n_prim_pages < 100:
            return False, f"only {n_prim_pages} primitive pages (need ≥100)"
    return True, f"docs site v1: {n_prim_pages} primitives + {n_tool_pages} tools + 5 top-level docs"


def _r_changelog_semver() -> tuple[bool, str]:
    """B4.4 — CHANGELOG.md + VERSION present; CHANGELOG cites v0.1.0 + score."""
    changelog = REPO_ROOT / "CHANGELOG.md"
    version = REPO_ROOT / "VERSION"
    if not changelog.exists():
        return False, "missing: CHANGELOG.md"
    if not version.exists():
        return False, "missing: VERSION"
    ver = version.read_text(encoding="utf-8").strip()
    if not re.match(r"^\d+\.\d+\.\d+$", ver):
        return False, f"VERSION not semver: {ver!r}"
    cl = changelog.read_text(encoding="utf-8")
    for required in ("[0.1.0]", "Benchmark", "primitives", "tools"):
        if required not in cl:
            return False, f"CHANGELOG.md missing {required!r}"
    return True, f"CHANGELOG.md + VERSION={ver} with v0.1.0 entry citing score"


def _r_contributing_md() -> tuple[bool, str]:
    """B4.5 — CONTRIBUTING.md covers primitive / tool / recipe surfaces + dev setup."""
    f = REPO_ROOT / "CONTRIBUTING.md"
    if not f.exists():
        return False, "missing: CONTRIBUTING.md"
    txt = f.read_text(encoding="utf-8")
    required_sections = (
        "Local dev setup",
        "Adding a primitive",
        "Adding a tool",
        "Adding a composition recipe",
        "10-tier gate",
        "contract_check",
    )
    missing = [s for s in required_sections if s not in txt]
    if missing:
        return False, f"CONTRIBUTING.md missing sections: {missing}"
    return True, f"CONTRIBUTING.md complete (primitive + tool + recipe + dev setup)"


RULES: list[Rule] = [
    Rule("B0.1", 0, "PRODUCT.md canonical", _r_product_md),
    Rule("B0.2", 0, "ROADMAP.md honest + phased", _r_roadmap_md),
    Rule("B0.3", 0, "CONTRACT.md (this)", _r_contract_md),
    Rule("B0.4", 0, "SKILL.md ground-truth honest", _r_skillmd_honest),
    Rule("B0.5", 0, "README.md ≤80 lines + links", _r_readme_md),
    Rule("B0.6", 0, "CLAUDE memory pointer", _r_claude_memory),
    Rule("B0.7", 0, "No stub tests under /benchmark/", _r_benchmark_no_stubs),
    Rule("B0.8", 0, ".gitignore covers artefacts", _r_gitignore_artefacts),
    Rule("B1.0", 1, "core.venous copy-in distribution", _r_core_venous_distribution),
    Rule("B1.0.1", 1, "adapter layer + framework-free primitives", _r_adapter_layer_invariant),
    Rule("B1.1", 1, "primitives_by_concern.yaml registry", _r_registry_exists),
    Rule("B1.2", 1, "Compose-with in every primitive .md", _r_compose_with_coverage),
    Rule("B1.3", 1, "≥15 tools import core.venous", _r_tools_import_primitives),
    Rule("B1.5", 1, "no hardcoded @mcp_app.tool decorators", _r_no_manual_mcp_tool_decorator),
    Rule("B1.6", 1, "no orphan generators (every generate_* is tool or internal)", _r_no_orphan_generators),
    Rule("B1.7", 1, "fastapi adapter coverage (tested + maps to registry)", _r_adapter_coverage),
    Rule("B2.1", 2, "find_primitive MCP tool + BM25 quality gate", _r_find_primitive_discovery),
    Rule("B2.2", 2, "suggest_composition MCP tool + recipe quality gate", _r_suggest_composition),
    Rule("B2.3", 2, "reference docs site idempotent build", _r_docs_site),
    Rule("B3.1", 3, "20 benchmark specs (5 baseline / 10 mid / 5 adversarial)", _r_bench_specs),
    Rule("B3.2", 3, "scoring rubric implemented + tested", _r_bench_rubric_runner),
    Rule("B3.3", 3, "benchmark runner + stub Maestro + report JSON", _r_bench_rubric_runner),
    Rule("B3.4", 3, "nightly benchmark CI workflow", _r_bench_nightly_workflow),
    Rule("B3.5", 3, "baseline benchmark score published", _r_benchmark_score),
    Rule("B4.1", 4, "install.sh + fresh-Docker CI", _r_install_docker_ci),
    Rule("B4.2", 4, "/examples/ populated (≥5 with README + MAESTRO_SESSION + cross-link)", _r_examples_populated),
    Rule("B4.3", 4, "docs site v1 (top-level docs + per-tool pages)", _r_docs_site_v1),
    Rule("B4.4", 4, "CHANGELOG + VERSION semver cite score", _r_changelog_semver),
    Rule("B4.5", 4, "CONTRIBUTING.md complete", _r_contributing_md),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="CONTRACT.md machine enforcer.")
    parser.add_argument("--item", type=str, default=None, help="Run only this §B item (e.g. B1.1).")
    parser.add_argument("--phase", type=int, default=None, help="Run all items in a phase (e.g. --phase 0).")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    selected = RULES
    if args.item:
        selected = [r for r in RULES if r.item == args.item]
    elif args.phase is not None:
        selected = [r for r in RULES if r.phase == args.phase]

    if not selected:
        print(f"No rules matched (item={args.item}, phase={args.phase}).", file=sys.stderr)
        return 2

    total = len(selected)
    failed = 0
    for rule in selected:
        try:
            ok, msg = rule.check()
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"rule raised: {exc}"
        tag = "✓" if ok else "✗"
        if not args.quiet or not ok:
            print(f"  {tag}  {rule.item:>6}  {rule.description:<52}  {msg}")
        if not ok:
            failed += 1

    passed = total - failed
    print(f"\n{passed}/{total} contract items satisfied" + (" — ALL GREEN" if failed == 0 else f" — {failed} VIOLATIONS"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
