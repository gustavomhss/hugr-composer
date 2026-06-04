"""Tests for TOOL-062 add_websocket_presence.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_websocket_presence.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_websocket_presence.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_websocket_presence import add_websocket_presence
from tests.common.fixture_factory import create_fixture_project

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


def _bare_project() -> Path:
    """A valid (existing) dir MISSING config/requirements prereqs.

    Exercises the auto-scaffold and prerequisite-error code paths.
    """
    d = Path(tempfile.mkdtemp()) / "bare"
    d.mkdir()
    return d


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
    project_dir = create_fixture_project(name="wsp_t01")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="wsp_t02")
    r1 = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="wsp_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 5 new files (model, schemas, manager, endpoint, routes)."""
    project_dir = create_fixture_project(name="wsp_t04")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init)."""
    project_dir = create_fixture_project(name="wsp_t05")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="wsp_t06")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="wsp_t07")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected PRESENCE_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="wsp_t08")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "PRESENCE_HEARTBEAT_SECONDS",
        "PRESENCE_TTL_SECONDS",
        "PRESENCE_MAX_DEVICES",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "PRESENCE_HEARTBEAT_SECONDS" in line:
            assert line.startswith("    "), (
                f"PRESENCE_HEARTBEAT_SECONDS not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """UserPresence is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="wsp_t09")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "UserPresence" in content, "UserPresence not registered in models __init__"


def test_routes_registered() -> None:
    """Presence HTTP routes are registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="wsp_t10")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "presence" in content.lower(), "Presence router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------


def test_presence_manager_file_created() -> None:
    """app/ws/presence.py exists with PresenceManager."""
    project_dir = create_fixture_project(name="wsp_t11")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    assert ws_file.exists(), "app/ws/presence.py not created"
    content = ws_file.read_text()
    assert "PresenceManager" in content


def test_presence_endpoint_file_created() -> None:
    """app/ws/presence_endpoint.py exists with websocket route."""
    project_dir = create_fixture_project(name="wsp_t12")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    endpoint_file = project_dir / "app" / "ws" / "presence_endpoint.py"
    assert endpoint_file.exists(), "app/ws/presence_endpoint.py not created"
    content = endpoint_file.read_text()
    assert "websocket" in content.lower() or "WebSocket" in content


def test_presence_model_created() -> None:
    """app/models/presence.py exists with UserPresence class."""
    project_dir = create_fixture_project(name="wsp_t13")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "presence.py"
    assert model_file.exists(), "app/models/presence.py not created"
    content = model_file.read_text()
    assert "UserPresence" in content, "UserPresence model not found"


def test_presence_schemas_created() -> None:
    """app/schemas/presence.py exists with PresenceUpdate and PresenceList."""
    project_dir = create_fixture_project(name="wsp_t14")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "presence.py"
    assert schema_file.exists(), "app/schemas/presence.py not created"
    content = schema_file.read_text()
    assert "PresenceUpdate" in content, "PresenceUpdate schema not found"
    assert "PresenceList" in content, "PresenceList schema not found"


def test_presence_http_routes_created() -> None:
    """app/api/routes/presence.py exists with REST routes."""
    project_dir = create_fixture_project(name="wsp_t15")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "presence.py"
    assert route_file.exists(), "app/api/routes/presence.py not created"
    content = route_file.read_text()
    assert "online" in content.lower(), "Presence routes must have /online endpoint"


def test_presence_rest_routes_require_auth() -> None:
    """R8-J8-2 — both REST companion handlers carry an auth param.

    ``GET /presence/online`` (``list_online_users``) enumerated every
    online user's UUID and ``GET /presence/{user_id}``
    (``get_user_presence``) leaked any user's status/last_seen/device,
    both with no auth dependency. Each handler must now declare a
    ``current_user``-style auth param so anonymous callers are denied.
    """
    project_dir = create_fixture_project(name="wsp_authz")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "presence.py"
    tree = ast.parse(route_file.read_text())

    auth_tokens = {"current_user", "superuser", "principal"}
    targets = {"list_online_users", "get_user_presence"}
    found: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in targets:
            continue
        params = node.args.args + node.args.kwonlyargs + node.args.posonlyargs
        found[node.name] = any(a.arg in auth_tokens for a in params)

    assert targets <= found.keys(), (
        f"missing presence handlers in rendered routes: {targets - found.keys()}"
    )
    for name in targets:
        assert found[name], (
            f"{name} has no auth param ({auth_tokens}); anonymous callers can "
            f"enumerate/leak presence data (R8-J8-2 regression)"
        )


def test_presence_manager_has_redis_pub_sub() -> None:
    """PresenceManager uses Redis pub/sub for broadcasting events."""
    project_dir = create_fixture_project(name="wsp_t16")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    assert "publish" in content, "PresenceManager must use Redis publish for events"


def test_presence_manager_has_ttl() -> None:
    """PresenceManager sets TTL = heartbeat × 3 in Redis."""
    project_dir = create_fixture_project(name="wsp_t17")
    add_websocket_presence(ToolInput(project_dir=str(project_dir), dry_run=False))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    # Default heartbeat=30, TTL=90
    assert "90" in content, "Default TTL (30s × 3 = 90s) not found in presence manager"


def test_heartbeat_ping_pong() -> None:
    """Presence endpoint handles ping/pong heartbeat messages."""
    project_dir = create_fixture_project(name="wsp_t18")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    endpoint_file = project_dir / "app" / "ws" / "presence_endpoint.py"
    content = endpoint_file.read_text()
    assert "ping" in content, "Endpoint must handle ping heartbeat"
    assert "pong" in content, "Endpoint must respond with pong"


def test_multi_device_support() -> None:
    """PresenceManager tracks multiple devices per user."""
    project_dir = create_fixture_project(name="wsp_t19")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    assert "device" in content.lower(), "PresenceManager must track devices"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="wsp_t20")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should mention Redis and heartbeat."""
    project_dir = create_fixture_project(name="wsp_t21")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "redis" in combined, "next_steps should mention Redis"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="wsp_t22")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_redis_module_created_if_absent() -> None:
    """app/core/redis.py is created when it doesn't exist."""
    project_dir = create_fixture_project(name="wsp_t23")
    # Ensure redis.py doesn't exist before the tool runs
    redis_module = project_dir / "app" / "core" / "redis.py"
    if redis_module.exists():
        redis_module.unlink()
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert redis_module.exists(), "app/core/redis.py should be created"


