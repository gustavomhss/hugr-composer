"""Regression tests for W2 — close add_multi_tenancy waivers.

Closes two waivers for ``extend/auth_access/add_multi_tenancy`` in one
PR; this test module holds focused assertions per finding so the rule
files + the templates can never silently regress together.

Findings closed:

* **B0.14** (rule: ``r_write_schemas_strict``)
  R6-O3-P13 — ``TenantCreate`` (via ``TenantBase``) and ``TenantUpdate``
  (the input boundaries for ``POST /tenants/`` and ``PATCH /tenants/
  {id}``) were missing ``extra="forbid"``, allowing arbitrary keys /
  mass-assignment. ``TenantUpdate.status`` was typed as ``str | None``
  so any string was accepted at the API boundary and only the DB
  CheckConstraint (``status IN ('active', 'suspended', 'archived')``)
  rejected invalid values — surfacing as IntegrityError on flush
  instead of a 422 at parse. Fix: both write schemas now declare
  ``model_config = ConfigDict(extra="forbid")``; ``status`` is bound
  to ``Literal["active", "suspended", "archived"] | None`` (mirrors
  the DB enum verbatim).

* **B0.16** (rule: ``r_no_silent_security_failures``)
  R5-O1-F4 / P7-F2 — ``_tenant_scoped_table`` in
  ``tenant_filter.py.tmpl`` had an ORM mapper-inspection branch
  (``inspect(TenantScopedMixin).mappers``) wrapped in a broad
  ``except Exception: pass``. The juror confirmed the branch was dead
  code: ``TenantScopedMixin`` is a non-mapped mixin so the mapper
  registry never contained an entry for it, AND the surrounding
  ``except`` was unreachable on the happy path — the
  AttributeError-on-None case was the only realistic failure and it
  was being swallowed silently. Fix: the mapper branch (and its
  broad-except) is removed; the column-fallback
  (``"tenant_id" in table.c``) is the actual recognition path and
  was already covering every model the tool patches.

DELICATE notes:
  - Don't regress R5-O1-F1 (BOLA) or R5-O1-F2 (INSERT cross-tenant);
    the fail-closed write-guard at line ~144 (``stmt.where(false())``
    when ``tenant_id is None`` for is_update/is_delete) MUST survive
    any edit to ``_tenant_scoped_table`` — covered by the dedicated
    `test_b0_16_filter_preserves_fail_closed_write_guard`.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "auth_access"
    / "add_multi_tenancy"
)
SCHEMAS_TMPL = TOOL_DIR / "templates" / "tenant_schemas.py.tmpl"
FILTER_TMPL = TOOL_DIR / "templates" / "tenant_filter.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — same shape as the rule files use, so the template
# can be exec'd here.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _exec_template(path: Path) -> dict:
    """Compile + exec a ``.py.tmpl`` (placeholders stripped) into a fresh ns."""
    src = _clean(path.read_text(encoding="utf-8"))
    ns: dict = {"__name__": f"under_test_{path.stem}"}
    exec(compile(src, str(path), "exec"), ns)  # noqa: S102 — exec is the test
    return ns


# ---------------------------------------------------------------------------
# B0.14 — TenantCreate + TenantUpdate declare extra="forbid"; status is
# constrained at the input boundary (R6-O3-P13).
# ---------------------------------------------------------------------------


def test_b0_14_tenant_create_rejects_unknown_keys() -> None:
    """B0.14 (Pattern P5 / R6-O3-P13): the write schema at the input
    boundary must reject unknown keys — this is the mass-assignment /
    key-smuggling defence. Pre-fix the schema lacked
    ``extra="forbid"`` and silently accepted any extra key.
    """
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    TenantCreate = ns["TenantCreate"]
    TenantCreate.model_rebuild(_types_namespace=ns)

    # Sanity: valid payload accepted.
    ok = TenantCreate(slug="acme", name="Acme Corp")
    assert ok.slug == "acme"
    assert ok.name == "Acme Corp"

    # Core assertion: unknown key MUST raise. Pre-fix a smuggled
    # ``id`` / ``status`` / ``is_admin`` slipped through model_dump
    # and the CRUD constructor blindly setattr'd it onto the Tenant
    # row.
    with pytest.raises(ValidationError):
        TenantCreate(
            slug="acme",
            name="Acme Corp",
            is_admin=True,  # smuggled key
        )


def test_b0_14_tenant_update_rejects_unknown_keys() -> None:
    """Same shape for the PATCH boundary. Pre-fix a smuggled
    ``id`` / ``slug`` / ``created_at`` slipped through model_dump
    and the CRUD update() blindly setattr'd it onto the Tenant row.
    """
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    TenantUpdate = ns["TenantUpdate"]
    TenantUpdate.model_rebuild(_types_namespace=ns)

    ok = TenantUpdate(name="Renamed")
    assert ok.name == "Renamed"

    with pytest.raises(ValidationError):
        TenantUpdate(name="Renamed", slug="hijacked")


def test_b0_14_tenant_update_status_is_literal_not_str() -> None:
    """R6-O3-P13: ``status`` was ``str | None`` so any string was
    accepted at the API boundary and only the DB CheckConstraint
    rejected the value — surfacing as IntegrityError on flush
    instead of a 422 at parse. The fix is a ``Literal[...]`` bound
    that mirrors the constraint enum verbatim.
    """
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    TenantUpdate = ns["TenantUpdate"]
    TenantUpdate.model_rebuild(_types_namespace=ns)

    # Each valid value accepted.
    for valid in ("active", "suspended", "archived"):
        out = TenantUpdate(status=valid)
        assert out.status == valid

    # None still allowed (PATCH semantics).
    assert TenantUpdate(status=None).status is None

    # Out-of-enum values MUST be rejected at parse, not on flush.
    for bad in ("Active", "ACTIVE", "deleted", "pending", ""):
        with pytest.raises(ValidationError):
            TenantUpdate(status=bad)


def test_b0_14_tenant_status_enum_matches_db_check_constraint() -> None:
    """Belt + braces: the Literal in tenant_schemas MUST stay in
    lockstep with the CheckConstraint in tenant_model. Without this
    test, drift between the two enums would re-open the same shape
    (Pydantic accepts a value that the DB then refuses).
    """
    schemas_src = SCHEMAS_TMPL.read_text(encoding="utf-8")
    model_src = (TOOL_DIR / "templates" / "tenant_model.py.tmpl").read_text(
        encoding="utf-8"
    )

    # Pull the Literal members out of the schemas template.
    literal_match = re.search(
        r'Literal\[\s*"active"\s*,\s*"suspended"\s*,\s*"archived"\s*\]',
        schemas_src,
    )
    assert literal_match, (
        "TenantStatus Literal must declare the three enum members in "
        "order: 'active', 'suspended', 'archived' — the rest of the "
        "fix depends on this exact shape."
    )

    # Pull the CheckConstraint enum out of the model template.
    constraint_match = re.search(
        r"status IN \('active', 'suspended', 'archived'\)", model_src
    )
    assert constraint_match, (
        "tenant_model.py.tmpl CheckConstraint must declare "
        "status IN ('active', 'suspended', 'archived') — the Literal "
        "in tenant_schemas mirrors it 1:1."
    )


def test_b0_14_tenant_create_inherits_extra_forbid_from_base() -> None:
    """Sanity: TenantBase carries ``extra="forbid"`` and TenantCreate
    inherits it (no separate model_config). Verifies that the base
    declaration actually propagates to the subclass — Pydantic v2
    inheritance is subtle enough to warrant the explicit check.
    """
    ns = _exec_template(SCHEMAS_TMPL)
    TenantBase = ns["TenantBase"]
    TenantCreate = ns["TenantCreate"]

    assert TenantBase.model_config.get("extra") == "forbid", (
        "TenantBase must declare extra='forbid' so TenantCreate "
        "inherits the strict input contract."
    )
    assert TenantCreate.model_config.get("extra") == "forbid", (
        "TenantCreate must end up with extra='forbid' — either via "
        "inheritance from TenantBase or its own model_config."
    )


def test_b0_14_waiver_removed() -> None:
    """The waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_write_schemas_strict import _WAIVED_TOOLS

    assert "add_multi_tenancy" not in _WAIVED_TOOLS, (
        "B0.14 waiver entry for add_multi_tenancy was NOT removed; "
        "the fix is meaningless if the rule still skips the template."
    )


