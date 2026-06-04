"""Tests for TOOL-017 add_websocket_chat.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_websocket_chat.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_websocket_chat.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_websocket_chat import (
    _patch_config,
    _patch_main,
    _patch_routes_init,
    add_websocket_chat,
)
from tests.common.fixture_factory import create_fixture_project


def _bare_project() -> Path:
    """A valid (existing) dir MISSING config/requirements prereqs.

    Exercises the auto-scaffold and prerequisite-error code paths.
    """
    d = Path(tempfile.mkdtemp()) / "bare"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and hasattr(node, "end_lineno")
                and node.end_lineno
            ):
                loc = node.end_lineno - node.lineno + 1
                max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="wsc_t01")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="wsc_t02")
    r1 = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="wsc_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 7 new files (models, schemas, crud, ws, routes, migration)."""
    project_dir = create_fixture_project(name="wsc_t04")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 7, (
        f"Expected >= 7 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init)."""
    project_dir = create_fixture_project(name="wsc_t05")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------


def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="wsc_t06")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="wsc_t07")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected WEBSOCKET_CHAT_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="wsc_t08")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER",
        "WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH",
        "WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER" in line:
            assert line.startswith("    "), (
                f"WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER not inside class body "
                f"(no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """ChatRoom and ChatMessage are registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="wsc_t09")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "ChatRoom" in content, "ChatRoom not registered in models __init__"
    assert "ChatMessage" in content, "ChatMessage not registered in models __init__"


def test_routes_registered() -> None:
    """Chat HTTP routes are registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="wsc_t10")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "chat" in content.lower(), "Chat router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------


def test_ws_chat_endpoint_file_created() -> None:
    """app/ws/chat.py exists with WebSocketManager references."""
    project_dir = create_fixture_project(name="wsc_t11")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "chat.py"
    assert ws_file.exists(), "app/ws/chat.py not created"
    content = ws_file.read_text()
    assert "WebSocketManager" in content


def test_connection_manager_created() -> None:
    """app/ws/connection_manager.py exists with WebSocketManager."""
    project_dir = create_fixture_project(name="wsc_t12")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "ws" / "connection_manager.py"
    assert manager_file.exists(), "connection_manager.py not created"
    content = manager_file.read_text()
    assert "WebSocketManager" in content
    assert "publish" in content or "broadcast" in content


def test_chat_models_created() -> None:
    """app/models/chat.py exists with ChatRoom and ChatMessage classes."""
    project_dir = create_fixture_project(name="wsc_t13")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "chat.py"
    assert model_file.exists(), "app/models/chat.py not created"
    content = model_file.read_text()
    assert "ChatRoom" in content, "ChatRoom model not found"
    assert "ChatMessage" in content, "ChatMessage model not found"


def test_chat_schemas_created() -> None:
    """app/schemas/chat.py exists with Pydantic schemas."""
    project_dir = create_fixture_project(name="wsc_t14")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "chat.py"
    assert schema_file.exists(), "app/schemas/chat.py not created"
    content = schema_file.read_text()
    assert "ChatMessageIn" in content or "ChatMessage" in content


def test_chat_crud_created() -> None:
    """app/crud/chat.py exists with CRUD helpers."""
    project_dir = create_fixture_project(name="wsc_t15")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "chat.py"
    assert crud_file.exists(), "app/crud/chat.py not created"
    content = crud_file.read_text()
    assert "async def" in content, "CRUD file must have async functions"


def test_http_companion_routes() -> None:
    """app/api/routes/chat.py exists with HTTP companion routes."""
    project_dir = create_fixture_project(name="wsc_t16")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "chat.py"
    assert route_file.exists(), "app/api/routes/chat.py not created"
    content = route_file.read_text()
    assert "room" in content.lower(), "Chat routes must reference rooms"


def test_tenant_conditional_fk_with_tenants() -> None:
    """When add_multi_tenancy is applied first, ChatRoom has tenant_id FK."""
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy

    project_dir = create_fixture_project(name="wsc_t17")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "chat.py"
    content = model_file.read_text()
    assert "tenant" in content.lower(), "ChatRoom must have tenant_id when tenants exist"
    assert "ForeignKey" in content, "tenant_id must be a ForeignKey when tenants exist"


def test_tenant_conditional_fk_without_tenants() -> None:
    """Without multi_tenancy, no FK to tenants.id."""
    project_dir = create_fixture_project(name="wsc_t18")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "chat.py"
    content = model_file.read_text()
    # Should not have ForeignKey("tenants.id") — either no FK at all, or plain column
    assert 'ForeignKey("tenants.id"' not in content, (
        "tenant_id must NOT have ForeignKey to tenants.id when tenants table absent"
    )


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="wsc_t19")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should mention Redis and alembic."""
    project_dir = create_fixture_project(name="wsc_t20")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "redis" in combined, "next_steps should mention Redis"
    assert "alembic" in combined, "next_steps should mention alembic"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="wsc_t21")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Category D — Mutation hardening
