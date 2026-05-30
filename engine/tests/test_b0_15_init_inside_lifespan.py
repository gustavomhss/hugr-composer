"""B0.15 — ``init_inside_lifespan_only`` regression suite.

Maps 1:1 to the rule body in
``engine/audit/contract_rules/r_init_inside_lifespan.py``.

Each test exercises one branch of the rule's classifier — the goal is
"explicit reds and explicit greens" so a future refactor that loosens
the AST walk turns one of these tests red instead of silently passing.

Convention: the rule's public helpers are
``find_offences(src) -> [(name, lineno), ...]`` (templates) and
``find_offences_in_patches(src) -> [(name, lineno), ...]``
(``_patches.py`` files). Tests pass synthetic Python sources directly —
NO disk fixture files — so the test runs identically inside CI,
inside a sandbox, and inside ``pytest --collect-only`` without
depending on the catalog scan.

Catalog-scan integration is covered by
``test_b0_15_callback_returns_bool_str_tuple`` at the bottom: it just
asserts the rule callback is callable and the return shape is
``(bool, str)`` — content is asserted by ``contract_check`` itself.
"""

from __future__ import annotations

import textwrap

import pytest

from engine.audit.contract_rules.r_init_inside_lifespan import (
    _is_offence_name,
    _r_init_inside_lifespan_only,
    _tool_key_for,
    find_offences,
    find_offences_in_patches,
)


def _src(body: str) -> str:
    """Dedent + strip leading newline so test bodies read naturally."""
    return textwrap.dedent(body).lstrip("\n")


# ----------------------------------------------------------------------
# REDS — these should trigger the rule
# ----------------------------------------------------------------------


def test_red_init_call_at_module_top() -> None:
    """``init_idempotency_cache(url)`` at module top → flagged."""
    hits = find_offences(_src("""
        import os as _os
        _redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")
        init_idempotency_cache(_redis_url)
    """))
    assert len(hits) == 1
    name, lineno = hits[0]
    assert name == "init_idempotency_cache"
    assert lineno == 3


def test_red_private_init_call() -> None:
    """``_init_metrics(prefix=...)`` (leading underscore) → flagged.

    Match strips leading underscores so private helpers count.
    """
    hits = find_offences(_src("""
        _init_metrics(prefix="http")
    """))
    assert len(hits) == 1
    assert hits[0][0] == "_init_metrics"


def test_red_create_pool() -> None:
    """``create_redis_pool(...)`` → flagged."""
    hits = find_offences(_src("""
        create_redis_pool(url="redis://...")
    """))
    assert len(hits) == 1
    assert hits[0][0] == "create_redis_pool"


def test_red_configure_arbitrary() -> None:
    """``configure_telemetry(...)`` → flagged (not allowlisted)."""
    hits = find_offences(_src("""
        configure_telemetry(endpoint="x")
    """))
    assert len(hits) == 1
    assert hits[0][0] == "configure_telemetry"


def test_red_start_listener() -> None:
    """``start_event_listener(bus)`` → flagged."""
    hits = find_offences(_src("""
        start_event_listener(bus)
    """))
    assert len(hits) == 1
    assert hits[0][0] == "start_event_listener"


def test_red_start_worker() -> None:
    """``start_outbox_worker()`` → flagged."""
    hits = find_offences(_src("""
        start_outbox_worker()
    """))
    assert len(hits) == 1
    assert hits[0][0] == "start_outbox_worker"


def test_red_register_routes() -> None:
    """``register_health_routes(app)`` → flagged (not register_router)."""
    hits = find_offences(_src("""
        register_health_routes(app)
    """))
    assert len(hits) == 1
    assert hits[0][0] == "register_health_routes"


def test_red_call_inside_if_block_still_top() -> None:
    """An ``init_*`` inside a top-level ``if`` is still module-top.

    Control-flow statements do NOT open a new function scope; the call
    runs at import time.
    """
    hits = find_offences(_src("""
        import os
        if os.getenv("METRICS_ENABLED") == "1":
            init_metrics()
    """))
    assert len(hits) == 1
    assert hits[0][0] == "init_metrics"


