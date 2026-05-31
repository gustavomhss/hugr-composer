"""B0.13 honesty test for ``extend/infrastructure/add_response_armor``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "Cache-Control: no-store applied to all 4xx/5xx responses automatically."

The matched B0.13 claim token is ``"automatically"``. The honest
reading: the emitted ``ResponseArmorMiddleware`` MUST install itself
on every response (no per-route opt-in) AND its
``_apply_cache_control`` branch MUST fire on *both* 4xx and 5xx (i.e.
the condition is ``status_code >= 400``, NOT
``status_code >= 500`` or a narrower band).

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

1. ``test_armor_middleware_automatically_sets_no_store_on_all_4xx_5xx``
   — ``_apply_cache_control`` gates on ``response.status_code >= 400``
   (lower-bound 400 = ALL 4xx AND 5xx, NOT a 5xx-only branch). A
   future edit that narrowed the band to ``>= 500`` would silently
   break the "all 4xx/5xx" half of the claim.

2. ``test_armor_middleware_automatically_writes_no_store_header_literal``
   — the assigned ``Cache-Control`` header MUST contain the literal
   token ``no-store`` (a future edit to ``"public, max-age=0"`` would
   pass the AST shape but break the claim's content).

3. ``test_armor_dispatch_automatically_applies_cache_control``
   — ``ResponseArmorMiddleware.dispatch`` MUST call
   ``self._apply_cache_control(response)`` on every response (after
   ``call_next``). Without this hop, ``_apply_cache_control`` exists
   but is never wired — "automatically" would be false at the
   request-boundary.

4. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* AST-only inspection of ``armor_middleware.py.tmpl`` — no exec, no
  FastAPI app boot. The shape of the gate (``>= 400`` Compare node
  with constant 400) is load-bearing; a future refactor that hoisted
  the comparison into a helper would need to be reviewed against this
  test.
* The "automatically" claim is also dependent on the middleware being
  registered in ``app/main.py`` via ``register_response_armor(app)``;
  that is asserted indirectly by test #3 (the dispatch wrapper that
  the FastAPI ``BaseHTTPMiddleware`` calls). The actual main.py patch
  lives in the tool's ``__init__.py`` and is covered by the
  prerequisite emitter tests.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_response_armor"
MIDDLEWARE_TMPL = TOOL_DIR / "templates" / "armor_middleware.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — parity with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _find_method(
    cls: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(cls):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"method {name} not found on class {cls.name}")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_chain(call_or_attr: ast.AST) -> str:
    parts: list[str] = []
    cur: ast.AST | None
    if isinstance(call_or_attr, ast.Call):
        cur = call_or_attr.func
    else:
        cur = call_or_attr
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# B0.13 — paired evidence for ``automatically``.
# ---------------------------------------------------------------------------


def test_armor_middleware_automatically_sets_no_store_on_all_4xx_5xx() -> None:
    """Notes claim "all 4xx/5xx responses automatically" — the
    Cache-Control branch MUST gate on ``status_code >= 400`` (the
    only lower-bound that covers ALL 4xx AND 5xx). A future edit
    narrowing the band to ``>= 500`` would silently break "all 4xx".
    """
    tree = _parse(MIDDLEWARE_TMPL)
    cls = _find_class(tree, "ResponseArmorMiddleware")
    fn = _find_method(cls, "_apply_cache_control")

    found_gate = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        # The expected shape is `response.status_code >= 400`.
        left_chain = _attr_chain(node.left)
        if not left_chain.endswith("status_code"):
            continue
        if not any(isinstance(op, ast.GtE) for op in node.ops):
            continue
        comparators = node.comparators
        if not comparators:
            continue
        rhs = comparators[0]
        if isinstance(rhs, ast.Constant) and rhs.value == 400:
            found_gate = True
            break
    assert found_gate, (
        "ResponseArmorMiddleware._apply_cache_control MUST gate on "
        "`response.status_code >= 400` (the only lower-bound that "
        "covers ALL 4xx AND 5xx). Narrowing to `>= 500` would silently "
        "drop the 4xx half of the `automatically` claim."
    )


def test_armor_middleware_automatically_writes_no_store_header_literal() -> None:
    """The assigned ``Cache-Control`` value MUST contain the literal
    token ``no-store``. A future edit to ``"public, max-age=0"`` would
    pass the AST shape but break the claim's *content* (the notes
    line names ``no-store`` specifically).
    """
    tree = _parse(MIDDLEWARE_TMPL)
    cls = _find_class(tree, "ResponseArmorMiddleware")
    fn = _find_method(cls, "_apply_cache_control")

    # Look for an assignment to response.headers["Cache-Control"] = "...".
    found_no_store = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Subscript):
                continue
            key = tgt.slice if not isinstance(tgt.slice, ast.Index) else tgt.slice.value  # type: ignore[attr-defined]
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value.lower() != "cache-control":
                continue
            v = node.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                if "no-store" in v.value.lower():
                    found_no_store = True
    assert found_no_store, (
        "_apply_cache_control MUST assign a Cache-Control header value "
        "containing the literal `no-store` (the notes line names "
        "`no-store` explicitly; `public, max-age=0` would pass shape "
        "but break the `automatically` claim's content)."
    )


def test_armor_dispatch_automatically_applies_cache_control() -> None:
    """``ResponseArmorMiddleware.dispatch`` MUST call
    ``self._apply_cache_control(response)`` after ``call_next``.
    Without this hop the header-mutation method is unreachable from
    the request boundary and "automatically" is false in practice.
    """
    tree = _parse(MIDDLEWARE_TMPL)
    cls = _find_class(tree, "ResponseArmorMiddleware")
    dispatch_fn = _find_method(cls, "dispatch")

    applied = False
    for call in _calls(dispatch_fn):
        if _attr_chain(call).endswith("_apply_cache_control"):
            applied = True
            break
    assert applied, (
        "ResponseArmorMiddleware.dispatch MUST invoke "
        "`self._apply_cache_control(response)`; otherwise the gate "
        "exists but is never reached and `automatically` is false."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_response_armor`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_response_armor" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_response_armor was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
