"""Phase-6 Round-4 adversarial-juror regression tests.

Four findings the Phase-5 PR (#76) closed at the user-side but moved
the failure mode rather than eliminating it. The Round-4 hostile probe
re-ran against the merged fix and found:

  N-1 (HIGH) — bola_guard's session Depends defaulted to
        ``lambda: None``; ``_enforce`` saw ``session is None`` and
        returned silently — fail-OPEN with no DB ownership check.
        Pre-fix: silent allow. Post-fix: fail-CLOSED 503.
  N-2 (LOW) — tenant_filter docstring claimed "Every SELECT, UPDATE,
        and DELETE" coverage; the listener only fires for ORM-issued
        constructs, raw ``session.execute(text("UPDATE ..."))`` slips
        past. Post-fix: docstring tightened + escape-hatch documented.
  N-3 (LOW) — ``except Exception`` swallowed all import failures in
        bola_guard (including SyntaxError). Post-fix: narrowed to
        ``except ImportError`` so non-import failures surface.
  N-4 (LOW) — tenant_routes caught any IntegrityError and returned
        409 "slug already exists" — future ``tenants_name_key``
        UNIQUE would be mis-attributed. Post-fix: inspect ``e.orig``
        and re-raise non-slug constraints.

Each test is written to FAIL pre-fix and PASS post-fix.

Run with::

    PYTHONPATH=. pytest engine/tests/test_phase6_round4_findings.py -v
"""

from __future__ import annotations

import ast as _ast
from pathlib import Path

import pytest

# ===========================================================================
# Helpers
# ===========================================================================


def _skill_root() -> Path:
    """Locate the SKILL-001 root from this test file's location."""
    return Path(__file__).resolve().parents[1].parent


def _load_bola_template_source() -> str:
    return (
        _skill_root()
        / "adapt"
        / "extend"
        / "auth_access"
        / "add_bola_guard"
        / "templates"
        / "bola_guard.py.tmpl"
    ).read_text()


def _load_tenant_filter_source() -> str:
    return (
        _skill_root()
        / "adapt"
        / "extend"
        / "auth_access"
        / "add_multi_tenancy"
        / "templates"
        / "tenant_filter.py.tmpl"
    ).read_text()


def _load_tenant_routes_source() -> str:
    return (
        _skill_root()
        / "adapt"
        / "extend"
        / "auth_access"
        / "add_multi_tenancy"
        / "templates"
        / "tenant_routes.py.tmpl"
    ).read_text()


# ===========================================================================
# N-1 — BOLA guard FAIL-CLOSED on un-wired session
# ===========================================================================


def test_N1_template_does_not_default_session_to_lambda_none() -> None:
    """N-1 (static): the ``session`` Depends default must not be the
    pre-fix ``Depends(lambda: None)``.

    Pre-fix: ``session: AsyncSession = Depends(lambda: None)`` — FastAPI
    invokes ``lambda: None`` at request time, ``_enforce`` sees
    ``session is None`` and returned silently. Fail-OPEN.

    Post-fix: ``Depends(_scaffold_session_dep)`` when the scaffold
    session dep imports OK. The ``lambda: None`` only appears as the
    last-resort fallback when the scaffold dep is missing, AND in that
    case ``_enforce`` raises 503 rather than silently returning.
    """
    src = _load_bola_template_source()
    # The scaffold session dep import + bind must be present.
    assert "from app.core.session import get_session as _scaffold_session_dep" in src, (
        "N-1 REGRESSION: bola_guard does not try to import the scaffold "
        "session dep. With no real session, every request degrades to "
        "the fail-CLOSED 503 path — a regression even when the scaffold "
        "IS wired."
    )
    assert "Depends(_scaffold_session_dep)" in src, (
        "N-1 REGRESSION: the verifier signature does not bind "
        "Depends(_scaffold_session_dep) — the session Depends still "
        "defaults to a no-op."
    )


