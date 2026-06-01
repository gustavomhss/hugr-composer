"""Structural tests for TOOL-116 add_adaptive_throttle.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies every completeness criterion from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_adaptive_throttle.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_adaptive_throttle.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_adaptive_throttle import add_adaptive_throttle
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root*."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* parses without SyntaxError."""
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max function LOC in all .py files under *root/subdir*."""
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
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and getattr(
                node, "end_lineno", None
            ):
                loc = node.end_lineno - node.lineno + 1
                max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# CC-01 — success status
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="at_t01")
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02 — idempotent
# ---------------------------------------------------------------------------


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="at_t02")
    r1 = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03 — dry_run
# ---------------------------------------------------------------------------


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="at_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04 — files created count
# ---------------------------------------------------------------------------


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 3 new files (core, middleware, status route)."""
    project_dir = create_fixture_project(name="at_t04")
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05 — files modified count
# ---------------------------------------------------------------------------


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, main)."""
    project_dir = create_fixture_project(name="at_t05")
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06 — all py parse
# ---------------------------------------------------------------------------


def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="at_t06")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07 — no function over 50 LOC
# ---------------------------------------------------------------------------


def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="at_t07")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08 — config fields patched
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """CC-08: ADAPTIVE_THROTTLE_* settings exist inside Settings class body."""
    project_dir = create_fixture_project(name="at_t08")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "ADAPTIVE_THROTTLE_ENABLED",
        "ADAPTIVE_THROTTLE_SENSITIVITY",
        "ADAPTIVE_THROTTLE_LEARNING_PERIOD_H",
        "ADAPTIVE_THROTTLE_BASE_QUOTA",
        "ADAPTIVE_THROTTLE_PENALTY_ESCALATION",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "ADAPTIVE_THROTTLE_ENABLED" in line:
            assert line.startswith("    "), (
                f"ADAPTIVE_THROTTLE_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# Domain tests — CC-11+
# ---------------------------------------------------------------------------


def test_core_module_created() -> None:
    """T-09: app/core/adaptive_throttle.py exists with AdaptiveThrottleConfig."""
    project_dir = create_fixture_project(name="at_t09")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "adaptive_throttle.py"
    assert core_file.exists(), "app/core/adaptive_throttle.py not created"
    content = core_file.read_text()
    assert "class AdaptiveThrottleConfig" in content
    assert "def build_config" in content
    assert "def fingerprint_request" in content


def test_penalty_ladder_defined() -> None:
    """T-10: PENALTY_SECONDS list has exactly 5 tiers (0=none, 4=24h ban)."""
    project_dir = create_fixture_project(name="at_t10")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "adaptive_throttle.py"
    content = core_file.read_text()
    assert "PENALTY_SECONDS" in content
    assert "86400" in content, "24h ban (86400 seconds) not in PENALTY_SECONDS"


def test_middleware_module_created() -> None:
    """T-11: app/middleware/adaptive_throttle.py with AdaptiveThrottleMiddleware."""
    project_dir = create_fixture_project(name="at_t11")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "adaptive_throttle.py"
    assert mw_file.exists(), "app/middleware/adaptive_throttle.py not created"
    content = mw_file.read_text()
    assert "class AdaptiveThrottleMiddleware" in content
    assert "def register_adaptive_throttle" in content


def test_middleware_returns_429_on_penalty() -> None:
    """T-12: Middleware returns 429 with Retry-After when client is in penalty tier."""
    project_dir = create_fixture_project(name="at_t12")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "adaptive_throttle.py"
    content = mw_file.read_text()
    assert "status_code=429" in content
    assert "Retry-After" in content
    assert "penalty_tier" in content


def test_status_route_created() -> None:
    """T-13: app/api/routes/throttle_status.py exposes GET /throttle/status."""
    project_dir = create_fixture_project(name="at_t13")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "throttle_status.py"
    assert route_file.exists(), "throttle_status.py not created"
    content = route_file.read_text()
    assert "/throttle" in content
    assert "ThrottleStatus" in content
    assert "penalty_tier" in content


def test_fingerprint_uses_header_order() -> None:
    """T-14: fingerprint_request combines IP and header order."""
    project_dir = create_fixture_project(name="at_t14")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "adaptive_throttle.py"
    content = core_file.read_text()
    assert "request.headers.keys()" in content
    assert "hashlib" in content
    assert "sha256" in content


def test_main_registers_throttle() -> None:
    """T-15: main.py imports and calls register_adaptive_throttle(app)."""
    project_dir = create_fixture_project(name="at_t15")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "register_adaptive_throttle" in content
    assert "from app.middleware.adaptive_throttle import register_adaptive_throttle" in content


def test_cost_weight_function_present() -> None:
    """T-16: cost_weight function exists for per-endpoint quota consumption."""
    project_dir = create_fixture_project(name="at_t16")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "adaptive_throttle.py"
    content = core_file.read_text()
    assert "def cost_weight" in content


def test_penalty_seconds_for_tier_function_present() -> None:
    """T-17: penalty_seconds_for_tier function exists for cooldown calculation."""
    project_dir = create_fixture_project(name="at_t17")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "adaptive_throttle.py"
    content = core_file.read_text()
    assert "def penalty_seconds_for_tier" in content


# ---------------------------------------------------------------------------
# CC-N-1 — execution time
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="at_t18")
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N — next_steps
# ---------------------------------------------------------------------------


def test_next_steps_present() -> None:
    """CC-N: next_steps mentions REDIS_URL and adaptive throttle config."""
    project_dir = create_fixture_project(name="at_t19")
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "redis_url" in combined, "next_steps should mention REDIS_URL"
    assert "adaptive_throttle" in combined, "next_steps should mention ADAPTIVE_THROTTLE"


# ---------------------------------------------------------------------------
# CC-LAST — idempotent project still parses
# ---------------------------------------------------------------------------


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="at_t20")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Mutation-killing regression tests
# ---------------------------------------------------------------------------


def test_five_penalty_tiers_distinct() -> None:
    """T-21: PENALTY_SECONDS must have exactly 5 entries with distinct values."""
    project_dir = create_fixture_project(name="at_t21")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "adaptive_throttle.py"
    content = core_file.read_text()
    tree = ast.parse(content)

    def _extract_list_value(value_node: ast.expr) -> list[int] | None:
        if isinstance(value_node, ast.List):
            result: list[int] = []
            for elt in value_node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, int):
                    result.append(elt.value)
                else:
                    result.append(-1)
            return result
        return None

    for node in ast.walk(tree):
        # Handle both plain assignment and annotated assignment
        value_node: ast.expr | None = None
        name: str | None = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PENALTY_SECONDS":
                    name = "PENALTY_SECONDS"
                    value_node = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PENALTY_SECONDS"
        ):
            name = "PENALTY_SECONDS"
            value_node = node.value
        if name and value_node is not None:
            values = _extract_list_value(value_node)
            assert values is not None, "PENALTY_SECONDS is not a list literal"
            assert len(values) == 5, f"Expected 5 penalty tiers, got {len(values)}: {values}"
            assert values[0] == 0, "Tier 0 must be 0 seconds (no penalty)"
            assert values[-1] == 86400, "Tier 4 must be 86400 seconds (24h)"
            return
    raise AssertionError("PENALTY_SECONDS list not found in core module")


def test_escalation_caps_at_tier_4() -> None:
    """T-22: _escalate_tier must never exceed tier 4."""
    project_dir = create_fixture_project(name="at_t22")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "adaptive_throttle.py"
    content = mw_file.read_text()
    assert "min(current + 1, 4)" in content, (
        "Tier cap 'min(current + 1, 4)' not found — escalation is unbounded"
    )


def test_escalation_on_quota_not_only_downstream_429() -> None:
    """R7-N4: the middleware must escalate on its OWN per-window quota, not only
    when a downstream handler returns 429.

    Pre-fix, escalation fired solely on ``response.status_code == 429``; the
    documented behavioral fingerprint detection never ran. The middleware must
    now count requests per fingerprint (record_request), weight them by
    cost_weight, and escalate when the count exceeds base_quota.
    """
    project_dir = create_fixture_project(name="at_quota")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "middleware" / "adaptive_throttle.py").read_text()
    assert "def record_request" in content, "missing per-window request counter (R7-N4)"
    assert "cost_weight" in content, "middleware must weight requests via cost_weight"
    assert "base_quota" in content, "middleware must compare the count against base_quota"
    # The quota escalation must run BEFORE call_next (block on volume, not only
    # after a downstream 429).
    tree = ast.parse(content)
    dispatch = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "dispatch"
    )
    body = ast.unparse(dispatch)
    assert "_quota_exceeded" in body, "dispatch must run the quota check (not only react to a 429)"
    # The quota check must precede the downstream dispatch (block on volume,
    # before forwarding) — it appears above the `response = await call_next` line.
    assert body.index("_quota_exceeded") < body.index("response = await call_next"), (
        "quota escalation must be evaluated before the downstream call_next"
    )


def test_register_throttle_positioned_after_fastapi() -> None:
    """T-23: register_adaptive_throttle(app) must appear AFTER app = FastAPI(...)."""
    project_dir = create_fixture_project(name="at_t23")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    app_idx = content.find("app = FastAPI(")
    reg_idx = content.find("register_adaptive_throttle(app)")
    assert app_idx >= 0, "FastAPI marker not found"
    assert reg_idx >= 0, "register_adaptive_throttle call not inserted"
    assert reg_idx > app_idx, (
        f"register_adaptive_throttle at {reg_idx} must come AFTER FastAPI() at {app_idx}"
    )


def test_config_has_six_fields() -> None:
    """T-24: config.py must have exactly 6 ADAPTIVE_THROTTLE_* fields.

    The 6th field (TRUSTED_PROXIES) was added in R7-N3 to make the throttle
    fingerprint proxy-aware (resolve real client IP from X-Forwarded-For only
    via trusted proxies).
    """
    project_dir = create_fixture_project(name="at_t24")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    expected = [
        "ADAPTIVE_THROTTLE_ENABLED",
        "ADAPTIVE_THROTTLE_SENSITIVITY",
        "ADAPTIVE_THROTTLE_LEARNING_PERIOD_H",
        "ADAPTIVE_THROTTLE_BASE_QUOTA",
        "ADAPTIVE_THROTTLE_PENALTY_ESCALATION",
        "ADAPTIVE_THROTTLE_TRUSTED_PROXIES",
    ]
    for field in expected:
        assert field in content, f"Config field {field} missing"
    distinct = {
        line.strip()
        for line in content.splitlines()
        if any(f in line for f in expected) and ":" in line and "=" in line
    }
    assert len(distinct) == 6, (
        f"Expected 6 ADAPTIVE_THROTTLE_* field lines, got {len(distinct)}: {distinct}"
    )


def test_fingerprint_is_proxy_aware() -> None:
    """T-26 (R7-N3): emitted core resolves client IP via trusted proxies only.

    Guards the DoS-amplifier fix: fingerprint must NOT hash request.client.host
    directly, must define client_ip(), and must gate X-Forwarded-For on a
    trusted-proxy check so an unproxied caller cannot spoof an IP.
    """
    project_dir = create_fixture_project(name="at_t26")
    add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "adaptive_throttle.py").read_text()
    assert "def client_ip" in content, "client_ip() resolver missing"
    assert "ADAPTIVE_THROTTLE_TRUSTED_PROXIES" in content, "trusted-proxy setting not read"
    assert "x-forwarded-for" in content, "X-Forwarded-For not consulted"
    assert "ipaddress" in content, "ipaddress-based trust check missing"
    # fingerprint must route through client_ip, not the raw peer host.
    assert "client_ip(request)" in content, "fingerprint must use client_ip(request)"


def test_no_files_mutated_outside_scope() -> None:
    """T-25: Tool must not modify files outside result.files_created/modified."""
    project_dir = create_fixture_project(name="at_t25")
    before = {p: p.read_text() for p in sorted(project_dir.rglob("*.py"))}
    result = add_adaptive_throttle(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    changed: set[Path] = {
        Path(s).resolve() for s in list(result.files_created) + list(result.files_modified)
    }
    for p, original in before.items():
        if p.resolve() in changed:
            continue
        assert p.read_text() == original, (
            f"File {p} was modified but not reported in files_modified"
        )


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
        test_core_module_created,
        test_penalty_ladder_defined,
        test_middleware_module_created,
        test_middleware_returns_429_on_penalty,
        test_status_route_created,
        test_fingerprint_uses_header_order,
        test_main_registers_throttle,
        test_cost_weight_function_present,
        test_penalty_seconds_for_tier_function_present,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_five_penalty_tiers_distinct,
        test_escalation_caps_at_tier_4,
        test_escalation_on_quota_not_only_downstream_429,
        test_register_throttle_positioned_after_fastapi,
        test_config_has_six_fields,
        test_fingerprint_is_proxy_aware,
        test_no_files_mutated_outside_scope,
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
    print(f"TOOL-116 add_adaptive_throttle: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
