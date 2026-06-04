"""Generic tool-contract mutation coverage for add_search.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_search.py in the mutation
runner: ``--tests test_add_search.py test_add_search_contract.py``.

The ``test_logic_*`` functions below target add_search's *tool-specific* logic
(model discovery, field extraction, route ordering, migration head wiring) — the
survivors the generic preamble contract cannot reach.
"""

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.contracts.migration_helper import find_migration_head
from adapt.extend.crud_data.add_search import add_search
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_search import add_search

    for check in UNIVERSAL_CHECKS:
        check(add_search, "add_search")


# ---------------------------------------------------------------------------
# Field extraction — _extract_text_fields (L186 / L188)
# ---------------------------------------------------------------------------


def test_logic_extracts_exact_str_fields_only():
    """L186 (``Mapped[str`` in s AND ``mapped_column`` in s) + L188 (name NOT in
    id/owner_id).

    The model has two ``Mapped[str]`` columns (headline, body) plus non-str
    columns (id, owner_id, created_at, updated_at). The emitted CRUD's
    ``_SEARCH_TEXT_COLUMNS`` must be EXACTLY ['headline', 'body']:
      - And->Or on L186 would also pull every ``mapped_column`` line
        (created_at / updated_at), polluting the list.
      - In->NotIn on L186 would extract nothing -> fallback ['title','description'].
      - NotIn->In on L188 would keep only id/owner_id (none str-typed) -> fallback.
    """
    project = create_fixture_project(
        name="search_logic_fields",
        models={"Article": {"headline": "str", "body": "str"}},
    )
    result = add_search(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error
    crud = (project / "app" / "crud" / "article.py").read_text()
    assert "_SEARCH_TEXT_COLUMNS: list[str] = ['headline', 'body']" in crud, (
        "field extraction must yield exactly the model's Mapped[str] columns"
    )
    # The non-text scaffold columns must never become searchable.
    assert "created_at" not in crud.split("_SEARCH_TEXT_COLUMNS")[1].split("\n")[0]
    assert "updated_at" not in crud.split("_SEARCH_TEXT_COLUMNS")[1].split("\n")[0]
    assert "owner_id" not in crud.split("_SEARCH_TEXT_COLUMNS")[1].split("\n")[0]


def test_logic_setweight_uses_real_field_names():
    """L186 / L188 again, via the setweight() vectors.

    Each extracted field is woven into a setweight(to_tsvector(...coalesce(
    Model.field...))) line. The real field names (headline/body) must appear and
    the fallback names (title/description) must not — proving extraction picked
    the model's actual str columns, not the fallback.
    """
    project = create_fixture_project(
        name="search_logic_setweight",
        models={"Article": {"headline": "str", "body": "str"}},
    )
    add_search(ToolInput(project_dir=str(project)))
    crud = (project / "app" / "crud" / "article.py").read_text()
    assert "_func.coalesce(Article.headline, '')" in crud
    assert "_func.coalesce(Article.body, '')" in crud
    assert "_func.coalesce(Article.title, '')" not in crud
    assert "_func.coalesce(Article.description, '')" not in crud


# ---------------------------------------------------------------------------
# Model discovery — skip set + route gating (L157)
# ---------------------------------------------------------------------------


def test_logic_skip_model_with_route_is_not_searched():
    """L157 ``stem in _SKIP_MODELS or stem not in available_routes`` (Or->And).

    'tenant' is in _SKIP_MODELS and has its own 'tenant' route file:
      - Or: (in SKIP)=True short-circuits -> Tenant is SKIPPED (correct).
      - And: True and (tenant not in routes)=False -> False -> Tenant would be
        searched, leaking search() into the tenant CRUD and into notes.
    """
    project = create_fixture_project(
        name="search_logic_skip",
        models={"Item": {"title": "str"}, "Tenant": {"name": "str"}},
    )
    result = add_search(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    enabled_note = result.notes[0]
    assert "Item" in enabled_note
    assert "Tenant" not in enabled_note, "Tenant is in _SKIP_MODELS — must not be searched"
    tenant_crud = project / "app" / "crud" / "tenant.py"
    assert tenant_crud.exists()
    assert "async def search" not in tenant_crud.read_text(), (
        "search() must not be injected into a _SKIP_MODELS table"
    )


def test_logic_all_non_skipped_models_are_searched():
    """L157 second clause — every model that DOES have a route gets search().

    Two ordinary models (Item, Product) each have a matching route, so both must
    receive search(). This pins the discovery loop's positive path.
    """
    project = create_fixture_project(
        name="search_logic_multi",
        models={"Item": {"title": "str"}, "Product": {"name": "str", "description": "str"}},
    )
    result = add_search(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for stem in ("item", "product"):
        crud = project / "app" / "crud" / f"{stem}.py"
        assert "async def search" in crud.read_text(), f"{stem} must be searched"


# ---------------------------------------------------------------------------
# Route insertion ordering — _patch_routes (L257 / L258 / L260 / L264)
# ---------------------------------------------------------------------------


def test_logic_search_routes_inserted_before_id_route():
    """L257 (regex anchor) + L258 (id_route_match is not None) + L264 (Add order).

    The /search and /autocomplete routes MUST be registered before the
    ``@router.get("/{id}")`` route so FastAPI does not treat 'search' as an id.
      - IsNot->Is on L258 would take the else-branch (append at end), landing the
        search block AFTER /{id}.
      - The L264 Add (src[:pos] + additions + src[pos:]) ordering being broken
        would also misplace it.
    """
    project = create_fixture_project(name="search_logic_order")
    add_search(ToolInput(project_dir=str(project)))
    src = (project / "app" / "api" / "routes" / "item.py").read_text()
    i_search = src.find('@router.get("/search"')
    i_auto = src.find('@router.get("/autocomplete"')
    i_id = src.find('@router.get("/{id}"')
    assert i_search != -1 and i_auto != -1 and i_id != -1
    assert i_search < i_id, "/search route must precede the /{id} route"
    assert i_auto < i_id, "/autocomplete route must precede the /{id} route"


def test_logic_search_import_precedes_search_route():
    """L264 BinOp Add ordering — the import header lands inside the inserted block,
    which itself lands before /{id}; the crud-search import must precede the route
    decorator that uses it.
    """
    project = create_fixture_project(name="search_logic_import_order")
    add_search(ToolInput(project_dir=str(project)))
    src = (project / "app" / "api" / "routes" / "item.py").read_text()
    i_import = src.find("from app.crud.item import search as _crud_search")
    i_route = src.find('@router.get("/search"')
    assert i_import != -1, "search import header must be emitted"
    assert i_route != -1
    assert i_import < i_route, "the _crud_search import must precede the /search route"


def test_logic_search_block_lands_after_existing_routes():
    """L260 (``pos > 0 and src[pos-1] == '\\n'`` walk-back) + L257 anchor.

    The block is spliced at the start of the /{id} decorator line, so the
    pre-existing list route stays first and the inserted block lands between the
    list route and /{id}.
    """
    project = create_fixture_project(name="search_logic_after_list")
    add_search(ToolInput(project_dir=str(project)))
    src = (project / "app" / "api" / "routes" / "item.py").read_text()
    i_list = src.find('@router.get("/", response_model')
    i_search = src.find('@router.get("/search"')
    i_id = src.find('@router.get("/{id}"')
    assert i_list < i_search < i_id, "ordering must be list -> search -> {id}"
    # The splice must not leave a route decorator glued onto the previous line.
    pos = src.find('@router.get("/search"')
    assert src[pos - 1] == "\n", "inserted block must start on its own line (newline-walked)"


# ---------------------------------------------------------------------------
# Migration wiring — _write_migration (L282)
# ---------------------------------------------------------------------------


def test_logic_migration_down_revision_is_current_head():
    """L282 ``find_migration_head(versions_dir) or "0001_initial"`` (Or->And).

    The fixture already has a real head (0002_baseline_schema). The new migration
    must chain off it:
      - Or: head is truthy -> down_revision = '0002_baseline_schema'.
      - And: truthy head AND '0001_initial' -> '0001_initial' (wrong parent,
        breaks the chain).
    """
    project = create_fixture_project(name="search_logic_down_rev")
    versions_dir = project / "alembic" / "versions"
    head_before = find_migration_head(versions_dir)
    assert head_before == "0002_baseline_schema", "fixture precondition"
    add_search(ToolInput(project_dir=str(project)))
    migration = next(versions_dir.glob("*search_idx*"))
    text = migration.read_text()
    assert f'down_revision = "{head_before}"' in text, (
        "migration must chain off the real current head, not the 0001 fallback"
    )
    assert 'down_revision = "0001_initial"' not in text


def test_logic_migration_generated_expr_joins_all_fields():
    """L283 ``||`` join of setweight parts — N text fields produce N setweight
    parts joined by (N-1) '||'. With two fields there must be exactly one '||'
    and two setweight() calls in the generated tsvector expression.
    """
    project = create_fixture_project(
        name="search_logic_genexpr",
        models={"Item": {"title": "str", "description": "str"}},
    )
    add_search(ToolInput(project_dir=str(project)))
    versions_dir = project / "alembic" / "versions"
    migration = next(versions_dir.glob("*search_idx*"))
    text = migration.read_text()
    assert text.count("setweight") == 2, "two text fields -> two setweight parts"
    assert text.count("||") == 1, "two parts must be joined by exactly one ||"


# ---------------------------------------------------------------------------
# Schema import dedup — _patch_schema (L227)
# ---------------------------------------------------------------------------


def test_logic_schema_import_not_duplicated():
    """L227 ``if missing not in src`` (NotIn->In).

    The generated schema already imports ConfigDict and Field. The dedup guard
    must NOT re-add them:
      - NotIn: 'ConfigDict' already present -> skip add (correct).
      - In: present -> re-run the replace, duplicating the import names.
    """
    project = create_fixture_project(name="search_logic_schema_dedup")
    add_search(ToolInput(project_dir=str(project)))
    schema = (project / "app" / "schemas" / "item.py").read_text()
    assert schema.count("from pydantic import BaseModel, ConfigDict, Field") == 1
    # No malformed double-name import like "BaseModel, ConfigDict, ConfigDict".
    assert "ConfigDict, ConfigDict" not in schema
    assert "Field, Field" not in schema


# ---------------------------------------------------------------------------
# Route header dedup — _patch_routes new_imports (L251)
# ---------------------------------------------------------------------------


def test_logic_route_header_imports_not_duplicated():
    """L251 ``line.strip() not in src`` (NotIn->In) — header lines already in the
    file must be filtered out so they are not re-emitted.

    HTTPException is already imported by the scaffolded route file. After patching,
    'from fastapi import HTTPException' must appear at most once (the dedup kept
    it out of the new header block).
    """
    project = create_fixture_project(name="search_logic_route_dedup")
    before = (project / "app" / "api" / "routes" / "item.py").read_text()
    # Scaffold imports HTTPException via the combined fastapi import line.
    add_search(ToolInput(project_dir=str(project)))
    after = (project / "app" / "api" / "routes" / "item.py").read_text()
    # The standalone header line must not be added when its content already exists.
    assert after.count("from app.crud.item import search as _crud_search") == 1
    # The crud-search import is genuinely new -> exactly one occurrence.
    assert before.count("from app.crud.item import search as _crud_search") == 0


# ---------------------------------------------------------------------------
# Idempotency on already-installed (L138 / L289 / L46 behaviour boundary)
# ---------------------------------------------------------------------------


def test_logic_second_run_no_op_when_marker_present():
    """L140 'Full-text search helpers' marker drives _search_already_installed.

    First run injects the marker into a CRUD file; the second run must detect it
    and return no_op, creating/modifying nothing.
    """
    project = create_fixture_project(name="search_logic_idem")
    r1 = add_search(ToolInput(project_dir=str(project)))
    assert r1.status == "success"
    crud = (project / "app" / "crud" / "item.py").read_text()
    assert "Full-text search helpers" in crud, "marker must be emitted on first run"
    r2 = add_search(ToolInput(project_dir=str(project)))
    assert r2.status == "no_op"
    assert not r2.files_created
    assert not r2.files_modified


def test_logic_emitted_project_test_created_and_files_exist():
    """L288-294 _emit_project_test + L90 files_created accumulation.

    The tool emits tests/test_add_search_emitted.py and lists it in files_created;
    every created path must resolve to a real file on disk.
    """
    project = create_fixture_project(name="search_logic_emit_test")
    result = add_search(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    emitted_rel = "tests/test_add_search_emitted.py"
    assert any(p.endswith(emitted_rel) for p in result.files_created), (
        "emitted project test must be reported in files_created"
    )
    for p in result.files_created:
        assert Path(p).exists(), f"reported created file missing: {p}"
