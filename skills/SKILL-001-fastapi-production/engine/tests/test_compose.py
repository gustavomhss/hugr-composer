"""Unit tests for mcp_tools.compose — the last-mile composition tool."""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from mcp_tools.compose import (
    DOMAIN_PRIMITIVE_BLACKLIST, MCP_TOOL,
    fastapi_meta_compose, _adapter_index, _derive_slug, _snake,
)


# ---------------------------------------------------------------------------
# Envelope + registration
# ---------------------------------------------------------------------------

def test_envelope_shape_on_success(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"], dry_run=True)
    assert r["ok"] is True
    required = {"ok", "what_happened", "result", "next_steps", "elapsed_ms"}
    assert required <= r.keys()
    assert len(r["next_steps"]) <= 5
    res = r["result"]
    for f in ("mode", "slug", "composition_source", "files_written",
              "primitives_used", "wiring_summary", "mount", "validation_report"):
        assert f in res, f"missing {f} in result"


def test_registered_as_mcp_tier1() -> None:
    import asyncio
    from mcp_tools.server import mcp as _mcp
    from mcp_tools.discovery import discover_and_register
    discover_and_register(_mcp)
    names = {t.name for t in asyncio.run(_mcp.list_tools())}
    assert "fastapi_meta_compose" in names, "compose must register as a tier-1 MCP tool"


def test_mcp_tool_metadata_has_required_fields() -> None:
    for k in ("name", "description", "tags", "entry"):
        assert k in MCP_TOOL
    assert MCP_TOOL["name"] == "fastapi_meta_compose"
    assert len(MCP_TOOL["description"]) >= 200, "description must be detailed (Anthropic guidance)"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_refuses_empty_input(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path))
    assert r["ok"] is False
    assert "primitives" in r["what_happened"].lower() or "recipe_id" in r["what_happened"].lower()


def test_refuses_unknown_primitive(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["DoesNotExistPrimitive"])
    assert r["ok"] is False
    assert "unknown" in r["what_happened"].lower()


def test_refuses_unknown_recipe_id(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), recipe_id="bogus__00_nothing")
    assert r["ok"] is False
    assert "unknown recipe" in r["what_happened"].lower()


def test_refuses_domain_primitives(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path),
                             primitives=["Aggregate", "SessionCache"])
    assert r["ok"] is False
    assert "domain-shaped" in r["what_happened"].lower()
    assert "Aggregate" in r["what_happened"]


def test_domain_blacklist_covers_all_ddd_building_blocks() -> None:
    expected = {"Aggregate", "Specification", "DomainEvent", "BoundedContext",
                "AntiCorruptionLayer", "ValueObject",
                "CommandBus", "QueryBus", "CommandQuerySeparator"}
    assert expected <= DOMAIN_PRIMITIVE_BLACKLIST


def test_recipe_id_plus_primitives_subset_ok(tmp_path: Path) -> None:
    """Passing recipe_id + a strict subset of its primitives should succeed."""
    # AccessLog__01 has primitives ['AuditEvent', 'TamperEvidentAuditLog']
    r = fastapi_meta_compose(
        output_dir=str(tmp_path),
        recipe_id="AccessLog__01_auditevent-tamperevidentauditlog-reads-a",
        primitives=["AuditEvent"],
        dry_run=True,
    )
    assert r["ok"] is True


def test_recipe_id_plus_primitives_non_subset_fails(tmp_path: Path) -> None:
    r = fastapi_meta_compose(
        output_dir=str(tmp_path),
        recipe_id="AccessLog__01_auditevent-tamperevidentauditlog-reads-a",
        primitives=["SessionCache"],   # NOT in this recipe
        dry_run=True,
    )
    assert r["ok"] is False
    assert "does not contain" in r["what_happened"].lower()


# ---------------------------------------------------------------------------
# Three-tier fallthrough
# ---------------------------------------------------------------------------