def test_requirements_patched() -> None:
    """requirements.txt contains redis after tool runs."""
    project_dir = create_fixture_project(name="wsp_t24")
    requirements_file = project_dir / "requirements.txt"
    # Remove redis if present to force a patch
    if requirements_file.exists():
        src = requirements_file.read_text()
        requirements_file.write_text(
            "\n".join(line for line in src.splitlines() if "redis" not in line.lower()) + "\n"
        )
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    content = requirements_file.read_text()
    assert "redis" in content.lower(), "redis not added to requirements.txt"


def test_custom_heartbeat_seconds() -> None:
    """Custom heartbeat_seconds=15 results in TTL=45 in the manager."""
    project_dir = create_fixture_project(name="wsp_t25")
    result = add_websocket_presence(
        ToolInput(project_dir=str(project_dir)),
        heartbeat_seconds=15,
    )
    assert result.status == "success"
    ws_file = project_dir / "app" / "ws" / "presence.py"
    content = ws_file.read_text()
    assert "45" in content, "TTL (15s × 3 = 45s) not found with custom heartbeat_seconds=15"


def test_dry_run_mentions_heartbeat_ttl() -> None:
    """dry_run notes contain heartbeat and TTL values."""
    project_dir = create_fixture_project(name="wsp_t26")
    result = add_websocket_presence(
        ToolInput(project_dir=str(project_dir), dry_run=True),
        heartbeat_seconds=20,
    )
    assert result.status == "success"
    combined = " ".join(result.notes)
    assert "20" in combined, "dry_run notes should mention heartbeat_seconds=20"
    assert "60" in combined, "dry_run notes should mention TTL (20 × 3 = 60)"


