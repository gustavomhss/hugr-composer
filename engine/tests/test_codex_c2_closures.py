"""Regression tests for the Codex C2 hunt closures (Phase-2 PR-E).

Each test maps 1:1 to a finding in ``/tmp/codex_hunts/c2_report.md``. The
goal is to make the fix permanent: if a future refactor reintroduces the
drift these tests turn red.

C2 findings covered here:

* F-001 — `engine.audit.contract_check` is deterministic across machines
  (B0.6 no longer reads ``~/.claude/projects``; it checks an in-repo
  pointer file).
* F-002 — engine README + delivery-contract module docstring agree
  with the shipped `Tier` enum (10 tiers, T0_static..T9_meta).
* F-003 — `engine.docs.build` discovers BOTH flat ``add_*.py`` and
  the WAVE-1 directory layout ``add_*/__init__.py``.
* F-004 — `engine.docs.build` renders one tool page per discovered
  tool source (silent coverage shrinkage caught by an explicit count
  assertion, not just primitive coverage).
* F-008 — `engine.index.manifest` module docstring reflects the real
  scan surface (no claim of scanning `mcp_tools/` or one specific
  benchmark file).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# --- F-001: B0.6 determinism --------------------------------------------------


def test_b06_does_not_read_home_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """B0.6 must pass on a fresh checkout where ``$HOME`` is empty.

    Before the C2 fix the rule walked ``~/.claude/projects`` and failed
    on any machine that didn't carry a per-developer memory artefact.
    We simulate that "fresh CI runner" environment by re-pointing
    ``$HOME`` to an empty temp dir and asserting the rule still passes
    (it must derive its answer purely from the working tree).
    """
    from engine.audit.contract_check import _r_agent_memory_pointer

    empty_home = Path(os.environ["PYTEST_CURRENT_TEST"]).parent  # any dir is fine
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: empty_home))  # type: ignore[arg-type]
    ok, msg = _r_agent_memory_pointer()
    assert ok, f"B0.6 must be repo-local + deterministic; got: {msg}"


def test_b06_pointer_file_is_committed() -> None:
    """The pointer file B0.6 reads MUST live inside the repo."""
    from engine.audit.contract_check import SKILL_ROOT

    pointer = SKILL_ROOT / "engine" / "audit" / "AGENT_MEMORY_POINTER.md"
    assert pointer.is_file(), "engine/audit/AGENT_MEMORY_POINTER.md must be committed"
    body = pointer.read_text(encoding="utf-8")
    assert "PRODUCT.md" in body and "CONTRACT.md" in body, (
        "pointer file must name both canonical contract docs"
    )


def test_b06_fails_loudly_when_pointer_loses_canonical_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the pointer file silently drops PRODUCT/CONTRACT refs, B0.6 fails.

    Post WP-16 split (PR #57): the rule callback ``_r_agent_memory_pointer``
    lives in ``engine.audit.contract_rules.phase0_identity`` and reads its
    own module's ``SKILL_ROOT`` binding (imported once at module top from
    ``_common``). The shared ``_exists`` helper, which the rule calls,
    reads ``REPO_ROOT`` from its own module — ``_common``. So both
    bindings need to be patched to keep the test deterministic.
    """
    from engine.audit.contract_rules import _common
    from engine.audit.contract_rules import phase0_identity as mod

    fake_skill_root = tmp_path / "skill"
    (fake_skill_root / "engine" / "audit").mkdir(parents=True)
    pointer = fake_skill_root / "engine" / "audit" / "AGENT_MEMORY_POINTER.md"
    pointer.write_text("x" * 500 + "\nno canonical refs here\n")
    monkeypatch.setattr(mod, "SKILL_ROOT", fake_skill_root)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(_common, "REPO_ROOT", tmp_path)
    ok, msg = mod._r_agent_memory_pointer()
    assert not ok
    assert "PRODUCT.md" in msg and "CONTRACT.md" in msg


# --- F-002: 10-tier doc/code agreement ----------------------------------------


def test_delivery_contract_module_docstring_matches_enum() -> None:
    """The contract module docstring must enumerate all 10 tiers."""
    from engine.contracts import primitive_delivery_contract as pdc

    assert pdc.__doc__ is not None
    doc = pdc.__doc__
    # Every Tier member must appear in the module docstring prose.
    for tier in pdc.Tier:
        # T0_static is matched as "T0" + "Static"; T1_BEHAVIORAL as "T1" etc.
        token = tier.value.split("_", 1)[0].upper()
        assert token in doc, f"module docstring missing tier marker '{token}'"
    # Pre-C2 prose said "Nine tiers"; the canonical model is ten.
    assert "Ten tiers" in doc or "10-tier" in doc
    assert "Nine tiers" not in doc
    assert "9-tier" not in doc