def test_red_attribute_call_uses_tail() -> None:
    """``mod.init_foo()`` matches on the tail (``init_foo``)."""
    hits = find_offences(_src("""
        import _m
        _m.init_foo()
    """))
    assert len(hits) == 1
    assert hits[0][0] == "init_foo"


def test_red_multiple_offenders_all_reported() -> None:
    """When several offences fire, all surface in deterministic order."""
    hits = find_offences(_src("""
        init_a()
        create_db_pool()
        configure_things()
    """))
    assert [h[0] for h in hits] == ["init_a", "create_db_pool", "configure_things"]


# ----------------------------------------------------------------------
# GREENS — these should NOT trigger the rule
# ----------------------------------------------------------------------


def test_green_call_inside_lifespan() -> None:
    """``init_X()`` inside ``async def lifespan(...)`` → allowed."""
    hits = find_offences(_src("""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app):
            init_idempotency_cache("redis://...")
            yield
    """))
    assert hits == []


def test_green_call_inside_lifespan_nested_control_flow() -> None:
    """Calls inside ``with``/``if`` inside lifespan are still inside lifespan."""
    hits = find_offences(_src("""
        async def lifespan(app):
            import os
            if os.getenv("X") == "1":
                init_thing()
                start_event_listener(bus)
            yield
    """))
    assert hits == []


def test_green_configure_logging_allowed() -> None:
    """Spec carve-out: ``configure_logging`` is allowed at module top."""
    hits = find_offences(_src("""
        configure_logging(level="INFO")
    """))
    assert hits == []


def test_green_register_router_allowed() -> None:
    """Spec carve-out: ``register_router`` is allowed at module top."""
    hits = find_offences(_src("""
        register_router(app)
    """))
    assert hits == []


def test_green_include_router_not_match() -> None:
    """``app.include_router(...)`` is not an init-class call."""
    hits = find_offences(_src("""
        app.include_router(health_router)
    """))
    assert hits == []


def test_green_add_middleware_not_match() -> None:
    """``app.add_middleware(...)`` is not an init-class call."""
    hits = find_offences(_src("""
        app.add_middleware(SomeMiddleware, x=1)
    """))
    assert hits == []


def test_green_install_prefix_not_match() -> None:
    """``install_audit_log(app)`` does not match any offence pattern."""
    hits = find_offences(_src("""
        install_audit_log(app)
    """))
    assert hits == []


def test_green_pragma_bypass_per_line() -> None:
    """``# pragma: B0.15: <reason>`` on the same line → exempted."""
    hits = find_offences(_src("""
        init_idempotency_cache("redis://...")  # pragma: B0.15: legacy single-process only
    """))
    assert hits == []


def test_red_pragma_without_reason_does_not_bypass() -> None:
    """Bare ``# pragma: B0.15:`` (no reason) → still flagged.

    Defensive: the bypass requires a written justification, mirroring
    B0.11's ``_PUBLIC_ROUTE_JUSTIFICATION`` posture.
    """
    hits = find_offences(_src("""
        init_idempotency_cache("redis://...")  # pragma: B0.15:
    """))
    assert len(hits) == 1
    assert hits[0][0] == "init_idempotency_cache"


def test_green_assign_without_call() -> None:
    """``_x = os.getenv(...)`` is not a Call to a matched name."""
    hits = find_offences(_src("""
        import os as _os
        _redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")
    """))
    assert hits == []


def test_green_call_inside_function_def() -> None:
    """``init_X()`` inside a non-lifespan ``def`` body is NOT module-top.

    A normal function defines its body but doesn't execute it at import,
    so the offence pattern doesn't apply.
    """
    hits = find_offences(_src("""
        def setup(app):
            init_idempotency_cache("redis://...")
    """))
    assert hits == []


def test_green_class_body_not_top() -> None:
    """Class body is its own scope — not module-top execution."""
    hits = find_offences(_src("""
        class X:
            init_foo()
    """))
    assert hits == []