def test_mode_adapter_reuse_on_exact_match(tmp_path: Path) -> None:
    """WebhookReceiverAdapter declares exactly these five primitives."""
    r = fastapi_meta_compose(
        output_dir=str(tmp_path),
        primitives=["SignatureVerifier", "IdempotentConsumer", "AuditEvent",
                    "InboxDeduplicator", "TransactionalOutbox"],
        mount_path="/webhooks/in",
    )
    assert r["ok"] is True
    assert r["result"]["mode"] == "adapter_reuse"
    assert "WebhookReceiverAdapter" in r["result"]["composition_source"]


def test_mode_tool_delegate_when_tool_emits_exact_set(tmp_path: Path) -> None:
    """If a catalog tool already emits this exact primitive set, compose
    must delegate to it rather than duplicate output. AuditEvent +
    TamperEvidentAuditLog is covered by fastapi_data_add_audit_log and
    by no FastAPI adapter — so tool_delegate wins."""
    r = fastapi_meta_compose(
        output_dir=str(tmp_path),
        primitives=["AuditEvent", "TamperEvidentAuditLog"],
        dry_run=True,
    )
    assert r["ok"] is True
    assert r["result"]["mode"] == "tool_delegate"
    assert r["result"]["delegate_tool"] == "fastapi_data_add_audit_log"
    assert r["result"]["files_written"] == []
    assert r["result"]["validation_report"]["mode_quality"] == "HIGH"


def test_mode_recipe_template_on_recipe_match(tmp_path: Path) -> None:
    r = fastapi_meta_compose(
        output_dir=str(tmp_path),
        primitives=["SignatureVerifier", "TamperEvidentAuditLog"],
    )
    assert r["ok"] is True
    assert r["result"]["mode"] == "recipe_template"
    assert r["result"]["recipe_used"], "recipe_template must name the recipe used"


def test_mode_ad_hoc_on_no_match(tmp_path: Path) -> None:
    """Rare combination that no adapter + no recipe covers."""
    r = fastapi_meta_compose(
        output_dir=str(tmp_path),
        primitives=["BreachNotificationQueue", "HealthProbe", "RetryBudget"],
    )
    assert r["ok"] is True
    assert r["result"]["mode"] == "ad_hoc"
    assert "WARNING" in r["result"]["composition_source"]
    assert r["result"]["validation_report"]["mode_quality"] == "LOW"


# ---------------------------------------------------------------------------
# Emission quality
# ---------------------------------------------------------------------------

def test_emitted_source_is_ast_parseable(tmp_path: Path) -> None:
    for prims in (
        ["SessionCache"],
        ["SignatureVerifier", "IdempotentConsumer", "AuditEvent"],
        ["HealthProbe", "CircuitBreaker"],
    ):
        r = fastapi_meta_compose(
            output_dir=str(tmp_path / "_".join(prims)),
            primitives=prims, dry_run=True,
        )
        assert r["ok"] is True
        # Actually parse the emitted source.
        ast.parse(r["result"]["composition_source"])


def test_files_written_include_package_init(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"])
    files = r["result"]["files_written"]
    # Must include both the composition .py and an __init__.py for the package
    assert any(f.endswith("__init__.py") for f in files)
    assert any(f.endswith(".py") and "__init__" not in f for f in files)


def test_composition_file_lives_under_app_compositions(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"])
    comp = next(f for f in r["result"]["files_written"] if "__init__" not in f)
    assert comp.startswith("app/compositions/"), comp


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"], dry_run=True)
    assert r["ok"] is True
    assert r["result"]["files_written"] == []
    # No files on disk either
    assert not (tmp_path / "app").exists()


def test_force_overwrites_existing(tmp_path: Path) -> None:
    # First call
    r1 = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"], name="myslug")
    assert r1["ok"] is True
    target = tmp_path / "app" / "compositions" / "myslug.py"
    original = target.read_text()

    # Second call without force should refuse
    r2 = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"], name="myslug")
    assert r2["ok"] is False
    assert "already exists" in r2["what_happened"]

    # Third call with force=True should overwrite
    r3 = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"],
                               name="myslug", force=True)
    assert r3["ok"] is True
    # Content re-emitted (same in this case, but write happened)
    assert target.read_text() == original  # deterministic emission


def test_slug_deterministic_on_same_primitives(tmp_path: Path) -> None:
    r1 = fastapi_meta_compose(output_dir=str(tmp_path / "a"),
                              primitives=["SessionCache", "RateLimiter"],
                              dry_run=True)
    r2 = fastapi_meta_compose(output_dir=str(tmp_path / "b"),
                              primitives=["RateLimiter", "SessionCache"],  # reversed
                              dry_run=True)
    # Same sorted primitives => same slug
    assert r1["result"]["slug"] == r2["result"]["slug"]


def test_custom_name_honored(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path), primitives=["SessionCache"],
                              name="my_custom_slug", dry_run=True)
    assert r["result"]["slug"] == "my_custom_slug"


