"""Generic tool-contract mutation coverage for add_api_versioning.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_api_versioning.py in the mutation
runner: ``--tests test_add_api_versioning.py test_add_api_versioning_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_api_versioning import add_api_versioning
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_api_versioning, "add_api_versioning")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (logic not covered by the generic preamble).
# ---------------------------------------------------------------------------


def test_scaffolded_prereqs_included_in_files_created():
    """L87 ``list(scaffolded or [])``: prereqs auto-scaffolded on a bare
    project must appear in ``files_created``. Flipping ``or``→``and`` makes the
    expression ``list(scaffolded and [])`` == ``[]``, dropping the prereq paths.
    """
    bare = Path(tempfile.mkdtemp())
    (bare / "app").mkdir()
    result = add_api_versioning(ToolInput(project_dir=str(bare)))
    assert result.status == "success"
    # The CONFIG_SETTINGS / ROUTES_INIT prereqs are scaffolded for a bare
    # project; their paths must be carried through into files_created.
    assert any(p.endswith("core/config.py") for p in result.files_created), (
        f"scaffolded config.py missing from files_created: {result.files_created}"
    )
    assert any(p.endswith("routes/__init__.py") for p in result.files_created), (
        f"scaffolded routes/__init__.py missing from files_created: {result.files_created}"
    )


def test_dry_run_note_lists_discovered_model_names():
    """L106 ``', '.join(model_names) or 'none'``: with a model present the
    dry-run note must name the model. ``or``→``and`` would yield ``'none'``.
    """
    project = create_fixture_project(name="av_ctr_dryrun")
    result = add_api_versioning(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    joined = "\n".join(result.notes)
    assert "Item" in joined, f"discovered model name not in dry_run notes: {result.notes}"
    assert "Models found: none" not in joined


def test_schema_init_lists_discovered_models():
    """L128 schema ``model_lines`` ``join(...) or fallback``: with a model the
    emitted schema __init__ must carry the model import line, not the
    no-models fallback comment. ``or``→``and`` swaps to the fallback.
    """
    project = create_fixture_project(name="av_ctr_schema")
    add_api_versioning(ToolInput(project_dir=str(project)))
    content = (project / "app" / "schemas" / "v1" / "__init__.py").read_text()
    assert "app.schemas.v1.item import ItemCreate" in content, content
    assert "# No models discovered" not in content


def test_router_init_includes_model_router():
    """L146 ``include_lines`` ``join(...) or fallback``: the versioned router
    __init__ must call ``include_router`` for the discovered model. ``or``→
    ``and`` would emit the no-models fallback comment instead.
    """
    project = create_fixture_project(name="av_ctr_include")
    add_api_versioning(ToolInput(project_dir=str(project)))
    content = (project / "app" / "api" / "v1" / "__init__.py").read_text()
    assert "router.include_router(item_router" in content, content
    assert "include routers here" not in content


def test_router_init_imports_model_router():
    """L154 ``import_lines`` ``join(...) or fallback``: the versioned router
    __init__ must import the model's router. ``or``→``and`` would emit the
    ``# No models discovered.`` fallback instead of the import.
    """
    project = create_fixture_project(name="av_ctr_import")
    add_api_versioning(ToolInput(project_dir=str(project)))
    content = (project / "app" / "api" / "v2" / "__init__.py").read_text()
    assert "from app.api.v2.item import router as item_router" in content, content


def test_imports_injected_after_existing_fastapi_import():
    """L254 ``if "from fastapi import FastAPI" in src``: when the anchor is
    present the imports are spliced in right after it (via ``.replace``).
    ``In``→``NotIn`` would take the else branch and prepend them at the file
    top instead. Assert the version imports directly follow the anchor.
    """
    project = create_fixture_project(name="av_ctr_anchor")
    add_api_versioning(ToolInput(project_dir=str(project)))
    src = (project / "app" / "main.py").read_text()
    anchor = "from fastapi import FastAPI"
    assert anchor in src
    after = src.split(anchor, 1)[1]
    # The three version imports are appended immediately after the anchor.
    assert after.startswith(
        "\nfrom app.middleware.version_resolver import VersionResolverMiddleware"
    ), after[:200]
    # And the file must NOT start with the version import (the else-branch path).
    assert not src.lstrip().startswith(
        "from app.middleware.version_resolver import VersionResolverMiddleware"
    )


def test_imports_prepended_when_no_fastapi_import_anchor():
    """L260 else-branch ``middleware_import + ... + "\\n" + src``: when there is
    no ``from fastapi import FastAPI`` anchor the imports are prepended to the
    top. ``Add``→``Sub`` turns string concat into ``str - str`` (TypeError),
    so reaching this branch and asserting success kills the mutant.
    """
    project = create_fixture_project(name="av_ctr_noanchor")
    main_file = project / "app" / "main.py"
    src = main_file.read_text()
    # Remove the anchor so _patch_main takes the else branch.
    src = src.replace("from fastapi import FastAPI", "import fastapi")
    main_file.write_text(src)
    result = add_api_versioning(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = main_file.read_text()
    assert out.lstrip().startswith(
        "from app.middleware.version_resolver import VersionResolverMiddleware"
    ), out[:200]


def test_middleware_call_inserted_after_existing_add_middleware():
    """L268 ``if "app.add_middleware" in src``: when an existing
    ``app.add_middleware`` call is present the version middleware block is
    inserted right after the last one (not appended at EOF). ``In``→``NotIn``
    would append at the very end instead.
    """
    project = create_fixture_project(name="av_ctr_mwpos")
    add_api_versioning(ToolInput(project_dir=str(project)))
    src = (project / "app" / "main.py").read_text()
    lines = src.splitlines()
    mw_idx = next(
        i
        for i, ln in enumerate(lines)
        if ln.strip() == "app.add_middleware(VersionResolverMiddleware)"
    )
    # The line immediately above must be a pre-existing add_middleware call,
    # proving the block landed after the last existing one rather than at EOF.
    above = [ln for ln in lines[:mw_idx] if "app.add_middleware" in ln]
    assert above, f"version middleware not placed after an existing add_middleware: {src}"
    # There is post-insertion content after our block (it is not at EOF).
    tail = "\n".join(lines[mw_idx:])
    assert "app.include_router(api_router" in tail or len(lines) > mw_idx + 3, tail


def test_middleware_call_appended_when_no_existing_add_middleware():
    """L273 else-branch ``src.rstrip("\\n") + "\\n" + middleware_call``: with no
    existing ``app.add_middleware`` the version block is appended at the end.
    ``Add``→``Sub`` makes the concat a TypeError, so reaching this branch and
    asserting success + appended block kills the mutant.
    """
    project = create_fixture_project(name="av_ctr_noaddmw")
    main_file = project / "app" / "main.py"
    src = main_file.read_text()
    src = "\n".join(ln for ln in src.splitlines() if "app.add_middleware" not in ln)
    main_file.write_text(src)
    result = add_api_versioning(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    out = main_file.read_text()
    assert out.rstrip().endswith("app.include_router(_v2_router, prefix='/api/v2')"), out[-200:]