def test_N1_enforce_raises_503_when_session_is_none() -> None:
    """N-1 (behavioral): ``_enforce`` MUST raise HTTPException(503)
    when session is None — fail-CLOSED.

    Pre-fix this branch returned silently → fail-OPEN: the route
    handler ran with ZERO ownership enforcement. Post-fix the guard
    refuses (503) rather than allows.

    We exercise the REAL template by AST-extracting ``_enforce`` from
    bola_guard.py.tmpl and exec'ing it in a namespace with shimmed
    FastAPI exception types.
    """
    from fastapi import HTTPException, status

    src = _load_bola_template_source()
    tree = _ast.parse(src)
    # Find OwnershipVerifier class, then its _enforce method + the
    # optional _fail_closed_no_session helper (refactored out to keep
    # _enforce under the 50-LOC cap pre-existing test enforces).
    cls_node = next(
        n for n in tree.body if isinstance(n, _ast.ClassDef) and n.name == "OwnershipVerifier"
    )
    enforce_fn = next(
        n for n in cls_node.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_enforce"
    )
    helper_fn = next(
        (
            n
            for n in cls_node.body
            if isinstance(n, _ast.FunctionDef) and n.name == "_fail_closed_no_session"
        ),
        None,
    )
    # Wrap as stand-alone fns; bind to a synthetic ``self`` that exposes
    # both methods + the attributes either reads (model + owner).
    body = [enforce_fn] if helper_fn is None else [helper_fn, enforce_fn]
    module = _ast.Module(body=body, type_ignores=[])
    _ast.fix_missing_locations(module)

    import logging as _logging

    class _Model:
        __name__ = "Order"

    ns: dict = {
        "HTTPException": HTTPException,
        "status": status,
        "logger": _logging.getLogger("bola_test"),
    }
    exec(compile(module, "<bola_enforce>", "exec"), ns)
    enforce = ns["_enforce"]
    fail_closed = ns.get("_fail_closed_no_session")

    class _SelfStub:
        _model = _Model
        _owner_field = "user_id"
        _fail_closed_no_session = (
            (lambda self, rid, _f=fail_closed: _f(self, rid)) if fail_closed is not None else None
        )

    import asyncio

    async def _drive():
        await enforce(_SelfStub(), session=None, resource_id=42, current_user_id=7)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_drive())
    assert excinfo.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        f"N-1 REGRESSION: _enforce with session=None must raise 503 "
        f"(fail-CLOSED), got status={excinfo.value.status_code}. Pre-fix "
        f"this branch returned silently → every protected route was a "
        f"fail-OPEN no-op invisible to pentest/SOC2 audit."
    )


def test_N1_enforce_does_not_silently_return_on_none_session() -> None:
    """N-1 (anti-regression): the source of ``_enforce`` MUST NOT
    contain the pre-fix silent-return path ``return`` inside the
    ``if session is None`` branch.

    Belt-and-braces alongside the behavioral test — guards against a
    future contributor reverting the body to ``logger.warning(...);
    return`` while leaving the surrounding surface intact.
    """
    src = _load_bola_template_source()
    # Find the _enforce method body and assert it raises an HTTPException
    # in the no-session branch.
    tree = _ast.parse(src)
    cls_node = next(
        n for n in tree.body if isinstance(n, _ast.ClassDef) and n.name == "OwnershipVerifier"
    )
    enforce_fn = next(
        n for n in cls_node.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_enforce"
    )
    # Find the first ``if session is None`` block.
    none_branch: _ast.If | None = None
    for stmt in enforce_fn.body:
        if (
            isinstance(stmt, _ast.If)
            and isinstance(stmt.test, _ast.Compare)
            and isinstance(stmt.test.left, _ast.Name)
            and stmt.test.left.id == "session"
            and any(isinstance(op, _ast.Is) for op in stmt.test.ops)
        ):
            none_branch = stmt
            break
    assert none_branch is not None, (
        "N-1: could not locate the ``if session is None`` branch in "
        "_enforce — refactor changed the shape; revisit the regression "
        "test."
    )
    # The branch must NOT contain a bare ``return`` (the pre-fix silent
    # fail-open). It MUST raise directly OR call a helper that raises
    # (e.g. _fail_closed_no_session — refactored to keep _enforce under
    # the 50-LOC cap pre-existing test enforces).
    has_bare_return = any(isinstance(s, _ast.Return) for s in none_branch.body)
    has_raise = any(isinstance(s, _ast.Raise) for s in none_branch.body)
    has_fail_closed_call = any(
        isinstance(s, _ast.Expr)
        and isinstance(s.value, _ast.Call)
        and isinstance(s.value.func, _ast.Attribute)
        and s.value.func.attr in ("_fail_closed_no_session", "_fail_closed")
        for s in none_branch.body
    )
    assert not has_bare_return, (
        "N-1 REGRESSION: _enforce's no-session branch still contains a "
        "bare ``return`` — silent fail-OPEN. The branch must raise."
    )
    assert has_raise or has_fail_closed_call, (
        "N-1 REGRESSION: _enforce's no-session branch does NOT raise "
        "nor call a fail-closed helper — fail-CLOSED path missing."
    )


# ===========================================================================
# N-2 — tenant_filter docstring tightened
# ===========================================================================


