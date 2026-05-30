"""Tests for CONTRACT.md §B0.10 — ``no_dead_security_features``.

Three red/green paths + bypass-mechanism path:

1. **Red** — synthetic security tool template carries ``# TODO`` in a
   function body → rule reports violation.
2. **Green (no marker)** — synthetic security tool template has clean
   code → rule reports ok.
3. **Green (waived)** — synthetic security tool declares
   ``_FEATURE_INCOMPLETE`` AND surfaces the gap in ``warnings=`` →
   rule treats the marker as bypassed.
4. **Bypass-mechanism guard** — declaring ``_FEATURE_INCOMPLETE`` but
   disclosing only in ``notes=`` (not ``warnings=``) → rule rejects
   (closes Round-6-S12-F4: agents read notes as success prose).

The rule is exercised via a fresh import that aliases the
``_security_tool_dirs`` callback so we don't have to mutate the real
catalog. Each test installs a temp tree, monkey-patches
``_security_tool_dirs`` to point at it, and calls the rule.

Run:
    PYTHONPATH=. pytest engine/tests/test_b0_10_no_dead_security_features.py -v
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from engine.audit.contract_rules import r_no_dead_security_features as M  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_tool(
    tmp_path: Path,
    name: str,
    *,
    init_body: str,
    templates: dict[str, str] | None = None,
    patches: str | None = None,
) -> Path:
    """Create a synthetic tool directory with __init__.py + templates."""
    tool_dir = tmp_path / name
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "__init__.py").write_text(textwrap.dedent(init_body).lstrip())
    if templates:
        tpl_dir = tool_dir / "templates"
        tpl_dir.mkdir(exist_ok=True)
        for tpl_name, tpl_body in templates.items():
            (tpl_dir / tpl_name).write_text(textwrap.dedent(tpl_body).lstrip())
    if patches is not None:
        (tool_dir / "_patches.py").write_text(textwrap.dedent(patches).lstrip())
    return tool_dir


def _patch_scope(monkeypatch, dirs: list[Path]) -> None:
    monkeypatch.setattr(M, "_security_tool_dirs", lambda: dirs)
    # Also clear waiver set to avoid interference (rules read it
    # from the module global).
    monkeypatch.setattr(M, "_WAIVED_TOOLS", frozenset())


# ---------------------------------------------------------------------------
# 1. RED — TODO in function body
# ---------------------------------------------------------------------------


def test_red_todo_in_function_body_rejects(tmp_path, monkeypatch) -> None:
    tool = _make_tool(
        tmp_path,
        "add_synthetic_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            def add_synthetic_security_feature(inp):
                return ToolResult(status="success")
        """,
        templates={
            "core.py.tmpl": """
                def verify_signature(proof):
                    # TODO: implement HMAC verification
                    return True
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is False, msg
    assert "TODO" in msg
    assert "core.py.tmpl" in msg


# ---------------------------------------------------------------------------
# 2. GREEN — clean implementation passes
# ---------------------------------------------------------------------------


def test_green_clean_template_passes(tmp_path, monkeypatch) -> None:
    tool = _make_tool(
        tmp_path,
        "add_clean_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            def add_clean_security_feature(inp):
                return ToolResult(status="success")
        """,
        templates={
            "core.py.tmpl": """
                import hmac

                def verify_signature(proof: bytes, key: bytes) -> bool:
                    expected = hmac.new(key, proof, "sha256").hexdigest()
                    return hmac.compare_digest(expected, proof.hex())
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is True, msg


# ---------------------------------------------------------------------------
# 3. GREEN (WAIVED) — _FEATURE_INCOMPLETE + warnings= bypass
# ---------------------------------------------------------------------------


def test_green_waived_via_feature_incomplete_and_warnings(
    tmp_path, monkeypatch
) -> None:
    tool = _make_tool(
        tmp_path,
        "add_partial_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            _FEATURE_INCOMPLETE: dict[str, str] = {
                "hmac_verification": (
                    "HMAC verifier requires shared-secret distribution "
                    "infra not in scope for v0.5"
                ),
            }

            def add_partial_security_feature(inp):
                return ToolResult(
                    status="success",
                    warnings=[
                        "hmac_verification not active — see _FEATURE_INCOMPLETE.",
                    ],
                )
        """,
        templates={
            "core.py.tmpl": """
                def hmac_verification(proof):
                    # TODO: requires shared-secret distribution infra
                    return True
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is True, msg


# ---------------------------------------------------------------------------
# 4. BYPASS GUARD — _FEATURE_INCOMPLETE in notes= (NOT warnings=) rejects
# ---------------------------------------------------------------------------


def test_red_feature_incomplete_in_notes_not_warnings_rejects(
    tmp_path, monkeypatch
) -> None:
    tool = _make_tool(
        tmp_path,
        "add_misdisclosed_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            _FEATURE_INCOMPLETE: dict[str, str] = {
                "jti_blocklist": "Redis required; module-level dict for now",
            }

            def add_misdisclosed_security_feature(inp):
                return ToolResult(
                    status="success",
                    notes=["jti_blocklist not active in this build."],
                )
        """,
        templates={
            "core.py.tmpl": """
                def jti_blocklist_check(jti):
                    # TODO: wire Redis blocklist
                    return False
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is False, msg
    assert "warnings=" in msg or "warnings" in msg
    assert "jti_blocklist" in msg


# ---------------------------------------------------------------------------
# 5. SKIP — test templates carrying TODO scaffolding pass
# ---------------------------------------------------------------------------


def test_test_templates_are_skipped(tmp_path, monkeypatch) -> None:
    """Per spec edge case: test templates may carry intentional TODO
    scaffolding for the user to fill in (JWT tokens, fixture data).
    """
    tool = _make_tool(
        tmp_path,
        "add_test_scaffold_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            def add_test_scaffold_security_feature(inp):
                return ToolResult(status="success")
        """,
        templates={
            # name-based skip
            "test_emitted.py.tmpl": """
                import pytest

                def test_owner_can_read():
                    # TODO: real token here
                    assert True
            """,
            # content-based skip — pytest fixture decorator
            "test_block.py.tmpl": """
                @pytest.fixture
                def owner_token() -> str:
                    # TODO: real JWT here
                    return "OWNER_PLACEHOLDER"
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is True, msg


# ---------------------------------------------------------------------------
# 6. SKIP — module-level TODO comment block (documentation) allowed
# ---------------------------------------------------------------------------


def test_module_level_todo_comment_is_allowed(tmp_path, monkeypatch) -> None:
    """Per spec edge case: a module-level comment block describing
    future work AT MODULE LEVEL is documentation; allowed. The
    regression we care about is a TODO INSIDE a function body, which
    means the security path it's documenting does not run.
    """
    tool = _make_tool(
        tmp_path,
        "add_documented_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            def add_documented_security_feature(inp):
                return ToolResult(status="success")
        """,
        templates={
            "core.py.tmpl": """
                # Module overview.
                # TODO(future): consider adding HSM support in v1.0.

                import hmac


                def verify(proof: bytes, key: bytes) -> bool:
                    return hmac.compare_digest(proof, key)
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is True, msg


# ---------------------------------------------------------------------------
# 7. RED — pass-only function body in implementation template
# ---------------------------------------------------------------------------


def test_red_pass_only_function_body_rejects(tmp_path, monkeypatch) -> None:
    tool = _make_tool(
        tmp_path,
        "add_pass_only_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            def add_pass_only_security_feature(inp):
                return ToolResult(status="success")
        """,
        templates={
            "core.py.tmpl": """
                def enforce_signature_check(request):
                    \"\"\"Enforce HMAC signature on incoming request.\"\"\"
                    pass
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is False, msg
    assert "pass" in msg
    assert "enforce_signature_check" in msg


# ---------------------------------------------------------------------------
# 8. ALLOWED — @abstractmethod with pass body is NOT flagged
# ---------------------------------------------------------------------------


def test_abstractmethod_pass_body_is_allowed(tmp_path, monkeypatch) -> None:
    tool = _make_tool(
        tmp_path,
        "add_abstract_security_feature",
        init_body="""
            from adapt.contracts import ToolResult

            def add_abstract_security_feature(inp):
                return ToolResult(status="success")
        """,
        templates={
            "core.py.tmpl": """
                from abc import ABC, abstractmethod


                class SignatureVerifier(ABC):
                    @abstractmethod
                    def verify(self, proof: bytes) -> bool:
                        pass
            """,
        },
    )
    _patch_scope(monkeypatch, [tool])
    ok, msg = M._r_no_dead_security_features()
    assert ok is True, msg


# ---------------------------------------------------------------------------
# 9. SCOPE — real catalog passes (sanity check against shipped code)
# ---------------------------------------------------------------------------


def test_real_catalog_passes_today() -> None:
    """Sanity check: the real catalog scan returns ok at PR-merge time.

    If this test starts failing, a security-tagged tool has regressed
    a TODO/pass placeholder into its implementation template, OR a new
    such regression has landed without the _FEATURE_INCOMPLETE +
    warnings= bypass.
    """
    ok, msg = M._r_no_dead_security_features()
    assert ok is True, msg


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
