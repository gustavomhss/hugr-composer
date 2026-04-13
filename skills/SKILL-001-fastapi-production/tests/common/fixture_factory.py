"""Factory that generates real FastAPI projects for use in adapt tool tests.

Uses ``generators.orchestrator.generate_project`` to produce a fully-wired
project in a temporary directory, then validates that every generated Python
file parses without ``SyntaxError``.

Typical usage inside a test::

    from tests.common.fixture_factory import create_fixture_project

    project_dir = create_fixture_project(name="myapp")
    # project_dir is a Path pointing to a fresh, valid FastAPI project
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from generators.orchestrator import generate_project


def create_fixture_project(
    name: str = "test_project",
    models: dict | None = None,
    tmp_dir: Path | None = None,
    with_auth: bool = True,
) -> Path:
    """Generate a fresh FastAPI project for testing.

    Uses ``generators.orchestrator.generate_project`` to produce a real
    project tree, then validates that every generated ``.py`` file parses
    via ``ast.parse``.

    Args:
        name: Application name (also used as the output directory name
            inside ``tmp_dir``).
        models: Domain models to generate.  Defaults to a minimal
            ``{"Item": {"title": "str", "description": "str"}}`` with an
            ``Item -> user`` owner relationship so soft-delete tests have a
            concrete model to target.
        tmp_dir: Parent directory in which to create the project.  When
            ``None`` a fresh ``tempfile.mkdtemp()`` directory is used and
            the project is placed directly inside it.
        with_auth: Whether to generate the full auth stack.  Defaults to
            ``True`` so that ``CurrentUser`` / ``CurrentSuperuser`` deps
            and the ``users.id`` FK used by soft-delete are available.

    Returns:
        ``Path`` pointing to the generated project root (contains ``app/``,
        ``alembic/``, ``requirements.txt``, etc.).

    Raises:
        SyntaxError: If any generated ``.py`` file fails ``ast.parse``.
        ValueError: If ``generate_project`` returns no files.
    """
    if models is None:
        models = {"Item": {"title": "str", "description": "str"}}

    if tmp_dir is None:
        output_dir = Path(tempfile.mkdtemp()) / name
    else:
        output_dir = Path(tmp_dir) / name

    owner_models = {m: "user" for m in models if m != "User"} if with_auth else None

    result = generate_project(
        output_dir=str(output_dir),
        name=name,
        models=models,
        owner_models=owner_models,
        with_auth=with_auth,
        with_docker_compose=False,
        with_ci=False,
        with_otel=False,
        with_prometheus=False,
    )

    if not result.get("files_created"):
        raise ValueError(
            f"generate_project produced no files for project '{name}' at {output_dir}"
        )

    _assert_all_py_parse(output_dir)

    return output_dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assert_all_py_parse(project_root: Path) -> None:
    """Raise ``SyntaxError`` if any ``.py`` file under *project_root* is invalid.

    Args:
        project_root: Root directory to walk recursively.

    Raises:
        SyntaxError: With the file path and original error message included
            so failing tests surface the exact culprit file immediately.
    """
    for py_file in sorted(project_root.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise SyntaxError(
                f"Generated file {py_file} has a syntax error: {exc}"
            ) from exc
