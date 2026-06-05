"""Generic tool-contract mutation coverage for add_input_sanitization.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_input_sanitization.py in the mutation
runner: ``--tests test_add_input_sanitization.py test_add_input_sanitization_contract.py``.
"""

import ast
import tempfile

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_input_sanitization import add_input_sanitization
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    for check in SCAFFOLDABLE_CHECKS:
        check(add_input_sanitization, "add_input_sanitization")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (beyond the shared preamble contract).
# ---------------------------------------------------------------------------


def _ends_with(paths: list[str], suffix: str) -> bool:
    """True if any path in *paths* ends with *suffix*."""
    return any(p.endswith(suffix) for p in paths)


def test_patches_existing_security_init_without_input_sanitizer() -> None:
    """Kills L94 NotIn->In, L163 In->NotIn, L166 Add->Sub, L89 exist_ok True->False.

    When app/security/__init__.py already exists but does NOT export
    InputSanitizer, the tool must patch it (append the import) and report it as
    modified. It must NOT recreate the existing security dir (exist_ok=True).
    """
    project = create_fixture_project(name="san_ct_patch_init")
    sec = project / "app" / "security"
    sec.mkdir(parents=True, exist_ok=True)
    init = sec / "__init__.py"
    init.write_text('"""Pre-existing security package."""\n')

    result = add_input_sanitization(ToolInput(project_dir=str(project)))

    assert result.status == "success", result.error
    # L94: the elif branch must fire -> __init__.py reported as modified.
    assert _ends_with(result.files_modified, "app/security/__init__.py"), (
        f"existing security __init__.py must be modified, got {result.files_modified}"
    )
    # __init__.py must NOT appear in files_created (it already existed).
    assert not _ends_with(result.files_created, "app/security/__init__.py")
    # L163/L166: the import line must actually be appended, and the file must
    # still parse (Add->Sub would crash before writing).
    src = init.read_text()
    assert "from app.security.sanitizer import InputSanitizer" in src, (
        f"InputSanitizer import must be appended, got:\n{src}"
    )
    assert '"""Pre-existing security package."""' in src, (
        "original content must be preserved (Add concatenation, not Sub)"
    )
    ast.parse(src)


def test_patch_existing_init_is_idempotent() -> None:
    """Kills L163 In->NotIn (dedup guard in _patch_security_init).

    If the security __init__.py already exports InputSanitizer, a re-patch must
    not append a duplicate import. (The In->NotIn flip would make the guard
    skip the already-patched file and append again.)
    """
    project = create_fixture_project(name="san_ct_patch_idem")
    sec = project / "app" / "security"
    sec.mkdir(parents=True, exist_ok=True)
    init = sec / "__init__.py"
    init.write_text(
        '"""Pre-existing security package."""\n'
        "from app.security.sanitizer import InputSanitizer  # noqa: F401\n"
    )

    result = add_input_sanitization(ToolInput(project_dir=str(project)))

    assert result.status == "success", result.error
    # Already exports InputSanitizer -> elif branch must NOT modify it again.
    assert not _ends_with(result.files_modified, "app/security/__init__.py"), (
        "init already exporting InputSanitizer must not be re-modified"
    )
    src = init.read_text()
    assert src.count("from app.security.sanitizer import InputSanitizer") == 1, (
        f"InputSanitizer import must not be duplicated, got:\n{src}"
    )


def test_scaffolded_prereqs_kept_in_files_created() -> None:
    """Kills L85 BoolOp Or->And (`list(scaffolded or [])`).

    On a bare project the tool auto-scaffolds config.py + package __init__.py
    files; those scaffolded paths must be carried into files_created. The
    Or->And flip would yield `list(scaffolded and [])` == [] and drop them.
    """
    bare = tempfile.mkdtemp()
    result = add_input_sanitization(ToolInput(project_dir=bare))

    assert result.status == "success", result.error
    # The scaffolded config.py is a prereq artifact, not one of the tool's own
    # security/* outputs -> its presence proves `scaffolded` survived.
    assert _ends_with(result.files_created, "app/core/config.py"), (
        f"scaffolded config.py must be in files_created, got {result.files_created}"
    )


def test_emitted_project_test_with_preexisting_tests_dir() -> None:
    """Kills L170 exist_ok True->False (`tests`.mkdir in _emit_project_test).

    Fixture projects already have a tests/ dir. The tool must still succeed and
    emit tests/test_add_input_sanitization_emitted.py. exist_ok=True->False
    would raise FileExistsError on the existing tests dir.
    """
    project = create_fixture_project(name="san_ct_emit")
    assert (project / "tests").is_dir(), "fixture must ship a tests/ dir"

    result = add_input_sanitization(ToolInput(project_dir=str(project)))

    assert result.status == "success", result.error
    emitted = project / "tests" / "test_add_input_sanitization_emitted.py"
    assert emitted.exists(), "emitted project test must be written"
    assert _ends_with(result.files_created, "tests/test_add_input_sanitization_emitted.py")


def test_emitted_project_test_idempotent() -> None:
    """Reinforces _emit_project_test early-return guard (emitted.exists()).

    A second run must not re-emit the project test (it already exists), and the
    project must remain syntactically valid.
    """
    project = create_fixture_project(name="san_ct_emit_idem")
    add_input_sanitization(ToolInput(project_dir=str(project)))
    emitted = project / "tests" / "test_add_input_sanitization_emitted.py"
    first = emitted.read_text()

    r2 = add_input_sanitization(ToolInput(project_dir=str(project)))

    assert r2.status == "no_op", r2.error
    assert emitted.read_text() == first
    ast.parse(emitted.read_text())