def test_N2_tenant_filter_docstring_uses_orm_qualifier() -> None:
    """N-2: the module docstring must say "ORM-issued" (not the
    unqualified "Every SELECT, UPDATE, and DELETE").

    Pre-fix the docstring claimed coverage the listener does NOT
    actually provide — raw ``session.execute(text("UPDATE ..."))``
    bypasses ``do_orm_execute`` entirely. The fix is to scope the
    promise to ORM-issued constructs and document the raw-text() escape
    hatch.
    """
    src = _load_tenant_filter_source()
    tree = _ast.parse(src)
    docstring = _ast.get_docstring(tree) or ""
    assert docstring, "N-2: tenant_filter must have a module docstring"
    assert "ORM-issued" in docstring, (
        "N-2 REGRESSION: tenant_filter docstring does not qualify the "
        "claim as ORM-issued — readers will assume raw text() is also "
        "covered when it is not."
    )
    # The unqualified pre-fix promise must NOT be present.
    assert "Every SELECT, UPDATE, and DELETE against a\nTenantScopedMixin" not in docstring, (
        "N-2 REGRESSION: tenant_filter docstring still makes the "
        "unqualified ``Every SELECT, UPDATE, and DELETE`` claim — "
        "promises raw-text() coverage the listener does not provide."
    )
    # And the escape-hatch / before_execute pointer must be there.
    assert "before_execute" in docstring, (
        "N-2: docstring must point at the engine-level ``before_execute`` "
        "listener as the alternative for raw-text() coverage."
    )
    assert "text(" in docstring or "raw" in docstring.lower(), (
        "N-2: docstring must mention raw-text() as the uncovered surface."
    )


# ===========================================================================
# N-3 — bola_guard scaffold import narrowed to ImportError
# ===========================================================================


def test_N3_bola_guard_narrows_scaffold_import_to_ImportError() -> None:
    """N-3: the try/except around the scaffold ``get_current_user``
    import MUST catch ``ImportError`` specifically, not bare
    ``Exception``.

    Pre-fix: ``except Exception`` swallowed SyntaxError, RuntimeError,
    and every other failure class — if ``app.api.deps`` had a typo,
    ``_scaffold_get_current_user`` would silently become None and the
    verifier would lose its primary auth path with no diagnostic.
    Exactly the failure-class that produced the Round-3 BOLA disconnect.
    """
    src = _load_bola_template_source()
    tree = _ast.parse(src)

    # Walk top-level statements; find the Try whose body imports
    # ``get_current_user`` from ``app.api.deps``.
    target_try: _ast.Try | None = None
    for node in tree.body:
        if not isinstance(node, _ast.Try):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, _ast.ImportFrom)
                and stmt.module == "app.api.deps"
                and any(alias.name == "get_current_user" for alias in stmt.names)
            ):
                target_try = node
                break
        if target_try is not None:
            break
    assert target_try is not None, (
        "N-3: could not locate the try-block around the scaffold "
        "get_current_user import — refactor changed shape; revisit."
    )
    # All handlers must be narrow to ImportError (no bare Exception).
    for handler in target_try.handlers:
        # ``except ImportError as _exc`` → handler.type = Name('ImportError')
        # ``except Exception`` → handler.type = Name('Exception')
        # ``except:`` → handler.type = None  (also forbidden)
        assert handler.type is not None, (
            "N-3 REGRESSION: bare ``except:`` in bola_guard scaffold import."
        )
        if isinstance(handler.type, _ast.Name):
            assert handler.type.id == "ImportError", (
                f"N-3 REGRESSION: bola_guard scaffold import handler "
                f"catches ``{handler.type.id}`` — must be narrowed to "
                f"``ImportError`` so non-import failures (SyntaxError, "
                f"transitive RuntimeError, etc.) surface rather than "
                f"silently NULL-out the auth path."
            )
        elif isinstance(handler.type, _ast.Tuple):
            ids = {e.id for e in handler.type.elts if isinstance(e, _ast.Name)}
            assert ids <= {"ImportError"}, (
                f"N-3 REGRESSION: bola_guard scaffold import handler "
                f"catches {ids} — non-ImportError exceptions must NOT "
                f"be swallowed."
            )


