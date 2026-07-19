"""Structural tests for TOOL-076 add_sms_otp.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_sms_otp.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_sms_otp import add_sms_otp
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, sorted."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Raise AssertionError if any .py file under root fails ast.parse."""
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _run(name: str) -> tuple[Path, object]:
    """Create fixture project and apply the tool."""
    project_dir = create_fixture_project(name=name)
    result = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    return project_dir, result


def _max_func_loc(path: Path) -> tuple[int, str]:
    """Return (max_loc, func_name) for all functions in a Python file."""
    tree = ast.parse(path.read_text())
    max_loc = 0
    max_name = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hasattr(node, "end_lineno"):
                loc = node.end_lineno - node.lineno + 1
                if loc > max_loc:
                    max_loc = loc
                    max_name = node.name
    return max_loc, max_name


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    _, result = _run("t076_01_success")
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent_returns_no_op() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="t076_02_idempotent")
    r1 = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="t076_03_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_sms_otp(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: files_created has at least 5 entries and all exist."""
    project_dir, result = _run("t076_04_created_count")
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: files_modified has at least 2 entries and all exist."""
    project_dir, result = _run("t076_05_modified_count")
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All .py files in the project parse without SyntaxError."""
    project_dir, result = _run("t076_06_parse_all")
    assert result.status == "success"
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir, result = _run("t076_07_loc")
    assert result.status == "success"
    for path_str in result.files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            loc, name = _max_func_loc(p)
            assert loc <= 50, (
                f"Function {name!r} in {p.name} has {loc} LOC (max 50)"
            )


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: Config fields TWILIO_ACCOUNT_SID etc. patched with 4-space indent."""
    project_dir, _ = _run("t076_08_config")
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    for field in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "OTP_LENGTH", "OTP_EXPIRY_SECONDS"):
        assert field in content, f"Config field {field!r} not patched"
        for line in content.splitlines():
            if field in line:
                assert line.startswith("    "), (
                    f"Field {field!r} missing 4-space indent: {line!r}"
                )


# ---------------------------------------------------------------------------
# CC-09: models/__init__.py patched
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """CC-09: OtpCode imported in app/models/__init__.py."""
    project_dir, _ = _run("t076_09_models_init")
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert models_init.exists()
    content = models_init.read_text()
    assert "OtpCode" in content, "OtpCode not registered in models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10: routes/__init__.py patched
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: sms_auth router registered in app/routes/__init__.py."""
    project_dir, _ = _run("t076_10_routes_registered")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    assert routes_init.exists()
    content = routes_init.read_text()
    assert "sms_auth_router" in content, "sms_auth router not registered"
    assert "sms_auth" in content


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_otp_code_model_created() -> None:
    """CC-11: app/models/otp_code.py exists with OtpCode class."""
    project_dir, _ = _run("t076_11_model")
    model_file = project_dir / "app" / "models" / "otp_code.py"
    assert model_file.exists(), "otp_code.py not created"
    content = model_file.read_text()
    assert "class OtpCode" in content
    assert "phone" in content
    assert "code" in content
    assert "expires_at" in content
    assert "verified" in content


def test_otp_service_file_created() -> None:
    """CC-12: app/auth/sms_otp.py created with generate_otp, verify_otp, send_sms."""
    project_dir, _ = _run("t076_12_sms_otp_service")
    sms_file = project_dir / "app" / "auth" / "sms_otp.py"
    assert sms_file.exists(), "sms_otp.py not created"
    content = sms_file.read_text()
    assert "def generate_otp" in content
    assert "def verify_otp" in content
    assert "async def send_sms" in content


def test_twilio_is_lazy_import() -> None:
    """CC-13: twilio is imported lazily (inside function body) in sms_otp.py."""
    project_dir, _ = _run("t076_13_lazy_twilio")
    sms_file = project_dir / "app" / "auth" / "sms_otp.py"
    tree = ast.parse(sms_file.read_text())
    # Top-level imports should NOT include twilio
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "twilio" not in names and "twilio" not in module, (
                "twilio must not be a top-level import in sms_otp.py"
            )


