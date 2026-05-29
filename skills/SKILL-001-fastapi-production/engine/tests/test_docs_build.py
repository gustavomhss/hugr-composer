"""Unit tests for CONTRACT §B2.3 — docs site generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from engine.docs.build import (
    SKILL_ROOT,
    _inline_rich,
    _md_to_html,
    _site_hash,
    build_site,
)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    out = tmp_path_factory.mktemp("docs")
    manifest = build_site(out)
    return out, manifest


def test_every_primitive_has_a_page(site: tuple[Path, dict]) -> None:
    out, manifest = site
    registry = yaml.safe_load((SKILL_ROOT / "engine" / "primitives_by_concern.yaml").read_text())
    for entry in registry["primitives"]:
        page = out / "primitive" / f"{entry['name']}.html"
        assert page.is_file(), f"missing page for {entry['name']}"
        content = page.read_text(encoding="utf-8")
        assert entry["name"] in content
        assert entry["concern"] in content


def test_landing_page_has_search_and_concerns(site: tuple[Path, dict]) -> None:
    out, _ = site
    idx = (out / "index.html").read_text()
    assert 'id="q"' in idx
    assert "Primitives by concern" in idx
    assert "search.js" in idx


def test_search_index_covers_every_primitive(site: tuple[Path, dict]) -> None:
    out, manifest = site
    docs = json.loads((out / "search.json").read_text())
    prim_names = {d["name"] for d in docs if d["kind"] == "primitive"}
    assert len(prim_names) == manifest["primitives"]


def test_flat_navigation_two_clicks_from_landing(site: tuple[Path, dict]) -> None:
    """CONTRACT §B2.3 Quality: every primitive reachable in ≤ 2 clicks."""
    out, _ = site
    idx = (out / "index.html").read_text()
    # Landing links directly to each primitive page → 1 click.
    sample_names = ["CircuitBreaker", "SignatureVerifier", "EventBus", "TotpVerifier"]
    for name in sample_names:
        assert f'href="primitive/{name}.html"' in idx


def test_idempotent_build_same_hash(tmp_path: Path) -> None:
    out = tmp_path / "site"
    m1 = build_site(out)
    m2 = build_site(out)
    assert m1["hash"] == m2["hash"]


def test_md_to_html_handles_subset() -> None:
    md = "# Title\n\nHello **world** with `code`.\n\n- a\n- b\n\n```py\nprint(1)\n```"
    out = _md_to_html(md)
    assert "<h1>Title</h1>" in out
    assert "<strong>world</strong>" in out
    assert "<code>code</code>" in out
    assert "<ul>" in out and "<li>a</li>" in out
    assert '<pre><code class="lang-py">' in out


def test_inline_escapes_html() -> None:
    assert "&lt;script&gt;" in _inline_rich("<script>alert(1)</script>")


def test_compose_with_cross_links_exist(site: tuple[Path, dict]) -> None:
    out, _ = site
    page = (out / "primitive" / "CircuitBreaker.html").read_text()
    # Registry entry lists siblings; at least one should appear as a link.
    assert 'href="' in page
    # compose_with siblings for CircuitBreaker include RetryPolicy etc.
    assert "RetryPolicy" in page


def test_site_hash_excludes_manifest(site: tuple[Path, dict]) -> None:
    out, manifest = site
    # Re-compute from files; must match what was stored in manifest.
    assert _site_hash(out) == manifest["hash"]
