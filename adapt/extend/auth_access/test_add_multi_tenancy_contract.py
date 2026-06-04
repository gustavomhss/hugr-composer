"""Generic tool-contract mutation coverage for add_multi_tenancy.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_multi_tenancy.py in the mutation
runner: ``--tests test_add_multi_tenancy.py test_add_multi_tenancy_contract.py``.
"""

import re
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    for check in UNIVERSAL_CHECKS:
        check(add_multi_tenancy, "add_multi_tenancy")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills (survivors not covered by the generic contract).
# Each test targets one cited operator/literal in
# adapt/extend/auth_access/add_multi_tenancy/__init__.py.
# ---------------------------------------------------------------------------


def test_migration_chains_off_real_head_not_root() -> None:
    """L191 (Or -> And): down_rev = find_migration_head(...) or "0001_initial".

    The fixture project's chain HEAD is ``0002_baseline_schema``. The ``or``
    keeps that real head; mutating it to ``and`` would discard the head and
    emit ``down_revision = "0001_initial"`` (forking the chain off the wrong
    parent). Assert the emitted migration chains off the ACTUAL head.
    """
    project_dir = create_fixture_project(name="mtc_head")
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"tool failed: {result.error}"

    versions = project_dir / "alembic" / "versions"
    mig = next(iter(versions.glob("*multi_tenancy*.py")))
    src = mig.read_text()
    m = re.search(r'down_revision = "([^"]+)"', src)
    assert m is not None, "migration missing down_revision assignment"
    assert m.group(1) == "0002_baseline_schema", (
        "L191: migration must chain off the real head (0002_baseline_schema), "
        f"got down_revision={m.group(1)!r} — the `or` fallback was bypassed"
    )


def test_conftest_actually_patched_when_present() -> None:
    """L186 (And -> Or), short-circuit branch.

    When ``tests/conftest.py`` exists, the ``and`` requires
    ``patch_test_conftest`` to run and return truthy before conftest is
    recorded as modified. Mutating to ``or`` would short-circuit on
    ``exists()`` being True, recording conftest as modified WITHOUT ever
    patching it. Assert the patch genuinely ran (sentinel present) and the
    file is reported modified.
    """
    project_dir = create_fixture_project(name="mtc_ctpresent")
    conftest = project_dir / "tests" / "conftest.py"
    assert conftest.exists(), "fixture should emit tests/conftest.py"

    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"tool failed: {result.error}"

    content = conftest.read_text()
    assert "_MT_TENANT_SLUG" in content, (
        "L186: conftest reported modified but the patch never ran (short-circuit on exists())"
    )
    assert "conftest.py" in [Path(m).name for m in result.files_modified], (
        "conftest was patched but not reported in files_modified"
    )


def test_missing_conftest_is_skipped_cleanly() -> None:
    """L186 (And -> Or), missing-file branch.

    When ``tests/conftest.py`` does NOT exist, the ``and`` short-circuits on
    ``exists()`` being False and never calls ``patch_test_conftest``. Mutating
    to ``or`` would invoke ``patch_test_conftest`` on a non-existent path
    (``read_text`` -> FileNotFoundError), crashing the tool. Assert the tool
    still succeeds and does not report a conftest as modified.
    """
    project_dir = create_fixture_project(name="mtc_ctabsent")
    conftest = project_dir / "tests" / "conftest.py"
    conftest.unlink()

    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"tool failed: {result.error}"
    modified_names = [Path(m).name for m in result.files_modified]
    assert "conftest.py" not in modified_names, (
        f"L186: a missing conftest must not be recorded as modified: {result.files_modified}"
    )
    assert not conftest.exists(), "tool must not create a conftest that was absent"


def test_auto_scaffold_recovers_missing_prereq_on_real_run() -> None:
    """L61 (not X -> X): auto_scaffold=not inp.dry_run.

    On a real (non-dry) run, ``auto_scaffold`` must be True so a missing but
    scaffoldable prerequisite is auto-created and the tool proceeds. Mutating
    ``not inp.dry_run`` to ``inp.dry_run`` makes auto_scaffold False on a real
    run, so the missing prereq is never created and the tool errors out.

    Delete the (scaffoldable) ROUTES_INIT prereq, then assert the tool both
    succeeds AND re-created the file.
    """
    project_dir = create_fixture_project(name="mtc_autoscaffold")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    routes_init.unlink()

    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        "L61: real run must auto-scaffold the missing prereq and succeed, "
        f"got status={result.status} error={result.error}"
    )
    assert routes_init.exists(), (
        "L61: missing scaffoldable prereq was not auto-created on a real run"
    )


def test_dry_run_with_missing_prereq_reports_error() -> None:
    """L66 (Add -> Sub): error = "Prerequisites not met:\\n" + "\\n".join(...).

    A dry run sets auto_scaffold False, so a missing prerequisite is reported
    rather than scaffolded, and the error message is built by string
    concatenation. Mutating ``+`` to ``-`` would raise TypeError (str does not
    support ``-``) instead of producing the message. Assert the prereq-error
    path returns the concatenated message intact.
    """
    project_dir = create_fixture_project(name="mtc_prereq_err")
    (project_dir / "app" / "models" / "base.py").unlink()

    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "error", "missing prereq under dry_run must error"
    assert result.error is not None
    assert result.error.startswith("Prerequisites not met:\n"), (
        "L66: prerequisite error message must be the concatenation of the "
        f"header and the joined errors, got: {result.error!r}"
    )
    assert "Missing:" in result.error, "joined prereq errors must be appended"


def test_emit_creates_module_under_existing_parent_dir() -> None:
    """L36 (True -> False): dest.parent.mkdir(parents=True, exist_ok=True).

    ``_emit`` writes ``app/core/tenant_context.py`` into ``app/core``, which
    ALREADY exists in a full fixture project. With ``exist_ok=True`` the mkdir
    is a harmless no-op; mutating to ``exist_ok=False`` raises FileExistsError
    on the pre-existing directory, crashing the emit. Assert the tool succeeds
    and the emitted module landed under the pre-existing parent.
    """
    project_dir = create_fixture_project(name="mtc_emit")
    core_dir = project_dir / "app" / "core"
    assert core_dir.is_dir(), "fixture should already contain app/core"

    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"L36: emit into a pre-existing parent dir must succeed, got: {result.error}"
    )
    assert (core_dir / "tenant_context.py").exists(), (
        "L36: tenant_context.py was not emitted under the existing app/core dir"
    )
