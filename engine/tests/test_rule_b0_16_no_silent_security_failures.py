"""B0.16 — ``no_silent_security_failures`` regression suite.

Maps 1:1 to the rule body in
``engine/audit/contract_rules/r_no_silent_security_failures.py``.

Each test exercises one branch of the rule's classifier — the goal is
"explicit reds and explicit greens" so a future refactor that loosens
the AST walk turns one of these tests red instead of silently passing
(no irony intended).

Convention mirrors ``test_no_module_state_rule.py``: the rule exposes
``find_silent_handlers(src: str) -> list[(lineno, except_repr)]`` and
tests pass synthetic Python sources directly — no disk fixtures, so
the suite runs identically inside CI / sandbox / ``--collect-only``.

Catalog-scan integration is covered by the smoke test at the bottom
that asserts callable + ``(bool, str)`` return shape.
"""

from __future__ import annotations

import textwrap

import pytest

from engine.audit.contract_rules.r_no_silent_security_failures import (
    _r_no_silent_security_failures,
    _tool_key_for,
    find_silent_handlers,
)


def _src(body: str) -> str:
    """Dedent + lstrip so test bodies read naturally."""
    return textwrap.dedent(body).lstrip("\n")


# ----------------------------------------------------------------------
# REDS — these should trigger the rule
# ----------------------------------------------------------------------


def test_red_except_exception_pass() -> None:
    """``except Exception: pass`` → flagged."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                pass
    """))
    assert len(hits) == 1
    lineno, etype = hits[0]
    assert etype == "Exception"
    assert lineno == 4


def test_red_bare_except_pass() -> None:
    """Bare ``except: pass`` → flagged."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except:
                pass
    """))
    assert len(hits) == 1
    assert hits[0][1] == "bare"


def test_red_except_base_exception_pass() -> None:
    """``except BaseException: pass`` → flagged (broader than Exception)."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except BaseException:
                pass
    """))
    assert len(hits) == 1
    assert hits[0][1] == "BaseException"


def test_red_log_only_handler() -> None:
    """Logger-only body with no raise → flagged (the canonical P7 shape)."""
    hits = find_silent_handlers(_src("""
        import logging
        log = logging.getLogger(__name__)

        def f():
            try:
                do_thing()
            except Exception:
                log.warning("it failed")
                log.exception("uh oh")
    """))
    assert len(hits) == 1


def test_red_log_then_return_none() -> None:
    """Logger-only followed by ``return None`` → flagged."""
    hits = find_silent_handlers(_src("""
        import logging
        log = logging.getLogger(__name__)

        def f():
            try:
                return do_thing()
            except Exception:
                log.warning("redis down")
                return None
    """))
    assert len(hits) == 1


def test_red_log_then_bare_return() -> None:
    """Logger-only followed by bare ``return`` → flagged."""
    hits = find_silent_handlers(_src("""
        import logging
        log = logging.getLogger(__name__)

        def f():
            try:
                do_thing()
            except Exception:
                log.error("nope")
                return
    """))
    assert len(hits) == 1


def test_red_logging_module_call_only() -> None:
    """``logging.X(...)`` (no logger object) — also a logger call."""
    hits = find_silent_handlers(_src("""
        import logging

        def f():
            try:
                do_thing()
            except Exception:
                logging.warning("oops")
    """))
    assert len(hits) == 1


def test_red_async_handler_same_rules() -> None:
    """Async function — silent handler still flagged."""
    hits = find_silent_handlers(_src("""
        async def f():
            try:
                await do_thing()
            except Exception:
                pass
    """))
    assert len(hits) == 1


def test_red_multiple_handlers_all_reported() -> None:
    """Two silent handlers in one file → both surface."""
    hits = find_silent_handlers(_src("""
        import logging
        log = logging.getLogger(__name__)

        def f():
            try:
                a()
            except Exception:
                pass

        def g():
            try:
                b()
            except Exception:
                log.warning("g")
    """))
    assert len(hits) == 2


# ----------------------------------------------------------------------
# GREENS — these should NOT trigger the rule
# ----------------------------------------------------------------------


