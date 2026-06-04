"""Generic + tool-specific mutation coverage for add_cache_layer.

The generic block applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. The remaining tests target the
add_cache_layer-specific operators that the shared preamble does NOT cover:

- requirements.txt dependency dedup (``'msgpack' not in`` / ``'redis' not in``)
- main.py patch anchor placement (``'from fastapi import FastAPI' in src``)
- the no-anchor else branch string concat (``cache_import + src``)
- the glue logic-line counter (``_count_logic_lines`` BoolOp/BinOp)

Run alongside test_add_cache_layer.py in the mutation runner:
``--tests test_add_cache_layer.py test_add_cache_layer_contract.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cache_layer import (
    _count_logic_lines,
    _patch_main,
    add_cache_layer,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_cache_layer, "add_cache_layer")


# ---------------------------------------------------------------------------
# requirements.txt dependency injection — L107/L109 (NotIn) + L112 (concat)
# ---------------------------------------------------------------------------


def test_msgpack_dependency_added_when_absent() -> None:
    """L107 ``'msgpack' not in req_src``: the default fixture ships NO msgpack,
    so the tool MUST append ``msgpack>=1.0.0``. NotIn->In would skip it.
    Also exercises the L112 ``+`` concat that builds the new requirements body
    (Add->Sub would raise TypeError on the str rstrip/join)."""
    project = create_fixture_project(name="cl_req_msgpack")
    req = project / "requirements.txt"
    assert "msgpack" not in req.read_text()  # precondition: fixture lacks it

    result = add_cache_layer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    body = req.read_text()
    assert "msgpack>=1.0.0" in body, "msgpack dependency must be appended"
    # requirements.txt was actually edited and reported
    resolved = {str(Path(p).resolve()) for p in result.files_modified}
    assert str(req.resolve()) in resolved


def test_redis_dependency_added_when_absent() -> None:
    """L109 ``'redis' not in req_src``: on a project whose requirements lack
    redis, the tool MUST append ``redis[hiredis]>=5.0.0``. NotIn->In would
    only add it when redis is ALREADY present (wrong)."""
    project = create_fixture_project(name="cl_req_redis")
    req = project / "requirements.txt"
    stripped = "\n".join(line for line in req.read_text().splitlines() if "redis" not in line)
    req.write_text(stripped + "\n")
    assert "redis" not in req.read_text()  # precondition: redis removed

    result = add_cache_layer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert "redis[hiredis]>=5.0.0" in req.read_text(), "redis dependency must be appended"


def test_redis_dependency_not_duplicated_when_present() -> None:
    """L109 guard (other direction): when redis is ALREADY in requirements the
    tool must NOT append a second redis pin. NotIn->In would add a duplicate."""
    project = create_fixture_project(name="cl_req_redis_dup")
    req = project / "requirements.txt"
    assert "redis" in req.read_text()  # default fixture pins redis

    add_cache_layer(ToolInput(project_dir=str(project)))
    body = req.read_text()
    assert "redis[hiredis]>=5.0.0" not in body, "must not duplicate the redis pin"


# ---------------------------------------------------------------------------
# main.py patching — L135 anchor branch + L138 else-branch concat
# ---------------------------------------------------------------------------


def test_main_patch_inserts_after_fastapi_import() -> None:
    """L135 ``'from fastapi import FastAPI' in src``: when the anchor import is
    present the cache import is spliced in RIGHT AFTER it (not prepended at the
    top of the module). In->NotIn flips to the else branch, prepending the
    import before the module docstring."""
    project = create_fixture_project(name="cl_main_anchor")
    main_file = project / "app" / "main.py"
    assert "from fastapi import FastAPI" in main_file.read_text()

    add_cache_layer(ToolInput(project_dir=str(project)))
    patched = main_file.read_text()
    anchor_idx = patched.find("from fastapi import FastAPI")
    cache_idx = patched.find("from app.cache.core import init_cache")
    assert anchor_idx != -1 and cache_idx != -1
    assert cache_idx > anchor_idx, "cache import must follow the FastAPI import anchor"
    # the cache import is glued directly after the anchor line, not at file start
    assert not patched.lstrip().startswith("from app.cache.core import init_cache")


def test_patch_main_else_branch_prepends_import() -> None:
    """L138 ``cache_import + src`` (else branch, taken when the FastAPI import
    anchor is absent): the cache import is prepended to the source. Add->Sub
    would raise TypeError on the str concatenation."""
    tmp = Path(tempfile.mkdtemp()) / "main.py"
    tmp.write_text("app = make_app()\n")
    _patch_main(tmp)
    out = tmp.read_text()
    assert out.lstrip().startswith("from app.cache.core import init_cache")
    assert "app = make_app()" in out, "original source must be preserved after prepend"
    assert "init_cache" in out


def test_patch_main_idempotent() -> None:
    """L131 ``'init_cache' in src`` early-return guard: a second patch is a
    no-op. In->NotIn would re-inject the import block on every call."""
    project = create_fixture_project(name="cl_main_idem")
    main_file = project / "app" / "main.py"
    add_cache_layer(ToolInput(project_dir=str(project)))
    first = main_file.read_text()
    _patch_main(main_file)
    assert main_file.read_text() == first, "second _patch_main must not change main.py"
    assert first.count("from app.cache.core import init_cache") == 1


# ---------------------------------------------------------------------------
# idempotency guard — L67 BoolOp + Compare (tool-specific anchor)
# ---------------------------------------------------------------------------


def test_idempotent_no_op_on_second_run() -> None:
    """L67 ``glue_file.exists() and 'KeyValueBucket' in read_text()``: a second
    run detects the wired glue and returns no_op with no writes. And->Or would
    crash reading a missing file on the first run; In->NotIn would re-create on
    the second run instead of short-circuiting to no_op."""
    project = create_fixture_project(name="cl_idem_guard")
    first = add_cache_layer(ToolInput(project_dir=str(project)))
    assert first.status == "success", first.error
    second = add_cache_layer(ToolInput(project_dir=str(project)))
    assert second.status == "no_op", f"second run must be no_op, got {second.status}"
    assert not second.files_created
    assert not second.files_modified


# ---------------------------------------------------------------------------
# glue logic-line counter — L153 / L155 / L156
# ---------------------------------------------------------------------------


def test_count_logic_lines_counts_only_function_bodies() -> None:
    """L153 ``isinstance(...) and node.body``: only function bodies count;
    module-level statements are ignored. And->Or would attempt ``node.body`` on
    non-function nodes (e.g. an Assign) and raise AttributeError."""
    src = "x = 1\ny = 2\n\ndef g():\n    return 1\n"
    assert _count_logic_lines(src) == 1


def test_count_logic_lines_spans_full_function_body() -> None:
    """L155 ``node.end_lineno or first`` + L156 ``last - first + 1``: the span
    is computed across the whole body. Or->And collapses end_lineno to first
    (yielding 1); Add->Sub / Sub->Add shift the count off the true span (3)."""
    src = "def f():\n    a = 1\n    b = 2\n    return a + b\n"
    assert _count_logic_lines(src) == 3


def test_count_logic_lines_sums_multiple_functions() -> None:
    """L156 accumulator ``loc += last - first + 1``: per-function spans sum.
    Two 2-line bodies => 4 (Add->Sub would undercount)."""
    src = "def a():\n    p = 1\n    return p\n\n\ndef b():\n    q = 2\n    return q\n"
    assert _count_logic_lines(src) == 4


def test_emitted_glue_at_or_under_20_logic_lines() -> None:
    """L115 ``glue_loc > 20``: the emitted glue sits at exactly 20 logic lines,
    so the tool returns success (not the >20 error). Gt->GtE would flip the
    boundary and make the tool error out at the limit."""
    project = create_fixture_project(name="cl_glue_loc")
    result = add_cache_layer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    glue = (project / "app" / "cache" / "primitives.py").read_text()
    assert _count_logic_lines(glue) <= 20


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
