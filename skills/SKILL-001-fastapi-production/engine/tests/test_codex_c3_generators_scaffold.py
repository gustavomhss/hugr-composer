"""Codex 3 hunt — generator + scaffold-tool fix regression tests.

One test per closed finding (F-004, F-005, F-006, F-007, F-008, F-012,
F-013, F-014). Each asserts a property of the generated output (or the
tier-1 / server surface) that would have FAILED on pre-fix main —
that's how we keep the audit honest if any of these regresses.

Hunt report: /tmp/codex_hunts/c3_report.md (Phase-2 fix-PR-B scope).
"""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared scaffold fixture — one full project, reused across the cheap
# tests below. ``models`` covers both an owner-bearing + shared variant
# so the BOLA tests have both shapes to assert against.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scaffold_with_auth() -> Path:
    from generators.orchestrator import generate_project

    td = tempfile.mkdtemp(prefix="codex_c3_with_auth_")
    generate_project(
        output_dir=td,
        name="codex_c3",
        models={
            "Product": {"name": "str", "price": "Decimal"},
            "Tag": {"label": "str"},
        },
        owner_models={"Product": "user", "Tag": "user"},
        shared_models={"Tag"},
        profile="full",
        with_auth=True,
    )
    return Path(td)


@pytest.fixture(scope="module")
def scaffold_no_auth() -> Path:
    from generators.orchestrator import generate_project

    td = tempfile.mkdtemp(prefix="codex_c3_no_auth_")
    generate_project(
        output_dir=td,
        name="codex_c3_no_auth",
        models={"Item": {"name": "str", "qty": "int"}},
        profile="api",
        with_auth=False,
    )
    return Path(td)


# ---------------------------------------------------------------------------
# F-004 — Tier-1 scaffold MUST expose shared_models AND actually
# propagate it into the generated project (audit file + emitted tests).
# Pre-fix: fastapi_meta_scaffold accepted owner_models but not
# shared_models, so the BOLA opt-out was unreachable from the primary
# tool surface.
# ---------------------------------------------------------------------------


def test_f004_meta_scaffold_signature_has_shared_models() -> None:
    from mcp_tools.tier1 import fastapi_meta_scaffold

    sig = inspect.signature(fastapi_meta_scaffold)
    assert "shared_models" in sig.parameters, (
        "fastapi_meta_scaffold MUST accept shared_models — F-004 regressed."
    )


def test_f004_meta_scaffold_propagates_shared_models() -> None:
    """End-to-end: meta_scaffold(shared_models=...) writes the audit file."""
    from mcp_tools.tier1 import fastapi_meta_scaffold

    td = tempfile.mkdtemp(prefix="codex_c3_f004_")
    out = fastapi_meta_scaffold(
        output_dir=td,
        name="f004_demo",
        models={
            "Product": {"name": "str"},
            "Tag": {"label": "str"},
        },
        owner_models={"Product": "user", "Tag": "user"},
        shared_models=["Tag"],
        with_auth=True,
    )
    assert out["ok"] is True, out
    audit = Path(td) / "tests" / "test_bola_shared_models.py"
    assert audit.exists(), (
        "shared_models did not propagate from tier-1 scaffold to audit file — F-004 regressed."
    )
    body = audit.read_text(encoding="utf-8")
    assert "'Tag'" in body, body[:400]


# ---------------------------------------------------------------------------
# F-005 — no-auth scaffolds must NOT emit auth-dependent CRUD tests.
# Pre-fix: emitted tests asked for ``superuser_token`` which the
# no-auth conftest does not provide → test collection blows up.
# ---------------------------------------------------------------------------


def test_f005_no_auth_crud_tests_have_no_auth_fixtures(
    scaffold_no_auth: Path,
) -> None:
    test_item = scaffold_no_auth / "tests" / "api" / "routes" / "test_item.py"
    assert test_item.exists()
    body = test_item.read_text(encoding="utf-8")
    assert "superuser_token" not in body, (
        "no-auth scaffold emitted a test depending on the "
        "superuser_token fixture (which the no-auth conftest never "
        "creates) — F-005 regressed."
    )
    assert "Authorization" not in body
    # Sanity: the basic CRUD body is still present.
    assert "test_create_item" in body
    assert "test_list_items" in body


# ---------------------------------------------------------------------------
# F-006 — generated conftest must seed a deterministic SECRET_KEY
# BEFORE importing ``app.main``. Pre-fix: settings instantiation
# raised at import time on missing/short SECRET_KEY, so the emitted
# test suite never even collected on a clean checkout.
# ---------------------------------------------------------------------------