def test_green_placeholder_substitution_parses() -> None:
    """``${var}`` / ``$var`` placeholders normalise before AST parse."""
    src = _src("""
        class ${EventName}V1:
            pass

        $registry_init

        # Inside the lifespan placeholder:
        async def lifespan(app):
            init_thing()
            yield
    """)
    hits = find_offences(src)
    assert hits == []


def test_green_unparseable_fragment_returns_empty() -> None:
    """A non-parseable compose fragment is silently skipped."""
    src = "leftover ${if condition}\ninit_foo()\nleftover\n"
    # The ``${if condition}`` placeholder normalises to ``if`` —
    # an ``if`` token followed by whitespace alone is still a
    # syntax error, so parse fails → empty result.
    assert find_offences(src) == []


# ----------------------------------------------------------------------
# _patches.py — intent-detected mutators
# ----------------------------------------------------------------------


def test_patches_red_init_in_patch_main_body() -> None:
    """``def patch_main(...)`` body calls ``init_X`` → flagged."""
    hits = find_offences_in_patches(_src("""
        def patch_main(path):
            init_idempotency_cache("redis://...")
    """))
    assert len(hits) == 1
    assert hits[0][0] == "init_idempotency_cache"


def test_patches_green_call_inside_lifespan_inside_patch_main() -> None:
    """``patch_main`` that splices into a lifespan body → allowed.

    A ``_patches.py`` may emit Python whose top-level shape includes
    ``async def lifespan(...)`` — calls inside that lifespan don't
    fire.
    """
    hits = find_offences_in_patches(_src("""
        def patch_main(path):
            async def lifespan(app):
                init_thing()
                yield
            install(lifespan)
    """))
    assert hits == []


def test_patches_green_no_patch_main_function() -> None:
    """A ``_patches.py`` without any ``*patch_main*`` helper → ignored.

    Intent detection: if the file never names a patcher targeting main,
    we don't try to guess.
    """
    hits = find_offences_in_patches(_src("""
        def patch_models_init(p):
            init_metrics()
    """))
    assert hits == []


def test_patches_green_unparseable() -> None:
    """Unparseable ``_patches.py`` returns empty list (defensive)."""
    assert find_offences_in_patches("def foo(:\n  init_x()") == []


# ----------------------------------------------------------------------
# Waiver + bypass behaviour (integration with the catalog)
# ----------------------------------------------------------------------


def test_waiver_skips_listed_tool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A tool in ``_WAIVED_TOOLS`` is exempt from the catalog scan.

    Strategy: point ADAPT_ROOT at a temp tree with one offending
    template under ``extend/_w/synthetic/templates/main_patch.py.tmpl``,
    add that tool key to the waiver set, assert OK.
    """
    from engine.audit.contract_rules import r_init_inside_lifespan as mod

    tool_dir = tmp_path / "extend" / "_w" / "synthetic" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "main_patch.py.tmpl").write_text(_src("""
        init_idempotency_cache("redis://...")
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(
        mod,
        "_WAIVED_TOOLS",
        frozenset({"extend/_w/synthetic"}),
    )
    ok, msg = mod._r_init_inside_lifespan_only()
    assert ok, msg


def test_unwaived_tool_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Same offender WITHOUT the waiver → rule rejects."""
    from engine.audit.contract_rules import r_init_inside_lifespan as mod

    tool_dir = tmp_path / "extend" / "_u" / "tool" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "main_patch.py.tmpl").write_text(_src("""
        init_idempotency_cache("redis://...")
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, msg = mod._r_init_inside_lifespan_only()
    assert not ok
    assert "init_idempotency_cache" in msg
    assert "main_patch.py.tmpl" in msg


