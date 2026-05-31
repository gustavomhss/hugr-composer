"""B0.13 honesty test for ``extend/infrastructure/add_rate_limiting``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "429 + Retry-After emitted automatically when the bucket is empty."

The matched B0.13 claim token is ``"automatically"``. (The phrase
"when the bucket is empty" is NOT one of the rule's escape phrases
— ``_ESCAPE_PHRASES`` is ``("only when", "requires manual", "see
next_steps", "⚠")``, so "when X" alone does not bypass.)

The waiver comment previously said: "no engine-level test asserts
the middleware always sets Retry-After on 429." This pair test
closes exactly that gap.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py``.

What we actually assert
=======================

1. ``test_rate_limit_middleware_automatically_returns_429`` —
   the FastAPI adapter's ``install`` function defines an HTTP
   middleware (``@app.middleware("http")``) whose body returns a
   ``JSONResponse`` with ``status_code=429`` when
   ``limiter.try_acquire(...)`` returns falsy. Anchors the
   "automatically" half — the middleware is wired on import, no
   caller opt-in is required beyond calling ``install(app)``.

2. ``test_rate_limit_429_automatically_sets_retry_after_header`` —
   the same ``JSONResponse`` MUST include a ``Retry-After`` header
   in its ``headers=`` kwarg. This is the load-bearing structural
   claim — without it the notes line lies about "Retry-After
   emitted automatically".

3. ``test_rate_limit_glue_wires_adapter_install`` — the emitted
   ``rate_limit_glue.py.tmpl`` imports ``install`` from
   ``core.venous._adapters.fastapi.RateLimiterAdapter`` and calls
   it inside ``install_rate_limiting(app)``. Without the glue
   actually invoking install, the user must wire the middleware
   themselves and "automatically" is false at the project
   boundary.

4. ``test_b0_13_waiver_removed`` — waiver entry MUST be gone.

Bypass surface declared
=======================

* The function names contain ``automatically`` so the fuzzy matcher
  binds them to the claim. AST-only inspection of the adapter +
  glue templates; no FastAPI app boot. Behavioural confirmation
  (the actual 429 emission under real load) belongs in
  ``core/venous/_adapters/fastapi/test_RateLimiterAdapter.py``
  which DOES exec the middleware against a TestClient.
* The notes line also contains "when the bucket is empty" — that
  is a *condition* on the claim ("automatically once the bucket is
  drained"), not an opt-in caveat. We treat it as part of the
  factual statement, not as escape language; the rule agrees
  (substring match against ``"only when"`` fails).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_rate_limiting"
GLUE_TMPL = TOOL_DIR / "templates" / "rate_limit_glue.py.tmpl"
ADAPTER_PY = (
    SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi" / "RateLimiterAdapter.py"
)


# ---------------------------------------------------------------------------
# Placeholder cleanup helper — parity with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_func(
    tree: ast.AST, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"def {name}(...) not found")


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


def _find_middleware_fn(install_fn: ast.AST) -> ast.AsyncFunctionDef:
    """Return the nested ``@app.middleware("http")`` async function."""
    for node in ast.walk(install_fn):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and _attr_chain(dec).endswith("middleware"):
                return node
    raise AssertionError(
        "no @app.middleware-decorated async function found in install()"
    )


# ---------------------------------------------------------------------------
# B0.13 — paired evidence for ``automatically``.
# ---------------------------------------------------------------------------


def test_rate_limit_middleware_automatically_returns_429() -> None:
    """Notes claim ``429 + Retry-After emitted automatically`` — the
    FastAPI adapter MUST register an HTTP middleware that returns a
    JSONResponse with status_code=429 on the limit-exceeded branch.

    "Automatically" means the user does not have to write any
    middleware themselves; calling ``install(app)`` is enough.
    """
    tree = _parse(ADAPTER_PY)
    install_fn = _find_func(tree, "install")
    mw_fn = _find_middleware_fn(install_fn)

    # The middleware MUST construct a JSONResponse with
    # status_code=429.
    found_429 = False
    for call in _calls(mw_fn):
        if not _attr_chain(call).endswith("JSONResponse"):
            continue
        for kw in call.keywords:
            if kw.arg == "status_code":
                v = kw.value
                if isinstance(v, ast.Constant) and v.value == 429:
                    found_429 = True
    assert found_429, (
        "RateLimiterAdapter middleware MUST return "
        "`JSONResponse(..., status_code=429, ...)` when the bucket "
        "is empty; without it the `automatically` claim is false."
    )


def test_rate_limit_429_automatically_sets_retry_after_header() -> None:
    """The same JSONResponse MUST include a ``Retry-After`` header in
    its ``headers=`` kwarg. The notes line names "Retry-After
    emitted automatically" — without the header the claim is half-
    true (429 fires but with no retry guidance) and RFC-6585 §4
    compliance is broken.
    """
    tree = _parse(ADAPTER_PY)
    install_fn = _find_func(tree, "install")
    mw_fn = _find_middleware_fn(install_fn)

    found_header = False
    for call in _calls(mw_fn):
        if not _attr_chain(call).endswith("JSONResponse"):
            continue
        # status_code MUST be 429.
        is_429 = any(
            kw.arg == "status_code"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == 429
            for kw in call.keywords
        )
        if not is_429:
            continue
        for kw in call.keywords:
            if kw.arg != "headers":
                continue
            v = kw.value
            if isinstance(v, ast.Dict):
                for key in v.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        if key.value.lower() == "retry-after":
                            found_header = True
    assert found_header, (
        "RateLimiterAdapter 429 response MUST set a `Retry-After` "
        "header in its `headers=` dict; the `automatically` claim in "
        "the notes line specifically names Retry-After emission."
    )


def test_rate_limit_glue_wires_adapter_install_automatically() -> None:
    """The emitted ``rate_limit_glue.py.tmpl`` MUST import ``install``
    from the FastAPI adapter and call it inside
    ``install_rate_limiting(app)``. Without the glue actually
    invoking install, the user must wire the middleware themselves
    and "automatically" is false at the project boundary.
    """
    tree = _parse(GLUE_TMPL)

    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    adapter_install_imports = [
        i
        for i in imports
        if (i.module or "").endswith("RateLimiterAdapter")
        and any(a.name == "install" for a in i.names)
    ]
    assert adapter_install_imports, (
        "rate_limit_glue.py.tmpl MUST import `install` from "
        "core.venous._adapters.fastapi.RateLimiterAdapter."
    )

    install_fn = _find_func(tree, "install_rate_limiting")
    delegates = [
        c
        for c in _calls(install_fn)
        if _attr_chain(c) == "install" or _attr_chain(c).endswith(".install")
    ]
    assert delegates, (
        "install_rate_limiting(app) MUST call the adapter's "
        "`install(...)`; otherwise the middleware is imported but "
        "never wired and `automatically` is false."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_rate_limiting`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_rate_limiting" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_rate_limiting was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
