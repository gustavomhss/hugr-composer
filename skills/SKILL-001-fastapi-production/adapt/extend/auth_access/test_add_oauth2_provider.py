"""Tests for TOOL-011 add_oauth2_provider.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_oauth2_provider.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider
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


def _run(name: str) -> tuple[Path, object]:
    project_dir = create_fixture_project(name=name)
    result = add_oauth2_provider(ToolInput(project_dir=str(project_dir)))
    return project_dir, result


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    _, result = _run("t011_01_success")
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    _, result = _run("t011_02_created")
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    _, result = _run("t011_03_modified")
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_model_file_created() -> None:
    """CC-01: app/models/oauth_account.py exists with OAuthAccount."""
    project_dir, _ = _run("t011_04_model")
    model_file = project_dir / "app" / "models" / "oauth_account.py"
    assert model_file.exists(), "oauth_account.py not created"
    content = model_file.read_text()
    assert "class OAuthAccount" in content
    assert "provider" in content
    assert "provider_user_id" in content
    assert "access_token_enc" in content
    assert "refresh_token_enc" in content


def test_model_unique_constraint() -> None:
    """CC-11: OAuthAccount has unique constraint (provider, provider_user_id)."""
    project_dir, _ = _run("t011_05_unique")
    content = (project_dir / "app" / "models" / "oauth_account.py").read_text()
    assert "uq_oauth_provider_user" in content or "UniqueConstraint" in content


def test_model_provider_check_constraint() -> None:
    """Model has CHECK constraint for known providers."""
    project_dir, _ = _run("t011_06_provider_constraint")
    content = (project_dir / "app" / "models" / "oauth_account.py").read_text()
    assert "google" in content and "github" in content and "facebook" in content and "microsoft" in content


def test_model_uses_largebinary_for_tokens() -> None:
    """INV-OA-05: Token columns use LargeBinary (encrypted bytes), not String."""
    project_dir, _ = _run("t011_07_largebinary")
    content = (project_dir / "app" / "models" / "oauth_account.py").read_text()
    assert "LargeBinary" in content, "Token columns must be LargeBinary for encrypted bytes"


def test_oauth_base_file_created() -> None:
    """CC-02: app/core/oauth/base.py exists with OAuthProvider ABC."""
    project_dir, _ = _run("t011_08_base")
    base_file = project_dir / "app" / "core" / "oauth" / "base.py"
    assert base_file.exists(), "oauth/base.py not created"
    content = base_file.read_text()
    assert "class OAuthProvider" in content
    assert "abstractmethod" in content
    assert "OAuthUserInfo" in content
    assert "OAuthTokens" in content


def test_all_four_providers_created() -> None:
    """CC-03: Provider files exist for google, github, facebook, microsoft."""
    project_dir, _ = _run("t011_09_providers")
    oauth_dir = project_dir / "app" / "core" / "oauth"
    for provider in ("google", "github", "facebook", "microsoft"):
        f = oauth_dir / f"{provider}.py"
        assert f.exists(), f"Provider file missing: {provider}.py"
        content = f.read_text()
        assert "authorization_url" in content
        assert "exchange_code" in content
        assert "fetch_user" in content


def test_providers_use_pkce_s256() -> None:
    """CC-17 / QS-02: Provider authorization URLs include code_challenge_method=S256."""
    project_dir, _ = _run("t011_10_pkce")
    # Google and Microsoft support PKCE natively
    for provider in ("google", "microsoft"):
        content = (project_dir / "app" / "core" / "oauth" / f"{provider}.py").read_text()
        assert "S256" in content, f"{provider}.py must include S256 challenge method"


def test_registry_file_created() -> None:
    """CC-04: app/core/oauth/registry.py exists with get_provider/list_providers."""
    project_dir, _ = _run("t011_11_registry")
    registry_file = project_dir / "app" / "core" / "oauth" / "registry.py"
    assert registry_file.exists(), "oauth/registry.py not created"
    content = registry_file.read_text()
    assert "def get_provider" in content
    assert "def list_providers" in content


def test_state_file_created() -> None:
    """CC-05: app/core/oauth/state.py exists with generate_pkce_pair, store_state, consume_state."""
    project_dir, _ = _run("t011_12_state")
    state_file = project_dir / "app" / "core" / "oauth" / "state.py"
    assert state_file.exists(), "oauth/state.py not created"
    content = state_file.read_text()
    assert "def generate_pkce_pair" in content
    assert "async def store_state" in content
    assert "async def consume_state" in content


def test_state_uses_pipeline_get_del() -> None:
    """CC-16 / INV-OA-01: consume_state uses pipeline GET+DEL for atomic single-use."""
    project_dir, _ = _run("t011_13_pipeline")
    content = (project_dir / "app" / "core" / "oauth" / "state.py").read_text()
    assert "pipeline" in content or "pipe" in content, "Must use Redis pipeline for atomic GET+DEL"
    assert "delete" in content.lower() or "DEL" in content


def test_state_uses_set_nx() -> None:
    """INV-OA-01 / QS-01: store_state uses SET NX to prevent overwrites."""
    project_dir, _ = _run("t011_14_set_nx")
    content = (project_dir / "app" / "core" / "oauth" / "state.py").read_text()
    assert "nx=True" in content or "NX" in content.upper()


def test_pkce_uses_sha256() -> None:
    """CC-17: generate_pkce_pair uses SHA-256 for S256 challenge."""
    project_dir, _ = _run("t011_15_sha256")
    content = (project_dir / "app" / "core" / "oauth" / "state.py").read_text()
    assert "sha256" in content.lower() or "SHA256" in content


def test_crypto_file_created() -> None:
    """CC-06: app/core/oauth/crypto.py exists with encrypt_token/decrypt_token."""
    project_dir, _ = _run("t011_16_crypto")
    crypto_file = project_dir / "app" / "core" / "oauth" / "crypto.py"
    assert crypto_file.exists(), "oauth/crypto.py not created"
    content = crypto_file.read_text()
    assert "def encrypt_token" in content
    assert "def decrypt_token" in content


def test_crypto_uses_fernet() -> None:
    """CC-06 / QS-03: crypto.py uses Fernet (AES-128-CBC + HMAC)."""
    project_dir, _ = _run("t011_17_fernet")
    content = (project_dir / "app" / "core" / "oauth" / "crypto.py").read_text()
    assert "Fernet" in content


def test_crud_file_created() -> None:
    """CC-08: app/crud/oauth_account.py exists with get and upsert."""
    project_dir, _ = _run("t011_18_crud")
    crud_file = project_dir / "app" / "crud" / "oauth_account.py"
    assert crud_file.exists(), "crud/oauth_account.py not created"
    content = crud_file.read_text()
    assert "async def get" in content
    assert "async def upsert" in content


def test_crud_always_encrypts_tokens() -> None:
    """INV-OA-05: CRUD upsert calls encrypt_token before storing."""
    project_dir, _ = _run("t011_19_crud_encrypt")
    content = (project_dir / "app" / "crud" / "oauth_account.py").read_text()
    assert "encrypt_token" in content, "CRUD must call encrypt_token before storage"


def test_routes_file_created() -> None:
    """CC-07: app/api/routes/oauth.py exists with login and callback endpoints."""
    project_dir, _ = _run("t011_20_routes")
    routes_file = project_dir / "app" / "api" / "routes" / "oauth.py"
    assert routes_file.exists(), "routes/oauth.py not created"
    content = routes_file.read_text()
    assert "async def oauth_login" in content
    assert "async def oauth_callback" in content


def test_callback_validates_email_verified() -> None:
    """CC-18 / INV-OA-04: Callback rejects unverified emails."""
    project_dir, _ = _run("t011_21_email_verified")
    content = (project_dir / "app" / "api" / "routes" / "oauth.py").read_text()
    assert "email_verified" in content


def test_callback_validates_provider_match() -> None:
    """CC-19 / INV-OA-03: Callback validates state.provider == provider."""
    project_dir, _ = _run("t011_22_provider_match")
    content = (project_dir / "app" / "api" / "routes" / "oauth.py").read_text()
    assert "provider" in content and "mismatch" in content.lower() or "state_obj.provider" in content


def test_callback_prevents_open_redirect() -> None:
    """CC-20 / INV-OA-06: return_to validated to start with '/'."""
    project_dir, _ = _run("t011_23_open_redirect")
    content = (project_dir / "app" / "api" / "routes" / "oauth.py").read_text()
    assert 'startswith("/")' in content or "starts with /" in content.lower()


def test_migration_file_created() -> None:
    """CC-09: Alembic migration file 0011_add_oauth2_provider.py exists."""
    project_dir, _ = _run("t011_24_migration")
    migration_files = list((project_dir / "alembic" / "versions").glob("*oauth*"))
    assert migration_files, "No oauth migration file created"
    content = migration_files[0].read_text()
    assert "oauth_accounts" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_migration_relaxes_hashed_password() -> None:
    """CC-10 / QS-12: Migration allows users.hashed_password to be NULL."""
    project_dir, _ = _run("t011_25_nullable_password")
    migration_files = list((project_dir / "alembic" / "versions").glob("*oauth*"))
    content = migration_files[0].read_text()
    assert "hashed_password" in content and "nullable" in content.lower()


def test_all_py_files_parse() -> None:
    """CC-26: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir, result = _run("t011_26_parse_all")
    assert result.status == "success"
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-30: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="t011_27_idempotent")
    r1 = add_oauth2_provider(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_oauth2_provider(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="t011_28_idempotent_parse")
    add_oauth2_provider(ToolInput(project_dir=str(project_dir)))
    add_oauth2_provider(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="t011_29_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_oauth2_provider(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    _, result = _run("t011_30_timing")
    assert result.execution_time_ms > 0


def test_next_steps_include_alembic() -> None:
    """next_steps should mention alembic upgrade."""
    _, result = _run("t011_31_next_steps")
    assert result.status == "success"
    assert any("alembic" in s.lower() for s in result.next_steps)


def test_notes_mention_pkce() -> None:
    """notes should confirm PKCE is enforced."""
    _, result = _run("t011_32_notes_pkce")
    assert result.status == "success"
    combined = " ".join(result.notes).lower()
    assert "pkce" in combined or "s256" in combined


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_model_file_created,
        test_model_unique_constraint,
        test_model_provider_check_constraint,
        test_model_uses_largebinary_for_tokens,
        test_oauth_base_file_created,
        test_all_four_providers_created,
        test_providers_use_pkce_s256,
        test_registry_file_created,
        test_state_file_created,
        test_state_uses_pipeline_get_del,
        test_state_uses_set_nx,
        test_pkce_uses_sha256,
        test_crypto_file_created,
        test_crypto_uses_fernet,
        test_crud_file_created,
        test_crud_always_encrypts_tokens,
        test_routes_file_created,
        test_callback_validates_email_verified,
        test_callback_validates_provider_match,
        test_callback_prevents_open_redirect,
        test_migration_file_created,
        test_migration_relaxes_hashed_password,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_include_alembic,
        test_notes_mention_pkce,
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
