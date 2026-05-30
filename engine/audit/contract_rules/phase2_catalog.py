"""Phase 2 catalog — discovery + manifest + schema (CONTRACT.md §B2.1–§B2.4 + §B2.8).

CONTRACT.md scope: §B2.1 find_primitive discovery, §B2.2 suggest_composition,
§B2.3 docs site idempotent build, §B2.4 index catalog manifest synced
+ deterministic, §B2.8 catalog.json schema_version == "2.0" + v2 fields.

Cohesion: every rule subprocess-shells into ``engine.{discovery,docs,index}.*``
modules, parses the catalog manifest, and/or exercises an MCP-tool
registration smoke. They share the ``env_pythonpath = str(SKILL_ROOT)`` +
``subprocess`` pattern.

B2.5 (skill_md_contract) and B2.6 + B2.7 (tier-1 surface) live in
sibling modules (``phase2_skill_md`` and ``phase2_tier1``); see WP-16 §3.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ._common import REPO_ROOT, SKILL_ROOT


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
            "t = asyncio.run(mcp.get_tool('fastapi_meta_search_primitive')); "
            "assert t.name == 'fastapi_meta_search_primitive', t.name; print('ok')"
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
        sys.executable,
        "-m",
        "engine.discovery.compose_bench",
        "--min-top-1",
        "0.70",
        "--min-p-at-3",
        "0.90",
    ]
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

    cmd = [
        sys.executable,
        "-c",
        (
            "from mcp_tools import mcp, discover_and_register; "
            "discover_and_register(mcp); "
            "import asyncio; "
            "t = asyncio.run(mcp.get_tool('fastapi_meta_search_composition')); "
            "assert t.name == 'fastapi_meta_search_composition', t.name; print('ok')"
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
            sys.executable,
            "-m",
            "engine.docs.build",
            "--out",
            tmp,
            "--verify",
        ]
        out = subprocess.run(
            cmd,
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
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

        registry = _yaml.safe_load(
            (SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text()
        )
        missing = [
            e["name"]
            for e in registry["primitives"]
            if not (Path(tmp) / "primitive" / f"{e['name']}.html").is_file()
        ]
        if missing:
            return False, f"missing pages: {missing[:5]}"
    return True, f"docs site generator green; {manifest['pages_written']} pages, idempotent hash"


def _r_index_manifest() -> tuple[bool, str]:
    """B2.4 — engine/index/catalog.json is synced with the on-disk sources.

    Runs `python -m engine.index.manifest build` into a tempdir, compares
    the fresh stable-hash with the committed hash. Drift = failure.
    Also asserts the committed file is schema-valid.
    """
    catalog = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog.exists():
        return False, f"missing: {catalog.relative_to(SKILL_ROOT)}"
    try:
        data = json.loads(catalog.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"catalog.json malformed: {exc}"
    schema_version = data.get("schema_version")
    if schema_version != "2.0":
        return False, f"catalog.json schema_version={schema_version!r}; expected '2.0'"
    counts = data.get("counts") or {}
    # Schema v2: tools_total replaces v1's flat `tools` key (ADR-0003).
    for field, minimum in (
        ("tools_total", 150),
        ("primitives", 100),
        ("recipes", 200),
        ("skills", 1),
        ("bundles", 6),
    ):
        if int(counts.get(field, 0)) < minimum:
            return False, f"catalog.json counts.{field}={counts.get(field)} < floor {minimum}"

    # Determinism check — rebuild into a tempdir and compare stable hashes.
    import tempfile

    env_pythonpath = str(SKILL_ROOT)
    with tempfile.TemporaryDirectory(prefix="hugr_manifest_") as tmp:
        out_path = Path(tmp) / "catalog.json"
        proc = subprocess.run(
            [sys.executable, "-m", "engine.index.manifest", "verify", "--out", str(out_path)],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**__import__("os").environ, "PYTHONPATH": env_pythonpath},
        )
        if proc.returncode != 0:
            return False, f"manifest verify failed: {(proc.stdout + proc.stderr)[-300:]}"
        # Compare committed catalog's stable content (ignoring generated_at + kit_commit)
        live = json.loads(out_path.read_text())
        committed = json.loads(catalog.read_text())
        for f in ("generated_at", "kit_commit"):
            live.pop(f, None)
            committed.pop(f, None)
        if json.dumps(live, sort_keys=True) != json.dumps(committed, sort_keys=True):
            return False, (
                "engine/index/catalog.json drifted from on-disk sources. "
                "Regenerate via `python -m engine.index.manifest build` and commit."
            )
    return True, (
        f"catalog synced: {counts.get('tools_total')} tools "
        f"({counts.get('skills')} skill / {counts.get('bundles')} bundles), "
        f"{counts.get('primitives')} primitives, {counts.get('recipes')} recipes"
    )


def _r_catalog_schema_version() -> tuple[bool, str]:
    """B2.8 — `catalog.json schema_version == "2.0"` (the v2 invariant).

    Schema v2 (ADR-0003) was a breaking change for internal consumers
    (Tier-1 router, audit, INVENTORY emitter). Pinning the on-disk
    schema_version here means a future bump to v3 cannot land without
    explicitly retiring this rule and updating every consumer — closes
    the class of half-migrations the WAVE-0-F0 audit surfaced.
    """
    catalog = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if not catalog.exists():
        return False, (
            f"missing: {catalog.relative_to(SKILL_ROOT)} — "
            "run `python -m engine.index.manifest build`"
        )
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"catalog.json malformed: {exc}"
    sv = data.get("schema_version")
    if sv != "2.0":
        return False, (
            f"catalog.json schema_version={sv!r}; expected '2.0' "
            "(set in engine/index/__init__.py::MANIFEST_SCHEMA_VERSION)"
        )
    # Sanity: skills array must be present + non-empty + every tool
    # must carry skill + bundle fields. These were added in v2 (ADR-0003).
    skills = data.get("skills") or []
    if not skills:
        return False, "catalog.json schema_version=2.0 but `skills` array is empty"
    tools = data.get("tools") or []
    for t in tools[:5]:  # cheap sample — manifest invariants enforce the full check
        if "skill" not in t or "bundle" not in t:
            return False, (
                "catalog.json tool entry missing v2 fields `skill`/`bundle` "
                f"(offender: {t.get('name')!r})"
            )
    return True, f"catalog.json schema_version='2.0' with {len(skills)} skill(s)"
