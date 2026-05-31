"""Regression tests for W2 FINAL — close the last 2 B0.15 waivers.

Closes the last two entries that lived in
``engine/audit/contract_rules/r_init_inside_lifespan.py::_WAIVED_TOOLS``:

* ``extend/infrastructure/add_prometheus_metrics`` — ``_init_metrics(prefix=...)``
  was injected as a bare module-top statement after ``FastAPI()``
  construction by ``_patch_main``, splicing into the EOF snippet
  ``main_middleware_snippet.txt.tmpl``. Triage R5-S5-F2: re-registering
  the Prometheus registry at module-import time crashes the second
  importer with ``Duplicated timeseries``. Fix moves the call INSIDE
  ``async def lifespan(...)`` before the ``yield``.
* ``extend/infrastructure/add_structured_logging`` —
  ``_configure_structlog(...)`` was injected as a bare module-top
  statement after ``FastAPI()``. Fix moves the call INSIDE
  ``async def lifespan(...)``. Trade-off: log records emitted at
  module-import time use stdlib defaults until lifespan-startup
  completes; the request path is unaffected.

Test shape mirrors ``test_w2_batch_b011_all_admin_closed.py``:

1. Each tool MUST NOT re-appear in ``_WAIVED_TOOLS`` (someone added
   the waiver back instead of fixing the patcher).
2. Each tool's ``_patch_main`` MUST produce a ``main.py`` where the
   init-class call lives INSIDE the ``async def lifespan(...)`` body —
   we exercise the real patcher against a real fixture project and
   re-parse the AST.
3. The fallback branch (no ``async def lifespan(...)`` in the host
   ``main.py``) emits the call with a ``# pragma: B0.15: ...`` suffix
   so the contract rule still allows the literal line — we exercise
   that branch with a minimal stub ``main.py``.
4. The live B0.15 rule reports zero violations across the entire
   ``adapt/`` tree with the (now empty) waiver set.

Catalog scan + classifier behaviour is already covered by
``test_b0_15_init_inside_lifespan.py``; this file is the per-tool
acceptance test for the W2 FINAL closure.
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

# Tool-import surface kept inline so the test reads top-to-bottom even
# for a reviewer with no prior context on the catalog layout.
from adapt.contracts import ToolInput  # noqa: E402
from adapt.extend.infrastructure.add_prometheus_metrics import (  # noqa: E402
    _patch_main as _prometheus_patch_main,
    add_prometheus_metrics,
)
from adapt.extend.infrastructure.add_structured_logging import (  # noqa: E402
    _patch_main as _structlog_patch_main,
    add_structured_logging,
)

# ---------------------------------------------------------------------------
# Fixture table — one row per closed tool
# ---------------------------------------------------------------------------
# (tool_key, runner, init_call_name)
#   tool_key   — string registered in r_init_inside_lifespan._WAIVED_TOOLS
#                (so the "no longer waived" assertion has something stable
#                to compare against)
#   runner     — the public entry point that exercises _patch_main against
#                a real fixture project
#   init_call_name — the offending init function name (matched on
#                the AST tail, so leading underscore is fine)
# ---------------------------------------------------------------------------
_TOOL_FIXTURES: list[tuple[str, object, str]] = [
    (
        "extend/infrastructure/add_prometheus_metrics",
        add_prometheus_metrics,
        "_init_metrics",
    ),
    (
        "extend/infrastructure/add_structured_logging",
        add_structured_logging,
        "_configure_structlog",
    ),
]


# ---------------------------------------------------------------------------
# Helpers — AST shape probes (no string-matching on source)
# ---------------------------------------------------------------------------


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_lifespan_body(tree: ast.Module) -> list[ast.AST] | None:
    """Return the body of ``async def lifespan(...)`` or ``None`` if absent.

    Matches the rule's lifespan detection (``_is_lifespan_func``):
    any ``async def lifespan(...)`` at any nesting depth, plus
    ``@asynccontextmanager``-decorated sync ``def lifespan(...)``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return list(node.body)
        if isinstance(node, ast.FunctionDef) and node.name == "lifespan":
            for dec in node.decorator_list:
                tail = ""
                cur: ast.AST | None = dec
                if isinstance(cur, ast.Call):
                    cur = cur.func
                if isinstance(cur, ast.Attribute):
                    tail = cur.attr
                elif isinstance(cur, ast.Name):
                    tail = cur.id
                if tail == "asynccontextmanager":
                    return list(node.body)
    return None


