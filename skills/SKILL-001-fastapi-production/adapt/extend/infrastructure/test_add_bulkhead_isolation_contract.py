"""Generic + tool-specific mutation coverage for add_bulkhead_isolation.

The generic fleet contract checks (tests/common/tool_contract.py) kill the
shared preamble mutants (execution_time, idempotency, dry_run, auto-scaffold,
exist_ok, prereq-error). The tool-specific tests below pin behaviour that the
remaining survivors flip:

- ``_count_logic_lines`` arithmetic (``end - start + 1``) and the
  ``node.end_lineno or start`` fallback (L219/L220).
- ``_patch_main`` guard ``if "bulkhead" in src`` (L197) — note is only
  appended when main.py does not already reference bulkhead.
- the ``not <init>.exists()`` guards that create the resilience/ and
  middleware/ package ``__init__.py`` files (L106/L120).
- ``list(scaffolded or [])`` — auto-scaffolded prereq files must survive into
  ``files_created`` (L69).

Run alongside test_add_bulkhead_isolation.py in the mutation runner.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_bulkhead_isolation import (
    _count_logic_lines,
    _patch_main,
    add_bulkhead_isolation,
)
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _created_resolved(result) -> set[str]:
    """Resolve files_created so tempdir symlink (/var -> /private/var) matches."""
    return {str(Path(p).resolve()) for p in result.files_created}


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_bulkhead_isolation, "add_bulkhead_isolation")


# ---------------------------------------------------------------------------
# L220: _count_logic_lines counts ``end - start + 1`` body lines exactly.
# Kills both BinOps on that line: ``end - start`` (Sub->Add) and ``+ 1``
# (Add->Sub) — any flip changes the count away from 3.
# ---------------------------------------------------------------------------


def test_count_logic_lines_exact_body_count() -> None:
    source = "def f():\n    a = 1\n    b = 2\n    return a + b\n"
    # body lines: a=1 (L2), b=2 (L3), return (L4) => end-start+1 = 4-2+1 = 3
    assert _count_logic_lines(source) == 3


def test_count_logic_lines_single_line_body() -> None:
    # start == end => 1 logic line. Sub->Add would give start+end (>1);
    # +1->-1 would give -1.
    assert _count_logic_lines("def g():\n    return 1\n") == 1


# ---------------------------------------------------------------------------
# L219: ``end = node.end_lineno or start``. The end_lineno of a multi-line
# function is truthy, so ``or`` yields end_lineno. The And mutant would yield
# ``start`` (collapsing every function to 1 line), undercounting a multi-line
# body. A single multi-line function pins the difference.
# ---------------------------------------------------------------------------


def test_count_logic_lines_uses_end_lineno_not_start() -> None:
    # 5 body lines -> 5; And mutant (end = start) would yield 1.
    source = "def h():\n    x = 1\n    y = 2\n    z = 3\n    w = 4\n    return x\n"
    assert _count_logic_lines(source) == 5


# ---------------------------------------------------------------------------
# L197: _patch_main appends the install hint ONLY when main.py does not already
# mention bulkhead. ``if "bulkhead" in src`` -> NotIn flip would return early
# on a clean main.py and never append the note.
# ---------------------------------------------------------------------------


def test_patch_main_appends_note_when_absent() -> None:
    d = Path(tempfile.mkdtemp())
    main_file = d / "main.py"
    main_file.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    _patch_main(main_file)
    out = main_file.read_text()
    assert "add_bulkhead_isolation tool" in out
    assert "install_if_enabled" in out


def test_patch_main_noop_when_already_present() -> None:
    d = Path(tempfile.mkdtemp())
    main_file = d / "main.py"
    original = "# bulkhead already wired\napp = FastAPI()\n"
    main_file.write_text(original)
    _patch_main(main_file)
    # Guard returns early -> file untouched. NotIn flip would append a second
    # note (changing the content).
    assert main_file.read_text() == original


# ---------------------------------------------------------------------------
# L106: ``if not resilience_init.exists()`` creates app/resilience/__init__.py.
# On a bare dir the file does not preexist, so it must be created AND recorded.
# UnaryNot flip would skip creation.
# ---------------------------------------------------------------------------


def test_resilience_init_created_and_recorded() -> None:
    d = tempfile.mkdtemp()
    result = add_bulkhead_isolation(ToolInput(project_dir=d))
    assert result.status == "success"
    init_file = Path(d) / "app" / "resilience" / "__init__.py"
    assert init_file.exists(), "resilience/__init__.py must be created"
    assert str(init_file.resolve()) in _created_resolved(result)


# ---------------------------------------------------------------------------
# L120: ``if not middleware_init.exists()`` creates app/middleware/__init__.py.
# Same shape on a bare dir.
# ---------------------------------------------------------------------------


def test_middleware_init_created_and_recorded() -> None:
    d = tempfile.mkdtemp()
    result = add_bulkhead_isolation(ToolInput(project_dir=d))
    assert result.status == "success"
    init_file = Path(d) / "app" / "middleware" / "__init__.py"
    assert init_file.exists(), "middleware/__init__.py must be created"
    assert str(init_file.resolve()) in _created_resolved(result)


# ---------------------------------------------------------------------------
# L69: ``files_created: list[str] = list(scaffolded or [])``. On a bare dir the
# prereqs are auto-scaffolded; those files must flow into files_created. The
# And mutant (``scaffolded and []``) would yield [] and drop them.
# ---------------------------------------------------------------------------


def test_scaffolded_prereq_files_recorded() -> None:
    d = tempfile.mkdtemp()
    result = add_bulkhead_isolation(ToolInput(project_dir=d))
    assert result.status == "success"
    created = _created_resolved(result)
    # app/__init__.py is produced only by the prereq auto-scaffold, never by
    # the tool's own writes -> its presence proves ``scaffolded`` survived.
    scaffolded_only = Path(d) / "app" / "__init__.py"
    assert scaffolded_only.exists()
    assert str(scaffolded_only.resolve()) in created, (
        "auto-scaffolded prereq files must be recorded in files_created"
    )
