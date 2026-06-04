"""Generic tool-contract mutation coverage for add_schema_enforcer.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_schema_enforcer.py in the mutation
runner: ``--tests test_add_schema_enforcer.py test_add_schema_enforcer_contract.py``.

The ``test_se_*`` functions below target this tool's *specific* logic
(survivors the generic contract leaves alive): scaffolded-files passthrough,
the __init__/emitted-file creation guards, and the main.py import / register
placement arithmetic.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_schema_enforcer import add_schema_enforcer
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_schema_enforcer import add_schema_enforcer

    for check in SCAFFOLDABLE_CHECKS:
        check(add_schema_enforcer, "add_schema_enforcer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_project(*, with_config: bool = True, with_requirements: bool = True) -> Path:
    """A minimal project that passes prereqs but has no scaffold scaffolding.

    When ``with_config`` / ``with_requirements`` are False the respective
    prerequisite is left missing so ``ensure_prerequisites`` auto-scaffolds
    it — which is how we drive the ``scaffolded`` passthrough path.
    """
    d = Path(tempfile.mkdtemp())
    (d / "app").mkdir(parents=True)
    (d / "app" / "__init__.py").write_text("")
    if with_config:
        (d / "app" / "core").mkdir(parents=True)
        (d / "app" / "core" / "config.py").write_text(
            'class Settings:\n    APP_NAME: str = "x"\n\n\nsettings = Settings()\n'
        )
    if with_requirements:
        (d / "requirements.txt").write_text("fastapi\n")
    return d


# ---------------------------------------------------------------------------
# L87 BoolOp Or->And:  files_created = list(scaffolded or [])
# ---------------------------------------------------------------------------


def test_se_scaffolded_files_included_in_created():
    """Auto-scaffolded prereq files must flow into files_created.

    Omitting config.py forces ``ensure_prerequisites`` to scaffold it; the
    returned paths are seeded into ``files_created`` via ``scaffolded or []``.
    Flipping ``or`` to ``and`` collapses that to ``[]`` and the scaffolded
    config would vanish from the report.
    """
    project = _bare_project(with_config=False, with_requirements=False)
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        f"auto-scaffolded config.py missing from files_created: {result.files_created}"
    )


# ---------------------------------------------------------------------------
# L120 UnaryNot:  if not mw_init.exists(): write __init__.py
# ---------------------------------------------------------------------------


def test_se_creates_middleware_init_when_absent():
    """A fresh project with no middleware package gets an __init__.py.

    The guard ``if not mw_init.exists()`` creates the package marker. The
    UnaryNot flip inverts it to ``if mw_init.exists()`` so on a bare project
    (no existing __init__) the marker would never be written / reported.
    """
    project = _bare_project()
    init_path = project / "app" / "middleware" / "__init__.py"
    assert not init_path.exists()
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert init_path.exists(), "middleware/__init__.py was not created"
    assert any(p.endswith("app/middleware/__init__.py") for p in result.files_created), (
        f"middleware/__init__.py missing from files_created: {result.files_created}"
    )


# ---------------------------------------------------------------------------
# L163 UnaryNot:  if not emitted.exists(): render emitted test
# ---------------------------------------------------------------------------


def test_se_emits_emitted_test_when_absent():
    """The emitted-test file is rendered on a project that lacks it.

    ``if not emitted.exists()`` emits ``tests/test_add_schema_enforcer_emitted.py``.
    The UnaryNot flip would only emit when the file already exists, so on a
    fresh run the file (and its files_created entry) disappears.
    """
    project = _bare_project()
    emitted = project / "tests" / "test_add_schema_enforcer_emitted.py"
    assert not emitted.exists()
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert emitted.exists(), "emitted test file was not rendered"
    assert any(
        p.endswith("tests/test_add_schema_enforcer_emitted.py") for p in result.files_created
    ), f"emitted test missing from files_created: {result.files_created}"


# ---------------------------------------------------------------------------
# L211 Compare In->NotIn:  if "from fastapi import FastAPI" in src
# ---------------------------------------------------------------------------


def test_se_import_inserted_after_fastapi_import_line():
    """The enforcer import is spliced right after the FastAPI import line.

    When the anchor ``from fastapi import FastAPI`` is present (In branch),
    the import is inserted *immediately after* it. The In->NotIn flip routes
    to the else branch which *prepends* the import at the very top of the file
    — so the import would land BEFORE the FastAPI line instead of after it.
    """
    project = _bare_project(with_requirements=True)
    main = project / "app" / "main.py"
    main.write_text("from fastapi import FastAPI\n\napp = FastAPI()\n")
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    content = main.read_text()
    anchor = content.index("from fastapi import FastAPI")
    enforcer_import = content.index(
        "from app.middleware.schema_enforcer import register_schema_enforcer"
    )
    assert enforcer_import > anchor, (
        "enforcer import must be inserted AFTER the FastAPI import line, "
        f"not prepended (anchor={anchor}, import={enforcer_import})"
    )


# ---------------------------------------------------------------------------
# L217 BinOp Add->Sub:  src = import_line + src  (no FastAPI import anchor)
# ---------------------------------------------------------------------------


def test_se_import_prepended_when_no_fastapi_anchor():
    """With no FastAPI import anchor the import is prepended to the source.

    This drives the else branch ``src = import_line + src``. The Add->Sub
    mutant becomes ``import_line - src`` (str - str => TypeError), which the
    tool has no handler for, so the run fails instead of returning success.
    """
    project = _bare_project(with_requirements=True)
    main = project / "app" / "main.py"
    # No "from fastapi import FastAPI" and no "app = FastAPI(" marker.
    main.write_text("# custom entry point\napp = None\n")
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    content = main.read_text()
    assert "from app.middleware.schema_enforcer import register_schema_enforcer" in content, (
        "enforcer import not prepended when FastAPI anchor absent"
    )
    # Prepended: the import precedes the original first line.
    assert content.index(
        "from app.middleware.schema_enforcer import register_schema_enforcer"
    ) < content.index("# custom entry point")


# ---------------------------------------------------------------------------
# L220 Compare In->NotIn:  if marker in src  (marker = "app = FastAPI(")
# ---------------------------------------------------------------------------


def test_se_register_call_placed_right_after_fastapi_block():
    """register_schema_enforcer(app) lands right after the FastAPI() block.

    With the ``app = FastAPI(`` marker present (In branch), the register call
    is spliced immediately after the constructor's closing paren — even when
    more code follows. The In->NotIn flip routes to the else branch which
    *appends* the call at end-of-file, so it would no longer sit directly
    after the constructor and would become the file's last statement.
    """
    project = _bare_project(with_requirements=True)
    main = project / "app" / "main.py"
    main.write_text(
        "from fastapi import FastAPI\n"
        "\n"
        "app = FastAPI(\n"
        '    title="demo",\n'
        ")\n"
        "\n"
        "TRAILING_SENTINEL = 1\n"
    )
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    content = main.read_text()
    close_paren = content.index("app = FastAPI(")
    close_paren = content.index(")", close_paren) + 1
    reg = content.index("register_schema_enforcer(app)")
    # Inserted right after the constructor block (only whitespace between).
    between = content[close_paren:reg]
    assert between.strip() == "", (
        f"register call not directly after FastAPI() block; between={between!r}"
    )
    # And there is still trailing code after it (not appended at EOF).
    assert "TRAILING_SENTINEL = 1" in content[reg:], (
        "register call was appended at EOF instead of after the FastAPI() block"
    )


# ---------------------------------------------------------------------------
# L235 BinOp Add->Sub:  src = src.rstrip("\n") + "...register..."  (no marker)
# ---------------------------------------------------------------------------


def test_se_register_appended_when_no_fastapi_marker():
    """With no ``app = FastAPI(`` marker the register call is appended at EOF.

    Drives the else branch ``src = src.rstrip("\\n") + "\\nregister..."``.
    The Add->Sub mutant becomes ``str - str`` => TypeError, so the tool
    would fail rather than return success with the call appended.
    """
    project = _bare_project(with_requirements=True)
    main = project / "app" / "main.py"
    main.write_text("# custom entry point\napp = None\n")
    result = add_schema_enforcer(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    content = main.read_text()
    assert "register_schema_enforcer(app)" in content, (
        "register call not appended when FastAPI marker absent"
    )
    # Appended at end: it is the last meaningful statement.
    assert content.rstrip().endswith("register_schema_enforcer(app)"), (
        f"register call not appended at EOF: {content!r}"
    )