def _call_tail(call: ast.Call) -> str:
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _calls_in(body: list[ast.AST]) -> list[str]:
    out: list[str] = []
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                out.append(_call_tail(sub))
    return out


# ---------------------------------------------------------------------------
# Fixture project — used by the green-path lifespan test
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_project(tmp_path: Path) -> Path:
    """A real generated FastAPI project (lifespan present).

    We use the same factory the adapt-tool tests use so the patcher
    sees a realistic ``app/main.py`` shape — `async def lifespan(app)`
    with the `yield` sentinel, FastAPI app constructed via
    ``FastAPI(lifespan=lifespan)``.
    """
    sys.path.insert(0, str(SKILL_ROOT))
    from tests.common.fixture_factory import create_fixture_project

    return create_fixture_project(name="w2_final_b015", tmp_dir=tmp_path)


# ---------------------------------------------------------------------------
# 1. Waiver-set guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("tool_key", "runner", "init_name"), _TOOL_FIXTURES)
def test_tool_not_in_waiver_set(tool_key: str, runner, init_name: str) -> None:
    """The closed tool MUST NOT re-appear in ``_WAIVED_TOOLS``.

    If this fails, someone re-added the waiver instead of fixing
    ``_patch_main``. Don't re-waive — fix the patcher.
    """
    from engine.audit.contract_rules.r_init_inside_lifespan import _WAIVED_TOOLS

    assert tool_key not in _WAIVED_TOOLS, (
        f"{tool_key!r} was re-added to _WAIVED_TOOLS in "
        f"r_init_inside_lifespan.py; the waiver was intentionally removed "
        f"by the W2 FINAL B0.15 PR. Fix `_patch_main` to splice the init "
        f"call INSIDE `async def lifespan(...)` instead of re-waiving."
    )


def test_waiver_set_is_empty() -> None:
    """End-to-end: the live ``_WAIVED_TOOLS`` set is empty.

    The W2 FINAL PR drained the set to zero; any new entry must come
    with a written justification in its own PR.
    """
    from engine.audit.contract_rules.r_init_inside_lifespan import _WAIVED_TOOLS

    assert _WAIVED_TOOLS == frozenset(), (
        f"_WAIVED_TOOLS is no longer empty: {sorted(_WAIVED_TOOLS)!r}. "
        f"The W2 FINAL B0.15 PR drained the set to zero — any new entry "
        f"must come with a written justification in its own PR."
    )


# ---------------------------------------------------------------------------
# 2. Lifespan-path acceptance — init call lives INSIDE lifespan body
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("tool_key", "runner", "init_name"), _TOOL_FIXTURES)
def test_patcher_splices_init_into_lifespan(
    tool_key: str,
    runner,
    init_name: str,
    fixture_project: Path,
) -> None:
    """``_patch_main`` puts the init call INSIDE ``async def lifespan(...)``.

    Strategy:
      1. Run the real tool against a fresh fixture project (factory
         generates a lifespan-shaped ``app/main.py``).
      2. AST-walk the patched ``app/main.py``.
      3. Assert the offending init function name appears in the
         lifespan body's Call list, AND does NOT appear at module top.

    A regression where the patcher reverts to EOF-append will fail
    this test because the call shows up at module-top instead.
    """
    # Each parametrised case wants its own project (fixtures are
    # function-scoped, but the runner mutates files).
    result = runner(ToolInput(project_dir=str(fixture_project)))
    assert result.status == "success", (
        f"{tool_key}: tool runner returned {result.status!r}: "
        f"{result.error!r}"
    )

    main_file = fixture_project / "app" / "main.py"
    assert main_file.is_file(), f"{tool_key}: app/main.py not produced"

    tree = _parse(main_file)
    body = _find_lifespan_body(tree)
    assert body is not None, (
        f"{tool_key}: fixture project's main.py has no `async def lifespan(...)` "
        f"— fixture_factory regression? (the green-path test relies on the "
        f"factory producing a lifespan-shaped main.py)"
    )

    lifespan_calls = _calls_in(body)
    assert init_name in lifespan_calls, (
        f"{tool_key}: expected `{init_name}(...)` call INSIDE "
        f"`async def lifespan(...)` body, found calls={sorted(set(lifespan_calls))!r}. "
        f"_patch_main may have regressed to EOF-append shape."
    )

    # And it MUST NOT live at module top — that's the whole point.
    module_top_calls: list[str] = []
    for node in tree.body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                # Skip calls that are inside nested function defs at
                # module top (e.g. another `async def` sibling) —
                # we only care about *executed-at-import* Calls.
                pass
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            module_top_calls.append(_call_tail(node.value))
    assert init_name not in module_top_calls, (
        f"{tool_key}: `{init_name}(...)` is at module top of main.py "
        f"— it must live INSIDE `async def lifespan(...)`. Module-top "
        f"calls observed: {sorted(set(module_top_calls))!r}"
    )