def test_green_raise_after_logger() -> None:
    """Log then ``raise`` propagates the failure → allowed."""
    hits = find_silent_handlers(_src("""
        import logging
        log = logging.getLogger(__name__)

        def f():
            try:
                do_thing()
            except Exception:
                log.error("propagating")
                raise
    """))
    assert hits == []


def test_green_chained_raise_from() -> None:
    """``raise NewError(...) from exc`` → allowed."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except Exception as exc:
                raise RuntimeError("wrap") from exc
    """))
    assert hits == []


def test_green_metric_increment_inc() -> None:
    """Body bumps a Prometheus counter → allowed (failure is surfaced)."""
    hits = find_silent_handlers(_src("""
        from prometheus_client import Counter
        FAILURES = Counter("x_failures", "")

        def f():
            try:
                do_thing()
            except Exception:
                FAILURES.inc()
    """))
    assert hits == []


def test_green_metric_increment_labels() -> None:
    """``counter.labels(...).inc()`` → allowed."""
    hits = find_silent_handlers(_src("""
        from prometheus_client import Counter
        FAILURES = Counter("x_failures", "", ["reason"])

        def f():
            try:
                do_thing()
            except Exception:
                FAILURES.labels(reason="boom").inc()
    """))
    assert hits == []


def test_green_metric_increment_statsd() -> None:
    """``statsd.increment(...)`` → allowed."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                statsd.increment("x.failure")
    """))
    assert hits == []


def test_green_pragma_bypass() -> None:
    """``# pragma: B0.16-recoverable`` disclosure → allowed."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                # pragma: B0.16-recoverable: redis is best-effort cache
                return None
    """))
    assert hits == []


def test_green_pragma_on_except_line() -> None:
    """Pragma on the ``except`` line itself → allowed (still in range)."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except Exception:  # pragma: B0.16-recoverable: documented gap
                pass
    """))
    assert hits == []


def test_green_narrow_exception_type() -> None:
    """``except KeyError: pass`` → allowed (narrow type, surgical)."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                return data["x"]
            except KeyError:
                pass
    """))
    assert hits == []


def test_green_narrow_tuple_of_types() -> None:
    """``except (ValueError, KeyError): pass`` → allowed."""
    hits = find_silent_handlers(_src("""
        def f():
            try:
                do_thing()
            except (ValueError, KeyError):
                pass
    """))
    assert hits == []


def test_green_exit_method_swallows() -> None:
    """Context-manager ``__exit__`` may swallow by contract → allowed."""
    hits = find_silent_handlers(_src("""
        class CM:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                try:
                    self.cleanup()
                except Exception:
                    pass
                return False
    """))
    assert hits == []


def test_green_aexit_method_swallows() -> None:
    """Async ``__aexit__`` — same allowance."""
    hits = find_silent_handlers(_src("""
        class CM:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                try:
                    await self.cleanup()
                except Exception:
                    pass
                return False
    """))
    assert hits == []


def test_green_real_work_in_handler() -> None:
    """Handler with real work (db.rollback) + log → not silent, allowed."""
    hits = find_silent_handlers(_src("""
        def f(db):
            try:
                db.commit()
            except Exception:
                db.rollback()
                log.warning("rolled back")
    """))
    assert hits == []


def test_green_finally_block_not_scanned() -> None:
    """``finally:`` blocks are not scanned — they always run."""
    hits = find_silent_handlers(_src("""
        def f(conn):
            try:
                do_thing()
            finally:
                conn.close()
    """))
    assert hits == []


def test_green_conditional_raise_in_handler() -> None:
    """Conditional ``raise`` inside a branch → allowed (re-raise exists)."""
    hits = find_silent_handlers(_src("""
        def f(suppress):
            try:
                do_thing()
            except Exception:
                if not suppress:
                    raise
                log.warning("suppressed by caller")
    """))
    assert hits == []


def test_green_empty_input() -> None:
    """Empty source → no hits, no crash."""
    assert find_silent_handlers("") == []


def test_green_unparseable_fragment_skipped() -> None:
    """Non-Python fragment → returns [] (does not raise)."""
    # ``leftover_token`` triggers SyntaxError; the rule must degrade
    # gracefully to no findings rather than crash CI.
    assert find_silent_handlers("sa.Column(\nleftover_token\n") == []


