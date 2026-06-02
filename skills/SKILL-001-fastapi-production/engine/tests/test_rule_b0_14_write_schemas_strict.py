"""Unit tests for B0.14 — write_schemas_strict_forbid.

CONTRACT.md scope: §B0.14. Sister tests live next to other rule tests
under ``engine/tests/``. Each test installs a fake ``adapt/`` tree under
a temporary directory, points the rule's ``SKILL_ROOT`` at it, and runs
``_r_write_schemas_strict`` end-to-end. Tests cover:

  * RED on missing ``extra="forbid"`` for a ``*Create`` schema.
  * RED on bare ``dict`` / ``Any`` field in a non-Response schema.
  * GREEN when the offending tool is waived.
  * GREEN when the schema is fixed (extra=forbid + concrete value type).
  * GREEN when a per-line ``# pragma: schema-any: <reason>`` bypass is
    present on the offending field.
  * Plus auxiliary tests for the verb-prefix heuristic, the Pydantic-v1
    Config syntax, Read-suffix exemption, and the nested ``Any`` walk.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers — build a fake adapt/ tree under a tmp dir.
# ---------------------------------------------------------------------------


def _write_template(root: Path, tool: str, body: str) -> Path:
    """Write a schema template into a per-tool dir, mirroring the real layout."""
    d = root / "adapt" / "extend" / "fakegroup" / tool / "templates"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "schemas.py.tmpl"
    p.write_text(body, encoding="utf-8")
    return p


def _run_rule(monkeypatch: pytest.MonkeyPatch, fake_root: Path, *, waivers=()):
    """Reload the rule module against the fake skill root + waivers."""
    # Ensure no cached state from previous tests in this session.
    mod_name = "engine.audit.contract_rules.r_write_schemas_strict"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    from engine.audit.contract_rules import _common  # noqa: WPS433

    monkeypatch.setattr(_common, "SKILL_ROOT", fake_root, raising=True)
    mod = importlib.import_module(mod_name)
    monkeypatch.setattr(mod, "SKILL_ROOT", fake_root, raising=True)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset(waivers), raising=True)
    return mod._r_write_schemas_strict()


# ---------------------------------------------------------------------------
# Core RED tests.
# ---------------------------------------------------------------------------


def test_red_missing_extra_forbid_on_create_schema(tmp_path, monkeypatch):
    body = "from pydantic import BaseModel\n\nclass WidgetCreate(BaseModel):\n    name: str\n"
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "WidgetCreate" in msg
    assert "extra" in msg


def test_red_bare_dict_field_on_non_response_schema(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: dict\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "meta" in msg
    assert "bare-dict" in msg


def test_red_dict_str_any_field(tmp_path, monkeypatch):
    body = (
        "from typing import Any\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: dict[str, Any]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "dict[..., Any]" in msg


def test_red_list_dict_field(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class BulkUpdate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    updates: list[dict]\n"
    )
    _write_template(tmp_path, "add_bulk", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "list[dict]" in msg


def test_red_nested_any_in_generic_chain(tmp_path, monkeypatch):
    body = (
        "from typing import Any\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    nested: list[dict[str, list[Any]]]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    # The list[Any] inner-most token bubbles up.
    assert "list[Any]" in msg or "dict[..., Any]" in msg


def test_red_any_input_field(tmp_path, monkeypatch):
    body = (
        "from typing import Any\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class PredictionRequest(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    input: Any\n"
    )
    _write_template(tmp_path, "add_ml", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "Any" in msg


# ---------------------------------------------------------------------------
# Verb-prefix heuristic.
# ---------------------------------------------------------------------------


def test_red_verb_prefix_schema_without_forbid(tmp_path, monkeypatch):
    # RegistrationBeginRequest → matches both `Begin*` verb-prefix AND
    # `*Request` suffix. We exercise the verb-prefix arm too via a name
    # that ONLY matches via verb-prefix.
    body = (
        "from pydantic import BaseModel\n"
        "\n"
        "class SubmitOrderPayload(BaseModel):\n"
        "    order_id: str\n"
    )
    _write_template(tmp_path, "add_orders", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "SubmitOrderPayload" in msg


# ---------------------------------------------------------------------------
# R8-J4-3 — broadened write-name detection (Form/Input/Data + New/Edit).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls_name",
    ["UserForm", "UserInput", "UserData", "NewUser", "EditProfile"],
)
def test_red_broadened_write_name_without_forbid(tmp_path, monkeypatch, cls_name):
    """R8-J4-3: a write schema named with a Form/Input/Data suffix or a
    New/Edit prefix (and NO extra="forbid") MUST be flagged — these were
    previously classified as neither write nor read and skipped."""
    body = f"from pydantic import BaseModel\n\nclass {cls_name}(BaseModel):\n    name: str\n"
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok, f"{cls_name} should be a write schema requiring extra=forbid"
    assert cls_name in msg
    assert "extra" in msg


def test_green_broadened_write_name_with_forbid(tmp_path, monkeypatch):
    """R8-J4-3: a ``*Form`` write schema that DOES declare extra="forbid" passes."""
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class UserForm(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    name: str\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_green_response_named_data_summary_still_exempt(tmp_path, monkeypatch):
    """R8-J4-3 caution: a read-side response schema whose name happens to
    NOT end in Form/Input/Data and is a Response-suffix stays exempt.

    Guards against the broadening accidentally requiring extra=forbid on
    legit read schemas (the reason the full flip was rejected)."""
    body = (
        "from pydantic import BaseModel\n"
        "\n"
        "class RevenueAnalyticsResponse(BaseModel):\n"
        "    total_cents: int\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


# ---------------------------------------------------------------------------
# GREEN tests.
# ---------------------------------------------------------------------------


def test_green_when_tool_waived(tmp_path, monkeypatch):
    body = "from pydantic import BaseModel\n\nclass WidgetCreate(BaseModel):\n    name: str\n"
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path, waivers={"add_widget"})
    assert ok, msg
    assert "1 waived" in msg


def test_green_when_fixed(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    name: str\n"
        "    attributes: dict[str, str]\n"  # concrete value type → allowed
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_green_when_pragma_bypass_present(tmp_path, monkeypatch):
    body = (
        "from typing import Any\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: dict[str, Any]  # pragma: schema-any: webhook payload passthrough\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_red_when_pragma_lacks_reason(tmp_path, monkeypatch):
    body = (
        "from typing import Any\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: dict[str, Any]  # pragma: schema-any: \n"  # whitespace-only reason
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok


def test_green_pydantic_v1_config_class(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        "    name: str\n"
        "\n"
        "    class Config:\n"
        '        extra = "forbid"\n'
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_green_inherited_extra_forbid_from_same_module_base(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetStrictBase(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "\n"
        "class WidgetCreate(WidgetStrictBase):\n"
        "    name: str\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


# ---------------------------------------------------------------------------
# Read/Response exemptions.
# ---------------------------------------------------------------------------


def test_green_read_schema_exempt_from_extra_forbid(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetRead(BaseModel):\n"
        "    model_config = ConfigDict(from_attributes=True)\n"
        "    id: str\n"
        "    name: str\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_green_response_schema_with_bare_any_dict_exempt(tmp_path, monkeypatch):
    # Response schemas exempt from BOTH extra=forbid and bad-field checks.
    body = (
        "from typing import Any\n"
        "from pydantic import BaseModel\n"
        "\n"
        "class RegistrationBeginResponse(BaseModel):\n"
        "    options: dict[str, Any]\n"
        "    session_id: str\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


# ---------------------------------------------------------------------------
# Concrete value types — allowed.
# ---------------------------------------------------------------------------


def test_green_concrete_value_type_in_dict(tmp_path, monkeypatch):
    body = (
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    labels: dict[str, str]\n"
        "    counts: dict[str, int]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


# ---------------------------------------------------------------------------
# Catalog smoke — proves the live SKILL_ROOT rule passes (waivers in place).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Round-7 O3-F26 (HIGH) — typing.Dict/List/Set/Any capital-letter variants.
# ---------------------------------------------------------------------------


def test_red_typing_dict_attribute_form(tmp_path, monkeypatch):
    """``typing.Dict`` (attribute form) evaded the lowercase-only walker.

    After the patch the attribute tail is matched, so
    ``typing.Dict[str, typing.Any]`` is treated identically to the
    builtin ``dict[str, Any]``.
    """
    body = (
        "import typing\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: typing.Dict[str, typing.Any]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "dict[..., Any]" in msg


def test_red_typing_list_attribute_any(tmp_path, monkeypatch):
    """``typing.List[typing.Any]`` is rejected by the attribute walker."""
    body = (
        "import typing\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    tags: typing.List[typing.Any]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "list[Any]" in msg


def test_red_imported_dict_capital_d(tmp_path, monkeypatch):
    """``from typing import Dict, Any`` then ``Dict[str, Any]`` evaded
    the rule because the walker only matched lowercase ``dict`` Names.
    """
    body = (
        "from typing import Dict, Any\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: Dict[str, Any]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "dict[..., Any]" in msg


def test_red_imported_bare_dict_capital_d(tmp_path, monkeypatch):
    """Bare ``Dict`` (no subscript) is rejected the same as bare ``dict``."""
    body = (
        "from typing import Dict\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: Dict\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "bare-dict" in msg


def test_red_typing_any_attribute(tmp_path, monkeypatch):
    """``typing.Any`` (attribute form, not imported as Any) is rejected."""
    body = (
        "import typing\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    payload: typing.Any\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert not ok
    assert "Any" in msg


def test_green_typing_dict_with_concrete_value(tmp_path, monkeypatch):
    """``typing.Dict[str, str]`` mirrors the builtin allow rule — concrete
    value types are accepted regardless of the capital-D spelling.
    """
    body = (
        "import typing\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    labels: typing.Dict[str, str]\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_green_typing_pragma_bypass(tmp_path, monkeypatch):
    """Per-line ``# pragma: schema-any: <reason>`` bypass still works on
    the typing.Dict[str, Any] shape (parity with builtin dict[str, Any]).
    """
    body = (
        "import typing\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "\n"
        "class WidgetCreate(BaseModel):\n"
        '    model_config = ConfigDict(extra="forbid")\n'
        "    meta: typing.Dict[str, typing.Any]  # pragma: schema-any: opaque metric blob\n"
    )
    _write_template(tmp_path, "add_widget", body)
    ok, msg = _run_rule(monkeypatch, tmp_path)
    assert ok, msg


def test_catalog_passes_with_baked_in_waivers():
    """Live invocation against the real adapt/ tree.

    Asserts the rule lands green out-of-the-box (waivers cover legacy
    debt). Independent of the tmp-path tests above so a regression in
    either waiver list OR a fresh template defect surfaces immediately.
    """
    from engine.audit.contract_rules.r_write_schemas_strict import (
        _r_write_schemas_strict,
    )

    ok, msg = _r_write_schemas_strict()
    assert ok, msg