def test_f006_conftest_seeds_secret_key_before_app_import(
    scaffold_with_auth: Path,
) -> None:
    conftest = scaffold_with_auth / "tests" / "conftest.py"
    body = conftest.read_text(encoding="utf-8")

    # Anchor on the actual setdefault call (not a docstring/comment
    # mention of SECRET_KEY) and the actual top-level import statement.
    # Parsing with ast gives us bullet-proof line numbers regardless of
    # how generous the surrounding documentation gets.
    import ast

    tree = ast.parse(body)
    secret_lineno: int | None = None
    app_main_lineno: int | None = None
    for node in tree.body:
        # `os.environ.setdefault("SECRET_KEY", ...)` — an Expr -> Call.
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "setdefault"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "SECRET_KEY"
            ):
                secret_lineno = node.lineno
        # `from app.main import app`
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "app.main"
            and any(alias.name == "app" for alias in node.names)
        ):
            app_main_lineno = node.lineno
    assert secret_lineno is not None, (
        "conftest never calls os.environ.setdefault('SECRET_KEY', ...) "
        "as a top-level statement — F-006 regressed."
    )
    assert app_main_lineno is not None, (
        "conftest never imports app.main as a top-level statement — scaffold shape changed."
    )
    assert secret_lineno < app_main_lineno, (
        f"SECRET_KEY seed at L{secret_lineno} appears AFTER `from "
        f"app.main import app` at L{app_main_lineno} — the Settings "
        f"validator fires before the seed lands. F-006 regressed."
    )
    # The seeded key must clear the production-grade 32-char floor or
    # the test setup itself raises in Settings._enforce_security_contract.
    # Re-walk the AST to extract the second argument and fold any
    # implicit string concatenation literal-by-literal.
    seed_value: str | None = None
    for node in tree.body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "setdefault"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "SECRET_KEY"
        ):
            continue
        value_node = call.args[1]
        # Python parses adjacent string literals as a single Constant,
        # so a Constant is the common case.
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            seed_value = value_node.value
        break
    assert isinstance(seed_value, str) and len(seed_value) >= 32, (
        f"seeded SECRET_KEY only "
        f"{len(seed_value) if isinstance(seed_value, str) else '??'} "
        f"chars — Settings requires >=32. F-006 regressed."
    )


# ---------------------------------------------------------------------------
# F-007 — owner-bearing models must ship a BOLA regression test; shared
# models must ship the open-access counterpart. Pre-fix: emitted CRUD
# tests only exercised superuser happy paths.
# ---------------------------------------------------------------------------


def test_f007_emitted_tests_cover_bola_owner_guard(
    scaffold_with_auth: Path,
) -> None:
    # Product is owner-bearing + NOT shared → secure-by-default 403.
    product = scaffold_with_auth / "tests" / "api" / "routes" / "test_product.py"
    assert product.exists()
    p_body = product.read_text(encoding="utf-8")
    assert "test_product_bola_non_owner_denied" in p_body, (
        "owner-bearing model missing non-owner-403 regression — "
        "F-007 regressed (secure-by-default branch)."
    )
    assert "assert response.status_code == 403" in p_body

    # Tag is owner-bearing + IS shared → open-access (non-owner gets 200).
    tag = scaffold_with_auth / "tests" / "api" / "routes" / "test_tag.py"
    assert tag.exists()
    t_body = tag.read_text(encoding="utf-8")
    assert "test_tag_shared_model_open_access" in t_body, (
        "shared model missing open-access regression — F-007 regressed (BOLA opt-out branch)."
    )


# ---------------------------------------------------------------------------
# F-008 — password policy must be APPLIED, not just declared. The
# emitted NewPassword + UpdatePassword + UserCreate schemas must all
# bind ``password_strength_validator`` to their password field(s).
# ---------------------------------------------------------------------------


def test_f008_password_policy_applied_to_real_inputs(
    scaffold_with_auth: Path,
) -> None:
    token = scaffold_with_auth / "app" / "schemas" / "token.py"
    user = scaffold_with_auth / "app" / "schemas" / "user.py"
    routes = scaffold_with_auth / "app" / "api" / "routes" / "users.py"

    for path, label in (
        (token, "NewPassword (token.py)"),
        (user, "UserCreate (user.py)"),
        (routes, "UpdatePassword (users.py)"),
    ):
        assert path.exists(), f"{label} missing — generator shape changed."
        body = path.read_text(encoding="utf-8")
        assert "password_strength_validator" in body, (
            f"{label} does not bind password_strength_validator — F-008 regressed."
        )


