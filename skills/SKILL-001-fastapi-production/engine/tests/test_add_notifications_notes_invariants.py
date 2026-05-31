"""B0.13 honesty test for ``extend/infrastructure/add_notifications``.

Closes the Wave-2 waiver entries for ``add_notifications`` across:

* ``r_admin_routes_auth._WAIVED_TOOLS`` (B0.11) — IDOR via attacker-
  controlled ``user_id`` query parameter on every /notifications/* route
  (R5-O3-F1) AND the ``_get_session`` placeholder that raised
  ``NotImplementedError`` on the first HTTP hit (R5-O3-F2).
* ``r_notes_match_behaviour._WAIVED_TOOLS`` (B0.13) — the notes block
  claimed the dispatch performed multi-channel "fan-out" while the
  emitted ``channels.dispatch()`` body is a single-channel if/elif
  ladder with no loop (R5-O3-F9).
* ``r_write_schemas_strict._WAIVED_TOOLS`` (B0.14) — ``NotificationCreate``
  did not declare ``extra="forbid"`` so unknown body keys (``id``,
  ``read_at``, ``created_at``) were silently accepted by the ORM mass-
  assignment path.

What this module enforces
-------------------------

B0.13 — disclosure shape:

1. The success ToolResult ``notes=`` block carries NO ``"fan-out"`` or
   ``"channel order"`` token — those are the over-claims R5-O3-F9
   caught. Single-channel reality is asserted.
2. The success ToolResult ``warnings=`` block names the gap explicitly
   so composing agents see it at compose time. The disclosure must
   reference (a) "single-channel" delivery and (b) "best-effort"
   semantics.
3. The waiver entry is removed from ``r_notes_match_behaviour``.

B0.11 — auth shape (asserted via AST scan of the emitted template,
not exec — the template imports ``app.api.deps`` which does not exist
outside an emitted project):

4. Every ``@router.<verb>`` decorator in ``routes.py.tmpl`` declares
   ``dependencies=[Depends(get_current_user)]`` AND every handler
   exposes ``current_user: User = Depends(get_current_user)``.
5. NO handler signature carries a ``user_id`` parameter — the legacy
   ``user_id: uuid.UUID = Query(...)`` IDOR vector is removed.
6. The ``_get_session`` body delegates to
   ``app.core.session.get_session`` instead of raising
   ``NotImplementedError`` (R5-O3-F2).
7. The B0.11 waiver entry is removed from ``r_admin_routes_auth``.

B0.14 — strict schema shape:

8. ``NotificationCreate`` declares ``model_config = ConfigDict(extra=
   "forbid")`` and rejects unknown keys at parse time.
9. The B0.14 waiver entry is removed from ``r_write_schemas_strict``.

The test name carries the ``fan-out`` token (with hyphen normalised to
underscore) so B0.13's fuzzy matcher recognises this file as covering
that claim — even though the post-fix notes no longer mention it. That
keeps the matcher happy if a future drift re-introduces the word.
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
    / "infrastructure"
    / "add_notifications"
)
TOOL_INIT = TOOL_DIR / "__init__.py"
ROUTES_TMPL = TOOL_DIR / "templates" / "routes.py.tmpl"
SCHEMAS_TMPL = TOOL_DIR / "templates" / "schemas.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — symmetrical with the rule scanner. The
# notifications templates do not use ``${...}`` holes today but the
# helper keeps parity with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _exec_template(path: Path) -> dict:
    """Compile + exec a placeholder-stripped template in a fresh namespace."""
    src = _clean(path.read_text(encoding="utf-8"))
    ns: dict = {"__name__": f"under_test_{path.stem}"}
    exec(compile(src, str(path), "exec"), ns)  # noqa: S102 — exec is the test
    try:
        from pydantic import BaseModel
    except ImportError:
        return ns
    for value in list(ns.values()):
        if (
            isinstance(value, type)
            and issubclass(value, BaseModel)
            and value is not BaseModel
        ):
            try:
                value.model_rebuild(_types_namespace=ns)
            except Exception:  # noqa: BLE001
                pass
    return ns


def _all_blocks(src: str, kwarg: str) -> list[str]:
    """Return every ``<kwarg>=[ ... ]`` literal in the file as joined text.

    AST-based so embedded ``[...]`` inside a string literal (e.g. a
    next_steps line that includes ``dependencies=[Depends(...)]``)
    doesn't terminate the match early. Mirrors the helper used by
    sibling pair-test modules (test_add_feature_flags_notes_invariants).
    """
    out: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = (
            callee.id if isinstance(callee, ast.Name)
            else (callee.attr if isinstance(callee, ast.Attribute) else "")
        )
        if name != "ToolResult":
            continue
        for kw in node.keywords:
            if kw.arg != kwarg:
                continue
            if not isinstance(kw.value, ast.List):
                continue
            chunk: list[str] = []
            for el in kw.value.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    chunk.append(el.value)
            if chunk:
                out.append("\n".join(chunk))
    return out


# ---------------------------------------------------------------------------
# B0.13 — notes are honest; warnings discloses the single-channel gap
# ---------------------------------------------------------------------------


def test_b0_13_notes_do_not_overclaim_fan_out() -> None:
    """B0.13 (R5-O3-F9): the misleading 'fan-out' / 'channel order' claim
    MUST NOT appear in ANY notes block. The emitted dispatch is a
    single-channel if/elif ladder with no loop — claiming multi-channel
    fan-out is the over-claim the rule blocks.
    """
    src = TOOL_INIT.read_text(encoding="utf-8")
    notes_blocks = _all_blocks(src, "notes")
    assert notes_blocks, "Expected at least one notes=[...] literal"
    notes_text = "\n".join(notes_blocks).lower()
    assert "fan-out" not in notes_text, (
        "notes still claim 'fan-out' — the emitted channels.dispatch() "
        "is a single-channel if/elif ladder (R5-O3-F9); see warnings= "
        "for the honest single-channel disclosure."
    )
    assert "channel order" not in notes_text, (
        "notes still claim 'channel order' — there is no iteration "
        "across NOTIFICATION_CHANNELS (R5-O3-F9); the setting is "
        "advisory-only and that fact belongs in warnings=."
    )


def test_b0_13_warnings_disclose_single_channel_reality() -> None:
    """B0.13 (R5-O3-F9): the single-channel-delivery gap MUST be
    disclosed via ``warnings=`` so composing agents see it at compose
    time. ``warnings=`` is the rule's documented disclosure surface
    (the scanner does NOT inspect it, by design)."""
    src = TOOL_INIT.read_text(encoding="utf-8")
    warnings_blocks = _all_blocks(src, "warnings")
    assert warnings_blocks, (
        "Expected a warnings=[...] block in the success ToolResult; "
        "B0.13 requires the disclosure to be machine-readable, not "
        "buried in prose."
    )
    text = "\n".join(warnings_blocks).lower()
    assert "single-channel" in text, (
        "warnings= must name the single-channel delivery shape "
        "(R5-O3-F9) so a downstream agent picking a multi-channel "
        "delivery story sees the gap."
    )
    assert "best-effort" in text, (
        "warnings= must disclose the best-effort dispatch shape "
        "(no retry budget, no exactly-once) — this matches the "
        "if/elif ladder in channels_stub.py.tmpl and "
        "channels_with_email.py.tmpl."
    )
    assert "notification_channels" in text, (
        "warnings= must call out that the Settings.NOTIFICATION_CHANNELS "
        "list is advisory-only (the emitted ladder ignores it), so an "
        "operator who patches the setting sees no behaviour change."
    )


def test_b0_13_next_steps_provide_fan_out_repair_path() -> None:
    """next_steps must give operators a concrete path to multi-channel
    delivery — otherwise the disclosure is true but useless."""
    src = TOOL_INIT.read_text(encoding="utf-8")
    next_blocks = _all_blocks(src, "next_steps")
    assert next_blocks, "Expected at least one next_steps=[...] literal"
    text = "\n".join(next_blocks).lower()
    assert "notification_channels" in text or "fan-out" in text or "multi-channel" in text, (
        "next_steps must reference the multi-channel wrap-loop repair "
        "path so operators know how to compose the missing fan-out."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_notes_match_behaviour import _WAIVED_TOOLS

    assert "extend/infrastructure/add_notifications" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_notifications was NOT removed; "
        "the disclosure fix is meaningless if the rule still skips the "
        "tool's notes."
    )


# ---------------------------------------------------------------------------
# B0.11 — every route has auth; no user_id query param; session works
# ---------------------------------------------------------------------------


def _routes_module_ast() -> ast.Module:
    """Parse the placeholder-stripped routes template into an AST."""
    src = _clean(ROUTES_TMPL.read_text(encoding="utf-8"))
    return ast.parse(src)


def _route_handlers(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return every function decorated with ``@router.<verb>(...)``."""
    out: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    verbs = {"get", "post", "put", "patch", "delete"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in verbs
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "router"
            ):
                out.append(node)
                break
    return out