def test_bypass_lifespan_exempt_plus_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``_LIFESPAN_EXEMPT = True`` + ``warnings=[..."lifespan"...]`` → exempted.

    The tool gets the offending template AND the disclosure pair; the
    rule must accept the bypass even though the tool is NOT in
    ``_WAIVED_TOOLS``.
    """
    from engine.audit.contract_rules import r_init_inside_lifespan as mod

    tool_dir = tmp_path / "extend" / "_b" / "bypass_tool"
    (tool_dir / "templates").mkdir(parents=True)
    (tool_dir / "__init__.py").write_text(_src("""
        from __future__ import annotations
        _LIFESPAN_EXEMPT: bool = True

        def run():
            return {"warnings": ["module-top init disclosed (no lifespan)"]}
    """))
    (tool_dir / "templates" / "main_patch.py.tmpl").write_text(_src("""
        init_idempotency_cache("redis://...")
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, msg = mod._r_init_inside_lifespan_only()
    assert ok, msg


def test_bypass_requires_both_signals(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``_LIFESPAN_EXEMPT = True`` ALONE (no warnings) does NOT bypass.

    Mirrors the B0.10 / B0.12 posture: both disclosure halves are
    required for the structural bypass — a magic boolean alone is not
    enough.
    """
    from engine.audit.contract_rules import r_init_inside_lifespan as mod

    tool_dir = tmp_path / "extend" / "_n" / "no_warning"
    (tool_dir / "templates").mkdir(parents=True)
    (tool_dir / "__init__.py").write_text(_src("""
        _LIFESPAN_EXEMPT: bool = True
    """))
    (tool_dir / "templates" / "main_patch.py.tmpl").write_text(_src("""
        init_idempotency_cache("redis://...")
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, msg = mod._r_init_inside_lifespan_only()
    assert not ok


# ----------------------------------------------------------------------
# Name classification unit tests
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "init_metrics",
        "_init_metrics",
        "init_idempotency_cache",
        "create_redis_pool",
        "create_db_pool",
        "configure_telemetry",
        "_configure_structlog",
        "start_event_listener",
        "start_outbox_worker",
        "register_health_routes",
    ],
)
def test_is_offence_name_red(name: str) -> None:
    assert _is_offence_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "",
        "install_audit_log",
        "include_router",
        "add_middleware",
        "configure_logging",            # allowlisted
        "register_router",              # allowlisted
        "create_app",                   # ``create_*`` w/o ``_pool`` suffix
        "start_worker",                 # ``start_*`` w/o suffix
        "register_handler",             # ``register_*`` w/o ``_routes`` suffix
        "init",                         # bare ``init`` (no underscore tail)
    ],
)
def test_is_offence_name_green(name: str) -> None:
    assert _is_offence_name(name) is False


# ----------------------------------------------------------------------
# Integration with the registry
# ----------------------------------------------------------------------


def test_b0_15_registered_in_rules_list() -> None:
    """B0.15 appears in the canonical RULES list with description + phase."""
    from engine.audit.contract_rules import RULES

    matches = [r for r in RULES if r.item == "B0.15"]
    assert len(matches) == 1, "B0.15 must appear exactly once in RULES"
    rule = matches[0]
    assert rule.phase == 0
    assert "lifespan" in rule.description.lower()
    assert callable(rule.check)


def test_b0_15_callback_returns_bool_str_tuple() -> None:
    """Smoke test: callback against the live catalog returns shape (bool, str)."""
    result = _r_init_inside_lifespan_only()
    assert isinstance(result, tuple)
    assert len(result) == 2
    ok, msg = result
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_tool_key_for_extracts_tool_dir() -> None:
    """Sanity: tool-key derivation maps template paths to waivable keys."""
    from engine.audit.contract_rules._common import SKILL_ROOT

    p = (
        SKILL_ROOT
        / "adapt"
        / "extend"
        / "crud_data"
        / "add_bulk_operations"
        / "templates"
        / "main_patch.py.tmpl"
    )
    assert _tool_key_for(p) == "extend/crud_data/add_bulk_operations"


def test_tool_key_for_patches_file() -> None:
    """``_patches.py`` lives at the tool dir root (no ``templates/``)."""
    from engine.audit.contract_rules._common import SKILL_ROOT

    p = (
        SKILL_ROOT
        / "adapt"
        / "extend"
        / "auth_access"
        / "add_multi_tenancy"
        / "_patches.py"
    )
    assert _tool_key_for(p) == "extend/auth_access/add_multi_tenancy"
