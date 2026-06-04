"""Generic tool-contract mutation coverage for add_batch_endpoint.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_batch_endpoint.py in the mutation
runner: ``--tests test_add_batch_endpoint.py test_add_batch_endpoint_contract.py``.

The ``test_kills_*`` functions below target this tool's *specific* logic
(model discovery filter, router patch ordering/fallbacks, idempotency-store
merge dedup, dir-creation guards) that the generic preamble checks do not
cover.
"""

from __future__ import annotations

import tempfile

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint

    for check in UNIVERSAL_CHECKS:
        check(add_batch_endpoint, "add_batch_endpoint")


# ---------------------------------------------------------------------------
# Model discovery filter — _discover_models (kills L207 And->Or, In->NotIn)
# ---------------------------------------------------------------------------


def test_kills_model_requires_both_create_and_public_schema() -> None:
    """A model whose schema has Create but NOT Public must be excluded.

    Kills L207 ``and``->``or`` (Or would include the half-defined model) and the
    ``in`` compares (a NotIn flip inverts which models qualify).
    """
    project = create_fixture_project(name="be_ct_partial", models={"Item": {"title": "str"}})
    # Add a model that has a Create schema but no Public schema.
    (project / "app" / "models" / "gadget.py").write_text("class Gadget:\n    pass\n")
    (project / "app" / "schemas" / "gadget.py").write_text("class GadgetCreate:\n    pass\n")

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    bulk = project / "app" / "api" / "routes" / "bulk"
    assert (bulk / "item_bulk.py").exists(), "Item (full schema) should be wired"
    assert not (bulk / "gadget_bulk.py").exists(), (
        "Gadget lacks GadgetPublic — must NOT get a bulk route"
    )


def test_kills_model_without_schema_excluded() -> None:
    """A model file with no matching schema file at all must be excluded."""
    project = create_fixture_project(name="be_ct_noschema", models={"Item": {"title": "str"}})
    (project / "app" / "models" / "orphan.py").write_text("class Orphan:\n    pass\n")

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    bulk = project / "app" / "api" / "routes" / "bulk"
    assert not (bulk / "orphan_bulk.py").exists()
    assert (bulk / "item_bulk.py").exists()


# ---------------------------------------------------------------------------
# Router patch — normal-path ordering (kills L271, L282 Add->Sub)
# ---------------------------------------------------------------------------


def test_kills_bulk_import_lands_after_last_app_import() -> None:
    """The bulk import is inserted at ``last_app_import_idx + 1``.

    Kills L271 ``+ 1``->``- 1`` (Sub would put the import before the last
    ``from app.`` import instead of right after it).
    """
    project = create_fixture_project(name="be_ct_imp_order")
    routes_init = project / "app" / "routes" / "__init__.py"

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    lines = routes_init.read_text().splitlines()
    app_imports = [
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and "bulk" not in ln
    ]
    bulk_import = next(i for i, ln in enumerate(lines) if ln.startswith("from app.api.routes.bulk"))
    assert bulk_import == max(app_imports) + 1, (
        "bulk import must land immediately after the last app import"
    )


def test_kills_bulk_include_lands_after_last_include() -> None:
    """The bulk include is inserted at ``last_include_idx + 1``.

    Kills L282 ``+ 1``->``- 1`` (Sub would put the include before the last
    existing ``api_router.include_router`` call).
    """
    project = create_fixture_project(name="be_ct_inc_order")
    routes_init = project / "app" / "routes" / "__init__.py"

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    lines = routes_init.read_text().splitlines()
    includes = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and "bulk" not in ln
    ]
    bulk_include = next(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and "bulk" in ln
    )
    assert bulk_include == max(includes) + 1, (
        "bulk include must land immediately after the last existing include"
    )


# ---------------------------------------------------------------------------
# Router patch — dedup (kills L259 In->NotIn)
# ---------------------------------------------------------------------------


def test_kills_router_import_not_duplicated_when_already_present() -> None:
    """If the bulk import line already exists, the patch must not re-add it.

    Kills L259 ``in``->``not in`` (a NotIn flip would skip the dedup and append
    a second identical import).
    """
    project = create_fixture_project(name="be_ct_dedup", models={"Item": {"title": "str"}})
    routes_init = project / "app" / "routes" / "__init__.py"
    inject = "from app.api.routes.bulk.item_bulk import router as _item_bulk_router"
    src = routes_init.read_text()
    routes_init.write_text(
        src.replace("api_router = APIRouter()", inject + "\napi_router = APIRouter()")
    )

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert routes_init.read_text().count(inject) == 1, "import line must not be duplicated"


# ---------------------------------------------------------------------------
# Router patch — import fallback when no ``from app.`` imports exist
# (kills L266 Eq->NotEq, L268 And->Or + In->NotIn, L269 Sub->Add)
# ---------------------------------------------------------------------------


def test_kills_import_fallback_lands_before_apirouter() -> None:
    """With no ``from app.`` imports, the bulk import lands right before the
    ``api_router = APIRouter()`` line.

    A comment line mentioning ``api_router`` precedes the real definition so
    the And/Or and In/NotIn flips on the anchor guard are distinguishable, and
    the position pins down the ``- 1`` index math.
    """
    project = create_fixture_project(name="be_ct_imp_fb", models={"Item": {"title": "str"}})
    routes_init = project / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        "from fastapi import APIRouter\n"
        "\n"
        "# configure api_router below\n"
        "api_router = APIRouter()\n"
        "\n"
        '__all__ = ["api_router"]\n'
    )

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    lines = routes_init.read_text().splitlines()
    bulk_import = next(i for i, ln in enumerate(lines) if ln.startswith("from app.api.routes.bulk"))
    apirouter = next(i for i, ln in enumerate(lines) if "APIRouter()" in ln)
    assert bulk_import == apirouter - 1, (
        "import must land immediately before the api_router = APIRouter() line"
    )