def test_N3_non_import_error_propagates_through_template_import() -> None:
    """N-3 (behavioral): when ``app.api.deps`` raises a non-import
    error at import time, the template import MUST propagate it (not
    silently NULL-out ``_scaffold_get_current_user``).

    We synthesise a fake ``app.api.deps`` module that raises
    ``ValueError`` on access of ``get_current_user``, then exec the
    real bola_guard.py.tmpl into a namespace and assert the import
    actually surfaces — not swallowed.

    Note: ``from X import Y`` where attribute access on the module
    raises a non-ImportError will propagate that exception (not wrap
    it in ImportError). The pre-fix ``except Exception`` would have
    caught + swallowed it. The post-fix ``except ImportError`` will
    NOT catch it — exactly the contract this test pins.
    """
    import sys
    import types as _types

    # Construct a fake ``app.api.deps`` module whose attribute access
    # for ``get_current_user`` raises ValueError (simulating a
    # transitive import-time bug like a SyntaxError in a sub-module).
    class _ExplodingModule(_types.ModuleType):
        def __getattr__(self, name):  # noqa: D401
            if name == "get_current_user":
                raise ValueError("simulated transitive failure")
            raise AttributeError(name)

    # Parent packages.
    saved = {}
    try:
        for pkg in ("app", "app.api"):
            saved[pkg] = sys.modules.get(pkg)
            mod = _types.ModuleType(pkg)
            mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg] = mod
        saved["app.api.deps"] = sys.modules.get("app.api.deps")
        sys.modules["app.api.deps"] = _ExplodingModule("app.api.deps")

        # Also need a fake ``app.core.session`` so the OTHER import
        # branch doesn't itself blow up first.
        saved["app.core"] = sys.modules.get("app.core")
        sys.modules["app.core"] = _types.ModuleType("app.core")
        sys.modules["app.core"].__path__ = []  # type: ignore[attr-defined]
        saved["app.core.session"] = sys.modules.get("app.core.session")
        session_mod = _types.ModuleType("app.core.session")

        def _stub_get_session():
            yield None

        session_mod.get_session = _stub_get_session  # type: ignore[attr-defined]
        sys.modules["app.core.session"] = session_mod

        src = _load_bola_template_source()
        # Exec the template. With the pre-fix ``except Exception``,
        # the ValueError would be swallowed and the exec completes
        # silently with _scaffold_get_current_user = None. With the
        # post-fix narrowed ``except ImportError``, ValueError
        # propagates and exec raises.
        with pytest.raises(ValueError, match="simulated transitive failure"):
            exec(compile(src, "<bola_guard.py.tmpl>", "exec"), {})
    finally:
        # Restore sys.modules.
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ===========================================================================
# N-4 — tenant_routes IntegrityError narrowed to slug constraint
# ===========================================================================


def test_N4_tenant_routes_inspects_e_orig_for_constraint() -> None:
    """N-4 (static): the IntegrityError handler must inspect
    ``e.orig`` rather than blanket-returning 409.

    Pre-fix: ``except IntegrityError: raise HTTPException(409, ...)``
    surfaced ALL UNIQUE / FK / CHECK constraint failures as a
    misleading "slug already exists" 409. Post-fix: inspect
    ``e.orig`` and re-raise non-slug constraints.
    """
    src = _load_tenant_routes_source()
    tree = _ast.parse(src)
    create_fn = next(
        n for n in tree.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "create_tenant"
    )
    # Find the IntegrityError handler and assert it does at least one
    # of: (a) attribute access on ``e.orig`` / ``e``, (b) contains a
    # bare ``raise`` (re-raise of non-slug constraints).
    try_node = next(s for s in create_fn.body if isinstance(s, _ast.Try))
    integrity_handler = next(
        h
        for h in try_node.handlers
        if isinstance(h.type, _ast.Name) and h.type.id == "IntegrityError"
    )
    assert integrity_handler.name, (
        "N-4 REGRESSION: IntegrityError handler does not bind the "
        "exception (``as e``) — cannot inspect e.orig."
    )
    # Walk the handler body and assert ``e.orig`` (Attribute on Name)
    # appears at least once.
    saw_orig_access = False
    saw_bare_raise = False
    for sub in _ast.walk(integrity_handler):
        if (
            isinstance(sub, _ast.Attribute)
            and sub.attr == "orig"
            and isinstance(sub.value, _ast.Name)
            and sub.value.id == integrity_handler.name
        ):
            saw_orig_access = True
        if isinstance(sub, _ast.Raise) and sub.exc is None:
            # ``raise`` with no expression = re-raise current exception.
            saw_bare_raise = True
        # ``getattr(e, "orig", ...)`` is also an acceptable inspection.
        if (
            isinstance(sub, _ast.Call)
            and isinstance(sub.func, _ast.Name)
            and sub.func.id == "getattr"
            and len(sub.args) >= 2
            and isinstance(sub.args[0], _ast.Name)
            and sub.args[0].id == integrity_handler.name
            and isinstance(sub.args[1], _ast.Constant)
            and sub.args[1].value == "orig"
        ):
            saw_orig_access = True
    assert saw_orig_access, (
        "N-4 REGRESSION: IntegrityError handler does not inspect "
        "``e.orig`` — every IntegrityError still maps to a 409 "
        "regardless of which constraint actually failed."
    )
    assert saw_bare_raise, (
        "N-4 REGRESSION: IntegrityError handler does not re-raise on "
        "non-slug constraints — a future tenants_name_key violation "
        "would still surface as a misleading 'slug already exists'."
    )


