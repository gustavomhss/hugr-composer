"""Every failed tier-1 / compose envelope carries a code from the closed set."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mcp_tools import compose, tier1
from mcp_tools.error_codes import ERROR_CODES, require_code

MODULES = [Path(compose.__file__), Path(tier1.__file__)]


def test_require_code_rejects_missing_unknown_and_success_codes() -> None:
    assert require_code(True, None) is None
    assert require_code(False, "target-exists") == "target-exists"
    with pytest.raises(ValueError):
        require_code(False, None)
    with pytest.raises(ValueError):
        require_code(False, "made-up")
    with pytest.raises(ValueError):
        require_code(True, "target-exists")


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_every_literal_failure_site_names_a_known_code(module: Path) -> None:
    calls = [
        node
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_envelope"
    ]
    failures = [
        call
        for call in calls
        if any(k.arg == "ok" and isinstance(k.value, ast.Constant) and k.value.value is False for k in call.keywords)
    ]
    # Positive control: the scan must actually see failure sites.
    assert len(failures) >= 4
    for call in failures:
        code = next((k.value for k in call.keywords if k.arg == "code"), None)
        assert code is not None, f"{module.name}:{call.lineno} failure without code"
        if isinstance(code, ast.Constant):
            assert code.value in ERROR_CODES, f"{module.name}:{call.lineno} unknown code {code.value!r}"


def test_compose_failure_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = str(tmp_path)
    assert compose.fastapi_meta_compose(output_dir=out)["code"] == "missing-selection"
    assert compose.fastapi_meta_compose(output_dir=out, primitives=["DoesNotExist"])["code"] == "unknown-primitive"
    assert compose.fastapi_meta_compose(output_dir=out, recipe_id="bogus__00")["code"] == "unknown-recipe"
    assert (
        compose.fastapi_meta_compose(output_dir=out, primitives=["Aggregate", "SessionCache"])["code"]
        == "domain-boundary"
    )

    recipe = compose._load_catalog()["recipes"][0]["id"]
    assert compose.fastapi_meta_compose(output_dir=out, recipe_id=recipe, primitives=["NotInRecipe"])[
        "code"
    ] == "recipe-mismatch"

    first = compose.fastapi_meta_compose(output_dir=out, primitives=["SessionCache"])
    assert first["ok"] is True and first["code"] is None
    assert compose.fastapi_meta_compose(output_dir=out, primitives=["SessionCache"])["code"] == "target-exists"

    monkeypatch.setattr(compose, "_ast_validate", lambda source: (False, "forced"))
    assert (
        compose.fastapi_meta_compose(output_dir=out, primitives=["SessionCache"], name="fresh", dry_run=True)["code"]
        == "invalid-output"
    )


def test_path_guard_failures_become_coded_envelopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    monkeypatch.setenv("HUGR_WORKTREE_ROOT", str(root))
    outside = str(tmp_path / "outside")

    composed = compose.fastapi_meta_compose(output_dir=outside, primitives=["SessionCache"])
    scaffolded = tier1.fastapi_meta_scaffold(output_dir=outside)
    assert (composed["ok"], composed["code"]) == (False, "path-rejected")
    assert (scaffolded["ok"], scaffolded["code"]) == (False, "path-rejected")
    assert not (tmp_path / "outside").exists()


def test_tier1_failure_codes() -> None:
    assert tier1.fastapi_meta_search("   ")["code"] == "empty-query"
    assert tier1.fastapi_meta_describe("NoSuchThingAnywhere")["code"] == "not-found"
    assert tier1.fastapi_meta_list_bundle("no-such-bundle")["code"] == "unknown-bundle"
    assert tier1.fastapi_meta_list_bundle("core", skill="no-such-skill")["code"] == "unknown-skill"
    assert tier1.fastapi_meta_activate_bundle("no-such-bundle")["code"] == "unknown-bundle"
    assert tier1.fastapi_meta_activate_bundle("core", skill="no-such-skill")["code"] == "unknown-skill"
    home = tier1.fastapi_meta_home()
    assert home["ok"] is True and home["code"] is None