# ---------------------------------------------------------------------------


def test_execution_time_within_sane_bound() -> None:
    """execution_time_ms is a small positive number, not a monotonic blow-up.

    Guards ``_ms`` against a ``monotonic() - start`` -> ``+`` mutation, which
    would still be > 0 but absurdly large.
    """
    project_dir = create_fixture_project(name="wsc_m01")
    ms = add_websocket_chat(ToolInput(project_dir=str(project_dir))).execution_time_ms
    assert 0 < ms < 60_000, f"implausible execution_time_ms={ms}"


def test_auto_scaffolds_missing_prereqs() -> None:
    """A bare project (no config/requirements) is auto-scaffolded on a real run.

    Guards ``auto_scaffold=not inp.dry_run`` (L75 UnaryNot: drop the ``not`` ->
    no scaffold -> error) and ``files_created = list(scaffolded or [])`` (L85
    BoolOp Or->And: scaffolded files silently dropped from the report).
    """
    p = _bare_project()
    r = add_websocket_chat(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    created = set(r.files_created)
    # scaffolded config.py must be reported (guards L85 ``scaffolded or []``).
    assert any(c.endswith("config.py") for c in created), created
    # physically scaffolded (without auto_scaffold these never exist).
    assert (p / "app" / "core" / "config.py").exists()
    assert (p / "requirements.txt").exists()


def test_missing_prereqs_dry_run_reports_error() -> None:
    """dry_run on a bare project: auto_scaffold OFF, so prereqs are missing.

    Guards the error-message ``+`` concat path (a ``+`` -> ``-`` mutation would
    raise ``TypeError`` instead of returning the error result).
    """
    p = _bare_project()
    r = add_websocket_chat(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "error"
    assert "Prerequisites not met" in (r.error or "")


def test_ws_init_created_and_reported() -> None:
    """app/ws/__init__.py is written on a fresh run and reported.

    Guards L140 ``if not ws_init.exists()`` UnaryNot: flipping ``not`` would
    skip creation, leaving the WS sub-package without an __init__.
    """
    project_dir = create_fixture_project(name="wsc_m02")
    r = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    ws_init = project_dir / "app" / "ws" / "__init__.py"
    assert ws_init.exists(), "app/ws/__init__.py not created"
    assert str(ws_init) in r.files_created, "ws/__init__.py not reported in files_created"


def test_redis_module_created_and_reported() -> None:
    """app/core/redis.py is written on a fresh run and reported.

    Guards L190 ``if not redis_module.exists()`` UnaryNot: flipping ``not``
    would skip creating the redis module.
    """
    project_dir = create_fixture_project(name="wsc_m03")
    r = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    redis_module = project_dir / "app" / "core" / "redis.py"
    assert redis_module.exists(), "app/core/redis.py not created"
    assert str(redis_module) in r.files_created, "redis.py not reported in files_created"


def test_emitted_project_test_created_and_reported() -> None:
    """tests/test_add_websocket_chat_emitted.py is written and reported.

    Guards L243 ``if not emitted.exists()`` UnaryNot: flipping ``not`` would
    skip emitting the project test.
    """
    project_dir = create_fixture_project(name="wsc_m04")
    r = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    emitted = project_dir / "tests" / "test_add_websocket_chat_emitted.py"
    assert emitted.exists(), "emitted project test not created"
    assert str(emitted) in r.files_created, "emitted test not reported in files_created"


def test_migration_down_revision_is_real_head() -> None:
    """The migration's down_revision is the real Alembic head, not a fallback.

    Guards L158 ``find_migration_head(...) or "0001_initial"`` BoolOp Or->And:
    ``and`` would yield the literal "0001_initial" (head is truthy), pointing
    the new migration at the wrong parent.
    """
    project_dir = create_fixture_project(name="wsc_m05")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    mig = project_dir / "alembic" / "versions" / "0017_add_websocket_chat.py"
    content = mig.read_text()
    assert 'down_revision = "0002_baseline_schema"' in content, (
        f"down_revision not pinned to real head:\n{content}"
    )


def test_config_block_inserted_after_anchor() -> None:
    """The WEBSOCKET_CHAT block lands right after the ACCESS_TOKEN anchor.

    Guards L272 ``if anchor in src`` Compare In->NotIn: NotIn skips the
    anchor-replacement branch, so the block would instead be dumped before
    ``settings = Settings()`` far from the anchor.
    """
    project_dir = create_fixture_project(name="wsc_m06")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    field = "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER"
    a_idx = content.find(anchor)
    f_idx = content.find(field)
    assert a_idx != -1 and f_idx != -1
    # Block must follow the anchor closely (it is inserted right after it).
    assert 0 < (f_idx - a_idx) < 200, (
        f"WEBSOCKET block not adjacent to anchor (anchor={a_idx}, field={f_idx})"
    )


def test_config_block_uses_settings_fallback_branch() -> None:
    """With the anchor absent, the block is placed BEFORE ``settings = Settings()``.

    Guards L274 ``elif "settings = Settings()" in src`` Compare In->NotIn:
    NotIn skips that branch, dumping the block at end-of-file (after
    ``settings = Settings()``) instead.
    """
    project_dir = create_fixture_project(name="wsc_m07")
    config_file = project_dir / "app" / "core" / "config.py"
    # Remove the primary anchor so _patch_config takes the elif branch.
    config_file.write_text(
        config_file.read_text().replace(
            "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30",
            "ACCESS_TOKEN_EXPIRE_MINUTES: int = 99",
        )
    )
    r = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    content = config_file.read_text()
    f_idx = content.find("WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER")
    s_idx = content.find("settings = Settings()")
    assert f_idx != -1 and s_idx != -1
    assert f_idx < s_idx, "WEBSOCKET block must precede settings = Settings()"


def test_routes_import_ordered_after_last_app_import() -> None:
    """Chat router import lands after the last ``from app.`` import, before APIRouter().

    Guards L288 ``if last_app == -1`` Eq->NotEq (would recompute the anchor and
    insert after APIRouter()) and L290 ``last_app + 1`` BinOp Add->Sub (would
    insert before the last existing import).
    """
    project_dir = create_fixture_project(name="wsc_m08")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "app" / "routes" / "__init__.py").read_text()
    chat_imp = src.find("from app.api.routes.chat import router as chat_router")
    health_imp = src.find("from app.routes.health import router as health_router")
    apirouter = src.find("api_router = APIRouter()")
    assert chat_imp != -1, "chat router import not added"
    assert chat_imp > health_imp, "chat import must follow the last from-app import (L290)"
    assert chat_imp < apirouter, "chat import must precede APIRouter() (L288)"


def test_routes_include_ordered_after_last_include() -> None:
    """Chat include lands after the last existing ``api_router.include_router``.

    Guards L294 ``if last_inc == -1`` Eq->NotEq (would insert right after
    APIRouter(), before the other includes) and L296 ``last_inc + 1`` BinOp
    Add->Sub (would insert before the last existing include).
    """
    project_dir = create_fixture_project(name="wsc_m09")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "app" / "routes" / "__init__.py").read_text()
    chat_inc = src.find("api_router.include_router(chat_router)")
    item_inc = src.find("api_router.include_router(item_router)")
    assert chat_inc != -1, "chat include not added"
    assert item_inc != -1
    assert chat_inc > item_inc, "chat include must follow the last existing include (L294/L296)"