# ---------------------------------------------------------------------------
# B0.16 — tenant_filter dead-mapper branch + silent except removed
# (R5-O1-F4 / P7-F2).
# ---------------------------------------------------------------------------


def test_b0_16_filter_has_no_broad_except_in_tenant_scoped_table() -> None:
    """R5-O1-F4 / P7-F2: the broad ``except Exception: pass`` in
    ``_tenant_scoped_table`` must be gone — the entire mapper branch
    was dead code, so the fix is removal (not narrowing).
    """
    src = FILTER_TMPL.read_text(encoding="utf-8")
    tree = ast.parse(src)

    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_tenant_scoped_table":
            target = node
            break
    assert target is not None, (
        "_tenant_scoped_table function not found — tenant_filter.py.tmpl "
        "structure changed; revalidate the B0.16 fix."
    )

    # No ExceptHandler anywhere in the function body — the whole
    # try/except construct was dead code and is gone.
    for sub in ast.walk(target):
        assert not isinstance(sub, ast.Try), (
            "_tenant_scoped_table still contains a try/except — the "
            "R5-O1-F4 fix is to REMOVE the dead mapper branch entirely. "
            "If you must keep a try/except, the handler MUST narrow to "
            "AttributeError (not Exception) AND surface the failure."
        )

    # The mapper introspection import has to go too — leaving it
    # behind would tempt a future edit to re-add the dead branch.
    assert "from sqlalchemy import inspect as _sa_inspect" not in src, (
        "The local ``inspect as _sa_inspect`` import is no longer used "
        "after removing the mapper branch; clean it up to keep the "
        "module surface minimal."
    )
    assert "_sa_inspect(TenantScopedMixin" not in src, (
        "Mapper-inspect call must be gone — the column-fallback "
        "(``tenant_id`` in table.c) is the actual recognition path."
    )