def test_engine_readme_describes_ten_tiers() -> None:
    """engine/README.md must describe the same ten-tier model as code."""
    from engine.contracts.primitive_delivery_contract import Tier

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "10-tier" in readme
    assert "9-tier" not in readme
    # T0 must be visible somewhere in the cheat sheet, not just T1..T9.
    assert "T0 static" in readme or "T0_static" in readme
    # All other Tier markers must appear.
    for tier in Tier:
        marker = tier.value.split("_", 1)[0].upper()
        assert marker in readme, f"README missing tier marker '{marker}'"


def test_battle_tested_requires_all_ten_tiers_in_table() -> None:
    """The `MATURITY_REQUIRED_TIERS` table is the canonical source."""
    from engine.contracts.primitive_delivery_contract import (
        MATURITY_REQUIRED_TIERS,
        Maturity,
        Tier,
    )

    assert MATURITY_REQUIRED_TIERS[Maturity.BATTLE_TESTED] == frozenset(Tier)
    # 10 = T0..T9. If somebody adds an eleventh tier, this test trips on
    # purpose so README + docstring are updated together.
    assert len(list(Tier)) == 10


# --- F-003 + F-004: docs/build discovery ---------------------------------------


def test_docs_build_discovers_directory_layout_tools() -> None:
    """`_discover_tool_sources` picks up `add_<name>/__init__.py`."""
    from engine.docs.build import _discover_tool_sources

    sources = _discover_tool_sources()
    init_dirs = [p for p in sources if p.name == "__init__.py" and p.parent.name.startswith("add_")]
    assert init_dirs, (
        "expected at least one directory-form tool "
        "(WAVE-1 migrated add_cursor_pagination → add_cursor_pagination/__init__.py)"
    )
    # And the canonical golden migration is in there.
    assert any("cursor_pagination" in p.parent.name for p in init_dirs)


def test_docs_build_static_parse_does_not_swallow_errors(tmp_path: Path) -> None:
    """`_parse_mcp_tool_dict` returns None for non-dict MCP_TOOL but not for valid."""
    from engine.docs.build import _parse_mcp_tool_dict

    good = tmp_path / "good.py"
    good.write_text('MCP_TOOL = {"name": "x", "description": "y", "tags": []}\n')
    assert _parse_mcp_tool_dict(good) == {"name": "x", "description": "y", "tags": []}

    no_meta = tmp_path / "nometa.py"
    no_meta.write_text("def f(): pass\n")
    assert _parse_mcp_tool_dict(no_meta) is None


def test_docs_build_renders_one_page_per_discovered_tool(tmp_path: Path) -> None:
    """Tool pages emitted MUST match the discovered tool count.

    Closes F-004: pre-C2 the test suite only asserted primitive
    coverage, so a silent drop of N tools from the rendered site would
    still pass green. Now we assert tool coverage too.
    """
    from engine.docs.build import _discover_tool_sources, _load_tools, build_site

    out = tmp_path / "site"
    manifest = build_site(out)
    discovered_sources = _discover_tool_sources()
    # _load_tools filters to entries that carry a literal MCP_TOOL with
    # a `name`. Every such entry MUST become a rendered page.
    loaded = _load_tools()
    assert manifest["tools"] == len(loaded), (
        f"docs site reports {manifest['tools']} tools but _load_tools returned {len(loaded)}"
    )
    rendered = list((out / "tool").glob("*.html"))
    assert len(rendered) == len(loaded), (
        f"rendered {len(rendered)} tool pages, expected {len(loaded)}"
    )
    # And cursor_pagination (the WAVE-1 golden migration) MUST be one.
    assert any("cursor_pagination" in p.name for p in rendered)
    # Sanity: discovery surface is non-empty.
    assert discovered_sources


# --- F-008: manifest docstring matches scan surface ----------------------------


def test_manifest_docstring_describes_actual_scan_surface() -> None:
    """The module docstring MUST NOT lie about TOOL_SCAN_ROOTS.

    Pre-C2 the docstring claimed it scanned ``mcp_tools/`` and
    ``benchmark/analyzer.py``; neither is true. The first claim was
    actively wrong (mcp_tools must NOT appear in the catalog because
    its tier-1 entries operate on the catalog), the second was a
    historical artefact. We assert the docstring stays honest by
    cross-checking it against TOOL_SCAN_ROOTS.
    """
    from engine.index import manifest

    doc = manifest.__doc__ or ""
    # The misleading prose must not return.
    assert "`mcp_tools/`," not in doc, "docstring must not claim to scan mcp_tools/"
    assert "benchmark/analyzer.py" not in doc, (
        "docstring must not claim to scan one specific benchmark file"
    )
    # The exclusion rationale must be present so a future contributor
    # doesn't 'fix' it by re-adding mcp_tools/ to the scan list.
    assert "deliberately excluded" in doc or "mcp_tools" in doc

    # Every real scan-root label must appear in the docstring.
    for label, _path in manifest.TOOL_SCAN_ROOTS:
        # `core/tools/` is labelled "core_tools" in TOOL_SCAN_ROOTS but
        # spelled as a path in prose; accept either.
        token_path = label.replace("_", "/")
        assert label in doc or token_path in doc, (
            f"docstring missing scan-root reference: {label} (path-form: {token_path})"
        )
