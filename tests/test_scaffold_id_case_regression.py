"""test_scaffold_id_case_regression.py — scaffold entry-point regression tests.

Covers the two confirmed failure modes found by exercising
``fastapi_meta_scaffold`` the way an end user would:

  (a) CALLER-DECLARED ``id``: a user passes ``id`` in the model field map
      (``{"Order": {"id": "int", ...}}``).  The generator's auto-injected
      ``id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)``
      used to be re-declared by the caller's ``id: Mapped[int]`` field,
      and the class-level redefinition silently dropped the PRIMARY KEY —
      emitting a model that crashed at runtime with
      ``sqlalchemy.exc.ArgumentError: could not assemble any primary key
      columns``.

  (b) LOWERCASE / SNAKE_CASE MODEL KEYS: a user passes ``{"order": ...}``
      or ``{"order_item": ...}``.  Leaf generators capitalize only the
      first letter, so ``order`` produced ``class Order`` but the
      orchestrator's ``models/__init__.py`` emitted
      ``from app.models.order import order`` — an ``ImportError`` on
      project import.

Run from the skill root:
    PYTHONPATH=. .venv/bin/python -m pytest tests/test_scaffold_id_case_regression.py -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SKILL_ROOT = Path(__file__).resolve().parent.parent


def _gen(tmp_path: Path, **kwargs) -> Path:
    """Call generate_project and return the project dir."""
    sys.path.insert(0, str(_SKILL_ROOT))
    from generators.orchestrator import generate_project

    project_dir = tmp_path / "proj"
    result = generate_project(output_dir=str(project_dir), **kwargs)
    assert result["total_files"] > 0, "orchestrator produced no files"
    return project_dir


# ---------------------------------------------------------------------------
# (a) Caller-declared ``id`` must not clobber the auto PK
# ---------------------------------------------------------------------------


class TestCallerDeclaredId:
    """A user-supplied ``id`` field must not re-declare the primary key."""

    def test_id_field_keeps_single_pk(self, tmp_path: Path) -> None:
        """``id: 'int'`` in the field map → exactly one PK column (Uuid)."""
        project_dir = _gen(
            tmp_path,
            name="idfix",
            models={"Order": {"id": "int", "customer_name": "str"}},
            owner_models={"Order": "user"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )
        model_src = (project_dir / "app" / "models" / "order.py").read_text()

        # Exactly one ``id:`` attribute declaration in the class body.
        id_attr_lines = [
            ln
            for ln in model_src.splitlines()
            if ln.startswith("    id:") and not ln.startswith("    id_")
        ]
        assert len(id_attr_lines) == 1, (
            "model must declare the id attribute exactly once.\nGot:\n" + model_src
        )
        # The surviving PK is the Uuid one, not the caller's int.
        assert "Uuid, primary_key=True" in id_attr_lines[0]

    def test_id_absent_from_input_schema(self, tmp_path: Path) -> None:
        """Caller-declared ``id`` must not leak into *Create/*Update schemas."""
        project_dir = _gen(
            tmp_path,
            name="idfix_schema",
            models={"Order": {"id": "int", "customer_name": "str"}},
            owner_models={"Order": "user"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )
        schema_src = (project_dir / "app" / "schemas" / "order.py").read_text()

        assert "class OrderCreate" in schema_src
        create_body = schema_src.split("class OrderCreate")[1].split("class OrderUpdate")[0]
        id_lines = [ln for ln in create_body.splitlines() if ln.startswith("    id:")]
        assert not id_lines, "OrderCreate must not require an id on create.\nGot:\n" + create_body


# ---------------------------------------------------------------------------
# (b) Lowercase / snake_case model keys normalise to PascalCase
# ---------------------------------------------------------------------------


class TestModelKeyNormalisation:
    """``models`` / ``owner_models`` keys accept any case and stay consistent."""

    def test_lowercase_key_imports_match_class(self, tmp_path: Path) -> None:
        """``{"order": ...}`` → ``class Order`` + ``from app.models.order import Order``."""
        project_dir = _gen(
            tmp_path,
            name="lowkey",
            models={"order": {"customer_name": "str"}},
            owner_models={"order": "user"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )
        init_src = (project_dir / "app" / "models" / "__init__.py").read_text()
        model_src = (project_dir / "app" / "models" / "order.py").read_text()

        assert "class Order(Base)" in model_src
        assert "from app.models.order import Order" in init_src, (
            "models/__init__.py must import the PascalCase class.\nGot:\n" + init_src
        )
        assert "import order" not in init_src

    def test_snake_case_key_normalises(self, tmp_path: Path) -> None:
        """``{"order_item": ...}`` → ``class OrderItem`` + ``orderitem.py`` + matching import."""
        project_dir = _gen(
            tmp_path,
            name="snakekey",
            models={"order_item": {"name": "str"}},
            owner_models={"order_item": "user"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )
        init_src = (project_dir / "app" / "models" / "__init__.py").read_text()
        model_src = (project_dir / "app" / "models" / "orderitem.py").read_text()

        assert "class OrderItem(Base)" in model_src
        assert "from app.models.orderitem import OrderItem" in init_src, (
            "snake_case key must normalise to PascalCase in the import.\nGot:\n" + init_src
        )

    def test_pascal_case_key_is_idempotent(self, tmp_path: Path) -> None:
        """``{"OrderItem": ...}`` stays ``OrderItem`` (never mangled to ``Orderitem``)."""
        project_dir = _gen(
            tmp_path,
            name="pascalkey",
            models={"OrderItem": {"name": "str"}},
            owner_models={"OrderItem": "user"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )
        init_src = (project_dir / "app" / "models" / "__init__.py").read_text()
        model_src = (project_dir / "app" / "models" / "orderitem.py").read_text()

        assert "class OrderItem(Base)" in model_src
        assert "from app.models.orderitem import OrderItem" in init_src, (
            "already-PascalCase key must not be lowercased.\nGot:\n" + init_src
        )
        assert "Orderitem" not in model_src

    def test_shared_models_accepts_any_case(self, tmp_path: Path) -> None:
        """``shared_models`` keys must normalise like ``owner_models`` (BOLA check)."""
        project_dir = _gen(
            tmp_path,
            name="sharedkey",
            models={"order_item": {"name": "str"}},
            owner_models={"order_item": "user"},
            shared_models={"order_item"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )
        assert (project_dir / "app" / "models" / "orderitem.py").exists()
        bola_file = (project_dir / "tests" / "test_bola_shared_models.py").read_text()
        assert "OrderItem" in bola_file


# ---------------------------------------------------------------------------
# (c) End-to-end: emitted project pytest passes (no PK / import crash)
# ---------------------------------------------------------------------------


class TestEmittedProjectPytest:
    """The emitted project's own pytest suite must pass after the fix."""

    @pytest.mark.slow
    def test_id_field_and_lowercase_key_project_pytest_passes(self, tmp_path: Path) -> None:
        """Generate a project that combines both failure modes, install deps,
        run its tests — no ArgumentError and no ImportError.

        This exercises the exact user story that surfaced the bugs:
        ``models={"order": {"id": "int", ...}}`` — a natural way to
        declare a resource with an explicit numeric id.
        """
        project_dir = _gen(
            tmp_path,
            name="combo",
            models={"order": {"id": "int", "customer_name": "str", "total_cents": "int"}},
            owner_models={"order": "user"},
            with_auth=True,
            with_docker_compose=False,
            with_ci=False,
            with_otel=False,
            with_prometheus=False,
        )

        env_file = project_dir / ".env"
        env_file.write_text(
            "SECRET_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
            "ENVIRONMENT=local\n"
            "FIRST_SUPERUSER_EMAIL=admin@x.com\n"
            "FIRST_SUPERUSER_PASSWORD=testpassword123\n"
            "RATE_LIMITING_ENABLED=false\n"
        )

        venv_dir = project_dir / ".venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
        )
        pip = venv_dir / "bin" / "pip"
        subprocess.run(
            [str(pip), "install", "-r", str(project_dir / "requirements.txt"), "-q"],
            check=True,
            capture_output=True,
            timeout=300,
        )

        python = venv_dir / "bin" / "python3"
        result = subprocess.run(
            [str(python), "-m", "pytest", "tests/", "-v", "--tb=short", "--no-header"],
            cwd=str(project_dir),
            env={
                **__import__("os").environ,
                "PYTHONPATH": str(project_dir),
                "SECRET_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "ENVIRONMENT": "local",
                "RATE_LIMITING_ENABLED": "false",
            },
            capture_output=True,
            text=True,
            timeout=180,
        )

        assert "could not assemble any primary key columns" not in result.stdout
        assert "ImportError" not in result.stdout
        assert result.returncode == 0, (
            f"Emitted project pytest FAILED (rc={result.returncode})\n"
            f"--- stdout ---\n{result.stdout[-4000:]}\n"
            f"--- stderr ---\n{result.stderr[-1000:]}"
        )
