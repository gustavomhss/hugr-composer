"""Generic tool-contract mutation coverage for add_data_seeder.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_data_seeder.py in the mutation
runner: ``--tests test_add_data_seeder.py test_add_data_seeder_contract.py``.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_data_seeder import add_data_seeder
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_data_seeder import add_data_seeder

    for check in SCAFFOLDABLE_CHECKS:
        check(add_data_seeder, "add_data_seeder")


def _resolved(paths) -> set[str]:
    """Resolve each path so /var vs /private/var symlink differences vanish."""
    return {str(Path(p).resolve()) for p in paths}


def test_scaffolded_prereqs_kept_in_files_created() -> None:
    """L67 (BoolOp Or->And): on a bare project the prerequisite files that the
    tool auto-scaffolds (config, base model, routes init, package __init__s)
    seed ``files_created`` via ``list(scaffolded or [])``.

    Flipping ``or`` to ``and`` makes ``files_created`` start as ``[]`` (the
    short-circuit drops the scaffolded list entirely), so the auto-created
    prerequisite files would vanish from the reported output even though they
    were written to disk.
    """
    bare = Path(tempfile.mkdtemp())
    result = add_data_seeder(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error

    created = result.files_created
    # The seeder's own files (always appended after L67) would survive an
    # ``and`` flip, so anchor on the *prerequisite* scaffold output instead.
    assert any(p.endswith("app/core/config.py") for p in created), (
        f"scaffolded config.py missing from files_created: {created}"
    )
    assert any(p.endswith("app/models/base.py") for p in created), (
        f"scaffolded base model missing from files_created: {created}"
    )
    assert any(p.endswith("app/routes/__init__.py") for p in created), (
        f"scaffolded routes init missing from files_created: {created}"
    )
    # Sanity: an ``and`` flip would also drop the count well below the full set.
    assert len(created) >= 10, (
        f"expected scaffolded prereqs + seeder files (>=10), got {len(created)}: {created}"
    )


def test_emitted_test_file_is_created() -> None:
    """L142 (UnaryNot ``not emitted.exists()`` -> ``emitted.exists()``): on a
    fresh project the emitted regression test does not yet exist, so the guard
    must be truthy and the tool renders ``tests/test_add_data_seeder_emitted.py``
    and records it in ``files_created``.

    Flipping the ``not`` inverts the guard: on a fresh project the file does not
    exist, the condition is False, and the emitted test is never written.
    """
    project_dir = create_fixture_project(name="ds_contract_emitted")
    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    emitted = project_dir / "tests" / "test_add_data_seeder_emitted.py"
    assert emitted.exists(), "emitted regression test was not written"
    assert str(emitted.resolve()) in _resolved(result.files_created), (
        f"emitted test not in files_created: {result.files_created}"
    )


def test_routes_patch_keeps_import_on_its_own_line() -> None:
    """L172 (UnaryNot ``not content.endswith(chr(10))`` -> ``content.endswith``):
    when the existing routes ``__init__.py`` does NOT end with a newline, the
    tool first appends a newline so the seeder import lands on its own line.

    Flipping the ``not`` skips that newline insertion, gluing the import onto
    the last existing line (producing a broken/merged source line). Drive the
    WITHOUT-trailing-newline branch and assert the import is a standalone line.
    """
    project_dir = create_fixture_project(name="ds_contract_routespatch")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    assert routes_init.exists()
    # Force the no-trailing-newline branch.
    routes_init.write_text(routes_init.read_text().rstrip("\n"))
    assert not routes_init.read_text().endswith("\n")

    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    content = routes_init.read_text()
    import_line = "from app.api.routes.seeder import router as seeder_router"
    include_line = "api_router.include_router(seeder_router)"
    lines = content.splitlines()
    assert import_line in lines, f"seeder import line missing: {content[-200:]!r}"
    assert include_line in lines, "seeder include_router line missing"

    # When the original file did NOT end with a newline, the ``not`` guard
    # appends one *before* the f-string's own leading newline, producing a
    # blank-line separator (``\n\n``) ahead of the import. Flipping ``not`` to
    # plain ``endswith`` skips that extra newline, collapsing the separator to a
    # single ``\n`` (import glued directly under the prior line). Assert the
    # blank-line separator survived to distinguish the two.
    assert "\n\n" + import_line in content, (
        "blank-line separator before seeder import missing (newline guard "
        f"collapsed): {content[-200:]!r}"
    )