def test_main_mounts_ws_chat_router() -> None:
    """app/main.py imports and mounts the WS chat router, and is reported modified.

    Guards L185 ``main_file.exists() and _patch_main(...)`` BoolOp And->Or
    (``or`` short-circuits before patching), L302 ``if "...ws_chat_router" in
    src`` In->NotIn (early bail), L306 ``last_from_app == -1`` Eq->NotEq, L312
    ``inc == -1`` Eq->NotEq, and L316 ``return True`` BoolLiteral (False would
    drop main.py from files_modified).
    """
    project_dir = create_fixture_project(name="wsc_m10")
    r = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    # _patch_main must actually run and rewrite the file (L185/L302/L306/L312).
    assert "from app.ws.chat import router as ws_chat_router" in content, (
        "ws chat router import missing from main.py"
    )
    assert "app.include_router(ws_chat_router)" in content, "ws_chat_router not mounted in main.py"
    # _patch_main must return True so main.py is reported modified (L316).
    assert str(main_file) in r.files_modified, "main.py not reported in files_modified"


# ---------------------------------------------------------------------------
# Category E — Mutation hardening (helper-level + requirements dedup)
# ---------------------------------------------------------------------------


def test_redis_requirement_not_duplicated_when_present() -> None:
    """``redis`` already in requirements.txt must NOT be appended again.

    Guards L198 ``if "redis" not in src`` Compare NotIn->In: flipping ``not in``
    to ``in`` re-appends ``redis[hiredis]`` whenever redis is already declared,
    yielding a duplicate dependency line.
    """
    project_dir = create_fixture_project(name="wsc_m11")
    req = project_dir / "requirements.txt"
    # Normalise to a single, known redis line so the dedup assertion is exact.
    lines = [ln for ln in req.read_text().splitlines() if "redis" not in ln]
    lines.append("redis[hiredis]>=5.2.0")
    req.write_text("\n".join(lines) + "\n")
    before = req.read_text()
    redis_lines_before = [ln for ln in before.splitlines() if "redis" in ln]
    assert len(redis_lines_before) == 1, "test setup must leave exactly one redis line"
    r = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    after = req.read_text()
    assert after == before, f"redis requirement was modified despite already present:\n{after}"
    redis_lines_after = [ln for ln in after.splitlines() if "redis" in ln]
    assert len(redis_lines_after) == 1, f"redis dependency duplicated:\n{after}"