def test_mount_path_appears_in_source(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path),
                              primitives=["SessionCache"],
                              mount_path="/my/custom/path",
                              dry_run=True)
    assert "/my/custom/path" in r["result"]["composition_source"]


# ---------------------------------------------------------------------------
# Result metadata
# ---------------------------------------------------------------------------

def test_primitives_used_resolves_module_paths(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path),
                              primitives=["SessionCache"], dry_run=True)
    used = r["result"]["primitives_used"]
    assert len(used) == 1
    assert used[0]["name"] == "SessionCache"
    assert used[0]["module"] == "core.venous.cache.SessionCache.SessionCache"


def test_validation_report_passes_ast(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path),
                              primitives=["SessionCache"], dry_run=True)
    rep = r["result"]["validation_report"]
    assert rep["ast_parse"] is True
    assert rep["primitives_resolved"] is True
    assert rep["mode_quality"] in ("HIGH", "MEDIUM", "LOW")


def test_next_steps_point_at_wire_up(tmp_path: Path) -> None:
    r = fastapi_meta_compose(output_dir=str(tmp_path),
                              primitives=["SessionCache"])
    ns = " ".join(r["next_steps"])
    assert "install" in ns and "app/main.py" in ns, "must breadcrumb the wire-up step"
    assert "fastapi_meta_audit" in ns, "must breadcrumb the verify step"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_snake_conversion() -> None:
    assert _snake("SessionCache") == "session_cache"
    assert _snake("HTTPServer") == "h_t_t_p_server"
    assert _snake("A") == "a"


def test_derive_slug_prefers_explicit_name() -> None:
    assert _derive_slug(recipe_id=None, primitives=["X"], name="Foo-Bar") == "foo_bar"


def test_derive_slug_uses_recipe_id_tail() -> None:
    # Slug must be a valid Python identifier; leading-digit tails get `c_` prefix.
    assert _derive_slug(recipe_id="Foo__01_bar-baz", primitives=["X"], name=None) == "c_01_bar_baz"


def test_derive_slug_letter_start_no_prefix() -> None:
    assert _derive_slug(recipe_id="Foo__bar_baz", primitives=["X"], name=None) == "bar_baz"


def test_derive_slug_falls_back_to_hash() -> None:
    slug = _derive_slug(recipe_id=None, primitives=["A", "B", "C"], name=None)
    assert slug.startswith("composition_")
    # Deterministic on sorted input
    assert slug == _derive_slug(recipe_id=None, primitives=["C", "A", "B"], name=None)


def test_adapter_index_filters_non_primitives() -> None:
    idx = _adapter_index()
    assert idx, "expected at least one shipped adapter"
    # WebhookReceiverAdapter should have exactly the registered primitives
    wra = idx.get("WebhookReceiverAdapter", set())
    assert "SignatureVerifier" in wra
    assert "IdempotentConsumer" in wra
    # Internal helpers MUST be filtered out
    assert "TrustAnchor" not in wra, "non-primitive helpers must be filtered"
    assert "InMemoryAuditSink" not in wra
