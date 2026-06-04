"""Generic + tool-specific mutation coverage for add_adaptive_timeouts.

The generic ``test_contract`` applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. The remaining tests target tool-specific
survivors surfaced by the mutation runner. Run alongside
test_add_adaptive_timeouts.py in the mutation runner:
``--tests test_add_adaptive_timeouts.py test_add_adaptive_timeouts_contract.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_adaptive_timeouts import (
    _count_logic_lines,
    add_adaptive_timeouts,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _resolved(paths: list[str]) -> set[str]:
    """Resolve a list of returned path strings (macOS /var -> /private/var)."""
    return {str(Path(p).resolve()) for p in paths}


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_adaptive_timeouts, "add_adaptive_timeouts")


def test_scaffolded_prereqs_flow_into_files_created():
    """L70: ``list(scaffolded or [])`` — auto-scaffolded prerequisite files
    must seed files_created.

    On a bare project directory the CONFIG_SETTINGS / REQUIREMENTS_TXT
    prerequisites are missing, so ensure_prerequisites scaffolds them and
    returns their paths. The tool seeds ``files_created`` from that list via
    ``list(scaffolded or [])``. If ``or`` flips to ``and`` the truthy
    scaffolded list is discarded (``scaffolded and []`` == ``[]``) and the
    scaffolded config.py never appears in files_created.
    """
    bare = Path(tempfile.mkdtemp())
    result = add_adaptive_timeouts(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error
    created = _resolved(result.files_created)
    scaffolded_config = str((bare / "app" / "core" / "config.py").resolve())
    assert scaffolded_config in created, (
        "auto-scaffolded config.py must be carried into files_created"
    )


def test_resilience_init_created_on_fresh_project():
    """L106: ``if not resilience_init.exists()`` — the package __init__ is
    written (and recorded) when it does NOT already exist.

    On a fresh project app/resilience/__init__.py is absent, so the tool
    writes it with the package docstring and appends it to files_created.
    Flipping ``not exists()`` to ``exists()`` would skip the write entirely:
    the file would be missing and absent from files_created.
    """
    project_dir = create_fixture_project(name="at_ct_init")
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    init_file = project_dir / "app" / "resilience" / "__init__.py"
    assert init_file.exists(), "resilience package __init__.py must be created"
    assert "Resilience patterns package" in init_file.read_text()
    assert str(init_file.resolve()) in _resolved(result.files_created), (
        "the created __init__.py must be recorded in files_created"
    )


def test_succeeds_when_resilience_dir_preexists():
    """L104 (exist_ok): ``resilience_dir.mkdir(..., exist_ok=True)`` must not
    raise when app/resilience already exists.

    Pre-create the directory before running. With exist_ok=True the tool
    proceeds normally; if exist_ok flips to False the mkdir raises
    FileExistsError and the call fails.
    """
    project_dir = create_fixture_project(name="at_ct_predir")
    (project_dir / "app" / "resilience").mkdir(parents=True, exist_ok=True)
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert (project_dir / "app" / "resilience" / "timeouts.py").exists()


def test_count_logic_lines_spans_full_body():
    """L184/L185: ``end = node.end_lineno or start`` and
    ``loc += end - start + 1`` must count every line of a multi-line body.

    A 3-statement function body spans 3 source lines. The original returns 3.
    Flipping ``or`` to ``and`` collapses ``end`` to ``start`` (-> 1); flipping
    the ``+ 1`` to ``- 1`` yields ``end - start - 1`` (-> 1). Either mutant
    shrinks the count, so asserting exactly 3 kills both.
    """
    src = "def handler():\n    a = 1\n    b = 2\n    return a + b\n"
    assert _count_logic_lines(src) == 3

    # A single-statement body counts as exactly 1 (end == start path).
    assert _count_logic_lines("def f():\n    return 0\n") == 1

    # Two functions accumulate (2-line body + 1-line body == 3).
    two = "def f():\n    x = 1\n    return x\n\ndef g():\n    return 2\n"
    assert _count_logic_lines(two) == 3