# ---------------------------------------------------------------------------
# 3. Fallback path — no `lifespan` → module-top call + pragma
# ---------------------------------------------------------------------------


_STUB_MAIN_NO_LIFESPAN = '''\
"""Stub main.py with NO `async def lifespan(...)` — exercises the
B0.15 fallback branch of `_patch_main`. The patcher should emit the
init call at module-top with a `# pragma: B0.15: <reason>` suffix so
the contract rule still allows the literal line.
"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    return {"ok": True}
'''


@pytest.mark.parametrize(
    ("patcher", "init_name"),
    [
        (_prometheus_patch_main, "_init_metrics"),
        (_structlog_patch_main, "_configure_structlog"),
    ],
)
def test_patcher_fallback_emits_pragma_when_no_lifespan(
    patcher,
    init_name: str,
    tmp_path: Path,
) -> None:
    """When ``main.py`` has no ``async def lifespan(...)``, the patcher
    falls back to module-top call + ``# pragma: B0.15: ...``.

    This is the documented fallback so the tool still completes against
    non-standard scaffolds (e.g. a hand-rolled main.py without
    lifespan). The pragma keeps the B0.15 rule satisfied — verified
    by parsing the patched file through the rule's own offence scanner.
    """
    main_file = tmp_path / "main.py"
    main_file.write_text(_STUB_MAIN_NO_LIFESPAN)

    patcher(main_file)
    patched = main_file.read_text()

    # 1. The init call IS in the patched source.
    assert init_name in patched, (
        f"{patcher.__name__}: fallback did not emit `{init_name}(...)` "
        f"call into the stub main.py"
    )

    # 2. AST: no `async def lifespan(...)` was created out of thin air.
    tree = ast.parse(patched)
    assert _find_lifespan_body(tree) is None, (
        f"{patcher.__name__}: fallback unexpectedly synthesised an "
        f"`async def lifespan(...)` — the test setup is supposed to "
        f"exercise the no-lifespan branch."
    )

    # 3. B0.15 rule reports zero offences against the patched file
    #    (the per-line pragma is honoured by the scanner).
    from engine.audit.contract_rules.r_init_inside_lifespan import find_offences

    hits = find_offences(patched)
    init_hits = [(n, ln) for n, ln in hits if n.lstrip("_") == init_name.lstrip("_")]
    assert init_hits == [], (
        f"{patcher.__name__}: B0.15 scanner reported the init call as "
        f"an offence — the fallback's `# pragma: B0.15: ...` is missing "
        f"or on the wrong line. Patched source:\n{patched}"
    )


# ---------------------------------------------------------------------------
# 4. Live rule — zero violations across adapt/
# ---------------------------------------------------------------------------


def test_b015_rule_reports_zero_violations() -> None:
    """End-to-end: the live B0.15 rule reports zero violations across
    the entire ``adapt/`` tree with the (now empty) waiver set.

    Catches:
      * a new tool that lands with module-top init and forgets to
        gate inside lifespan,
      * a regression in either of the two tools this PR closes that
        the per-tool checks above don't catch (e.g. a *different*
        offence name landing in the same file).
    """
    from engine.audit.contract_rules.r_init_inside_lifespan import (
        _r_init_inside_lifespan_only,
    )

    ok, msg = _r_init_inside_lifespan_only()
    assert ok, f"§B0.15 reported violations: {msg}"
