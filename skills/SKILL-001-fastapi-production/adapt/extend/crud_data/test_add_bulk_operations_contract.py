"""Generic tool-contract mutation coverage for add_bulk_operations.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_bulk_operations.py in the mutation
runner: ``--tests test_add_bulk_operations.py test_add_bulk_operations_contract.py``.
"""

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_bulk_operations import (
    _discover_models,
    _ensure_pydantic_imports,
    add_bulk_operations,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations

    for check in UNIVERSAL_CHECKS:
        check(add_bulk_operations, "add_bulk_operations")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills. Each test below targets the bespoke logic of
# add_bulk_operations (NOT the shared preamble, which the generic contract
# above already covers). Survivors referenced by source line.
# ---------------------------------------------------------------------------


def test_ensure_pydantic_imports_adds_field_validator():
    """L222 NotIn->In: ``if "field_validator" not in src`` must add field_validator.

    A schema that imports only ``BaseModel`` must come out with
    ``field_validator`` (and friends) added. Flipping the guard to ``in``
    skips the insert and the bulk-update validator import would be missing.
    """
    out = _ensure_pydantic_imports("from pydantic import BaseModel\n")
    import_line = out.splitlines()[0]
    assert "field_validator" in import_line, "field_validator import must be added"


def test_ensure_pydantic_imports_adds_configdict_when_only_field_validator():
    """L230 NotIn->In: ``if "ConfigDict" not in src`` must add ConfigDict.

    Source already importing ``field_validator`` (so L222 is skipped) but
    lacking ``ConfigDict`` must gain ``ConfigDict``. Flipping to ``in`` skips
    the insert and the emitted ``model_config = ConfigDict(...)`` breaks.
    """
    out = _ensure_pydantic_imports("from pydantic import BaseModel, field_validator\n")
    import_line = out.splitlines()[0]
    assert "ConfigDict" in import_line, "ConfigDict import must be added"


def test_ensure_pydantic_imports_adds_field_when_absent():
    """L234 NotIn->In: ``if ", Field" not in src and "Field" not in src`` adds Field.

    Source with ConfigDict + field_validator but no ``Field`` reference must
    gain ``Field``. Flipping either ``not in`` to ``in`` skips the insert.
    """
    out = _ensure_pydantic_imports("from pydantic import BaseModel, ConfigDict, field_validator\n")
    import_line = out.splitlines()[0]
    assert "Field" in import_line, "Field import must be added when absent"


def test_ensure_pydantic_imports_does_not_duplicate_field_when_referenced():
    """L234 BoolOp And->Or: both clauses must hold before Field is re-imported.

    When ``Field`` is already referenced in the body (so ``"Field" not in src``
    is False) the import must NOT be touched. Flipping ``and`` to ``or`` would
    fire on the still-True ``", Field" not in src`` clause and inject a
    duplicate ``Field`` into the import line.
    """
    src = "from pydantic import BaseModel, ConfigDict, field_validator\nx = Field(1)\n"
    out = _ensure_pydantic_imports(src)
    import_line = out.splitlines()[0]
    assert "Field" not in import_line, (
        "Field must NOT be added to the import when already referenced (and-guard)"
    )


def test_discover_models_skips_model_without_route():
    """L177 BoolOp Or->And: a model whose stem has no route file is skipped.

    ``if stem in _SKIP_MODELS or stem not in available_routes: continue``.
    A model file ``widget.py`` (class ``Widget``) with no ``routes/widget.py``
    must be excluded. Flipping ``or`` to ``and`` would require BOTH clauses,
    so the routeless Widget would NOT be skipped and leak into discovery.
    """
    project = create_fixture_project(name="bulk_contract_l177")
    widget = project / "app" / "models" / "widget.py"
    widget.write_text(
        'from app.models.base import Base\n\n\nclass Widget(Base):\n    __tablename__ = "widgets"\n'
    )
    discovered = _discover_models(project / "app")
    assert "Item" in discovered, "Item (which has a route) must be discovered"
    assert "Widget" not in discovered, (
        "Widget has no route file and must be skipped (or-guard); "
        "an and-guard would leak it into discovery"
    )


def test_missing_scaffoldable_prereq_is_autocreated_and_reported():
    """L54 UnaryNot + L64 BoolOp Or->And on the auto-scaffold path.

    Deleting ``app/models/__init__.py`` (a scaffoldable prereq) means:
      * L54 ``auto_scaffold=not inp.dry_run`` must be True on a normal run so
        the prereq is recreated and the tool still succeeds. Flipping
        ``not`` makes auto_scaffold False -> prereq_errors -> status error.
      * L64 ``files_created = list(scaffolded or [])`` must seed files_created
        with the scaffolded path. Flipping ``or`` to ``and`` yields
        ``[x] and [] == []`` and the scaffolded file would be dropped.
    """
    project = create_fixture_project(name="bulk_contract_l54_l64")
    (project / "app" / "models" / "__init__.py").unlink()
    result = add_bulk_operations(ToolInput(project_dir=str(project)))
    assert result.status == "success", (
        f"missing scaffoldable prereq must auto-scaffold (L54), got {result.status}: {result.error}"
    )
    assert any(p.endswith("app/models/__init__.py") for p in result.files_created), (
        "the auto-scaffolded prereq must appear in files_created (L64 or-guard)"
    )


def test_existing_idempotency_file_is_merged_not_replaced():
    """L102 NotIn->In: merge IdempotencyCache into a pre-existing idempotency.py.

    A project that already has ``app/core/idempotency.py`` WITHOUT
    ``IdempotencyCache`` must get the cache merged in while the original
    content is preserved. Flipping ``not in`` to ``in`` skips the merge so
    IdempotencyCache never lands.
    """
    project = create_fixture_project(name="bulk_contract_l102")
    idem = project / "app" / "core" / "idempotency.py"
    idem.parent.mkdir(parents=True, exist_ok=True)
    idem.write_text("# pre-existing helper\nMARKER_FOO = 1\n")
    result = add_bulk_operations(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    text = idem.read_text()
    assert "IdempotencyCache" in text, "IdempotencyCache must be merged into the existing file"
    assert "MARKER_FOO = 1" in text, "original content must be preserved (append, not replace)"


def test_migration_chains_off_real_head_not_initial_fallback():
    """L122 BoolOp Or->And: down_revision is the real migration head.

    ``down_rev = find_migration_head(versions_dir) or "0001_initial"``. The
    fixture ships a baseline migration, so the head is a real revision (not
    ``0001_initial``). Flipping ``or`` to ``and`` yields
    ``<real_head> and "0001_initial" == "0001_initial"``, breaking the chain.
    """
    project = create_fixture_project(name="bulk_contract_l122")
    add_bulk_operations(ToolInput(project_dir=str(project)))
    migs = list((project / "alembic" / "versions").glob("*bulk_ops_index*"))
    assert migs, "bulk ops index migration must be created"
    mig_text = migs[0].read_text()
    down_line = next(ln for ln in mig_text.splitlines() if ln.strip().startswith("down_revision"))
    assert "0001_initial" not in down_line, (
        "down_revision must chain off the real head, not the 0001_initial fallback (or-guard)"
    )
    assert "0002_baseline_schema" in down_line, (
        "down_revision must be the discovered migration head"
    )


def test_main_import_lands_immediately_after_last_from_app():
    """L295 NotEq->Eq + L296 BinOp Add->Sub: import placement in main.py.

    The idempotency import must be inserted at ``last_from_app + 1`` (right
    after the final ``from app.`` import).
      * L296 ``+ 1`` -> ``- 1`` would place the import one line too early.
      * L295 ``if last_from_app != -1`` -> ``== -1`` would take the legacy
        logging-anchor branch and place the import elsewhere entirely.
    """
    project = create_fixture_project(name="bulk_contract_l295_l296")
    add_bulk_operations(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "main.py").read_text().splitlines()
    idem_imp = next(i for i, ln in enumerate(lines) if "from app.core.idempotency import" in ln)
    last_from_app = max(
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and "idempotency" not in ln
    )
    assert idem_imp == last_from_app + 1, (
        "idempotency import must land immediately after the last from-app import "
        "(L295 != -1 branch, L296 +1 offset)"
    )


def test_main_lifespan_startup_before_yield_shutdown_after():
    """L335 BinOp Add->Sub: shutdown call is spliced AFTER the yield.

    The startup ``init_idempotency_cache(...)`` lives before ``yield`` and the
    ``await close_idempotency_cache()`` shutdown lives after it
    (``shutdown_at = yield_idx + len(startup_lines) + 1``). Flipping the
    trailing ``+ 1`` shifts the shutdown block on top of the startup/yield.
    """
    project = create_fixture_project(name="bulk_contract_l335")
    add_bulk_operations(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "main.py").read_text().splitlines()
    yield_i = next(i for i, ln in enumerate(lines) if ln.strip() == "yield")
    init_i = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("init_idempotency_cache(")
    )
    close_i = next(i for i, ln in enumerate(lines) if "await close_idempotency_cache()" in ln)
    assert init_i < yield_i, "startup init must run before yield"
    assert close_i > yield_i, "shutdown close must run after yield (L335 +1 offset)"


def test_main_os_alias_imported_exactly_once():
    """L324 BoolOp/NotIn guard: the ``import os as _os`` alias is added once.

    ``if os_import not in src and "import os as _os" not in "\\n".join(lines)``
    gates the single insertion of the REDIS_URL os alias. Any flip of this
    guard either skips the insert (alias missing, count 0) or double-inserts.
    """
    project = create_fixture_project(name="bulk_contract_l324")
    add_bulk_operations(ToolInput(project_dir=str(project)))
    lines = (project / "app" / "main.py").read_text().splitlines()
    os_aliases = [ln for ln in lines if "import os as _os" in ln]
    assert len(os_aliases) == 1, (
        f"the os alias must be imported exactly once, found {len(os_aliases)}"
    )


def test_emitted_project_test_written_into_existing_tests_dir():
    """L365 BoolLiteral True->False: mkdir(exist_ok=True) over a pre-existing dir.

    The fixture already ships a ``tests/`` directory. ``_emit_project_test``
    calls ``(project / "tests").mkdir(parents=True, exist_ok=True)``. Flipping
    ``exist_ok`` to False would raise ``FileExistsError`` on the existing dir
    and the tool would not succeed / emit the test.
    """
    project = create_fixture_project(name="bulk_contract_l365")
    assert (project / "tests").exists(), "fixture must ship a tests/ dir for this kill"
    result = add_bulk_operations(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    assert any(
        p.endswith("tests/test_add_bulk_operations_emitted.py") for p in result.files_created
    ), "emitted project test must be written into the pre-existing tests/ dir (exist_ok=True)"


def test_main_fallback_appends_when_no_lifespan():
    """L358 BinOp Add->Sub: EOF-append fallback for a main.py with no ``yield``.

    For a non-standard main.py with no ``lifespan`` (no ``yield`` line), the
    patcher concatenates the rendered fallback to the file body:
    ``"\\n".join(lines).rstrip("\\n") + fallback``. This ``+`` is string
    concatenation; flipping it to ``-`` raises TypeError and the tool crashes.
    The original body must be preserved and the fallback appended after it.
    """
    project = create_fixture_project(name="bulk_contract_l358")
    main_file = project / "app" / "main.py"
    main_file.write_text(
        "from fastapi import FastAPI\nfrom app.core.config import settings\n\napp = FastAPI()\n"
    )
    result = add_bulk_operations(ToolInput(project_dir=str(project)))
    assert result.status == "success", (
        f"fallback path must succeed, got {result.status}: {result.error}"
    )
    text = main_file.read_text()
    app_idx = text.index("app = FastAPI()")
    init_idx = text.index("init_idempotency_cache(")
    assert init_idx > app_idx, (
        "fallback must be appended AFTER the original body (L358 string concat)"
    )
    assert "added by add_bulk_operations tool" in text, "fallback comment must be present"
