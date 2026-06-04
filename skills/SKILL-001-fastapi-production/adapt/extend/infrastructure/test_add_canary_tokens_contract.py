"""Generic + tool-specific mutation coverage for add_canary_tokens.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. The tool-specific block below targets the
config/route-insertion branches in ``_patch_config`` / ``_patch_routes_init``
that the shared checks cannot reach. Run alongside test_add_canary_tokens.py in
the mutation runner:
``--tests test_add_canary_tokens.py test_add_canary_tokens_contract.py``.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_canary_tokens import (
    _patch_config,
    _patch_routes_init,
    add_canary_tokens,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_canary_tokens import add_canary_tokens

    for check in SCAFFOLDABLE_CHECKS:
        check(add_canary_tokens, "add_canary_tokens")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L161 `if anchor in src`, L162 insertion order)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_after_anchor(tmp_path: Path) -> None:
    """When the ACCESS_TOKEN anchor is present, CANARY_* fields land directly
    AFTER it (not before, not via the settings fallback).

    Kills L161 In->NotIn: flipping the membership test skips the anchor branch
    and inserts via the ``settings = Settings()`` fallback, so the fields no
    longer follow the anchor line.
    """
    anchor = "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    src = f"class Settings:\n{anchor}\n    OTHER: int = 1\n\nsettings = Settings()\n"
    cfg = tmp_path / "config.py"
    cfg.write_text(src)
    _patch_config(cfg)
    out = cfg.read_text()
    lines = out.splitlines()
    anchor_idx = lines.index(anchor)
    # The line immediately after the anchor must be a CANARY_* field.
    assert "CANARY_ENABLED" in lines[anchor_idx + 1], (
        f"CANARY field must follow the anchor line; got:\n{out}"
    )
    # And it must appear BEFORE the original OTHER field (proves anchor branch,
    # not end-append fallback).
    assert out.index("CANARY_ENABLED") < out.index("OTHER: int = 1"), out


def test_patch_config_anchor_fields_are_indented(tmp_path: Path) -> None:
    """The injected fields keep the 4-space Settings-body indentation when
    taking the anchor branch.

    Reinforces L162 (Add->Sub on the anchor concat) by pinning the exact
    rendered block following the anchor.
    """
    anchor = "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    cfg = tmp_path / "config.py"
    cfg.write_text(f"class Settings:\n{anchor}\nsettings = Settings()\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "    CANARY_ENABLED: bool = True" in out, out
    assert '    CANARY_ALERT_WEBHOOK_URL: str = ""' in out, out


# ---------------------------------------------------------------------------
# _patch_config — settings fallback branch (L165 `if target in src`, L166 order)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_before_settings_when_no_anchor(tmp_path: Path) -> None:
    """With NO anchor but a ``settings = Settings()`` line, the fields are
    inserted BEFORE that line.

    Kills L165 In->NotIn (flip routes to the end-append else branch, so the
    fields end up after ``settings = Settings()``) and L166 Add->Sub (which
    would reorder the concat, also pushing the marker line ordering off).
    """
    target = "settings = Settings()"
    cfg = tmp_path / "config.py"
    cfg.write_text(f"class Settings:\n    X: int = 1\n{target}\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "CANARY_ENABLED" in out, out
    assert out.index("CANARY_ENABLED") < out.index(target), (
        f"fields must precede '{target}':\n{out}"
    )


# ---------------------------------------------------------------------------
# _patch_config — end-append fallback (L168 `src.rstrip + fields`)
# ---------------------------------------------------------------------------


def test_patch_config_appends_at_end_when_no_anchor_no_settings(tmp_path: Path) -> None:
    """With neither anchor nor settings line, fields are appended at the END,
    after the original content.

    Kills L168 Add->Sub: the rstrip/concat order determines that the original
    body precedes the appended CANARY fields.
    """
    cfg = tmp_path / "config.py"
    cfg.write_text("class Settings:\n    EXISTING: int = 9\n")
    _patch_config(cfg)
    out = cfg.read_text()
    assert "CANARY_ENABLED" in out, out
    assert out.index("EXISTING: int = 9") < out.index("CANARY_ENABLED"), (
        f"original content must precede appended fields:\n{out}"
    )
    # No accidental gluing of the last existing line to the field block.
    assert "EXISTING: int = 9    CANARY_ENABLED" not in out, out


def test_patch_config_idempotent(tmp_path: Path) -> None:
    """Re-running _patch_config does not duplicate the CANARY fields."""
    cfg = tmp_path / "config.py"
    cfg.write_text("class Settings:\n    EXISTING: int = 9\nsettings = Settings()\n")
    _patch_config(cfg)
    once = cfg.read_text()
    _patch_config(cfg)
    twice = cfg.read_text()
    assert once == twice, "second patch must be a no-op"
    assert twice.count("CANARY_ENABLED") == 1, twice


# ---------------------------------------------------------------------------
# _patch_routes_init — trailing-newline guard (L182 `if not content.endswith`)
# ---------------------------------------------------------------------------


def test_patch_routes_init_no_trailing_newline(tmp_path: Path) -> None:
    """When the existing routes file has NO trailing newline, the import line
    must NOT be glued onto the last existing line.

    Kills L182 not X->X: dropping the negation skips adding the separating
    newline, producing ``...routerfrom app.api...`` on one line.
    """
    ri = tmp_path / "__init__.py"
    ri.write_text("api_router.include_router(item_router)")  # no trailing \n
    _patch_routes_init(ri)
    out = ri.read_text()
    assert "include_router(item_router)\n" in out, (
        f"missing newline separator between original line and addition:\n{out!r}"
    )
    assert "item_router)from" not in out, f"lines were glued together:\n{out!r}"
    assert "canary_honeypot" in out, out


def test_patch_routes_init_with_trailing_newline(tmp_path: Path) -> None:
    """When the file already ends with a newline, no DOUBLE separator is added
    and the router registration is present."""
    ri = tmp_path / "__init__.py"
    ri.write_text("api_router.include_router(item_router)\n")
    _patch_routes_init(ri)
    out = ri.read_text()
    assert "canary_honeypot_router" in out, out
    assert "api_router.include_router(canary_honeypot_router)" in out, out


def test_patch_routes_init_idempotent(tmp_path: Path) -> None:
    """Re-running does not register the honeypot router twice."""
    ri = tmp_path / "__init__.py"
    ri.write_text("api_router.include_router(item_router)\n")
    _patch_routes_init(ri)
    once = ri.read_text()
    _patch_routes_init(ri)
    assert ri.read_text() == once
    assert ri.read_text().count("canary_honeypot_router") == 2, (
        "exactly one import + one include_router expected"
    )


# ---------------------------------------------------------------------------
# files_created seeding (L85 `list(scaffolded or [])`)
# ---------------------------------------------------------------------------


def test_files_created_contains_only_real_paths(tmp_path: Path) -> None:
    """files_created is seeded from ``scaffolded or []`` and then extended with
    the rendered canary files; every entry must be a real existing path and the
    registry must be among them.

    Kills L85 Or->And: ``scaffolded and []`` evaluates to ``[]`` only when
    scaffolded is truthy and otherwise to the (possibly None) scaffolded value,
    which would either drop genuine scaffolded paths or crash list(None).
    """
    project = create_fixture_project(name="ct_contract_fc")
    result = add_canary_tokens(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    created_resolved = {str(Path(p).resolve()) for p in result.files_created}
    registry = project / "app" / "core" / "canary" / "registry.py"
    assert str(registry.resolve()) in created_resolved, result.files_created
    for p in result.files_created:
        assert Path(p).exists(), f"phantom path in files_created: {p}"


def test_config_fields_follow_anchor_via_tool(tmp_path: Path) -> None:
    """End-to-end: the fixture config carries the ACCESS_TOKEN anchor, so the
    tool-run patch lands the CANARY fields immediately after it.

    Provides an integration-level guard for the anchor branch independent of
    the direct _patch_config unit tests.
    """
    project = create_fixture_project(name="ct_contract_anchor")
    result = add_canary_tokens(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    config_text = (project / "app" / "core" / "config.py").read_text()
    lines = config_text.splitlines()
    anchor_idx = next(i for i, line in enumerate(lines) if "ACCESS_TOKEN_EXPIRE_MINUTES" in line)
    follow = "\n".join(lines[anchor_idx + 1 : anchor_idx + 3])
    assert "CANARY_ENABLED" in follow, f"CANARY fields not directly after anchor:\n{follow}"
