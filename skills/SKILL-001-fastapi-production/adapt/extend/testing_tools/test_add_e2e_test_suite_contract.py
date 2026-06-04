"""Generic tool-contract mutation coverage for add_e2e_test_suite.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_e2e_test_suite.py in the mutation
runner: ``--tests test_add_e2e_test_suite.py test_add_e2e_test_suite_contract.py``.

The ``test_specific_*`` functions below target this tool's bespoke logic
(requirements.txt dep dedup/parse, config.py patch outcome branches, the
ast.parse validation loop guard) — the survivors the generic contract test
cannot reach.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.contracts.config_patcher import PatchResult
from adapt.extend.testing_tools.add_e2e_test_suite import (
    _extract_req_name,
    _patch_config,
    _patch_requirements_with_test_deps,
    add_e2e_test_suite,
)
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_e2e_test_suite import add_e2e_test_suite

    for check in SCAFFOLDABLE_CHECKS:
        check(add_e2e_test_suite, "add_e2e_test_suite")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_project(requirements: str) -> Path:
    """Minimal project: app/core/config.py with a Settings class + a custom
    requirements.txt body. Returns the project root."""
    d = Path(tempfile.mkdtemp())
    (d / "app" / "core").mkdir(parents=True)
    (d / "app" / "core" / "config.py").write_text(
        'class Settings:\n    APP_NAME: str = "x"\n\nsettings = Settings()\n'
    )
    (d / "requirements.txt").write_text(requirements)
    return d


# ---------------------------------------------------------------------------
# requirements.txt dep patcher — L692 / L694 / L695 / L696 / L699
# ---------------------------------------------------------------------------


def test_specific_requirements_adds_only_missing_dep():
    """L692 (`pkg not in declared`): httpx already declared so it must NOT be
    re-added; pytest-asyncio is missing so it MUST be added. NotIn->In flip
    would invert (drop pytest-asyncio, duplicate httpx)."""
    d = _bare_project("fastapi>=0.115.0\nhttpx>=0.28.0\n")
    changed = _patch_requirements_with_test_deps(d / "requirements.txt")
    assert changed is True  # L699: at least one dep added
    body = (d / "requirements.txt").read_text()
    # pytest-asyncio added exactly once.
    assert body.count("pytest-asyncio") == 1
    # httpx NOT duplicated (was already declared -> deduped via L692).
    assert body.count("httpx") == 1


def test_specific_requirements_noop_when_all_present():
    """L694 (`if not to_add: return False`) + L695 (`return False`): when every
    dep is already declared the helper must report no change. UnaryNot flip or
    BoolLiteral False->True would falsely claim a modification."""
    req = _bare_project("fastapi>=0.115.0\nhttpx>=0.28.0\npytest-asyncio>=0.24.0\n")
    before = (req / "requirements.txt").read_text()
    changed = _patch_requirements_with_test_deps(req / "requirements.txt")
    assert changed is False
    # File untouched.
    assert (req / "requirements.txt").read_text() == before


def test_specific_requirements_appends_both_when_empty():
    """Both deps missing -> both appended; L699 returns True."""
    req = _bare_project("fastapi>=0.115.0\n")
    changed = _patch_requirements_with_test_deps(req / "requirements.txt")
    assert changed is True
    body = (req / "requirements.txt").read_text()
    assert "httpx>=0.28.0" in body
    assert "pytest-asyncio>=0.24.0" in body


def test_specific_requirements_no_merged_lines_when_missing_trailing_newline():
    """L696 (`if not src.endswith("\\n"): src += "\\n"`): a requirements file
    with NO trailing newline must not merge the last existing dep with the
    first appended dep. UnaryNot flip would drop the separator, producing a
    line like `fastapihttpx>=0.28.0`."""
    req = _bare_project("fastapi>=0.115.0")  # no trailing newline
    changed = _patch_requirements_with_test_deps(req / "requirements.txt")
    assert changed is True
    lines = (req / "requirements.txt").read_text().splitlines()
    # The original dep stays on its own line, unmerged.
    assert "fastapi>=0.115.0" in lines
    assert "httpx>=0.28.0" in lines
    assert not any("fastapihttpx" in ln for ln in lines)


# ---------------------------------------------------------------------------
# requirements line parser — L712 / L714 / L716 / L718 / L720 / L723
# ---------------------------------------------------------------------------


def test_specific_extract_req_name_skips_blank_and_comment():
    """L712 (`if not line or line.startswith("#")`): blank lines and comment
    lines declare no package. BoolOp Or->And or UnaryNot flip would let one of
    them through as a bogus package name."""
    assert _extract_req_name("") is None
    assert _extract_req_name("   ") is None
    assert _extract_req_name("# a comment") is None


def test_specific_extract_req_name_skips_option_lines():
    """L714 (`if line.startswith("-") or line.startswith("--")`): pip option
    lines (`-r reqs.txt`, `--index-url ...`) declare no package. Or->And flip
    would only skip one prefix, mis-parsing the other as a package name."""
    assert _extract_req_name("-r other.txt") is None
    assert _extract_req_name("--index-url https://example.test/simple") is None


def test_specific_extract_req_name_strips_inline_comment():
    """L716 (`if " #" in line`): inline `pkg  # note` comment is stripped.
    In->NotIn flip would leave the comment glued to the name."""
    assert _extract_req_name("httpx  # http client") == "httpx"


def test_specific_extract_req_name_strips_env_marker():
    """L718 (`if ";" in line`): environment marker is stripped.
    In->NotIn flip would keep the marker in the name."""
    assert _extract_req_name('httpx; python_version >= "3.10"') == "httpx"


def test_specific_extract_req_name_strips_extras():
    """L720 (`if "[" in line`): extras bracket is stripped.
    In->NotIn flip would keep `[argon2]` in the name."""
    assert _extract_req_name("pwdlib[argon2]>=0.2.1") == "pwdlib"


def test_specific_extract_req_name_strips_version_specifier():
    """L723 (`if sep in line`): the version specifier is split off.
    In->NotIn flip would keep `>=0.28.0` glued to the name."""
    assert _extract_req_name("httpx>=0.28.0") == "httpx"
    assert _extract_req_name("fastapi==0.115.0") == "fastapi"


def test_specific_extract_req_name_dedup_is_specifier_insensitive():
    """End-to-end of the parse path: a dep already present under a DIFFERENT
    specifier must still be recognised as declared (so not re-added). This
    pins the parse-then-compare contract that several In/NotIn flips break."""
    req = _bare_project("httpx==0.27.0\npytest-asyncio>=0.24.0\n")
    changed = _patch_requirements_with_test_deps(req / "requirements.txt")
    # httpx (different pin) + pytest-asyncio both already declared -> no change.
    assert changed is False


# ---------------------------------------------------------------------------
# config.py patch-outcome branches — L177 / L179 / L184
# ---------------------------------------------------------------------------


def test_specific_config_patch_applied_marks_modified():
    """L177/L178: a config.py with a real `class Settings` is patched and
    reported in files_modified."""
    d = _bare_project("fastapi>=0.115.0\n")
    result = add_e2e_test_suite(ToolInput(project_dir=str(d)))
    assert result.status == "success"
    assert any(p.endswith("app/core/config.py") for p in result.files_modified)
    body = (d / "app" / "core" / "config.py").read_text()
    assert "E2E_BASE_URL" in body
    assert "E2E_TEST_EMAIL" in body
    assert "E2E_TEST_PASSWORD" in body


def test_specific_config_patch_outcome_is_applied_for_settings_class():
    """L179 (`is PatchResult.TARGET_MISSING`) / L184 (`is PatchResult.
    SYNTAX_ERROR`): with a valid Settings class the helper returns APPLIED, so
    neither the TARGET_MISSING note path nor the SYNTAX_ERROR error path fire.
    The Is->IsNot flips would mis-route a clean APPLIED into those branches."""
    d = _bare_project("fastapi>=0.115.0\n")
    outcome = _patch_config(d / "app" / "core" / "config.py")
    assert outcome is PatchResult.APPLIED
    # APPLIED is none of the alternate outcomes the elif chain checks.
    assert outcome is not PatchResult.TARGET_MISSING
    assert outcome is not PatchResult.SYNTAX_ERROR


def test_specific_config_patch_helper_distinguishes_target_missing():
    """L179 (Is->IsNot): the patch helper returns TARGET_MISSING for a config
    that lacks `class Settings`, which is a DIFFERENT identity from APPLIED.
    (NOTE: the TARGET_MISSING *note* branch in the tool body is upstream-guarded
    by the CONFIG_SETTINGS prerequisite, so it is classified equivalent at the
    tool level; this pins the helper-level discrimination L179 depends on.)"""
    d = Path(tempfile.mkdtemp())
    (d / "app" / "core").mkdir(parents=True)
    # No `class Settings` — only a module-level constant.
    (d / "app" / "core" / "config.py").write_text("DEBUG = True\n")
    outcome = _patch_config(d / "app" / "core" / "config.py")
    assert outcome is PatchResult.TARGET_MISSING
    assert outcome is not PatchResult.APPLIED


def test_specific_config_syntax_error_returns_error():
    """L184 (Is->IsNot): a config.py with a syntax error must abort with
    status='error' and refuse to patch. The Is->IsNot flip would route the
    SYNTAX_ERROR outcome away from the error return."""
    d = Path(tempfile.mkdtemp())
    (d / "app" / "core").mkdir(parents=True)
    (d / "app" / "core" / "config.py").write_text("class Settings(:\n  oops\n")
    (d / "requirements.txt").write_text("fastapi>=0.115.0\n")
    result = add_e2e_test_suite(ToolInput(project_dir=str(d)))
    assert result.status == "error"
    assert "config.py" in (result.error or "")


# ---------------------------------------------------------------------------
# files_modified dedup guard — L199 / L201
# ---------------------------------------------------------------------------


def test_specific_requirements_listed_once_in_files_modified():
    """L199 (BoolOp And) / L201 (`str(...) not in files_modified`): when the
    requirements patch applies, requirements.txt is appended to files_modified
    exactly once (NotIn->In flip would either drop it or duplicate it)."""
    d = _bare_project("fastapi>=0.115.0\n")  # both test deps missing
    result = add_e2e_test_suite(ToolInput(project_dir=str(d)))
    req_entries = [p for p in result.files_modified if p.endswith("requirements.txt")]
    assert len(req_entries) == 1


def test_specific_requirements_not_modified_when_deps_present():
    """L198/L199 (And, requirements only modified when patch returns truthy):
    when all test deps are already declared, requirements.txt must NOT appear
    in files_modified. The And->Or flip would list it despite no write."""
    d = _bare_project("fastapi>=0.115.0\nhttpx>=0.28.0\npytest-asyncio>=0.24.0\n")
    result = add_e2e_test_suite(ToolInput(project_dir=str(d)))
    assert result.status == "success"
    assert not any(p.endswith("requirements.txt") for p in result.files_modified)


# ---------------------------------------------------------------------------
# ast.parse validation loop — L208 (Eq->NotEq, And->Or)
# ---------------------------------------------------------------------------


def test_specific_emitted_python_files_parse_and_are_returned():
    """L206-216 validation loop (L208 guard `p.suffix == ".py" and
    p.is_file()`): every emitted .py file is real, parses, and the tool
    returns success. The created conftest carries the async_client fixture."""
    import ast as _ast

    d = _bare_project("fastapi>=0.115.0\n")
    result = add_e2e_test_suite(ToolInput(project_dir=str(d)))
    assert result.status == "success"
    py_created = [p for p in result.files_created if p.endswith(".py")]
    assert py_created  # at least conftest + flow modules
    for p in py_created:
        text = Path(p).read_text()
        _ast.parse(text)  # must not raise
    conftest = next(p for p in py_created if p.endswith("e2e/conftest.py"))
    assert "async_client" in Path(conftest).read_text()
