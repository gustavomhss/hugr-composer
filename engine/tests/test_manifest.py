"""Unit tests for engine.index.manifest — the single source of truth."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.index.manifest import (
    CATALOG_PATH, ManifestError, build, write,
    _canonical_tool_name, _infer_domain, _infer_verb, _infer_tags,
    _extract_intent, _slugify,
)
from engine.index.schemas import DOMAINS, TAG_VOCABULARY, VERBS


# ---------------------------------------------------------------------------
# High-level build
# ---------------------------------------------------------------------------

def test_build_succeeds_and_produces_expected_counts() -> None:
    m = build()
    assert m.counts["tools"] >= 150, f"too few tools: {m.counts['tools']}"
    assert m.counts["primitives"] == 122, m.counts
    assert m.counts["recipes"] >= 250
    assert m.schema_version == "2"


def test_build_is_deterministic(tmp_path: Path) -> None:
    m1 = build()
    m2 = build()
    p1 = tmp_path / "c1.json"
    p2 = tmp_path / "c2.json"
    h1 = write(m1, p1)
    h2 = write(m2, p2)
    assert h1 == h2, "stable hash drifted across two builds — breaks prompt cache"


def test_committed_catalog_matches_fresh_build() -> None:
    """benchmarks/blind/catalog.json on disk must match a fresh build
    (ignoring generated_at and kit_commit, which are legitimately variable).
    """
    m = build()
    live = m.model_dump(mode="json")
    live.pop("generated_at", None)
    live.pop("kit_commit", None)
    committed = json.loads(CATALOG_PATH.read_text())
    committed.pop("generated_at", None)
    committed.pop("kit_commit", None)
    # Compare ignoring ordering of sibling dicts by dumping sorted.
    assert json.dumps(live, sort_keys=True) == json.dumps(committed, sort_keys=True), (
        "engine/index/catalog.json drifted from on-disk sources; "
        "run `python -m engine.index.manifest build` and commit"
    )


# ---------------------------------------------------------------------------
# Entry invariants
# ---------------------------------------------------------------------------

def test_every_tool_verb_domain_in_closed_vocab() -> None:
    m = build()
    for t in m.tools:
        assert t.verb in VERBS, f"{t.name}: verb {t.verb!r} not in VERBS"
        assert t.domain in DOMAINS, f"{t.name}: domain {t.domain!r} not in DOMAINS"
        for tag in t.tags:
            assert tag in TAG_VOCABULARY, f"{t.name}: tag {tag!r} not in TAG_VOCABULARY"


def test_every_tool_primitives_used_are_registered() -> None:
    m = build()
    registered = {p.name for p in m.primitives}
    for t in m.tools:
        for p in t.primitives_used:
            assert p in registered, f"{t.name}: references unregistered primitive {p!r}"


def test_no_duplicate_tool_names() -> None:
    m = build()
    names = [t.name for t in m.tools]
    assert len(names) == len(set(names)), "duplicate tool names in manifest"


def test_tools_sorted_by_domain_verb_name() -> None:
    m = build()
    keys = [(t.domain, t.verb, t.name) for t in m.tools]
    assert keys == sorted(keys), "tools not in (domain, verb, name) order"


def test_primitives_sorted_by_namespace_name() -> None:
    m = build()
    keys = [(p.namespace, p.name) for p in m.primitives]
    assert keys == sorted(keys), "primitives not in (namespace, name) order"


def test_recipes_sorted_by_id() -> None:
    m = build()
    ids = [r.id for r in m.recipes]
    assert ids == sorted(ids), "recipes not sorted by id"


def test_every_recipe_references_at_least_one_registered_primitive() -> None:
    m = build()
    registered = {p.name for p in m.primitives}
    for r in m.recipes:
        hits = [p for p in r.primitives if p in registered]
        assert hits, f"recipe {r.id} has no registered primitives: {r.primitives}"


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def test_infer_verb_from_add_prefix() -> None:
    assert _infer_verb("fastapi_add_rbac", "add_rbac") == "add"


def test_infer_verb_from_generate_prefix() -> None:
    assert _infer_verb("fastapi_generate_project", "orchestrator") == "generate"


def test_infer_verb_from_scaffold_maps_to_generate() -> None:
    assert _infer_verb("scaffold_db", "scaffold_db") == "generate"


def test_infer_domain_from_adapt_extend_auth_access() -> None:
    p = Path("adapt/extend/auth_access/add_oauth2_provider.py")
    assert _infer_domain(p, "fastapi_add_oauth2_provider") == "auth"


def test_infer_domain_from_infrastructure_observability_keyword() -> None:
    p = Path("adapt/extend/infrastructure/add_observability_stack.py")
    # infrastructure bucket + observability keyword → observability domain
    assert _infer_domain(p, "fastapi_add_observability_stack") == "observability"


def test_infer_tags_hits_closed_vocab() -> None:
    tags = _infer_tags("fastapi_add_rate_limiting", "add_rate_limiting")
    assert "rate-limit" in tags


def test_canonical_tool_name_renames_to_domain_verb_noun() -> None:
    n = _canonical_tool_name("add", "auth", "fastapi_add_oauth2_provider")
    assert n == "fastapi_auth_add_oauth2_provider"


def test_extract_intent_parses_bold_after_arrow() -> None:
    body = "`A` + `B` → **compose webhook with dedup + audit**. Use when..."
    assert _extract_intent(body) == "compose webhook with dedup + audit"


def test_slugify_collapses_nonalnum() -> None:
    assert _slugify("Compose! webhook+dedup/audit") == "compose-webhook-dedup-audit"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_manifest_error_raised_on_duplicate_mcp_name(tmp_path: Path, monkeypatch) -> None:
    """Plant two modules with the same MCP_TOOL name; scanner must reject.

    We have to plant the files UNDER SKILL_ROOT so `relative_to(SKILL_ROOT)`
    resolves. Use a tmp dir inside the skill's engine/ tree and clean up.
    """
    import engine.index.manifest as mod
    fake_root = mod.SKILL_ROOT / "engine" / "_manifest_test_fixtures"
    try:
        fake_root.mkdir(parents=True, exist_ok=True)
        (fake_root / "a.py").write_text(
            'MCP_TOOL = {"name": "fastapi_dup_demo", "description": "a"}\n'
        )
        (fake_root / "b.py").write_text(
            'MCP_TOOL = {"name": "fastapi_dup_demo", "description": "b"}\n'
        )
        monkeypatch.setattr(mod, "TOOL_SCAN_ROOTS", (("fake", fake_root),))
        with pytest.raises(ManifestError, match="duplicate MCP_TOOL name"):
            mod._scan_tools()
    finally:
        import shutil
        shutil.rmtree(fake_root, ignore_errors=True)