# ---------------------------------------------------------------------------
# F-006: requirements parse must be line-by-line (no raw substring)
# ---------------------------------------------------------------------------


def test_requirements_aioredis_does_not_suppress_redis_add() -> None:
    """F-006: a pre-existing ``aioredis`` line must NOT prevent the tool from
    declaring ``redis``.

    Pre-fix the patcher used ``"redis" not in src`` which falsely treated
    ``aioredis>=2.0.0`` (a different package) as proof that ``redis`` was
    declared and skipped the add. Post-fix the line-by-line parser sees
    ``aioredis`` as a distinct package and still appends ``redis[hiredis]``.
    """
    project_dir = create_fixture_project(name="wsp_f006_aioredis")
    requirements_file = project_dir / "requirements.txt"
    # Strip every redis-like line, then add aioredis only.
    src = requirements_file.read_text()
    cleaned = "\n".join(line for line in src.splitlines() if "redis" not in line.lower())
    requirements_file.write_text(cleaned + "\naioredis>=2.0.0\n")

    add_websocket_presence(ToolInput(project_dir=str(project_dir)))

    final = requirements_file.read_text()
    declared = set()
    for raw_line in final.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip extras BEFORE version specifier so ``redis[hiredis]>=5.0.0``
        # normalises to ``redis`` (the extras list contains ``[`` which is
        # an earlier separator than ``>=``).
        if "[" in line:
            line = line.split("[", 1)[0].strip()
        for sep in ("===", "==", ">=", "<=", "!=", "~=", ">", "<"):
            if sep in line:
                line = line.split(sep, 1)[0].strip()
                break
        declared.add(line.lower())
    assert "redis" in declared, (
        f"redis package not added when aioredis was already declared "
        f"(F-006 regression). Final declared: {declared}\n--- file ---\n{final}"
    )
    assert "aioredis" in declared, "aioredis must be preserved"


def test_requirements_redis_comment_does_not_suppress_add() -> None:
    """F-006: a ``# redis comment`` line must NOT suppress the redis add."""
    project_dir = create_fixture_project(name="wsp_f006_comment")
    requirements_file = project_dir / "requirements.txt"
    src = requirements_file.read_text()
    cleaned = "\n".join(line for line in src.splitlines() if "redis" not in line.lower())
    requirements_file.write_text(cleaned + "\n# redis: TODO add when caching lands\n")

    add_websocket_presence(ToolInput(project_dir=str(project_dir)))

    final = requirements_file.read_text()
    # The exact package name redis must appear as a distinct requirement.
    declared = set()
    for raw_line in final.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip extras BEFORE version specifier so ``redis[hiredis]>=5.0.0``
        # normalises to ``redis`` (the extras list contains ``[`` which is
        # an earlier separator than ``>=``).
        if "[" in line:
            line = line.split("[", 1)[0].strip()
        for sep in ("===", "==", ">=", "<=", "!=", "~=", ">", "<"):
            if sep in line:
                line = line.split(sep, 1)[0].strip()
                break
        declared.add(line.lower())
    assert "redis" in declared, (
        f"redis not added when only a comment mentioned 'redis' (F-006 regression). "
        f"declared: {declared}; file:\n{final}"
    )


# ---------------------------------------------------------------------------
# Mutation-hardening — bare-project prereq paths (L68, L78)
# ---------------------------------------------------------------------------


