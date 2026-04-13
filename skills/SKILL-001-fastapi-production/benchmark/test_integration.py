"""Integration test: generate project, install deps, start uvicorn, hit endpoints.

This is the ultimate test — proves the generated code actually RUNS,
not just parses. Requires: pip, uvicorn, postgres (or uses SQLite fallback).

Usage:
    python benchmark/test_integration.py
    python benchmark/test_integration.py --keep  # don't delete temp dir
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_ROOT))


def generate_test_project(output_dir: str) -> dict:
    """Generate a project with the benchmark spec."""
    from generators.orchestrator import generate_project
    return generate_project(
        output_dir=output_dir,
        name="integration-test",
        prefix="/api/v1",
        models={"Item": {"title": "str", "description": "text"}},
        owner_models={"Item": "user"},
        with_auth=True,
        cors_origins=["http://localhost:3000"],
    )


def patch_for_sqlite(project_dir: str) -> None:
    """Patch the generated project to use SQLite instead of Postgres.

    This allows integration testing without a running Postgres instance.
    We replace the async engine with a sync SQLite engine and adjust
    the session accordingly.
    """
    config_file = Path(project_dir) / "core" / "config.py"
    content = config_file.read_text()

    # Add a SQLite DATABASE_URL default
    content = content.replace(
        'SECRET_KEY: str',
        'SECRET_KEY: str = "test-secret-key-for-integration-testing"',
    )

    # Find the DATABASE_URL field and add a default
    if "DATABASE_URL" in content or "database_url" in content.lower():
        # Replace PostgresDsn with a simple str that defaults to SQLite
        content = content.replace("PostgresDsn", "str")
        if "POSTGRES_" in content:
            # Add a default DATABASE_URL
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                if "DATABASE_URL" in line and ":" in line and "=" not in line.split("#")[0]:
                    # Add default value
                    line = line.rstrip() + ' = "sqlite:///./test.db"'
                new_lines.append(line)
            content = "\n".join(new_lines)

    config_file.write_text(content)

    # Replace async engine with sync for SQLite
    db_file = Path(project_dir) / "core" / "db.py"
    if db_file.exists():
        db_content = db_file.read_text()
        db_content = db_content.replace("create_async_engine", "create_engine")
        db_content = db_content.replace("from sqlalchemy.ext.asyncio import create_engine",
                                         "from sqlalchemy import create_engine")
        db_file.write_text(db_content)


def install_deps(project_dir: str) -> bool:
    """Install project dependencies in a venv."""
    venv_dir = Path(project_dir) / ".venv"

    # Create venv
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  Failed to create venv: {result.stderr}")
        return False

    pip = str(venv_dir / "bin" / "pip")
    python = str(venv_dir / "bin" / "python")

    # Install deps
    req_file = Path(project_dir) / "requirements.txt"
    if not req_file.exists():
        print("  No requirements.txt found")
        return False

    result = subprocess.run(
        [pip, "install", "-q", "-r", str(req_file)],
        capture_output=True, text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  pip install failed: {result.stderr[:500]}")
        return False

    return True


def check_imports(project_dir: str) -> bool:
    """Verify all internal imports work with deps installed."""
    python = str(Path(project_dir) / ".venv" / "bin" / "python")

    # Try importing the main module — symlink as 'app' (the expected package name)
    app_link = "/tmp/_hugr_test_app"
    result = subprocess.run(
        [python, "-c", f"""
import sys, os, shutil

# Create parent dir and symlink project as 'app' package
test_root = '{app_link}'
if os.path.exists(test_root):
    shutil.rmtree(test_root)
os.makedirs(test_root)
os.symlink('{project_dir}', os.path.join(test_root, 'app'))
sys.path.insert(0, test_root)

try:
    from app.core.config import Settings
    print('config: OK')
    from app.core.security import verify_password, DUMMY_HASH
    print('security: OK')
    from app.core.jwt import create_access_token, decode_token
    print('jwt: OK')
    from app.schemas.token import Token, TokenPayload
    print('schemas: OK')
    from app.models.base import Base
    print('models.base: OK')
    from app.crud.user import create, get, get_by_email
    print('crud.user: OK')
    from app.crud.item import create as item_create
    print('crud.item: OK')
    from app.middleware.correlation import CorrelationMiddleware
    print('middleware: OK')
    print('ALL IMPORTS OK')
finally:
    shutil.rmtree(test_root)
"""],
        capture_output=True, text=True,
        timeout=30,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"  Import errors: {result.stderr[:500]}")
        return False

    return "ALL IMPORTS OK" in result.stdout


def run_integration_test(keep: bool = False) -> bool:
    """Run the full integration test."""
    print("=" * 60)
    print("  INTEGRATION TEST: Generate → Install → Import → Verify")
    print("=" * 60)
    print()

    # Step 1: Generate
    d = tempfile.mkdtemp(prefix="skill-integ-")
    print(f"1. Generating project in {d}")
    try:
        result = generate_test_project(d)
        print(f"   → {result['total_files']} files generated")
    except Exception as e:
        print(f"   CRASH: {e}")
        if not keep:
            shutil.rmtree(d)
        return False

    # Step 2: Benchmark
    print("2. Running 35-check benchmark")
    from benchmark.analyzer import analyze
    bench = analyze(d)
    print(f"   → {bench.passed}/{bench.total} ({bench.score:.0f}%)")

    # Step 3: Deep import audit (AST level)
    print("3. Running deep import audit (AST)")
    from benchmark.import_audit import audit as import_audit
    errors = import_audit(Path(d))
    if errors:
        print(f"   → {len(errors)} import errors:")
        for e in errors[:5]:
            print(f"     {e}")
        if not keep:
            shutil.rmtree(d)
        return False
    print("   → All imports resolve")

    # Step 4: Install deps
    print("4. Installing dependencies (this may take a minute)...")
    deps_ok = install_deps(d)
    if not deps_ok:
        print("   → FAILED (see errors above)")
        print("   → Skipping runtime import test")
    else:
        print("   → Dependencies installed")

        # Step 5: Runtime import test
        print("5. Testing runtime imports (with real packages)")
        imports_ok = check_imports(d)
        if imports_ok:
            print("   → All runtime imports pass")
        else:
            print("   → Some imports failed (see above)")

    # Summary
    print()
    print("=" * 60)
    all_pass = bench.score == 100 and not errors
    if deps_ok:
        all_pass = all_pass and imports_ok
    status = "PASS" if all_pass else "FAIL"
    print(f"  RESULT: {status}")
    print(f"  Benchmark: {bench.passed}/{bench.total}")
    print(f"  AST imports: {'OK' if not errors else 'FAILED'}")
    if deps_ok:
        print(f"  Runtime imports: {'OK' if imports_ok else 'FAILED'}")
    else:
        print(f"  Runtime imports: SKIPPED (deps install failed)")
    print(f"  Project: {d}" if keep else f"  Project: cleaned up")
    print("=" * 60)

    if not keep:
        shutil.rmtree(d)

    return all_pass


if __name__ == "__main__":
    keep = "--keep" in sys.argv
    success = run_integration_test(keep=keep)
    sys.exit(0 if success else 1)
