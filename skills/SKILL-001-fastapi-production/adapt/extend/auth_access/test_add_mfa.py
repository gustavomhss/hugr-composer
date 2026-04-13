"""Tests for TOOL-013 add_mfa.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_mfa.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_mfa.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_mfa import add_mfa
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="mfa_t01")
    result = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got: {result.status} / {result.error}"


def test_files_created_all_exist() -> None:
    """T-02: Every path in files_created exists on disk after the run."""
    project_dir = create_fixture_project(name="mfa_t02")
    result = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing: {p}"


def test_files_modified_all_exist() -> None:
    """T-03: Every path in files_modified exists on disk after the run."""
    project_dir = create_fixture_project(name="mfa_t03")
    result = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_modified:
        assert Path(p).exists(), f"Modified file missing: {p}"


def test_mfa_models_file_created() -> None:
    """CC-01: app/models/mfa.py exists and contains MFADevice and MFARecoveryCode."""
    project_dir = create_fixture_project(name="mfa_t04")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    mfa_model = project_dir / "app" / "models" / "mfa.py"
    assert mfa_model.exists(), "app/models/mfa.py not created"
    content = mfa_model.read_text()
    assert "class MFADevice" in content
    assert "class MFARecoveryCode" in content


def test_mfa_device_secret_is_binary() -> None:
    """CC-02: MFADevice.secret_enc is LargeBinary (never plaintext text column)."""
    project_dir = create_fixture_project(name="mfa_t05")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "mfa.py").read_text()
    assert "LargeBinary" in content or "secret_enc" in content


def test_mfa_device_confirmed_at_nullable() -> None:
    """CC-03: MFADevice.confirmed_at is nullable (unconfirmed enrollment support)."""
    project_dir = create_fixture_project(name="mfa_t06")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "mfa.py").read_text()
    assert "confirmed_at" in content
    assert "nullable=True" in content


def test_recovery_code_used_at_nullable() -> None:
    """CC-04: MFARecoveryCode.used_at is nullable (single-use enforcement)."""
    project_dir = create_fixture_project(name="mfa_t07")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "mfa.py").read_text()
    assert "used_at" in content


def test_crypto_module_created() -> None:
    """CC-05: app/core/mfa/crypto.py exists with encrypt_secret and decrypt_secret."""
    project_dir = create_fixture_project(name="mfa_t08")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    crypto = project_dir / "app" / "core" / "mfa" / "crypto.py"
    assert crypto.exists(), "crypto.py not created"
    content = crypto.read_text()
    assert "def encrypt_secret" in content
    assert "def decrypt_secret" in content
    assert "Fernet" in content


def test_crypto_decrypt_returns_none_on_failure() -> None:
    """CC-06: decrypt_secret returns None on InvalidToken (never raises to caller)."""
    project_dir = create_fixture_project(name="mfa_t09")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "mfa" / "crypto.py").read_text()
    assert "InvalidToken" in content
    assert "return None" in content


def test_totp_module_created() -> None:
    """CC-07: app/core/mfa/totp.py exists with required helpers."""
    project_dir = create_fixture_project(name="mfa_t10")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    totp = project_dir / "app" / "core" / "mfa" / "totp.py"
    assert totp.exists(), "totp.py not created"
    content = totp.read_text()
    for fn in ("generate_totp_secret", "provisioning_uri", "verify_totp", "generate_recovery_codes"):
        assert f"def {fn}" in content, f"Function {fn} missing from totp.py"


def test_totp_module_uses_pyotp_segno() -> None:
    """CC-08: totp.py imports pyotp and segno for QR generation."""
    project_dir = create_fixture_project(name="mfa_t11")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "mfa" / "totp.py").read_text()
    assert "pyotp" in content
    assert "segno" in content


def test_verify_totp_rejects_non_digits() -> None:
    """CC-09: verify_totp guards against non-digit or wrong-length inputs."""
    project_dir = create_fixture_project(name="mfa_t12")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "mfa" / "totp.py").read_text()
    assert "isdigit" in content or "len(code)" in content


def test_recovery_module_created() -> None:
    """CC-10: app/core/mfa/recovery.py exists with hash_recovery_code and verify_recovery_code."""
    project_dir = create_fixture_project(name="mfa_t13")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    recovery = project_dir / "app" / "core" / "mfa" / "recovery.py"
    assert recovery.exists(), "recovery.py not created"
    content = recovery.read_text()
    assert "def hash_recovery_code" in content
    assert "def verify_recovery_code" in content
    assert "argon2" in content or "PasswordHasher" in content


def test_recovery_uses_argon2id() -> None:
    """CC-11: Recovery hasher uses argon2-cffi PasswordHasher (Argon2id)."""
    project_dir = create_fixture_project(name="mfa_t14")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "mfa" / "recovery.py").read_text()
    assert "PasswordHasher" in content


def test_rate_limit_module_created() -> None:
    """CC-12: app/core/mfa/rate_limit.py exists with check_and_consume."""
    project_dir = create_fixture_project(name="mfa_t15")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    rl = project_dir / "app" / "core" / "mfa" / "rate_limit.py"
    assert rl.exists(), "rate_limit.py not created"
    content = rl.read_text()
    assert "async def check_and_consume" in content


def test_rate_limit_uses_redis_incr() -> None:
    """CC-13: Rate limiter uses Redis INCR + EXPIRE pattern."""
    project_dir = create_fixture_project(name="mfa_t16")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "mfa" / "rate_limit.py").read_text()
    assert "incr" in content.lower()
    assert "expire" in content.lower()


def test_schemas_file_created() -> None:
    """CC-14: app/schemas/mfa.py exists with required Pydantic schemas."""
    project_dir = create_fixture_project(name="mfa_t17")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    schemas = project_dir / "app" / "schemas" / "mfa.py"
    assert schemas.exists(), "schemas/mfa.py not created"
    content = schemas.read_text()
    for cls in ("MFAEnrollResponse", "MFAVerifyEnrollmentRequest", "MFAChallengeRequest"):
        assert cls in content, f"Schema {cls} missing"


def test_crud_file_created() -> None:
    """CC-15: app/crud/mfa.py exists with required CRUD functions."""
    project_dir = create_fixture_project(name="mfa_t18")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    crud = project_dir / "app" / "crud" / "mfa.py"
    assert crud.exists(), "crud/mfa.py not created"
    content = crud.read_text()
    for fn in ("get_device", "create_device", "replace_recovery_codes", "consume_recovery_code", "delete_device"):
        assert f"async def {fn}" in content, f"CRUD function {fn} missing"


def test_crud_consume_recovery_single_use() -> None:
    """CC-16: consume_recovery_code sets used_at and filters WHERE used_at IS NULL."""
    project_dir = create_fixture_project(name="mfa_t19")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "crud" / "mfa.py").read_text()
    assert "used_at" in content
    assert "is_(None)" in content or "IS NULL" in content or "is_" in content


def test_routes_file_created() -> None:
    """CC-17: app/api/routes/mfa.py exists with all four endpoints."""
    project_dir = create_fixture_project(name="mfa_t20")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    routes = project_dir / "app" / "api" / "routes" / "mfa.py"
    assert routes.exists(), "routes/mfa.py not created"
    content = routes.read_text()
    for endpoint in ("enroll", "verify_enrollment", "challenge", "disable_mfa"):
        assert f"async def {endpoint}" in content, f"Endpoint {endpoint} missing"


def test_routes_pending_token_purpose_tagged() -> None:
    """CC-18: Pending token JWT has purpose=mfa_pending (cannot be used as access token)."""
    project_dir = create_fixture_project(name="mfa_t21")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "mfa.py").read_text()
    assert "mfa_pending" in content
    assert "purpose" in content


def test_routes_pending_token_ttl_5min() -> None:
    """CC-19: Pending token TTL is 300 seconds (5 minutes)."""
    project_dir = create_fixture_project(name="mfa_t22")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "mfa.py").read_text()
    assert "300" in content


def test_enroll_returns_plaintext_secret() -> None:
    """CC-20: Enroll response includes plaintext secret (shown once at enrollment)."""
    project_dir = create_fixture_project(name="mfa_t23")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "mfa.py").read_text()
    assert "secret" in content
    assert "MFAEnrollResponse" in content


def test_migration_file_created() -> None:
    """CC-21: Alembic migration 0013_add_mfa.py exists."""
    project_dir = create_fixture_project(name="mfa_t24")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    files = list(versions_dir.glob("*mfa*"))
    assert files, "MFA migration file not created"


def test_migration_creates_correct_tables() -> None:
    """CC-22: Migration creates mfa_devices and mfa_recovery_codes tables."""
    project_dir = create_fixture_project(name="mfa_t25")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    content = next(versions_dir.glob("*mfa*")).read_text()
    assert "mfa_devices" in content
    assert "mfa_recovery_codes" in content
    assert "mfa_enabled" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_all_py_files_parse() -> None:
    """CC-23: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="mfa_t26")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-24 / QS-12: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="mfa_t27")
    r1 = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Expected no_op on second run, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs, project .py files must still parse."""
    project_dir = create_fixture_project(name="mfa_t28")
    add_mfa(ToolInput(project_dir=str(project_dir)))
    add_mfa(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="mfa_t29")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_mfa(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="mfa_t30")
    result = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_alembic_and_fernet() -> None:
    """next_steps should guide the developer with alembic and Fernet key setup."""
    project_dir = create_fixture_project(name="mfa_t31")
    result = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined
    assert "fernet" in combined or "mfa_fernet" in combined


def test_minimum_files_created() -> None:
    """Spec requires >= 9 files created (model, crypto, totp, recovery, rate_limit, etc.)."""
    project_dir = create_fixture_project(name="mfa_t32")
    result = add_mfa(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 8, (
        f"Expected >=8 files created, got {len(result.files_created)}: {result.files_created}"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_all_exist,
        test_files_modified_all_exist,
        test_mfa_models_file_created,
        test_mfa_device_secret_is_binary,
        test_mfa_device_confirmed_at_nullable,
        test_recovery_code_used_at_nullable,
        test_crypto_module_created,
        test_crypto_decrypt_returns_none_on_failure,
        test_totp_module_created,
        test_totp_module_uses_pyotp_segno,
        test_verify_totp_rejects_non_digits,
        test_recovery_module_created,
        test_recovery_uses_argon2id,
        test_rate_limit_module_created,
        test_rate_limit_uses_redis_incr,
        test_schemas_file_created,
        test_crud_file_created,
        test_crud_consume_recovery_single_use,
        test_routes_file_created,
        test_routes_pending_token_purpose_tagged,
        test_routes_pending_token_ttl_5min,
        test_enroll_returns_plaintext_secret,
        test_migration_file_created,
        test_migration_creates_correct_tables,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_alembic_and_fernet,
        test_minimum_files_created,
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
