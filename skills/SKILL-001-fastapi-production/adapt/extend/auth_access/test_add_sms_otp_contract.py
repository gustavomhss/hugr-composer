"""Generic tool-contract mutation coverage for add_sms_otp.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_sms_otp.py in the mutation
runner: ``--tests test_add_sms_otp.py test_add_sms_otp_contract.py``.

The hand-written ``test_*`` functions below this header target add_sms_otp's
TOOL-SPECIFIC logic (router import/include insertion ordering, models/__init__
append formatting, migration head chaining, auth package fallback) that the
generic preamble checks do not cover.
"""

from __future__ import annotations

from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_sms_otp import add_sms_otp
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_sms_otp import add_sms_otp

    for check in SCAFFOLDABLE_CHECKS:
        check(add_sms_otp, "add_sms_otp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(name: str) -> Path:
    project_dir = create_fixture_project(name=name)
    result = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"setup failed: {result.status} {result.error}"
    return project_dir


# ---------------------------------------------------------------------------
# _patch_routes_init: import lands AFTER the last `from app.` import
# Kills L236 BinOp Add->Sub (last_app_import_idx + 1) and the L233/L243
# In->NotIn / And->Or anchors that select the insertion target.
# ---------------------------------------------------------------------------


def test_router_import_inserted_after_last_app_import() -> None:
    """sms_auth_router import must land immediately after the LAST `from app.` import.

    Add->Sub on the insert index would push it before the last app import (and
    onto a different anchor); the And->Or / In->NotIn flips on the anchor line
    would mis-detect where the app imports end.
    """
    project_dir = _run("t076c_import_pos")
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    import_line = "from app.api.routes.sms_auth import router as sms_auth_router"
    assert import_line in lines, "router import not inserted"
    import_idx = lines.index(import_line)
    # The line directly before the inserted import must itself be a `from app.`
    # import (it was the previous "last app import"). With Add->Sub the inserted
    # line would sit before an app import, so the predecessor would not be one.
    assert lines[import_idx - 1].startswith("from app."), (
        f"import not placed after the last app import; predecessor={lines[import_idx - 1]!r}"
    )
    # And it must come BEFORE the api_router = APIRouter() definition.
    router_def_idx = next(
        i for i, ln in enumerate(lines) if "api_router" in ln and "APIRouter()" in ln
    )
    assert import_idx < router_def_idx, "import must precede api_router definition"


def test_router_include_inserted_after_last_include() -> None:
    """include_router(sms_auth_router) must land right after the LAST existing include.

    Add->Sub on last_include_idx + 1 would insert it before the last include
    (e.g. before item_router) instead of after it.
    """
    project_dir = _run("t076c_include_pos")
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    include_line = "api_router.include_router(sms_auth_router)"
    assert include_line in lines, "include not inserted"
    include_idx = lines.index(include_line)
    # The predecessor must itself be an include_router call (the previous last).
    assert lines[include_idx - 1].startswith("api_router.include_router"), (
        f"include not placed after the last include; predecessor={lines[include_idx - 1]!r}"
    )
    # The new include must be the LAST include in the file (nothing after it
    # is another include). Sub would place it mid-list.
    later_includes = [
        ln for ln in lines[include_idx + 1 :] if ln.startswith("api_router.include_router")
    ]
    assert not later_includes, f"include not appended last; trailing includes={later_includes}"


def test_router_import_precedes_include() -> None:
    """The new import line must come before the new include line.

    Guards the overall ordering produced by both insert positions.
    """
    project_dir = _run("t076c_import_before_include")
    text = (project_dir / "app" / "routes" / "__init__.py").read_text()
    import_pos = text.index("from app.api.routes.sms_auth import router as sms_auth_router")
    include_pos = text.index("api_router.include_router(sms_auth_router)")
    assert import_pos < include_pos, "router import must precede its include_router call"


def test_routes_init_idempotent_no_double_register() -> None:
    """Second run must not duplicate the import/include (L224 guard).

    Also exercises L233/L243 In anchors on the already-patched file.
    """
    project_dir = create_fixture_project(name="t076c_routes_idem")
    add_sms_otp(ToolInput(project_dir=str(project_dir)))
    text = (project_dir / "app" / "routes" / "__init__.py").read_text()
    add_sms_otp(ToolInput(project_dir=str(project_dir)))
    text2 = (project_dir / "app" / "routes" / "__init__.py").read_text()
    assert text == text2, "second run must not modify routes/__init__.py"
    assert text2.count("import router as sms_auth_router") == 1, "duplicate import"
    assert text2.count("api_router.include_router(sms_auth_router)") == 1, "duplicate include"


# ---------------------------------------------------------------------------
# _patch_routes_init fallback branches (no `from app.` import present).
# Kills L231/L241 Eq->NotEq, L233/L243 And->Or & In->NotIn, L234 Sub->Add.
# Builds a bare routes/__init__.py with NO `from app.` imports so the
# `last_*_idx == -1` fallback path (anchor on `api_router = APIRouter()`) runs.
# ---------------------------------------------------------------------------


def _bare_routes_init(project_dir: Path) -> Path:
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        '"""Route registration."""\n'
        "\n"
        "from fastapi import APIRouter\n"
        "\n"
        "api_router = APIRouter()\n"
        '\n__all__ = ["api_router"]\n'
    )
    return routes_init