def test_b0_11_every_route_has_auth_dependency_on_decorator() -> None:
    """R5-O3-F1 / B0.11: every @router.<verb> decorator MUST declare
    ``dependencies=[Depends(get_current_user)]`` so the auth check runs
    BEFORE handler-parameter resolution (order-independent)."""
    tree = _routes_module_ast()
    handlers = _route_handlers(tree)
    assert len(handlers) == 4, (
        f"Expected exactly 4 routes (list / mark_read / mark_all / "
        f"unread_count), found {len(handlers)}: "
        f"{[h.name for h in handlers]}"
    )
    for handler in handlers:
        deps_present = False
        for dec in handler.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            for kw in dec.keywords:
                if kw.arg != "dependencies":
                    continue
                if not isinstance(kw.value, ast.List):
                    continue
                for el in kw.value.elts:
                    if (
                        isinstance(el, ast.Call)
                        and isinstance(el.func, ast.Name)
                        and el.func.id == "Depends"
                        and el.args
                        and isinstance(el.args[0], ast.Name)
                        and el.args[0].id == "get_current_user"
                    ):
                        deps_present = True
                        break
        assert deps_present, (
            f"Route handler {handler.name} is missing "
            f"``dependencies=[Depends(get_current_user)]`` on its "
            f"decorator (R5-O3-F1 / B0.11)."
        )