@pytest.mark.asyncio
async def test_N4_non_slug_integrity_error_reraises() -> None:
    """N-4 (behavioral): a non-slug UNIQUE constraint violation MUST
    propagate as the underlying IntegrityError, NOT a misleading 409.

    We exec the real ``create_tenant`` function out of
    ``tenant_routes.py.tmpl`` and trigger an IntegrityError whose
    ``e.orig`` message identifies a ``tenants_name_key`` violation —
    a fictional future UNIQUE constraint on the ``name`` column.

    Pre-fix: returns 409 "Tenant slug already exists" → caller is
    misled. Post-fix: re-raises IntegrityError → framework surfaces a
    500 with the honest underlying message.
    """
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    src = _load_tenant_routes_source()
    tree = _ast.parse(src)
    create_fn = next(
        n for n in tree.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "create_tenant"
    )
    create_fn.decorator_list = []
    create_fn.returns = None
    module = _ast.Module(body=[create_fn], type_ignores=[])
    _ast.fix_missing_locations(module)

    class _CrudTenantStub:
        @staticmethod
        async def get_by_slug(session, *, slug: str):
            return None

        @staticmethod
        async def create(session, *, tenant_in):
            # Simulate a future tenants_name_key UNIQUE-constraint
            # collision (NOT the slug). orig carries the constraint
            # signature the handler should detect.
            raise IntegrityError(
                "INSERT INTO tenants ...",
                {},
                Exception('duplicate key value violates unique constraint "tenants_name_key"'),
            )

    class _FakeSession:
        async def rollback(self):
            return None

    class _TenantPublicStub:
        @staticmethod
        def model_validate(obj):
            return obj

    ns: dict = {
        "HTTPException": HTTPException,
        "IntegrityError": IntegrityError,
        "crud_tenant": _CrudTenantStub,
        "TenantPublic": _TenantPublicStub,
    }
    exec(compile(module, "<tenant_routes_create>", "exec"), ns)
    create_tenant_fn = ns["create_tenant"]

    class _Body:
        slug = "any-slug"

    body = _Body()
    session = _FakeSession()

    # Post-fix: the handler must detect ``tenants_name_key`` and
    # re-raise the underlying IntegrityError (NOT surface a 409).
    with pytest.raises(IntegrityError):
        await create_tenant_fn(body, session, None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_N4_slug_integrity_error_still_409() -> None:
    """N-4 (anti-regression): the slug-collision path MUST still
    surface as a 409.

    Ensures the narrowing did not break the legitimate slug-race
    handler that Phase-5 F-D added. Uses an ``e.orig`` message with
    the SQLite slug-constraint signature.
    """
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    src = _load_tenant_routes_source()
    tree = _ast.parse(src)
    create_fn = next(
        n for n in tree.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "create_tenant"
    )
    create_fn.decorator_list = []
    create_fn.returns = None
    module = _ast.Module(body=[create_fn], type_ignores=[])
    _ast.fix_missing_locations(module)

    class _CrudTenantStub:
        @staticmethod
        async def get_by_slug(session, *, slug: str):
            return None

        @staticmethod
        async def create(session, *, tenant_in):
            raise IntegrityError(
                "INSERT INTO tenants ...",
                {},
                Exception("UNIQUE constraint failed: tenants.slug"),
            )

    class _FakeSession:
        async def rollback(self):
            return None

    class _TenantPublicStub:
        @staticmethod
        def model_validate(obj):
            return obj

    ns: dict = {
        "HTTPException": HTTPException,
        "IntegrityError": IntegrityError,
        "crud_tenant": _CrudTenantStub,
        "TenantPublic": _TenantPublicStub,
    }
    exec(compile(module, "<tenant_routes_create>", "exec"), ns)
    create_tenant_fn = ns["create_tenant"]

    class _Body:
        slug = "shared-slug"

    body = _Body()
    session = _FakeSession()

    with pytest.raises(HTTPException) as excinfo:
        await create_tenant_fn(body, session, None)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 409, (
        f"N-4 anti-regression: slug-collision must still surface as "
        f"409, got {excinfo.value.status_code}."
    )