def test_green_placeholder_substitution_preserves_finding() -> None:
    """``${var}`` placeholders parse via substitution — rule still works."""
    hits = find_silent_handlers(_src("""
        ${header_comment}

        def $func_name():
            try:
                do_thing()
            except Exception:
                pass
    """))
    assert len(hits) == 1


# ----------------------------------------------------------------------
# Waiver behaviour
# ----------------------------------------------------------------------


def test_waiver_skips_listed_tool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A tool in ``_WAIVED_TOOLS`` is exempt from the catalog scan.

    Strategy: point ADAPT_ROOT at a temp tree with one offending
    template under ``extend/auth_access/synthetic_tool/templates/x.py.tmpl``,
    add that tool key to the waiver set, assert OK.
    """
    from engine.audit.contract_rules import r_no_silent_security_failures as mod

    tool_dir = tmp_path / "extend" / "auth_access" / "synthetic_tool" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "x.py.tmpl").write_text(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                pass
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(
        mod,
        "_WAIVED_TOOLS",
        frozenset({"extend/auth_access/synthetic_tool"}),
    )
    ok, msg = mod._r_no_silent_security_failures()
    assert ok, msg


def test_unwaived_tool_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Same offender WITHOUT the waiver → rule rejects with file:line."""
    from engine.audit.contract_rules import r_no_silent_security_failures as mod

    tool_dir = tmp_path / "extend" / "auth_access" / "synthetic_tool" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "x.py.tmpl").write_text(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                pass
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, msg = mod._r_no_silent_security_failures()
    assert not ok
    assert "except Exception" in msg
    assert "x.py.tmpl" in msg


def test_in_scope_by_path_keyword(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A template under a non-auth_access dir is in scope iff its path
    matches one of the security keywords (csrf/cors/dlp/…)."""
    from engine.audit.contract_rules import r_no_silent_security_failures as mod

    # ``add_csrf_protection`` matches the ``csrf`` keyword → in scope.
    tool_dir = tmp_path / "extend" / "infrastructure" / "add_csrf_protection" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "csrf_middleware.py.tmpl").write_text(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                pass
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, msg = mod._r_no_silent_security_failures()
    assert not ok
    assert "csrf_middleware" in msg


def test_out_of_scope_template_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A template that matches NONE of the scope rules is not scanned."""
    from engine.audit.contract_rules import r_no_silent_security_failures as mod

    # ``add_blog_post`` matches no keyword and lives outside auth_access.
    tool_dir = tmp_path / "extend" / "crud_data" / "add_blog_post" / "templates"
    tool_dir.mkdir(parents=True)
    (tool_dir / "model.py.tmpl").write_text(_src("""
        def f():
            try:
                do_thing()
            except Exception:
                pass
    """))

    monkeypatch.setattr(mod, "ADAPT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_WAIVED_TOOLS", frozenset())
    ok, _msg = mod._r_no_silent_security_failures()
    assert ok


# ----------------------------------------------------------------------
# Integration with the registry
# ----------------------------------------------------------------------


def test_b0_16_registered_in_rules_list() -> None:
    """B0.16 appears in the canonical RULES list with description + phase."""
    from engine.audit.contract_rules import RULES

    matches = [r for r in RULES if r.item == "B0.16"]
    assert len(matches) == 1, "B0.16 must appear exactly once in RULES"
    rule = matches[0]
    assert rule.phase == 0
    assert "silent" in rule.description.lower()
    assert callable(rule.check)


def test_b0_16_callback_returns_bool_str_tuple() -> None:
    """Smoke test: the callback against the live catalog returns shape (bool, str)."""
    result = _r_no_silent_security_failures()
    assert isinstance(result, tuple)
    assert len(result) == 2
    ok, msg = result
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


def test_tool_key_for_extracts_tool_dir() -> None:
    """Sanity: tool-key derivation maps template paths to waivable keys."""
    from engine.audit.contract_rules.r_no_silent_security_failures import (
        ADAPT_ROOT,
    )

    p = (
        ADAPT_ROOT
        / "extend"
        / "auth_access"
        / "add_api_key_auth"
        / "templates"
        / "rate_limit.py.tmpl"
    )
    assert _tool_key_for(p) == "extend/auth_access/add_api_key_auth"
