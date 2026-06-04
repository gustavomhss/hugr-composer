"""Generic tool-contract mutation coverage for add_graphql.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_graphql.py in the mutation
runner: ``--tests test_add_graphql.py test_add_graphql_contract.py``.

Appended below: tool-specific tests that kill the remaining add_graphql
survivors (model-presence fallbacks, main.py patch ordering/guards,
requirements dedup, and the emitted-test mkdir flag).
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_graphql import (
    _patch_main,
    _patch_requirements,
    add_graphql,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.api_design.add_graphql import add_graphql

    for check in SCAFFOLDABLE_CHECKS:
        check(add_graphql, "add_graphql")


# ---------------------------------------------------------------------------
# L134 / L166 / L105 — model-presence fallbacks ("... or '# No models'").
# The fixture project ships an `Item` model WITH a matching route, so
# _discover_models() returns ["Item"].  With models present the left operand
# is truthy, so the real content (not the placeholder) must be emitted.
# Or -> And would collapse to the placeholder string.
# ---------------------------------------------------------------------------


def test_dataloaders_registry_lists_discovered_model() -> None:
    """L134: registry_attrs uses the discovered model, not the '# No models' fallback."""
    project_dir = create_fixture_project(name="gql_c_l134")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    content = (project_dir / "app" / "graphql" / "dataloaders.py").read_text()
    # Real per-model registry attribute must be present.
    assert "item_by_id: ItemByIdLoader" in content
    # The fallback placeholder must NOT have replaced it.
    assert "# No models\n" not in content


def test_queries_emit_resolver_for_discovered_model() -> None:
    """L166: resolver_blocks emit the model resolver, not the '# No models' fallback."""
    project_dir = create_fixture_project(name="gql_c_l166")
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    content = (project_dir / "app" / "graphql" / "queries.py").read_text()
    # The Item resolver field (lowercased model name) must be emitted.
    assert "async def item(" in content
    assert "# No models discovered." not in content


def test_dry_run_note_lists_discovered_models_not_none() -> None:
    """L105: dry_run 'Models found' note shows the model name, not 'none'."""
    project_dir = create_fixture_project(name="gql_c_l105")
    result = add_graphql(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    note = next(n for n in result.notes if "Models found" in n)
    assert "Item" in note
    # ', '.join(model_names) or 'none' -> with models this is the join, never 'none'.
    assert "none" not in note


# ---------------------------------------------------------------------------
# L421 / L427 — _patch_main import placement.
#   In -> NotIn on the "from fastapi import FastAPI" anchor would flip which
#   branch runs.  Add -> Sub on `graphql_import + src` (the no-anchor branch)
#   would raise TypeError (str - str).  Drive BOTH branches explicitly.
# ---------------------------------------------------------------------------


def test_patch_main_inserts_after_fastapi_import_anchor() -> None:
    """L421: when 'from fastapi import FastAPI' is present, the gql import lands right after it."""
    tmp = Path(tempfile.mkdtemp())
    main = tmp / "main.py"
    main.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    _patch_main(main)
    src = main.read_text()
    anchor_idx = src.index("from fastapi import FastAPI")
    gql_idx = src.index("from strawberry.fastapi import GraphQLRouter")
    # The strawberry import must come AFTER the FastAPI anchor (replace-in-place).
    assert gql_idx > anchor_idx
    # And it must come BEFORE the app instantiation line (inserted, not appended).
    assert gql_idx < src.index("app = FastAPI()")


def test_patch_main_prepends_when_no_fastapi_anchor() -> None:
    """L427: with no FastAPI import anchor, graphql_import is prepended (Add, not Sub)."""
    tmp = Path(tempfile.mkdtemp())
    main = tmp / "main.py"
    # No "from fastapi import FastAPI" line -> the else branch (graphql_import + src).
    original = "import os\n\napp = make_app()\n"
    main.write_text(original)
    _patch_main(main)
    src = main.read_text()
    # The graphql import block must be at the very start (prepended).
    assert src.startswith("from strawberry.fastapi import GraphQLRouter")
    # Original content must be preserved after the prepended block.
    assert "import os" in src
    assert src.index("import os") > src.index("from strawberry.fastapi import GraphQLRouter")


# ---------------------------------------------------------------------------
# L412 — _patch_main idempotency guard:  if "GraphQLRouter" in src or "/graphql" in src.
#   Or -> And would only short-circuit when BOTH markers are present, so a
#   main.py carrying just one marker would be patched a second time.
# ---------------------------------------------------------------------------


def test_patch_main_skips_when_only_graphql_path_marker_present() -> None:
    """L412: '/graphql' alone must trigger the guard (Or, not And)."""
    tmp = Path(tempfile.mkdtemp())
    main = tmp / "main.py"
    sentinel = 'app.include_router(r, prefix="/graphql")\n'
    main.write_text(sentinel)
    _patch_main(main)
    # Guard hit -> file untouched, no GraphQLRouter import injected.
    assert main.read_text() == sentinel
    assert "GraphQLRouter" not in main.read_text()


def test_patch_main_skips_when_only_router_marker_present() -> None:
    """L412: 'GraphQLRouter' alone must trigger the guard (Or, not And)."""
    tmp = Path(tempfile.mkdtemp())
    main = tmp / "main.py"
    sentinel = "# uses GraphQLRouter elsewhere\nfrom fastapi import FastAPI\napp = FastAPI()\n"
    main.write_text(sentinel)
    _patch_main(main)
    # Guard hit -> no mount block appended, content unchanged.
    assert main.read_text() == sentinel


# ---------------------------------------------------------------------------
# L447 / L449 — _patch_requirements dedup guards (NotIn -> In).
#   "strawberry-graphql" not in src / "aiodataloader" not in src decide whether
#   to append.  NotIn -> In inverts the logic: present pkgs would be re-added and
#   absent pkgs skipped.
# ---------------------------------------------------------------------------


def test_patch_requirements_adds_missing_packages() -> None:
    """L447/L449: absent strawberry-graphql + aiodataloader are appended exactly once."""
    tmp = Path(tempfile.mkdtemp())
    req = tmp / "requirements.txt"
    req.write_text("fastapi>=0.110\n")
    _patch_requirements(req)
    src = req.read_text()
    assert "strawberry-graphql[fastapi]>=0.220.0" in src
    assert "aiodataloader>=0.2.1" in src
    assert src.count("strawberry-graphql") == 1
    assert src.count("aiodataloader") == 1


def test_patch_requirements_does_not_duplicate_present_packages() -> None:
    """L447/L449: already-present packages are NOT re-added (NotIn guard)."""
    tmp = Path(tempfile.mkdtemp())
    req = tmp / "requirements.txt"
    req.write_text("strawberry-graphql[fastapi]>=0.220.0\naiodataloader>=0.2.1\n")
    _patch_requirements(req)
    src = req.read_text()
    # Neither package gets a second line.
    assert src.count("strawberry-graphql") == 1
    assert src.count("aiodataloader") == 1


# ---------------------------------------------------------------------------
# L457 — _emit_project_test: (project / "tests").mkdir(parents=True, exist_ok=True).
#   The fixture project already ships a tests/ directory, so exist_ok=True is
#   load-bearing: True -> False would raise FileExistsError and the tool would
#   not return success.
# ---------------------------------------------------------------------------


def test_emit_project_test_tolerates_existing_tests_dir() -> None:
    """L457: run succeeds even though tests/ already exists (exist_ok=True)."""
    project_dir = create_fixture_project(name="gql_c_l457")
    # The fixture already created tests/; make sure it is there.
    assert (project_dir / "tests").exists()
    result = add_graphql(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"got {result.status}: {result.error}"
    # The emitted project test must have been written under the existing dir.
    assert (project_dir / "tests" / "test_add_graphql_emitted.py").exists()