def test_routes_init_fallback_inserts_around_apirouter_anchor() -> None:
    """With no `from app.` import, both import and include anchor on the
    `api_router = APIRouter()` line.

    The import is inserted at ``apirouter_idx - 1 + 1 == apirouter_idx``
    (just above the definition); the include at ``apirouter_idx + 1`` (just
    below). L234 ``idx - 1`` Sub->Add would push the import below the
    definition; the Eq->NotEq on the ``== -1`` guards would skip the fallback.
    """
    project_dir = create_fixture_project(name="t076c_fallback")
    routes_init = _bare_routes_init(project_dir)
    # Drive the patcher directly on a routes init that has NO `from app.`
    # import, so the `last_*_idx == -1` fallback (anchor on APIRouter()) runs.
    from adapt.extend.auth_access.add_sms_otp import _patch_routes_init

    _patch_routes_init(routes_init)
    lines = routes_init.read_text().splitlines()
    import_line = "from app.api.routes.sms_auth import router as sms_auth_router"
    include_line = "api_router.include_router(sms_auth_router)"
    assert import_line in lines and include_line in lines
    apirouter_idx = next(
        i for i, ln in enumerate(lines) if "api_router" in ln and "APIRouter()" in ln
    )
    import_idx = lines.index(import_line)
    include_idx = lines.index(include_line)
    # import goes ABOVE the APIRouter() definition, include BELOW it.
    assert import_idx < apirouter_idx, "import must sit above api_router definition in fallback"
    assert include_idx > apirouter_idx, "include must sit below api_router definition in fallback"
    assert import_idx < include_idx, "import must precede include in fallback"


# ---------------------------------------------------------------------------
# _patch_models_init: append formatting (L194 UnaryNot newline guard,
# L189 In dedup). The OtpCode import must be appended with NO blank line
# inserted before it (content already ends with \n).
# ---------------------------------------------------------------------------


def test_models_init_appends_without_blank_line() -> None:
    """OtpCode import is appended directly after the last existing import.

    The L194 `not content.endswith("\\n")` guard means: since the file already
    ends with a newline, NO extra blank line is inserted. Flipping the guard
    would add a stray blank line before the appended import.
    """
    project_dir = _run("t076c_models_append")
    lines = (project_dir / "app" / "models" / "__init__.py").read_text().splitlines()
    otp_line = next(ln for ln in lines if "OtpCode" in ln and "import" in ln)
    otp_idx = lines.index(otp_line)
    # Predecessor must be a real import line, not an empty/blank line.
    prev = lines[otp_idx - 1]
    assert prev.strip(), (
        f"unexpected blank line before OtpCode import: {lines[otp_idx - 2 : otp_idx + 1]!r}"
    )
    assert "import" in prev, f"OtpCode import not appended after the last import: prev={prev!r}"