def test_b0_16_filter_preserves_fail_closed_write_guard() -> None:
    """DELICATE — R5-O1-F1 (BOLA) + R5-O1-F2 (INSERT cross-tenant)
    regression guard. Removing the dead mapper branch MUST NOT touch
    the fail-closed write guard for is_update / is_delete (tenant_id
    is None → ``stmt.where(false())``). This test pins the exact
    structural invariants the prior Wave-1 fixes established.
    """
    src = FILTER_TMPL.read_text(encoding="utf-8")

    # FAIL-CLOSED on context-less writes: predicate that matches zero rows.
    assert "execute_state.statement = stmt.where(false())" in src, (
        "Fail-closed write guard removed — R5-O1-F2 regression. "
        "Context-less UPDATE/DELETE MUST be neutered with false()."
    )
    # Tenanted writes: rewrite WHERE to bind tenant_id.
    assert "stmt.where(table.c.tenant_id == tenant_id)" in src, (
        "Tenanted write guard removed — R5-O1-F2 regression. "
        "Core UPDATE/DELETE MUST be constrained to current tenant."
    )
    # SELECT path keeps its with_loader_criteria + fail-closed branch.
    assert "with_loader_criteria" in src, (
        "with_loader_criteria removed — SELECT-side tenant filter "
        "regression (R5-O1-F1 BOLA window)."
    )
    assert "lambda cls: false()" in src, (
        "Fail-closed SELECT guard removed — context-less SELECT must "
        "return zero rows, not unscoped data."
    )


def test_b0_16_filter_still_recognises_tenant_scoped_tables_by_column() -> None:
    """End-to-end: a Core ``update()`` against a table that carries a
    ``tenant_id`` column is still recognised as tenant-scoped after
    the mapper branch is removed. This is the only recognition path
    that survives the fix (and is the one R5-O1-F4 confirmed was
    doing the work all along).
    """
    # Build a minimal Core Table fixture with a tenant_id column and
    # confirm _tenant_scoped_table picks it up; build a sibling
    # without tenant_id and confirm it's rejected.
    import types

    from sqlalchemy import Column, MetaData, String, Table, Uuid, update

    # The template imports ``app.core.tenant_context`` and
    # ``app.models.mixins`` which only exist inside a generated
    # project. Stub them in sys.modules so exec can succeed in the
    # bare engine test env. We don't exercise either symbol below —
    # only ``_tenant_scoped_table``, which depends solely on the
    # column-fallback path.
    for name, attrs in (
        ("app", {}),
        ("app.core", {}),
        ("app.core.tenant_context", {"get_current_tenant": lambda: None}),
        ("app.models", {}),
        ("app.models.mixins", {"TenantScopedMixin": type("TenantScopedMixin", (), {})}),
    ):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules.setdefault(name, mod)

    ns = _exec_template(FILTER_TMPL)
    fn = ns["_tenant_scoped_table"]

    md = MetaData()
    scoped = Table(
        "widgets",
        md,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("name", String(64), nullable=False),
    )
    unscoped = Table(
        "global_config",
        md,
        Column("key", String(64), primary_key=True),
        Column("value", String(255), nullable=False),
    )

    assert fn(update(scoped)) is scoped, (
        "Scoped table not recognised — the column-fallback is the "
        "only path that remains; if this fails, the fix broke the "
        "tenant_id-column recognition that R5-O1-F2 depends on."
    )
    assert fn(update(unscoped)) is None, (
        "Unscoped table accepted — the function must return None for "
        "tables that do not carry a tenant_id column."
    )


def test_b0_16_rule_sees_no_silent_handler_in_tenant_filter() -> None:
    """Belt + braces: feed the rule's own ``find_silent_handlers`` the
    template source directly and confirm zero offenders. Catches a
    regression where someone re-introduces a broad-except inside the
    filter module.
    """
    from engine.audit.contract_rules.r_no_silent_security_failures import (
        find_silent_handlers,
    )

    src = FILTER_TMPL.read_text(encoding="utf-8")
    hits = find_silent_handlers(src)
    assert hits == [], (
        f"r_no_silent_security_failures still finds silent handlers in "
        f"tenant_filter.py.tmpl: {hits}. Any new broad-except in this "
        "module MUST either raise, bump a metric, or carry a "
        "``# pragma: B0.16-recoverable`` with a justification."
    )


def test_b0_16_waiver_removed() -> None:
    """The waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_no_silent_security_failures import (
        _WAIVED_TOOLS,
    )

    assert "extend/auth_access/add_multi_tenancy" not in _WAIVED_TOOLS, (
        "B0.16 waiver entry for add_multi_tenancy was NOT removed; "
        "the fix is meaningless if the rule still skips the template."
    )