def test_redis_requirement_added_when_absent() -> None:
    """``redis`` absent from requirements.txt must be appended exactly once.

    Complements the dedup test: confirms the NotIn branch still fires (the add
    path) so the Compare guard is asserted in both directions.
    """
    project_dir = create_fixture_project(name="wsc_m12")
    req = project_dir / "requirements.txt"
    req.write_text("fastapi\nuvicorn\n")  # no redis at all
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    after = req.read_text()
    redis_lines = [ln for ln in after.splitlines() if "redis[hiredis]" in ln]
    assert len(redis_lines) == 1, f"redis dependency not added exactly once:\n{after}"


def test_patch_main_bails_when_import_already_present() -> None:
    """``_patch_main`` returns False (no change) if the WS import is already there.

    Guards L303 ``return False`` BoolLiteral False->True: True would report a
    spurious modification (and re-insert) even though the file is untouched.
    """
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    original = (
        "from app.ws.chat import router as ws_chat_router\n"
        "app = FastAPI()\n"
        "app.include_router(ws_chat_router)\n"
    )
    mf.write_text(original)
    assert _patch_main(mf) is False, "already-wired main.py must report no change"
    assert mf.read_text() == original, "already-wired main.py must be left untouched"


def test_patch_main_bails_when_no_from_app_import() -> None:
    """``_patch_main`` returns False when there is no ``from app.`` anchor import.

    Guards L307 ``return False`` BoolLiteral False->True (True would claim a
    modification that never happened) and the file must remain byte-identical.
    """
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    original = "import os\napp = FastAPI()\n"
    mf.write_text(original)
    assert _patch_main(mf) is False, "main.py without a from-app import must report no change"
    assert mf.read_text() == original, "file must be untouched when no from-app anchor exists"


def test_patch_main_bails_when_no_mount_anchor() -> None:
    """``_patch_main`` returns False when neither include_router nor FastAPI() exists.

    Guards L313 ``return False`` BoolLiteral False->True. There is a ``from app.``
    line (so it gets past L307 and inserts the import) but no place to mount, so
    the function must back out with False.
    """
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    mf.write_text("from app.core.config import settings\nx = 1\n")
    assert _patch_main(mf) is False, "main.py without a mount anchor must report no change"


def test_patch_main_import_before_app_and_include_after() -> None:
    """Normal patch: import lands AFTER the last from-app, include AFTER FastAPI/mount.

    Guards L308 ``last_from_app + 1`` BinOp Add->Sub (Sub inserts the import
    before the last existing from-app import) and L314 ``inc + 1`` BinOp Add->Sub
    (Sub mounts the router before the anchor line). Also guards L309/L311
    In->NotIn for the mount-anchor search.
    """
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    mf.write_text(
        "from app.a import b\n"
        "from app.c import dd\n"
        "app = FastAPI()\n"
        "app.include_router(health_router)\n"
    )
    assert _patch_main(mf) is True
    lines = mf.read_text().splitlines()
    last_from_app = max(i for i, ln in enumerate(lines) if ln == "from app.c import dd")
    import_idx = next(i for i, ln in enumerate(lines) if "ws_chat_router" in ln and "import" in ln)
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(ws_chat_router)" in ln)
    health_idx = next(i for i, ln in enumerate(lines) if "include_router(health_router)" in ln)
    # L308: import must come AFTER the last from-app import (Sub would put it before).
    assert import_idx == last_from_app + 1, f"import not right after last from-app: {lines}"
    # L314 / L309: the WS include must follow the existing health include.
    assert include_idx > health_idx, f"ws include must come after existing includes: {lines}"