def test_auto_scaffolds_missing_prereqs() -> None:
    """A bare project is auto-scaffolded on a real run.

    Guards ``auto_scaffold=not inp.dry_run`` (L68: drop the ``not`` -> no
    scaffold -> error) and ``files_created = list(scaffolded or [])``
    (L78: ``or`` -> ``and`` -> scaffolded files silently dropped).
    """
    p = _bare_project()
    r = add_websocket_presence(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    created = set(r.files_created)
    # The scaffolded config.py must appear in files_created (L78 or->and
    # would drop it because ``nonempty and [] == []``).
    assert any(c.endswith("config.py") for c in created), created
    # Physically scaffolded — without auto_scaffold these never exist (L68).
    assert (p / "app" / "core" / "config.py").exists()
    assert (p / "requirements.txt").exists()


def test_missing_prereqs_dry_run_reports_error() -> None:
    """dry_run on a bare project: auto_scaffold OFF -> prereqs missing.

    Guards ``auto_scaffold=not inp.dry_run`` (L68): with the ``not`` dropped
    the scaffold would run and there would be no error to report.
    """
    p = _bare_project()
    r = add_websocket_presence(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "error"
    assert "Prerequisites not met" in (r.error or "")


# ---------------------------------------------------------------------------
# Mutation-hardening — execution_time_ms upper bound (L57/L75/L207 _ms)
# ---------------------------------------------------------------------------


def test_execution_time_within_sane_bounds() -> None:
    """execution_time_ms is positive and below a sane upper bound.

    Guards the ``monotonic() - start`` BinOp (Sub -> Add would balloon the
    value far past any sane wall-clock window).
    """
    project_dir = create_fixture_project(name="wsp_ms")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert 0 < result.execution_time_ms < 60_000, result.execution_time_ms


# ---------------------------------------------------------------------------
# Mutation-hardening — ws/__init__ and emitted-test guards (L129, L220)
# ---------------------------------------------------------------------------


def test_ws_init_created_and_reported() -> None:
    """app/ws/__init__.py is created and reported in files_created.

    Guards ``if not ws_init.exists()`` (L129): flipping the ``not`` skips
    creation so the package marker never appears.
    """
    project_dir = create_fixture_project(name="wsp_wsinit")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    ws_init = project_dir / "app" / "ws" / "__init__.py"
    assert ws_init.exists(), "app/ws/__init__.py not created"
    assert any(c.endswith("ws/__init__.py") for c in result.files_created), (
        f"ws/__init__.py not reported in files_created: {result.files_created}"
    )


def test_emitted_project_test_created_and_reported() -> None:
    """tests/test_add_websocket_presence_emitted.py is created and reported.

    Guards ``if not emitted.exists()`` (L220): flipping the ``not`` skips
    emitting the project test file.
    """
    project_dir = create_fixture_project(name="wsp_emitted")
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    emitted = project_dir / "tests" / "test_add_websocket_presence_emitted.py"
    assert emitted.exists(), "emitted project test not created"
    assert any(
        c.endswith("test_add_websocket_presence_emitted.py") for c in result.files_created
    ), f"emitted test not reported in files_created: {result.files_created}"


# ---------------------------------------------------------------------------
# Mutation-hardening — _patch_config TTL math + anchor placement (L244, L252)
# ---------------------------------------------------------------------------


def test_config_ttl_is_heartbeat_times_three() -> None:
    """PRESENCE_TTL_SECONDS == heartbeat_seconds * 3 in config.py.

    Guards ``ttl = heartbeat_seconds * 3`` (L244): Mult -> FloorDiv turns
    30*3=90 into 30//3=10.
    """
    project_dir = create_fixture_project(name="wsp_cfgttl")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    assert "PRESENCE_TTL_SECONDS: int = 90" in content, (
        "config TTL must be heartbeat(30) * 3 = 90 (Mult->FloorDiv would give 10)"
    )
    assert "PRESENCE_TTL_SECONDS: int = 10" not in content


def test_config_block_inserted_after_access_token_anchor() -> None:
    """The presence settings block is inserted right after the anchor field.

    Guards ``if anchor in src`` (L252: In -> NotIn would skip the anchor
    branch and fall through to a different insertion point) and the anchor
    branch's ``+`` concat.
    """
    project_dir = create_fixture_project(name="wsp_anchor")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    idx = content.find(anchor)
    assert idx != -1, "anchor field missing from fixture config"
    after = content[idx + len(anchor) : idx + len(anchor) + 80]
    assert "Presence settings" in after, (
        f"presence block not inserted immediately after anchor (L252): {after!r}"
    )


def test_config_block_inserted_before_settings_when_no_anchor() -> None:
    """When the anchor is absent, the block lands before ``settings = Settings()``.

    Guards ``elif "settings = Settings()" in src`` (L254: In -> NotIn would
    skip this branch and append at end-of-file with wrong indentation, and
    the block would no longer precede the instantiation line).
    """
    project_dir = create_fixture_project(name="wsp_noanchor")
    config_file = project_dir / "app" / "core" / "config.py"
    # Build a minimal config that has NO anchor field but DOES instantiate.
    config_file.write_text(
        "class Settings:\n    PROJECT_NAME: str = 'app'\n\nsettings = Settings()\n"
    )
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    content = config_file.read_text()
    assert "PRESENCE_HEARTBEAT_SECONDS" in content
    block_idx = content.find("PRESENCE_HEARTBEAT_SECONDS")
    settings_idx = content.find("settings = Settings()")
    assert block_idx != -1 and settings_idx != -1
    assert block_idx < settings_idx, (
        "presence block must be inserted before 'settings = Settings()' (L254)"
    )


# ---------------------------------------------------------------------------
# Mutation-hardening — _patch_routes_init insertion math (L268,L270,L274,L276)
# ---------------------------------------------------------------------------


def test_presence_import_inserted_after_last_app_import() -> None:
    """The presence import is inserted right after the last ``from app.`` line.

    Guards ``if last_app == -1`` (L268: Eq->NotEq recomputes the anchor from
    the APIRouter() line, misplacing the import) and ``last_app + 1``
    (L270: Add->Sub inserts the import before an existing app import).
    """
    project_dir = create_fixture_project(name="wsp_routeimp")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    import_idx = next(
        i for i, ln in enumerate(lines) if "presence import router as presence_router" in ln
    )
    # Must come after the last pre-existing ``from app.`` import (the health one)
    # and the line directly above it must itself be a ``from app.`` import.
    assert lines[import_idx - 1].startswith("from app."), (
        f"presence import not placed right after the last app import: "
        f"prev={lines[import_idx - 1]!r}"
    )
    # And it must precede the APIRouter() construction.
    api_idx = next(i for i, ln in enumerate(lines) if "APIRouter()" in ln)
    assert import_idx < api_idx, "import must precede api_router = APIRouter()"


def test_presence_include_inserted_after_last_include() -> None:
    """The include_router call lands right after the last existing include.

    Guards ``if last_inc == -1`` (L274: Eq->NotEq) and ``last_inc + 1``
    (L276: Add->Sub inserts before an existing include_router call).
    """
    project_dir = create_fixture_project(name="wsp_routeinc")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    inc_idx = next(i for i, ln in enumerate(lines) if "include_router(presence_router)" in ln)
    # The line directly above must be another include_router call (it is
    # appended after the last pre-existing include).
    assert lines[inc_idx - 1].startswith("api_router.include_router"), (
        f"presence include not placed after the last include: prev={lines[inc_idx - 1]!r}"
    )


# ---------------------------------------------------------------------------
# Mutation-hardening — strict insertion-position math (L270, L276)
# ---------------------------------------------------------------------------


def test_presence_import_is_last_app_import() -> None:
    """Presence import lands strictly AFTER every other ``from app.`` import.

    Guards ``lines.insert(last_app + 1, import_line)`` (L270): with Add->Sub
    (``last_app - 1``) the import is inserted *before* the final pre-existing
    app imports. The weaker "line above is a ``from app.`` import" check still
    passes under that mutation (the import lands between two app imports), so
    we assert the presence import index exceeds ALL other app-import indices.
    """
    project_dir = create_fixture_project(name="wsp_lastimp")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    presence_idx = next(
        i for i, ln in enumerate(lines) if "presence import router as presence_router" in ln
    )
    other_app_imports = [
        i for i, ln in enumerate(lines) if ln.startswith("from app.") and i != presence_idx
    ]
    assert other_app_imports, "fixture must have pre-existing app imports"
    assert presence_idx > max(other_app_imports), (
        f"presence import (idx {presence_idx}) must come after the last "
        f"pre-existing app import (idx {max(other_app_imports)}); Add->Sub on "
        f"L270 would place it earlier"
    )


def test_presence_include_is_last_include() -> None:
    """Presence include lands strictly AFTER every other ``include_router`` call.

    Guards ``lines.insert(last_inc + 1, include_line)`` (L276): with Add->Sub
    (``last_inc - 1``) the include is inserted *before* the final pre-existing
    include. The weaker "line above is an include_router call" check survives
    that mutation, so we assert the presence include index exceeds ALL other
    include-router indices.
    """
    project_dir = create_fixture_project(name="wsp_lastinc")
    add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    presence_idx = next(i for i, ln in enumerate(lines) if "include_router(presence_router)" in ln)
    other_includes = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and i != presence_idx
    ]
    assert other_includes, "fixture must have pre-existing includes"
    assert presence_idx > max(other_includes), (
        f"presence include (idx {presence_idx}) must come after the last "
        f"pre-existing include (idx {max(other_includes)}); Add->Sub on L276 "
        f"would place it earlier"
    )


# ---------------------------------------------------------------------------
# Mutation-hardening — APIRouter() fallback anchors (L269, L275)
# ---------------------------------------------------------------------------


def test_routes_fallback_anchors_on_apirouter_line() -> None:
    """With no app imports and no includes, both inserts anchor on APIRouter().

    A minimal routes ``__init__`` (only ``api_router = APIRouter()``, then
    ``__all__``) forces the ``last_app == -1`` / ``last_inc == -1`` fallback
    branches. Those use ``max(i for ... if "APIRouter()" in ln)`` (L269, L275)
    to anchor right after the APIRouter() construction — BEFORE ``__all__``.
    With In->NotIn the comprehension anchors on the wrong line and both
    statements are appended AFTER ``__all__`` instead.
    """
    project_dir = create_fixture_project(name="wsp_fallback")
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    routes_init.write_text(
        'from fastapi import APIRouter\n\napi_router = APIRouter()\n\n__all__ = ["api_router"]\n'
    )
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    lines = routes_init.read_text().splitlines()
    all_idx = next(i for i, ln in enumerate(lines) if ln.startswith("__all__"))
    import_idx = next(
        i for i, ln in enumerate(lines) if "presence import router as presence_router" in ln
    )
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(presence_router)" in ln)
    assert import_idx < all_idx, (
        f"presence import (idx {import_idx}) must precede __all__ (idx {all_idx}); "
        f"In->NotIn on L269 would append it after __all__"
    )
    assert include_idx < all_idx, (
        f"presence include (idx {include_idx}) must precede __all__ (idx {all_idx}); "
        f"In->NotIn on L275 would append it after __all__"
    )


# ---------------------------------------------------------------------------
# Mutation-hardening — _requirements_need_redis already-present (L287)
# ---------------------------------------------------------------------------


def test_redis_not_duplicated_when_already_present() -> None:
    """An existing ``redis`` requirement is NOT re-added (no duplicate line).

    Guards ``return False`` (L287) at the end of ``_requirements_need_redis``:
    when redis is already declared the function returns False so no line is
    appended. With BoolLiteral False->True the tool would append a second
    ``redis[hiredis]`` line, producing two redis package entries.
    """
    project_dir = create_fixture_project(name="wsp_redisdup")
    requirements_file = project_dir / "requirements.txt"
    src = requirements_file.read_text()
    cleaned = "\n".join(line for line in src.splitlines() if "redis" not in line.lower())
    requirements_file.write_text(cleaned + "\nredis>=5.0.0\n")

    add_websocket_presence(ToolInput(project_dir=str(project_dir)))

    redis_pkg_lines = [
        line
        for line in requirements_file.read_text().splitlines()
        if line.strip()
        and not line.strip().startswith(("#", "-"))
        and line.strip().split("[")[0].split(">=")[0].split("==")[0].strip().lower() == "redis"
    ]
    assert len(redis_pkg_lines) == 1, (
        f"redis must appear exactly once when already present; found "
        f"{len(redis_pkg_lines)} (False->True on L287 would duplicate it): "
        f"{redis_pkg_lines}"
    )


# ---------------------------------------------------------------------------
# Mutation-hardening — _patch_config end-of-file fallback concat (L259)
# ---------------------------------------------------------------------------


def test_config_block_appended_when_no_anchor_and_no_settings() -> None:
    """With neither anchor nor ``settings = Settings()``, block is appended.

    A config with only a ``Settings`` class (no anchor field, no instantiation)
    forces the final ``else`` branch ``src.rstrip("\\n") + "\\n" + block``
    (L259). The ``+`` string concatenation is killable: Add->Sub on strings
    raises ``TypeError`` -> the tool returns error / does not patch the field.
    """
    project_dir = create_fixture_project(name="wsp_cfgappend")
    config_file = project_dir / "app" / "core" / "config.py"
    config_file.write_text('class Settings:\n    PROJECT_NAME: str = "app"\n')

    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))

    assert result.status == "success", result.error
    content = config_file.read_text()
    assert "PRESENCE_HEARTBEAT_SECONDS: int = 30" in content, (
        "presence block must be appended via the end-of-file concat fallback (L259)"
    )
    assert "PRESENCE_TTL_SECONDS: int = 90" in content