def test_vonage_is_lazy_import() -> None:
    """CC-14: vonage is imported lazily (inside function body) in sms_otp.py."""
    project_dir, _ = _run("t076_14_lazy_vonage")
    sms_file = project_dir / "app" / "auth" / "sms_otp.py"
    tree = ast.parse(sms_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "vonage" not in names and "vonage" not in module, (
                "vonage must not be a top-level import in sms_otp.py"
            )


def test_rate_limiting_present() -> None:
    """CC-15: Route includes rate limit enforcement (OTP_RATE_LIMIT_MAX)."""
    project_dir, _ = _run("t076_15_rate_limit")
    routes_file = project_dir / "app" / "api" / "routes" / "sms_auth.py"
    content = routes_file.read_text()
    assert "rate" in content.lower() or "429" in content, (
        "Rate limiting not found in sms_auth.py"
    )
    assert "OTP_RATE_LIMIT_MAX" in content or "_RATE_LIMIT_MAX" in content


def test_schemas_file_created() -> None:
    """CC-16: app/schemas/otp.py created with OTP schemas."""
    project_dir, _ = _run("t076_16_schemas")
    schema_file = project_dir / "app" / "schemas" / "otp.py"
    assert schema_file.exists(), "schemas/otp.py not created"
    content = schema_file.read_text()
    assert "OtpSendRequest" in content
    assert "OtpVerifyRequest" in content
    assert "OtpVerifyResponse" in content


def test_routes_file_created() -> None:
    """CC-17: app/api/routes/sms_auth.py has send and verify endpoints."""
    project_dir, _ = _run("t076_17_routes")
    routes_file = project_dir / "app" / "api" / "routes" / "sms_auth.py"
    assert routes_file.exists(), "sms_auth.py not created"
    content = routes_file.read_text()
    assert "sms/send" in content or "send_otp" in content
    assert "sms/verify" in content or "verify_otp_code" in content


def test_migration_file_created() -> None:
    """CC-18: Alembic migration file 0076_add_sms_otp.py exists."""
    project_dir, _ = _run("t076_18_migration")
    migration_file = project_dir / "alembic" / "versions" / "0076_add_sms_otp.py"
    assert migration_file.exists(), "Migration file not created"
    content = migration_file.read_text()
    assert "otp_codes" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_verify_otp_uses_constant_time_comparison() -> None:
    """CC-19: verify_otp uses secrets.compare_digest for constant-time comparison."""
    project_dir, _ = _run("t076_19_constant_time")
    content = (project_dir / "app" / "auth" / "sms_otp.py").read_text()
    assert "compare_digest" in content, "verify_otp must use secrets.compare_digest"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer after a successful run."""
    _, result = _run("t076_20_timing")
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps includes 'alembic' and 'twilio'."""
    _, result = _run("t076_21_next_steps")
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined
    assert "twilio" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="t076_22_idempotent_parse")
    add_sms_otp(ToolInput(project_dir=str(project_dir)))
    add_sms_otp(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra domain test: SMS_PROVIDER config present
# ---------------------------------------------------------------------------

def test_sms_provider_config_patched() -> None:
    """CC-23: SMS_PROVIDER config field present in settings."""
    project_dir, _ = _run("t076_23_sms_provider")
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "SMS_PROVIDER" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent_returns_no_op,
        test_dry_run_writes_nothing,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_models_init_patched,
        test_routes_registered,
        test_otp_code_model_created,
        test_otp_service_file_created,
        test_twilio_is_lazy_import,
        test_vonage_is_lazy_import,
        test_rate_limiting_present,
        test_schemas_file_created,
        test_routes_file_created,
        test_migration_file_created,
        test_verify_otp_uses_constant_time_comparison,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_sms_provider_config_patched,
    ]

    passed = 0
    failed = 0
    errors: list[str] = []

    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
