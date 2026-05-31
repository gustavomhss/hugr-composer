"""B0.16 regression guard for ``extend/infrastructure/add_runtime_sentinel``.

Closes the B0.16 ``_WAIVED_TOOLS`` entry for this tool (cited finding
R5/R6 P7-F3): ``runtime_sentinel.py.tmpl`` line ~258 had

    try:
        ...
        body = _json.loads(body_bytes)
        for val in _extract_string_values(body):
            ...
    except Exception:
        pass

— so a malformed JSON body that ALSO carried a SQL / command
injection payload would slip past detection silently. An attacker
probing the parser surface (intentionally malformed bodies designed
to bypass the regex detector) generated no observable signal.

The fix in this PR:

1. Narrows the swallow to ``_json.JSONDecodeError`` and ``Exception``
   (body-read errors) with distinct reason keys.
2. Bumps a per-reason counter on the ``AttackPatternRegistry`` via
   the new ``record_body_parse_failure(reason, ...)`` method so each
   failure is visible to anyone reading the registry (and to any
   metrics scraper that exports the registry surface in future).
3. Emits a WARNING log line with the reason, request path, and
   client IP so the failure is observable in stderr / journald
   today even before a metrics exporter ships.
4. Returns ``None`` from ``_inspect`` cleanly so the happy-path
   detector flow is preserved (existing behaviour tests stay green).

What this test asserts
======================

* ``test_inspect_does_not_silently_swallow_body_parse_errors`` —
  the ``_inspect`` AST contains NO bare ``try/except Exception:
  pass`` block. (We allow narrow ``except`` blocks that bump the
  counter, log, and ``return None``.)
* ``test_parse_json_body_increments_registry_counter`` — at the
  exception handlers in ``_parse_json_body`` (or wherever the body
  parse swallow lives), ``self._note_body_parse_failure(...)`` is
  called AND ``logger.warning(...)`` is reachable from the helper
  it delegates to.
* ``test_registry_exposes_body_parse_failure_counter`` —
  ``sentinel_registry.py.tmpl::AttackPatternRegistry`` defines both
  ``record_body_parse_failure(reason, ...)`` and
  ``body_parse_failure_count(reason=None)`` so the counter is
  observable from operator code.
* ``test_register_body_parse_failure_count_is_reachable_runtime`` —
  end-to-end behaviour: instantiating the registry and recording
  two distinct reasons updates the per-reason counter as expected.

Bypass surface declared (per WP-16 §13)
=======================================

* The "no bare ``except Exception: pass``" assertion is a structural
  AST check inside the middleware module only. A future refactor
  that moves the body-parse swallow into another module would
  evade this rule; mitigated by the B0.16 contract rule
  (``r_no_silent_security_failures``) which scans every emitted
  template.
* The registry counter is in-process. Multi-worker deployments will
  each hold a separate counter — operators must export to a shared
  metric backend (Prometheus / statsd) for true cross-worker
  observability. Disclosed here so the disclosure cannot drift.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "infrastructure"
    / "add_runtime_sentinel"
)
SENTINEL_TMPL = TOOL_DIR / "templates" / "runtime_sentinel.py.tmpl"
REGISTRY_TMPL = TOOL_DIR / "templates" / "sentinel_registry.py.tmpl"


_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse_template(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_func(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"def {name}(...) not found in template")


def _find_method(
    tree: ast.Module, cls_name: str, method_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == cls_name:
            for node in cls.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
                    return node
    raise AssertionError(f"{cls_name}.{method_name} not found in template")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_chain(call: ast.Call) -> str:
    parts: list[str] = []
    cur: ast.AST | None = call.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# B0.16 — no silent body-parse swallow
# ---------------------------------------------------------------------------


def test_inspect_does_not_silently_swallow_body_parse_errors() -> None:
    """No ``try/except: pass`` block in the body-parse code path.

    The pre-fix offender at runtime_sentinel.py.tmpl:258 was

        except Exception:
            pass

    — the exact silent-failure pattern B0.16 rejects. This test scans
    every ExceptHandler in the methods that handle the request body
    (``_inspect`` + ``_parse_json_body``) and rejects any handler
    whose body is exclusively ``pass``. The IP-parse paths inside
    ``InjectionDetector.check_ssrf`` legitimately swallow
    ``ValueError`` to fall through to the next host-check branch
    (the SSRF detector returns a boolean either way — no security
    signal is lost), so those handlers are intentionally NOT in
    scope of this assertion."""
    tree = _parse_template(SENTINEL_TMPL)
    offenders: list[str] = []
    for method_name in ("_inspect", "_parse_json_body"):
        try:
            method = _find_method(
                tree, "RuntimeSentinelMiddleware", method_name
            )
        except AssertionError:
            continue
        for node in ast.walk(method):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            # Bare `pass` (with or without docstring) is the offender shape.
            non_doc = [
                s for s in body
                if not (
                    isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str)
                )
            ]
            if len(non_doc) == 1 and isinstance(non_doc[0], ast.Pass):
                offenders.append(
                    f"{method_name} line {node.lineno}: "
                    f"except {ast.unparse(node.type) if node.type else 'BARE'}: pass"
                )
    assert not offenders, (
        "runtime_sentinel.py.tmpl body-parse path contains a silent-swallow:\n  "
        + "\n  ".join(offenders)
        + "\nB0.16 requires the handler to (a) bump the registry counter "
        "AND (b) log a WARNING (or re-raise)."
    )


def test_parse_json_body_calls_registry_counter_and_logs() -> None:
    """Every exception handler in ``_parse_json_body`` MUST call
    ``self._note_body_parse_failure(...)`` (which itself bumps the
    registry counter and logs)."""
    tree = _parse_template(SENTINEL_TMPL)
    parser = _find_method(tree, "RuntimeSentinelMiddleware", "_parse_json_body")

    handlers = [n for n in ast.walk(parser) if isinstance(n, ast.ExceptHandler)]
    assert handlers, (
        "_parse_json_body MUST wrap body read + json.loads in a try block "
        "with at least one ExceptHandler — otherwise the parse can crash "
        "the middleware path."
    )
    for h in handlers:
        notes_called = any(
            _attr_chain(c).endswith("_note_body_parse_failure")
            for c in _calls(ast.Module(body=h.body, type_ignores=[]))
        )
        assert notes_called, (
            f"Exception handler at line {h.lineno} in `_parse_json_body` "
            "does NOT call `self._note_body_parse_failure(...)`. Without "
            "it the failure is silently dropped — exactly the B0.16 "
            "regression this test guards."
        )

    # And the helper itself MUST call the registry AND log.
    helper = _find_method(tree, "RuntimeSentinelMiddleware", "_note_body_parse_failure")
    helper_calls = {_attr_chain(c) for c in _calls(helper)}
    assert any(c.endswith("record_body_parse_failure") for c in helper_calls), (
        "`_note_body_parse_failure` MUST call "
        "`self._registry.record_body_parse_failure(...)` — without it the "
        "counter never moves."
    )
    assert any(c.endswith("logger.warning") or c.endswith("warning") for c in helper_calls), (
        "`_note_body_parse_failure` MUST call `logger.warning(...)` — "
        "without it the failure is invisible until a metrics exporter "
        "scrapes the registry."
    )


def test_registry_exposes_body_parse_failure_counter() -> None:
    """``AttackPatternRegistry`` MUST define ``record_body_parse_failure``
    and ``body_parse_failure_count`` so the counter is reachable from
    operator / metrics code."""
    tree = _parse_template(REGISTRY_TMPL)
    record = _find_method(tree, "AttackPatternRegistry", "record_body_parse_failure")
    count = _find_method(tree, "AttackPatternRegistry", "body_parse_failure_count")

    # record method MUST take a `reason` parameter — keyed counters
    # are how distinct failure modes are distinguished.
    arg_names = {a.arg for a in record.args.args}
    assert "reason" in arg_names, (
        "`record_body_parse_failure` MUST accept a `reason` kwarg so "
        "different failure modes (json_decode_error, body_read_error, …) "
        "are distinguished on the metrics surface."
    )

    # count method MUST take a `reason` parameter (optional).
    count_args = {a.arg for a in count.args.args}
    assert "reason" in count_args, (
        "`body_parse_failure_count` MUST accept a `reason` parameter so "
        "operators can query per-reason rates."
    )


def test_register_body_parse_failure_count_is_reachable_runtime() -> None:
    """End-to-end: load the registry template, instantiate it,
    record two distinct reasons, and verify the per-reason counter."""
    src = _clean(REGISTRY_TMPL.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_loader(
        "under_test_sentinel_registry", loader=None
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    # The registry uses @dataclass which needs the module registered
    # in sys.modules for the runtime to resolve __module__ correctly.
    sys.modules["under_test_sentinel_registry"] = mod
    try:
        exec(  # noqa: S102 — exec is the test mechanism
            compile(src, str(REGISTRY_TMPL), "exec"), mod.__dict__
        )

        registry = mod.AttackPatternRegistry()

        # Record two json_decode_error and one body_read_error.
        registry.record_body_parse_failure(
            reason="json_decode_error",
            request_path="/api/items",
            client_ip="1.2.3.4",
            detail="Expecting value: line 1 column 1 (char 0)",
        )
        registry.record_body_parse_failure(
            reason="json_decode_error",
            request_path="/api/items",
            client_ip="1.2.3.4",
            detail="Extra data: line 1 column 5 (char 4)",
        )
        registry.record_body_parse_failure(
            reason="body_read_error",
            request_path="/api/items",
            client_ip="1.2.3.4",
            detail="ClientDisconnect: ",
        )

        assert registry.body_parse_failure_count("json_decode_error") == 2, (
            "Per-reason counter for json_decode_error did not increment "
            "to 2 after two record_body_parse_failure(...) calls."
        )
        assert registry.body_parse_failure_count("body_read_error") == 1, (
            "Per-reason counter for body_read_error did not increment "
            "to 1 after one record_body_parse_failure(...) call."
        )
        assert registry.body_parse_failure_count() == 3, (
            "Aggregate body_parse_failure_count() did not return the sum "
            "of per-reason counters."
        )
    finally:
        sys.modules.pop("under_test_sentinel_registry", None)


def test_b0_16_waiver_removed() -> None:
    """The B0.16 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_no_silent_security_failures import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_runtime_sentinel" not in _WAIVED_TOOLS, (
        "B0.16 waiver entry for add_runtime_sentinel was NOT removed; "
        "the fix is meaningless if the rule still skips the tool."
    )