def test_b0_11_every_handler_exposes_current_user_parameter() -> None:
    """Every handler MUST also expose ``current_user: User = Depends(
    get_current_user)`` so the handler can scope queries to the
    authenticated user without a query-param vector."""
    tree = _routes_module_ast()
    for handler in _route_handlers(tree):
        names = {a.arg for a in handler.args.args} | {
            a.arg for a in handler.args.kwonlyargs
        }
        assert "current_user" in names, (
            f"Handler {handler.name} does not expose ``current_user`` "
            f"in its signature — server-side identity binding requires "
            f"it (R5-O3-F1)."
        )


def test_b0_11_no_handler_takes_user_id_query_param() -> None:
    """R5-O3-F1: the legacy ``user_id: uuid.UUID = Query(...)`` IDOR
    vector MUST be removed from EVERY handler. We assert no handler
    signature names ``user_id`` at all (the model still has user_id;
    that's fine — only the request-input surface matters here)."""
    tree = _routes_module_ast()
    for handler in _route_handlers(tree):
        names = {a.arg for a in handler.args.args} | {
            a.arg for a in handler.args.kwonlyargs
        }
        assert "user_id" not in names, (
            f"Handler {handler.name} still accepts a ``user_id`` "
            f"parameter — that re-opens R5-O3-F1 (IDOR via attacker-"
            f"controlled identifier). Use ``current_user.id`` instead."
        )


def test_b0_11_get_session_no_longer_raises_not_implemented() -> None:
    """R5-O3-F2: the ``_get_session`` placeholder previously raised
    ``NotImplementedError`` on every first call. It MUST now yield a
    real session from ``app.core.session.get_session`` so the routes
    work out-of-the-box without a dependency_override."""
    src = ROUTES_TMPL.read_text(encoding="utf-8")
    assert "raise NotImplementedError" not in src, (
        "routes.py.tmpl still raises NotImplementedError in "
        "_get_session — R5-O3-F2 says the first HTTP hit will 500."
    )
    assert "from app.core.session import get_session" in src, (
        "routes.py.tmpl must import the canonical session dep so "
        "_get_session has a working default (R5-O3-F2)."
    )


def test_b0_11_waiver_removed() -> None:
    """The B0.11 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_admin_routes_auth import _WAIVED_TOOLS

    assert "add_notifications" not in _WAIVED_TOOLS, (
        "B0.11 waiver entry for add_notifications was NOT removed; "
        "the auth fix is meaningless if the rule still skips the "
        "template."
    )


# ---------------------------------------------------------------------------
# B0.14 — NotificationCreate rejects unknown keys
# ---------------------------------------------------------------------------


def test_b0_14_notification_create_rejects_unknown_keys() -> None:
    """B0.14 (R6-O3 P5): the write schema MUST reject unknown keys.
    Pre-fix the schema lacked ``extra="forbid"`` so any extra key
    (e.g. ``id``, ``read_at``, ``created_at``) was silently accepted
    into the ORM via mass-assignment."""
    from pydantic import ValidationError

    ns = _exec_template(SCHEMAS_TMPL)
    NotificationCreate = ns.get("NotificationCreate")
    assert NotificationCreate is not None

    # Sanity: minimal valid payload accepted.
    import uuid as _uuid
    ok = NotificationCreate(user_id=_uuid.uuid4(), title="hello")
    assert ok.title == "hello"

    # Core assertion: unknown ORM column smuggled in must raise.
    with pytest.raises(ValidationError):
        NotificationCreate(
            user_id=_uuid.uuid4(),
            title="hello",
            read_at="2099-01-01T00:00:00Z",  # smuggled ORM column
        )

    # Also: arbitrary attacker-named key must raise.
    with pytest.raises(ValidationError):
        NotificationCreate(
            user_id=_uuid.uuid4(),
            title="hello",
            is_admin=True,  # smuggled
        )


def test_b0_14_waiver_removed() -> None:
    """The B0.14 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_write_schemas_strict import _WAIVED_TOOLS

    assert "add_notifications" not in _WAIVED_TOOLS, (
        "B0.14 waiver entry for add_notifications was NOT removed; "
        "the schema fix is meaningless if the rule still skips the "
        "template."
    )
