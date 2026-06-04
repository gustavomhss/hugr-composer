"""Generic tool-contract mutation coverage for add_data_export.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_export.py in the mutation
runner: ``--tests test_add_data_export.py test_add_data_export_contract.py``.

The ``test_mut_*`` functions below target add_data_export's TOOL-SPECIFIC logic
(survivors the generic preamble checks do not reach): prerequisite/dry_run gating,
the scaffolded-files fold, the per-core-module idempotency guards, the route skip
guard, the migration down_revision chaining, requirements dedup, and the
``_discover_models`` base-class detection.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_data_export import add_data_export
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_data_export import add_data_export

    for check in UNIVERSAL_CHECKS:
        check(add_data_export, "add_data_export")


# ---------------------------------------------------------------------------
# L65 UnaryNot (auto_scaffold=not inp.dry_run) + L70 BinOp (Add in the prereq
# error string).  A bare project missing prerequisites, run with dry_run=True,
# must NOT auto-scaffold (because ``not dry_run`` is False) and therefore must
# return status="error".  If ``not`` is dropped (L65), dry_run would scaffold
# the prereqs and fall through to a success dry-run return.  The error string
# itself is built with ``"..." + "\n".join(...)`` (L70); flipping ``+`` to ``-``
# raises TypeError when this same path executes.
# ---------------------------------------------------------------------------
def test_mut_dry_run_missing_prereqs_errors_no_autoscaffold():
    tmp = Path(tempfile.mkdtemp())
    proj = tmp / "bare"
    (proj / "app" / "models").mkdir(parents=True)
    (proj / "app" / "models" / "item.py").write_text(
        "from app.models.base import Base\nclass Item(Base):\n    pass\n"
    )
    (proj / "app" / "api" / "routes").mkdir(parents=True)
    (proj / "app" / "api" / "routes" / "item.py").write_text("# route\n")

    result = add_data_export(ToolInput(project_dir=str(proj), dry_run=True))

    assert result.status == "error", (
        "dry_run on a project missing prerequisites must error without "
        "auto-scaffolding (auto_scaffold=not dry_run)"
    )
    assert result.error is not None
    assert "Prerequisites not met:" in result.error


# ---------------------------------------------------------------------------
# L75 BoolOp (list(scaffolded or [])).  When a prerequisite is auto-scaffolded
# (here: a deleted app/core/config.py), ``ensure_prerequisites`` returns the
# recreated path in ``scaffolded`` and the tool seeds ``files_created`` with it
# via ``list(scaffolded or [])``.  Flipping ``or`` to ``and`` yields
# ``scaffolded and []`` == ``[]`` for a non-empty scaffolded list, silently
# dropping the auto-scaffolded files from files_created.
# ---------------------------------------------------------------------------
def test_mut_scaffolded_files_kept_in_files_created():
    project_dir = create_fixture_project(name="mut_export_scaffold_fold")
    (project_dir / "app" / "core" / "config.py").unlink()

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert any(p.endswith("app/core/config.py") for p in result.files_created), (
        "auto-scaffolded config.py must appear in files_created (list(scaffolded or []))"
    )


# ---------------------------------------------------------------------------
# L115 / L118 / L125 UnaryNot — per-core-module idempotency guards
# (storage.py, model_registry.py, jobs/__init__.py).  Each is written only
# ``if not <file>.exists()``.  Pre-seed each with sentinel content; a correct
# run leaves them untouched (and omits them from files_created).  Dropping the
# ``not`` inverts the guard, overwriting the existing files.
# ---------------------------------------------------------------------------
def test_mut_existing_core_modules_not_overwritten():
    project_dir = create_fixture_project(name="mut_export_idem_guards")
    storage = project_dir / "app" / "core" / "storage.py"
    registry = project_dir / "app" / "core" / "model_registry.py"
    jobs_dir = project_dir / "app" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs_init = jobs_dir / "__init__.py"

    storage.write_text("# SENTINEL_STORAGE")
    registry.write_text("# SENTINEL_REGISTRY")
    jobs_init.write_text("# SENTINEL_JOBSINIT")

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    # Pre-existing files must be preserved verbatim (guard = "if not exists").
    assert storage.read_text() == "# SENTINEL_STORAGE", "L115: storage.py overwritten"
    assert registry.read_text() == "# SENTINEL_REGISTRY", "L118: model_registry.py overwritten"
    assert jobs_init.read_text() == "# SENTINEL_JOBSINIT", "L125: jobs/__init__.py overwritten"
    # And they must not be reported as newly created.
    assert not any(p.endswith("app/core/storage.py") for p in result.files_created)
    assert not any(p.endswith("app/core/model_registry.py") for p in result.files_created)
    assert not any(p.endswith("app/jobs/__init__.py") for p in result.files_created)


# ---------------------------------------------------------------------------
# L136 BoolOp — route skip guard:
#   ``if "/export" in src or "StreamingResponse" in src: continue``.
# A route already carrying ONE marker (StreamingResponse) but not the other
# (/export) must be skipped.  Flipping ``or`` to ``and`` requires BOTH markers
# to skip, so this file would be (re)patched.
# ---------------------------------------------------------------------------
def test_mut_route_with_one_marker_is_skipped():
    project_dir = create_fixture_project(name="mut_export_route_skip")
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    sentinel = "# StreamingResponse marker only, no slash-export\n"
    route_file.write_text(sentinel)

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert route_file.read_text() == sentinel, (
        "route carrying StreamingResponse must be skipped (or-guard), not patched"
    )
    assert not any(p.endswith("routes/item.py") for p in result.files_modified)


# ---------------------------------------------------------------------------
# L149 BoolOp — migration down_revision chaining:
#   ``down_rev = find_migration_head(versions_dir) or "0001_initial"``.
# The fixture has a real HEAD (0002_baseline_schema), so the emitted migration
# must chain off it, NOT the literal "0001_initial".  Flipping ``or`` to ``and``
# yields ``<truthy head> and "0001_initial"`` == "0001_initial", a wrong parent.
# ---------------------------------------------------------------------------
def test_mut_migration_chains_off_real_head():
    project_dir = create_fixture_project(name="mut_export_migration_head")

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    mig = project_dir / "alembic" / "versions" / "0006_add_export_jobs.py"
    assert mig.exists()
    text = mig.read_text()
    assert 'down_revision = "0002_baseline_schema"' in text, (
        "migration must chain off the real HEAD, not the '0001_initial' fallback"
    )
    assert 'down_revision = "0001_initial"' not in text


# ---------------------------------------------------------------------------
# L165 / L167 / L169 Compare NotIn — requirements.txt dedup:
#   pyarrow / xlsxwriter are absent in the fixture requirements -> appended once.
#   redis is ALREADY present -> NOT re-appended.
# Flipping ``not in`` to ``in`` inverts each: pyarrow/xlsxwriter would be skipped
# (L165/L167) and redis would be duplicated (L169).
# ---------------------------------------------------------------------------
def test_mut_requirements_dedup_notin():
    project_dir = create_fixture_project(name="mut_export_requirements")
    req = project_dir / "requirements.txt"
    assert "redis" in req.read_text(), "fixture precondition: redis already present"

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    text = req.read_text()
    # L165 / L167: absent deps must now be present (exactly once).
    assert text.count("pyarrow>=17.0.0") == 1, "L165: pyarrow not appended"
    assert text.count("xlsxwriter>=3.2.0") == 1, "L167: xlsxwriter not appended"
    # L169: redis was already present, so the tool must NOT add its own line.
    assert "redis[hiredis]>=5.0.0" not in text, (
        "L169: redis re-appended despite already being present"
    )


# ---------------------------------------------------------------------------
# L239 BoolOp — _discover_models skip guard:
#   ``if stem in _SKIP_MODELS or stem not in available_routes: continue``.
# A model whose stem IS in _SKIP_MODELS (e.g. "tenant") but DOES have a route
# must be skipped.  Flipping ``or`` to ``and`` only skips when BOTH hold, so the
# skip-listed model with a route would wrongly get an export endpoint.
# ---------------------------------------------------------------------------
def test_mut_skip_listed_model_with_route_excluded():
    project_dir = create_fixture_project(name="mut_export_skip_model")
    (project_dir / "app" / "models" / "tenant.py").write_text(
        'from app.models.base import Base\nclass Tenant(Base):\n    __tablename__ = "tenant"\n'
    )
    tenant_route = project_dir / "app" / "api" / "routes" / "tenant.py"
    tenant_route.write_text("from fastapi import APIRouter\nrouter = APIRouter()\n")

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert "Tenant" not in " ".join(result.notes or []), (
        "skip-listed model 'tenant' must not be discovered"
    )
    assert "/export" not in tenant_route.read_text(), (
        "skip-listed model's route must not receive an export endpoint"
    )


# ---------------------------------------------------------------------------
# L250 BoolOp — base-class detection (ast.Name branch):
#   ``isinstance(b, ast.Name) and b.id == "Base"``.
# A model whose base is a plain Name but NOT "Base" must NOT be discovered.
# Flipping ``and`` to ``or`` makes ANY Name base qualify.
# ---------------------------------------------------------------------------
def test_mut_non_base_name_parent_not_discovered():
    project_dir = create_fixture_project(name="mut_export_nonbase_name")
    (project_dir / "app" / "models" / "widget.py").write_text(
        "class SomethingElse:\n    pass\n\n\nclass Widget(SomethingElse):\n    pass\n"
    )
    widget_route = project_dir / "app" / "api" / "routes" / "widget.py"
    widget_route.write_text("from fastapi import APIRouter\nrouter = APIRouter()\n")

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert "Widget" not in " ".join(result.notes or []), (
        "model whose base is a non-Base Name must not be discovered (and-guard)"
    )
    assert "/export" not in widget_route.read_text()


# ---------------------------------------------------------------------------
# L251 Compare Eq — base-class detection (ast.Attribute branch):
#   ``isinstance(b, ast.Attribute) and b.attr == "Base"``.
# A model using an attribute-style base (``base.Base``) must be discovered.
# Flipping ``==`` to ``!=`` makes attribute-style Base classes invisible.
# ---------------------------------------------------------------------------
def test_mut_attribute_base_parent_discovered():
    project_dir = create_fixture_project(name="mut_export_attr_base")
    (project_dir / "app" / "models" / "gadget.py").write_text(
        'from app.models import base\nclass Gadget(base.Base):\n    __tablename__ = "gadget"\n'
    )
    gadget_route = project_dir / "app" / "api" / "routes" / "gadget.py"
    gadget_route.write_text("from fastapi import APIRouter\nrouter = APIRouter()\n")

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    assert "Gadget" in " ".join(result.notes or []), (
        "model with attribute-style base (base.Base) must be discovered (== guard)"
    )
    assert "/export" in gadget_route.read_text(), (
        "attribute-style Base model must receive an export endpoint"
    )


# ---------------------------------------------------------------------------
# L262 / L269 BoolLiteral — mkdir(parents=True, exist_ok=True) in ``_emit`` and
# ``_emit_project_test``.  In a real fixture, ``app/core`` and ``tests`` ALREADY
# exist before the run, so flipping ``exist_ok=True`` to ``False`` raises
# FileExistsError on the very first emit.  A plain success run that lands the
# core export module and the emitted project test therefore kills both.
# ---------------------------------------------------------------------------
def test_mut_emit_into_existing_dirs_succeeds():
    project_dir = create_fixture_project(name="mut_export_existing_dirs")
    assert (project_dir / "app" / "core").is_dir(), "precondition: app/core exists"
    assert (project_dir / "tests").is_dir(), "precondition: tests/ exists"

    result = add_data_export(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success"
    # _emit landed the core module into the pre-existing app/core (L262).
    assert (project_dir / "app" / "core" / "export.py").exists()
    assert any(p.endswith("app/core/export.py") for p in result.files_created)
    # _emit_project_test landed the emitted test into the pre-existing tests/ (L269).
    emitted = project_dir / "tests" / "test_add_data_export_emitted.py"
    assert emitted.exists()
    assert any(p.endswith("tests/test_add_data_export_emitted.py") for p in result.files_created)
