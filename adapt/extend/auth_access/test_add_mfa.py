"""Structural + honesty-regression tests for TOOL-013 ``add_mfa``.

Structural tests (CONTRACT §B1.0 + §B1.0.1):
- Copy TotpVerifier primitive + TotpVerifierAdapter into generated project.
- Emit app/mfa.py shim (install_mfa / get_verifier / verify_code).

Honesty regression tests (P0 fix — "reports success while enforcing NOTHING"):
- ToolResult.warnings MUST lead with "⚠ MFA IS NOT ENFORCED:" on every
  success path (both normal run and dry_run) — an LLM driver reading
  status="success" must immediately see that MFA is not active.
- Example file app/api/routes/_mfa_example.py MUST be emitted and contain
  the actual verify_code wiring step (not just a stub).
- Missing user-model fields (totp_secret, totp_last_step) must be documented.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_mfa import _WARN_NOT_AUTO_ENFORCED, MCP_TOOL, add_mfa
from tests.common.fixture_factory import create_fixture_project


def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_success_status() -> None:
    p = create_fixture_project(name="mfa_t01")
    r = add_mfa(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    p = create_fixture_project(name="mfa_t02")
    add_mfa(ToolInput(project_dir=str(p)))
    assert add_mfa(ToolInput(project_dir=str(p))).status == "no_op"


def test_dry_run_writes_nothing() -> None:
    p = create_fixture_project(name="mfa_t03")
    before = {f: f.read_text() for f in _all_py(p)}
    add_mfa(ToolInput(project_dir=str(p), dry_run=True))
    after = {f: f.read_text() for f in _all_py(p)}
    assert before == after


def test_primitive_copied() -> None:
    p = create_fixture_project(name="mfa_t04")
    add_mfa(ToolInput(project_dir=str(p)))
    prim = p / "core" / "venous" / "auth" / "TotpVerifier" / "TotpVerifier.py"
    assert prim.exists()
    assert "class StandardTotpVerifier" in prim.read_text()


def test_adapter_copied() -> None:
    p = create_fixture_project(name="mfa_t05")
    add_mfa(ToolInput(project_dir=str(p)))
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "TotpVerifierAdapter.py"
    assert adapter.exists()
    assert "def verify_code(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    p = create_fixture_project(name="mfa_t06")
    add_mfa(ToolInput(project_dir=str(p)))
    m = json.loads((p / ".venous_manifest.json").read_text())
    assert "core.venous.auth.TotpVerifier" in {x["qualified_name"] for x in m["primitives"]}
    assert "core.venous._adapters.fastapi.TotpVerifierAdapter" in {x["qualified_name"] for x in m["adapters"]}


def test_glue_imports_adapter() -> None:
    p = create_fixture_project(name="mfa_t07")
    add_mfa(ToolInput(project_dir=str(p)))
    body = (p / "app" / "mfa.py").read_text()
    assert "from core.venous._adapters.fastapi.TotpVerifierAdapter import" in body
    assert "install_mfa" in body


def test_glue_under_20_loc_body() -> None:
    p = create_fixture_project(name="mfa_t08")
    add_mfa(ToolInput(project_dir=str(p)))
    glue = p / "app" / "mfa.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines += (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
    assert body_lines <= 20


def test_mcp_tool_lists_imports() -> None:
    assert "core.venous.auth.TotpVerifier" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.TotpVerifierAdapter" in MCP_TOOL["imports_adapters"]


def test_execution_time_recorded() -> None:
    p = create_fixture_project(name="mfa_t10")
    assert add_mfa(ToolInput(project_dir=str(p))).execution_time_ms > 0


# ---------------------------------------------------------------------------
# Honesty P0 regression tests — MFA IS NOT ENFORCED must be unmissable
# ---------------------------------------------------------------------------

def test_result_warns_mfa_not_enforced() -> None:
    """ToolResult.warnings MUST lead with 'MFA IS NOT ENFORCED' on success.

    The old implementation returned status='success' with warnings=[] (empty),
    letting LLM drivers and developers assume MFA was active. This regression
    test ensures the warning is always present and uses the exact P0 prefix.
    """
    p = create_fixture_project(name="mfa_t11")
    r = add_mfa(ToolInput(project_dir=str(p)))
    assert r.status == "success"
    assert r.warnings, "ToolResult.warnings must not be empty — MFA is NOT enforced"
    first_warning = r.warnings[0]
    assert "MFA IS NOT ENFORCED" in first_warning, (
        f"First warning must contain 'MFA IS NOT ENFORCED'; got: {first_warning!r}"
    )


def test_dry_run_result_also_warns_mfa_not_enforced() -> None:
    """dry_run result must also carry the not-enforced warning."""
    p = create_fixture_project(name="mfa_t12")
    r = add_mfa(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "success"
    assert r.warnings, "dry_run ToolResult.warnings must not be empty"
    first_warning = r.warnings[0]
    assert "MFA IS NOT ENFORCED" in first_warning, (
        f"dry_run first warning must contain 'MFA IS NOT ENFORCED'; got: {first_warning!r}"
    )


def test_warn_not_auto_enforced_constant_uses_symbol_prefix() -> None:
    """The warning constant must use the ⚠ symbol and all-caps 'MFA IS NOT ENFORCED'.

    This prevents softening the warning to something that LLM parsers might
    interpret as 'MFA is configured and ready'.
    """
    assert "⚠" in _WARN_NOT_AUTO_ENFORCED, (
        "Warning must start with ⚠ so LLM parsers cannot miss it"
    )
    assert "MFA IS NOT ENFORCED" in _WARN_NOT_AUTO_ENFORCED, (
        "Warning must contain 'MFA IS NOT ENFORCED' verbatim"
    )


def test_mfa_example_file_is_emitted() -> None:
    """add_mfa must emit app/api/routes/_mfa_example.py alongside app/mfa.py.

    A warning alone is insufficient: an LLM driver or developer needs a
    concrete, runnable snippet showing exactly where to call verify_code
    in the login flow.
    """
    p = create_fixture_project(name="mfa_t13")
    result = add_mfa(ToolInput(project_dir=str(p)))
    assert result.status == "success"
    example = p / "app" / "api" / "routes" / "_mfa_example.py"
    assert example.exists(), (
        "add_mfa must emit app/api/routes/_mfa_example.py — "
        "the concrete wired-example file was not found"
    )


def test_mfa_example_file_parses() -> None:
    """The emitted MFA example file must parse without syntax errors."""
    p = create_fixture_project(name="mfa_t14")
    add_mfa(ToolInput(project_dir=str(p)))
    example = p / "app" / "api" / "routes" / "_mfa_example.py"
    try:
        ast.parse(example.read_text())
    except SyntaxError as exc:
        raise AssertionError(f"_mfa_example.py has syntax error: {exc}") from exc


def test_mfa_example_contains_verify_code_wiring() -> None:
    """The example must contain the actual verify_code call — not just imports."""
    p = create_fixture_project(name="mfa_t15")
    add_mfa(ToolInput(project_dir=str(p)))
    body = (p / "app" / "api" / "routes" / "_mfa_example.py").read_text()
    assert "verify_code" in body, (
        "_mfa_example.py must contain a verify_code call"
    )
    assert "totp_secret" in body or "secret" in body, (
        "_mfa_example.py must reference the TOTP secret field"
    )
    assert "last_step" in body, (
        "_mfa_example.py must reference last_step for anti-replay"
    )


def test_mfa_example_in_files_created() -> None:
    """The example file path must appear in ToolResult.files_created."""
    p = create_fixture_project(name="mfa_t16")
    result = add_mfa(ToolInput(project_dir=str(p)))
    assert any("_mfa_example.py" in f for f in (result.files_created or [])), (
        f"_mfa_example.py not in files_created; got: {result.files_created}"
    )


def test_glue_docstring_documents_missing_user_fields() -> None:
    """app/mfa.py must document the user-model fields that MUST be added.

    Without totp_secret and totp_last_step on the user model, MFA cannot
    work. The glue docstring must name these fields explicitly so developers
    don't miss them.
    """
    p = create_fixture_project(name="mfa_t17")
    add_mfa(ToolInput(project_dir=str(p)))
    glue_text = (p / "app" / "mfa.py").read_text()
    assert "totp_secret" in glue_text, (
        "app/mfa.py must document the missing totp_secret user-model field"
    )
    assert "totp_last_step" in glue_text or "last_step" in glue_text, (
        "app/mfa.py must document the missing last_step user-model field"
    )
    assert "MFA IS NOT ENFORCED" in glue_text, (
        "app/mfa.py docstring must repeat the NOT-ENFORCED notice"
    )


if __name__ == "__main__":
    tests = [
        test_success_status, test_idempotent, test_dry_run_writes_nothing,
        test_primitive_copied, test_adapter_copied, test_manifest_records_provenance,
        test_glue_imports_adapter, test_glue_under_20_loc_body, test_mcp_tool_lists_imports,
        test_execution_time_recorded,
        # Honesty P0 regression tests
        test_result_warns_mfa_not_enforced,
        test_dry_run_result_also_warns_mfa_not_enforced,
        test_warn_not_auto_enforced_constant_uses_symbol_prefix,
        test_mfa_example_file_is_emitted,
        test_mfa_example_file_parses,
        test_mfa_example_contains_verify_code_wiring,
        test_mfa_example_in_files_created,
        test_glue_docstring_documents_missing_user_fields,
    ]
    p = f = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); p += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); f += 1
    print(f"\n{p}/{p+f} passed")
    sys.exit(0 if not f else 1)