# ---------------------------------------------------------------------------
# F-012 — server instructions must be DERIVED from the registered
# tier-1 surface + catalog. Pre-fix: a hand-maintained block named
# ``fastapi_generate_project`` and ``fastapi_analyze`` (both retired)
# plus a stale "35 checks" / "56 tools" advertisement.
# ---------------------------------------------------------------------------


def test_f012_server_instructions_have_no_retired_tool_names() -> None:
    from mcp_tools import server

    instr = server.mcp.instructions or ""
    for retired in (
        "fastapi_generate_project",
        "fastapi_analyze",
        "fastapi_add_soft_delete",  # was hardcoded as a representative example
        "fastapi_doctor",
    ):
        assert retired not in instr, (
            f"server instructions still advertise retired tool {retired!r} — F-012 regressed."
        )
    # The instructions must point at a live tier-1 entry point.
    assert "fastapi_meta_home" in instr, (
        "server instructions no longer mention fastapi_meta_home — "
        "the agent has no documented entry point."
    )


def test_f012_server_instructions_cite_live_catalog_counts() -> None:
    import json

    from mcp_tools import server

    instr = server.mcp.instructions or ""
    skill_root = Path(server.__file__).resolve().parents[1]
    catalog = json.loads(
        (skill_root / "engine" / "index" / "catalog.json").read_text(
            encoding="utf-8",
        ),
    )
    tools_total = int(
        catalog["counts"].get("tools_total", catalog["counts"].get("tools", 0)),
    )
    assert str(tools_total) in instr, (
        f"server instructions do not cite live catalog tool count "
        f"({tools_total}) — F-012 advertised-vs-real drift may regress."
    )


# ---------------------------------------------------------------------------
# F-013 — input_schema must NOT claim ``strict=True`` while emitting
# only ``extra="forbid"``. Pre-fix: docstring + notes both lied.
# ---------------------------------------------------------------------------


def test_f013_input_schema_does_not_advertise_strict_true() -> None:
    """Generator must not lie about strict-mode. Emitted notes + actual
    ConfigDict must agree: ``extra="forbid"``, NO ``strict=True``.
    """
    from generators.schemas.input_schema import generate_input_schema

    td = tempfile.mkdtemp(prefix="codex_c3_f013_")
    res = generate_input_schema(
        output_dir=td,
        name="Widget",
        fields={"name": "str", "price": "int"},
    )
    # Notes: must NOT claim strict=True; must claim extra="forbid".
    notes_blob = " ".join(res.get("notes", []))
    assert "strict=True" not in notes_blob, (
        f"input_schema notes still advertise strict=True — F-013 regressed: {notes_blob!r}"
    )
    assert 'extra="forbid"' in notes_blob or 'extra=\\"forbid\\"' in notes_blob

    # Emitted file: ConfigDict must NOT carry strict=True.
    emitted = Path(res["files_created"][0]).read_text(encoding="utf-8")
    assert "strict=True" not in emitted, (
        "emitted schema carries strict=True (changes Pydantic coercion) — F-013 regressed."
    )
    assert 'ConfigDict(extra="forbid")' in emitted


# ---------------------------------------------------------------------------
# F-014 — JWT password-reset TTL and the user-facing email copy must
# come from the same constant. Pre-fix: token was 60 min, email said
# 30 min.
# ---------------------------------------------------------------------------


def test_f014_password_reset_ttl_consistent(scaffold_with_auth: Path) -> None:
    from generators.auth.jwt import PASSWORD_RESET_TOKEN_EXPIRE_MINUTES

    jwt_path = scaffold_with_auth / "app" / "core" / "jwt.py"
    email_path = scaffold_with_auth / "app" / "utils" / "email.py"
    assert jwt_path.exists() and email_path.exists()

    jwt_body = jwt_path.read_text(encoding="utf-8")
    email_body = email_path.read_text(encoding="utf-8")

    # JWT module embeds the constant.
    assert (
        f"PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = {PASSWORD_RESET_TOKEN_EXPIRE_MINUTES}" in jwt_body
    ), (
        "core/jwt.py does not embed the canonical "
        "PASSWORD_RESET_TOKEN_EXPIRE_MINUTES constant — F-014 regressed."
    )
    # The email template must advertise the same lifetime.
    assert f"expire in {PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes" in email_body, (
        "Password-reset email advertises a TTL that differs from the JWT module — F-014 regressed."
    )