# ---------------------------------------------------------------------------
# Router patch — include fallback when no include_router calls exist
# (kills L277 Eq->NotEq, L279 And->Or + In->NotIn)
# ---------------------------------------------------------------------------


def test_kills_include_fallback_lands_after_apirouter() -> None:
    """With no existing ``include_router`` calls, the bulk include lands right
    after the ``api_router = APIRouter()`` line."""
    project = create_fixture_project(name="be_ct_inc_fb", models={"Item": {"title": "str"}})
    routes_init = project / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        "from fastapi import APIRouter\n"
        "\n"
        "# configure api_router below\n"
        "api_router = APIRouter()\n"
        "\n"
        '__all__ = ["api_router"]\n'
    )

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error

    lines = routes_init.read_text().splitlines()
    apirouter = next(i for i, ln in enumerate(lines) if "APIRouter()" in ln)
    bulk_include = next(
        i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")
    )
    assert bulk_include == apirouter + 1, (
        "include must land immediately after the api_router = APIRouter() line"
    )


# ---------------------------------------------------------------------------
# Idempotency-store merge (kills L215 In->NotIn, L246 Add->Sub)
# ---------------------------------------------------------------------------


def test_kills_idempotency_merge_appends_to_existing() -> None:
    """When idempotency.py exists without the store, the merge appends the
    store AFTER the original content (``src + addition``).

    Kills L246 ``src + addition``->``src - addition`` (str ``-`` raises
    TypeError → crash) and proves the original content is preserved.
    """
    project = create_fixture_project(name="be_ct_idem_merge")
    idem = project / "app" / "core" / "idempotency.py"
    idem.write_text("# preexisting idempotency module\nSENTINEL = 1\n")

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    out = idem.read_text()
    assert out.startswith("# preexisting idempotency module"), "original content must lead"
    assert "SENTINEL = 1" in out, "original content must be preserved"
    assert "def get_idempotency_store" in out, "store must be appended"
    assert any("idempotency.py" in m for m in result.files_modified)


def test_kills_idempotency_merge_dedup_when_store_present() -> None:
    """When idempotency.py already defines get_idempotency_store, the merge is
    a no-op (no second copy).

    Kills L215 ``in``->``not in`` (a NotIn flip would append the store again
    when it is already present).
    """
    project = create_fixture_project(name="be_ct_idem_dedup")
    idem = project / "app" / "core" / "idempotency.py"
    idem.write_text("def get_idempotency_store():\n    return None\n")

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    out = idem.read_text()
    assert out.count("def get_idempotency_store") == 1, "store must not be duplicated"
    assert "class IdempotencyStore" not in out, "nothing should be appended when already present"


# ---------------------------------------------------------------------------
# Dir-creation guards under collision (kills L142, L289 True->False)
# ---------------------------------------------------------------------------


def test_kills_bulk_dir_exist_ok_under_collision() -> None:
    """Tool still succeeds when the bulk dir already exists.

    Kills L142 ``exist_ok=True``->``False`` (a False flip would raise
    FileExistsError because the bulk dir is pre-created here).
    """
    project = create_fixture_project(name="be_ct_bulk_exist")
    (project / "app" / "api" / "routes" / "bulk").mkdir(parents=True, exist_ok=True)

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert (project / "app" / "api" / "routes" / "bulk" / "__init__.py").exists()


def test_kills_tests_dir_exist_ok_under_collision() -> None:
    """Tool still succeeds when the tests/ dir already exists.

    Kills L289 ``exist_ok=True``->``False`` in _emit_project_test.
    """
    project = create_fixture_project(name="be_ct_tests_exist")
    (project / "tests").mkdir(parents=True, exist_ok=True)

    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


# ---------------------------------------------------------------------------
# auto_scaffold gating + prereq error string (kills L79 not, L84 Add->Sub)
# ---------------------------------------------------------------------------


def test_kills_dry_run_does_not_auto_scaffold_prereqs() -> None:
    """On a bare dir with dry_run=True, auto_scaffold is OFF (``not dry_run``)
    so prerequisites are NOT created and the tool errors.

    Kills L79 ``not inp.dry_run``->``inp.dry_run`` (the flip would enable
    auto_scaffold under dry_run and the prereq error would never fire). Also
    kills L84 ``"..." + "\\n".join(...)``->``-`` (str ``-`` would crash while
    building the prereq error message).
    """
    bare = tempfile.mkdtemp()
    result = add_batch_endpoint(ToolInput(project_dir=bare, dry_run=True))
    assert result.status == "error"
    assert result.error is not None
    assert "Prerequisites not met:" in result.error
    assert "  - " in result.error, "error must list bullet-prefixed prereqs (the + concat)"


def test_kills_non_dry_run_auto_scaffolds() -> None:
    """On a real fixture (prereqs satisfied) a normal run succeeds and emits
    the bulk wiring — confirms the auto_scaffold path is exercised."""
    project = create_fixture_project(name="be_ct_scaffold")
    result = add_batch_endpoint(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    assert isinstance(result.files_created, list)
    assert any("batch_core.py" in f for f in result.files_created)