def test_models_init_import_format_and_idempotent() -> None:
    """The appended import uses the exact dotted-path + noqa form and dedups.

    Kills L189 In dedup (a second run must not append a duplicate).
    """
    project_dir = create_fixture_project(name="t076c_models_idem")
    add_sms_otp(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.otp_code import OtpCode  # noqa: F401" in content
    add_sms_otp(ToolInput(project_dir=str(project_dir)))
    content2 = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert content2.count("from app.models.otp_code import OtpCode") == 1, "duplicate model import"


# ---------------------------------------------------------------------------
# Migration head chaining: down_revision must equal the fixture's real head
# (L140 `or "0001_initial"`). The fixture has at least one real migration,
# so the `or` fallback must NOT fire — down_revision must be the real head,
# never the literal "0001_initial" unless that genuinely is the head.
# ---------------------------------------------------------------------------


def test_migration_chains_from_real_head() -> None:
    """Generated migration's down_revision points at the project's existing head.

    The L140 BoolOp `find_migration_head(...) or "0001_initial"` returns the
    real head whenever one exists; this asserts the emitted down_revision
    matches the head present BEFORE the tool ran (not a fabricated literal).
    """
    from adapt.contracts.migration_helper import find_migration_head

    project_dir = create_fixture_project(name="t076c_migration_head")
    versions = project_dir / "alembic" / "versions"
    # Head must be computed BEFORE the tool writes its own migration, because
    # the tool chains from the pre-existing head.
    expected_head = find_migration_head(versions)
    assert expected_head, "fixture must have a migration head"
    # The head must be a real on-disk revision, never the synthetic fallback.
    on_disk_revisions = []
    for f in versions.glob("*.py"):
        for ln in f.read_text().splitlines():
            s = ln.strip()
            if s.startswith("revision") and "=" in s and "down_revision" not in s:
                on_disk_revisions.append(s.split("=", 1)[1].strip().strip('"'))
    assert expected_head in on_disk_revisions, "pre-run head must be a real on-disk revision"

    result = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    mig = (versions / "0076_add_sms_otp.py").read_text()
    assert f'down_revision = "{expected_head}"' in mig, (
        f"migration must chain from the real pre-run head {expected_head!r}"
    )


# ---------------------------------------------------------------------------
# auth/__init__.py creation guard (L120 UnaryNot `not exists()`, L121 True).
# When the auth package __init__ does not yet exist, the tool must create it
# and list it among files_created.
# ---------------------------------------------------------------------------


def test_auth_init_created_when_absent() -> None:
    """app/auth/__init__.py is created when missing (L120 `not exists()`)."""
    project_dir = create_fixture_project(name="t076c_auth_init")
    auth_init = project_dir / "app" / "auth" / "__init__.py"
    # Ensure it is absent before the run so the `not exists()` branch runs.
    if auth_init.exists():
        auth_init.unlink()
    result = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert auth_init.exists(), "auth/__init__.py must be created when absent"
    assert str(Path(auth_init).resolve()) in {
        str(Path(p).resolve()) for p in result.files_created
    }, "created auth init must be listed"
    assert auth_init.read_text().strip(), "auth/__init__.py must not be empty"


# ---------------------------------------------------------------------------
# ast-parse / file-filter guard: L158 `p.suffix == ".py" and p.is_file()`.
# Every emitted .py file must be syntactically valid; the Eq->NotEq /
# And->Or flips on the filter would skip validating real .py files.
# ---------------------------------------------------------------------------


def test_all_created_py_files_parse() -> None:
    """All emitted .py files in files_created are valid Python (L158 filter)."""
    import ast

    project_dir = create_fixture_project(name="t076c_parse_created")
    res = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    assert res.status == "success", res.error
    py_created = [p for p in res.files_created if p.endswith(".py")]
    assert py_created, "expected at least one created .py file"
    for path_str in py_created:
        p = Path(path_str)
        assert p.is_file(), f"listed created file missing: {p}"
        ast.parse(p.read_text())  # raises SyntaxError if the tool emitted junk