# ---------------------------------------------------------------------------
# Mutation-hardening — ws_dir.mkdir exist_ok when dir pre-exists (L127)
# ---------------------------------------------------------------------------


def test_ws_dir_mkdir_tolerates_existing_dir() -> None:
    """Pre-existing ``app/ws`` does not break the run (mkdir exist_ok=True).

    Guards ``ws_dir.mkdir(parents=True, exist_ok=True)`` (L127): with the
    ``exist_ok`` flag flipped to False, ``mkdir`` raises ``FileExistsError``
    on the pre-created directory and the run fails. The default fixture lacks
    ``app/ws`` so the flag is otherwise never exercised.
    """
    project_dir = create_fixture_project(name="wsp_wsexists")
    (project_dir / "app" / "ws").mkdir(parents=True, exist_ok=True)
    result = add_websocket_presence(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"run must succeed with pre-existing app/ws (exist_ok=True on L127): {result.error}"
    )
    assert (project_dir / "app" / "ws" / "presence.py").exists()


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
        test_presence_manager_file_created,
        test_presence_endpoint_file_created,
        test_presence_model_created,
        test_presence_schemas_created,
        test_presence_http_routes_created,
        test_presence_rest_routes_require_auth,
        test_presence_manager_has_redis_pub_sub,
        test_presence_manager_has_ttl,
        test_heartbeat_ping_pong,
        test_multi_device_support,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_redis_module_created_if_absent,
        test_requirements_patched,
        test_custom_heartbeat_seconds,
        test_dry_run_mentions_heartbeat_ttl,
        test_auto_scaffolds_missing_prereqs,
        test_missing_prereqs_dry_run_reports_error,
        test_execution_time_within_sane_bounds,
        test_ws_init_created_and_reported,
        test_emitted_project_test_created_and_reported,
        test_config_ttl_is_heartbeat_times_three,
        test_config_block_inserted_after_access_token_anchor,
        test_config_block_inserted_before_settings_when_no_anchor,
        test_presence_import_inserted_after_last_app_import,
        test_presence_include_inserted_after_last_include,
        test_presence_import_is_last_app_import,
        test_presence_include_is_last_include,
        test_routes_fallback_anchors_on_apirouter_line,
        test_redis_not_duplicated_when_already_present,
        test_config_block_appended_when_no_anchor_and_no_settings,
        test_ws_dir_mkdir_tolerates_existing_dir,
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
    print(f"TOOL-062 add_websocket_presence: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
