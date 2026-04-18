"""Structural tests for TOOL-113 add_compliance_engine.

Generates real fixture projects, runs the tool, and verifies all
completeness criteria from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_compliance_engine.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_compliance_engine.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_compliance_engine import add_compliance_engine
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# CC-01 — status='success'
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="comp_t01")
    result = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02 — idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="comp_t02")
    r1 = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="comp_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_compliance_engine(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files_created_count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 6 files."""
    project_dir = create_fixture_project(name="comp_t04")
    result = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files_modified_count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init, routes init, requirements)."""
    project_dir = create_fixture_project(name="comp_t05")
    result = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="comp_t06")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="comp_t07")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """COMPLIANCE_* settings exist inside the Settings class body."""
    project_dir = create_fixture_project(name="comp_t08")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["COMPLIANCE_ENABLED", "COMPLIANCE_RETENTION_DEFAULT_DAYS",
                  "COMPLIANCE_ENCRYPTION_KEY"]:
        assert field in content, f"Config field {field} missing from config.py"
    for line in content.splitlines():
        if "COMPLIANCE_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"COMPLIANCE_ENABLED not inside class body: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09 — models/__init__ patched
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """ComplianceEvent is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="comp_t09")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert "ComplianceEvent" in models_init.read_text(), (
        "ComplianceEvent not registered in models/__init__.py"
    )


# ---------------------------------------------------------------------------
# CC-10 — routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """Compliance router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="comp_t10")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        assert "compliance" in routes_init.read_text().lower(), (
            "Compliance router not registered in routes/__init__.py"
        )


# ---------------------------------------------------------------------------
# CC-11+ — domain-specific tests
# ---------------------------------------------------------------------------

def test_compliance_engine_file_exists() -> None:
    """app/core/compliance_engine.py exists with ComplianceEngine class."""
    project_dir = create_fixture_project(name="comp_t11")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "core" / "compliance_engine.py"
    assert engine_file.exists(), "compliance_engine.py not created"
    content = engine_file.read_text()
    assert "ComplianceEngine" in content, "ComplianceEngine class not found"
    assert "encrypt_field" in content, "encrypt_field not found"
    assert "decrypt_field" in content, "decrypt_field not found"


def test_compliance_event_model_created() -> None:
    """app/models/compliance_event.py exists with ComplianceEvent class."""
    project_dir = create_fixture_project(name="comp_t12")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "compliance_event.py"
    assert model_file.exists(), "compliance_event.py not created"
    content = model_file.read_text()
    assert "class ComplianceEvent" in content, "ComplianceEvent model not found"
    assert "event_type" in content, "event_type column missing"


def test_compliance_crud_created() -> None:
    """app/crud/compliance.py exists with async helpers."""
    project_dir = create_fixture_project(name="comp_t13")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "compliance.py"
    assert crud_file.exists(), "crud/compliance.py not created"
    content = crud_file.read_text()
    assert content.count("async def ") >= 4, "Expected >= 4 async CRUD helpers"


def test_erasure_route_present() -> None:
    """app/api/routes/compliance.py contains erasure endpoint."""
    project_dir = create_fixture_project(name="comp_t14")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "compliance.py"
    assert route_file.exists(), "compliance routes not created"
    content = route_file.read_text()
    assert "erasure" in content.lower(), "Erasure endpoint not found in compliance routes"
    assert "ErasureCertificate" in content, "ErasureCertificate response not found"


def test_retention_worker_created() -> None:
    """app/workers/retention_worker.py exists with async scheduling logic."""
    project_dir = create_fixture_project(name="comp_t15")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "retention_worker.py"
    assert worker_file.exists(), "retention_worker.py not created"
    content = worker_file.read_text()
    assert "schedule_retention_worker" in content, "schedule_retention_worker not found"
    assert "asyncio.sleep" in content, "asyncio.sleep not found in worker"


def test_fernet_lazy_import() -> None:
    """cryptography/Fernet is NOT imported at module top level in compliance_engine.py."""
    project_dir = create_fixture_project(name="comp_t16")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "core" / "compliance_engine.py"
    tree = ast.parse(engine_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "cryptography" not in alias.name, (
                    f"cryptography imported at top level: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or "cryptography" not in node.module, (
                "cryptography imported at top level via 'from'"
            )


def test_article30_route_present() -> None:
    """compliance routes include GDPR Article 30 endpoint."""
    project_dir = create_fixture_project(name="comp_t17")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "compliance.py"
    content = route_file.read_text()
    assert "article30" in content.lower(), "Article 30 endpoint not found"


def test_soc2_evidence_route_present() -> None:
    """compliance routes include SOC2 evidence export endpoint."""
    project_dir = create_fixture_project(name="comp_t18")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "compliance.py"
    content = route_file.read_text()
    assert "soc2" in content.lower() or "evidence" in content.lower(), (
        "SOC2 evidence endpoint not found"
    )


def test_requirements_cryptography() -> None:
    """requirements.txt contains cryptography."""
    project_dir = create_fixture_project(name="comp_t19")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    assert "cryptography" in requirements.read_text(), (
        "cryptography dependency not added"
    )


# ---------------------------------------------------------------------------
# CC-N-1 — execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="comp_t_time")
    result = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps_present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """Result includes next_steps with alembic upgrade head."""
    project_dir = create_fixture_project(name="comp_t_ns")
    result = add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    joined = " ".join(result.next_steps).lower()
    assert "alembic" in joined, "alembic step missing from next_steps"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="comp_t_last")
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    add_compliance_engine(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_models_init_patched,
        test_routes_registered,
        test_compliance_engine_file_exists,
        test_compliance_event_model_created,
        test_compliance_crud_created,
        test_erasure_route_present,
        test_retention_worker_created,
        test_fernet_lazy_import,
        test_article30_route_present,
        test_soc2_evidence_route_present,
        test_requirements_cryptography,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-113 add_compliance_engine: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