def test_patch_main_uses_fastapi_anchor_when_no_include() -> None:
    """When no include_router exists, the mount falls back to the ``= FastAPI(`` line.

    Guards L311 ``"= FastAPI(" in ln`` Compare In->NotIn: NotIn would match the
    wrong (non-FastAPI) lines and mount in the wrong place / fail.
    """
    d = Path(tempfile.mkdtemp())
    mf = d / "main.py"
    mf.write_text('from app.x import y\napp = FastAPI(title="t")\nother = 1\n')
    assert _patch_main(mf) is True
    lines = mf.read_text().splitlines()
    fastapi_idx = next(i for i, ln in enumerate(lines) if "= FastAPI(" in ln)
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(ws_chat_router)" in ln)
    assert include_idx == fastapi_idx + 1, f"include not mounted right after FastAPI(): {lines}"


def test_patch_routes_fallback_inserts_after_apirouter() -> None:
    """With no ``from app.`` imports, both lines land after ``api_router = APIRouter()``.

    Guards L289 ``"APIRouter()" in ln`` and L295 ``"APIRouter()" in ln`` Compare
    In->NotIn in the fallback anchor search: NotIn would match the wrong line and
    insert the import/include before ``APIRouter()`` (or in the wrong spot).
    """
    d = Path(tempfile.mkdtemp())
    ri = d / "__init__.py"
    ri.write_text("from fastapi import APIRouter\napi_router = APIRouter()\n")
    _patch_routes_init(
        ri,
        "from app.api.routes.chat import router as chat_router",
        "api_router.include_router(chat_router)",
    )
    lines = ri.read_text().splitlines()
    apirouter_idx = next(i for i, ln in enumerate(lines) if "api_router = APIRouter()" in ln)
    import_idx = next(i for i, ln in enumerate(lines) if "import router as chat_router" in ln)
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(chat_router)" in ln)
    assert import_idx > apirouter_idx, f"import must follow APIRouter() in fallback: {lines}"
    assert include_idx > apirouter_idx, f"include must follow APIRouter() in fallback: {lines}"


def test_patch_config_fallback_appends_block_at_end() -> None:
    """No anchor and no ``settings = Settings()``: block is appended at end-of-file.

    Guards L279 ``src.rstrip("\\n") + "\\n" + block`` BinOp Add->Sub: a ``-``
    mutation makes ``str - str`` raise TypeError instead of appending the block.
    """
    d = Path(tempfile.mkdtemp())
    cf = d / "config.py"
    cf.write_text("class Settings:\n    X: int = 1\n")
    _patch_config(cf, 5, 4000, 30)
    out = cf.read_text()
    assert "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER: int = 5" in out, out
    assert "WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH: int = 4000" in out, out
    assert "WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE: int = 30" in out, out
    # the original class body must still precede the appended block (end-of-file).
    assert out.index("class Settings") < out.index("WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER"), out


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_models_init_patched,
        test_routes_registered,
        test_ws_chat_endpoint_file_created,
        test_connection_manager_created,
        test_chat_models_created,
        test_chat_schemas_created,
        test_chat_crud_created,
        test_http_companion_routes,
        test_tenant_conditional_fk_with_tenants,
        test_tenant_conditional_fk_without_tenants,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_execution_time_within_sane_bound,
        test_auto_scaffolds_missing_prereqs,
        test_missing_prereqs_dry_run_reports_error,
        test_ws_init_created_and_reported,
        test_redis_module_created_and_reported,
        test_emitted_project_test_created_and_reported,
        test_migration_down_revision_is_real_head,
        test_config_block_inserted_after_anchor,
        test_config_block_uses_settings_fallback_branch,
        test_routes_import_ordered_after_last_app_import,
        test_routes_include_ordered_after_last_include,
        test_main_mounts_ws_chat_router,
        test_redis_requirement_not_duplicated_when_present,
        test_redis_requirement_added_when_absent,
        test_patch_main_bails_when_import_already_present,
        test_patch_main_bails_when_no_from_app_import,
        test_patch_main_bails_when_no_mount_anchor,
        test_patch_main_import_before_app_and_include_after,
        test_patch_main_uses_fastapi_anchor_when_no_include,
        test_patch_routes_fallback_inserts_after_apirouter,
        test_patch_config_fallback_appends_block_at_end,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"TOOL-017 add_websocket_chat: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
