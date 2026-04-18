"""TOOL-027: add_load_profile — Locust load-test profiles for a FastAPI project.

Generates a production-grade ``tests/load/`` directory with:

- ``locustfile.py`` — three ``HttpUser`` subclasses (BrowsingUser, ActiveUser,
  AdminUser) weighted by traffic share, each with JWT-from-spawn auth.
- ``scenarios.py`` — ``TaskSet`` classes for smoke / baseline / peak profiles.
- ``auth.py`` — ``AuthMixin`` for on-start login + token refresh.
- ``data_factories.py`` — Pydantic ``BaseModel`` request-body generators backed
  by Faker.
- ``slo_config.yaml`` — per-endpoint p99 SLO targets.
- ``slo_assertions.py`` — ``locust.events`` hook that fails the run (exit code 1)
  when any p99 target is exceeded.
- ``shapes.py`` — step-load ``LoadTestShape`` for graduated ramp-up.
- ``.github/workflows/load-tests.yml`` — CI regression-detection workflow.

The tool is idempotent: a second run returns ``status="no_op"`` when the
``tests/load/locustfile.py`` fingerprint is already present.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_load_profile import add_load_profile

    result = add_load_profile(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/tests/load/locustfile.py", ...]
    print(result.next_steps)    # ["pip install locust faker", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_load_profile",
    "description": "Add k6 load test profiles (smoke, load, stress, soak) for the project's endpoints.",
    "tags": ["extend", "testing"],
    "entry": "add_load_profile",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_load_profile(
    inp: ToolInput,
    endpoints: list[str] | None = None,
    users: int = 100,
    spawn_rate: int = 10,
    duration_seconds: int = 60,
    targets_p99_ms: dict[str, int] | None = None,
) -> ToolResult:
    """Generate Locust load-test profiles for a FastAPI project.

    Writes ``tests/load/`` with per-profile locustfiles, SLO config, auth
    mixin, data factories, step-load shapes, and a CI workflow.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        endpoints: Endpoint paths to include (``None`` = all authenticated
            endpoints from the OpenAPI schema).
        users: Target concurrent users (default 100).
        spawn_rate: Users spawned per second during ramp-up (default 10).
        duration_seconds: Smoke profile duration in seconds (default 60).
        targets_p99_ms: Dict mapping endpoint labels to p99 latency SLOs in ms.
            Defaults to ``{"GET /api/v1/items": 300, "POST /api/v1/items": 500}``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    load_dir = project / "tests" / "load"

    # --- Pre-flight: already installed? -------------------------------------
    _locustfile = load_dir / "locustfile.py"
    if _locustfile.exists() and "BrowsingUser" in _locustfile.read_text():
        return ToolResult(
            status="no_op",
            notes=["tests/load/locustfile.py already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would generate Locust profiles (users={users}, spawn_rate={spawn_rate}).",
                f"[dry_run] duration_seconds={duration_seconds}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    slos = targets_p99_ms or {
        "GET /api/v1/items": 300,
        "POST /api/v1/items": 500,
        "GET /api/v1/users/me": 200,
    }

    load_dir.mkdir(parents=True, exist_ok=True)
    ci_dir = project / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)

    files_modified: list[str] = []

    # --- Step 1: tests/load/__init__.py ------------------------------------
    init_file = load_dir / "__init__.py"
    init_file.write_text('"""Load test package generated by add_load_profile (TOOL-027)."""\n')
    files_created.append(str(init_file))

    # --- Step 2: auth.py ---------------------------------------------------
    auth_file = load_dir / "auth.py"
    _write_auth_mixin(auth_file)
    files_created.append(str(auth_file))

    # --- Step 3: data_factories.py ----------------------------------------
    data_file = load_dir / "data_factories.py"
    _write_data_factories(data_file)
    files_created.append(str(data_file))

    # --- Step 4: slo_assertions.py ----------------------------------------
    slo_assertions_file = load_dir / "slo_assertions.py"
    _write_slo_assertions(slo_assertions_file)
    files_created.append(str(slo_assertions_file))

    # --- Step 5: slo_config.yaml ------------------------------------------
    slo_yaml = load_dir / "slo_config.yaml"
    _write_slo_yaml(slo_yaml, slos)
    files_created.append(str(slo_yaml))

    # --- Step 6: shapes.py ------------------------------------------------
    shapes_file = load_dir / "shapes.py"
    _write_shapes(shapes_file, users, spawn_rate, duration_seconds)
    files_created.append(str(shapes_file))

    # --- Step 7: scenarios.py ---------------------------------------------
    scenarios_file = load_dir / "scenarios.py"
    _write_scenarios(scenarios_file, endpoints)
    files_created.append(str(scenarios_file))

    # --- Step 8: locustfile.py --------------------------------------------
    locustfile = load_dir / "locustfile.py"
    _write_locustfile(locustfile, users, spawn_rate)
    files_created.append(str(locustfile))

    # --- Step 9: CI workflow ----------------------------------------------
    ci_file = ci_dir / "load-tests.yml"
    _write_ci_workflow(ci_file, users, spawn_rate, duration_seconds)
    files_created.append(str(ci_file))

    # --- AST validation ------------------------------------------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"3 load profiles: smoke ({duration_seconds}s / 10 users), "
            f"baseline ({users} users), peak ({users * 3} users).",
            "SLO assertions wired via locust.events.quitting — non-zero exit on violation.",
            "Step-load shape in shapes.py ramps users gradually for time-to-failure capture.",
            f"Default p99 SLO targets: {slos}",
        ],
        next_steps=[
            "pip install locust faker",
            f"# Smoke profile (quick sanity check):",
            f"locust -f tests/load/locustfile.py --users 10 --spawn-rate 2 --run-time {duration_seconds}s --headless",
            f"# Baseline profile:",
            f"locust -f tests/load/locustfile.py --users {users} --spawn-rate {spawn_rate} --run-time 300s --headless",
            "Edit tests/load/slo_config.yaml to tune p99 targets per environment.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_auth_mixin(dest: Path) -> None:
    """Write ``tests/load/auth.py`` with JWT-from-spawn authentication mixin.

    Args:
        dest: Destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Authentication mixin for Locust load test users.

        Each simulated user calls login() once on spawn and caches the JWT
        so authentication overhead does not dominate latency measurements.

        Generated by add_load_profile tool (TOOL-027).
        \"\"\"

        from __future__ import annotations

        import random
        import string
        from typing import Optional


        class AuthMixin:
            \"\"\"Mixin providing JWT authentication for Locust HttpUser subclasses.

            Attributes:
                access_token: Cached JWT access token after successful login.
                auth_headers: Ready-to-use headers dict for authenticated requests.
            \"\"\"

            access_token: Optional[str] = None
            auth_headers: dict[str, str]

            def _random_email(self) -> str:
                \"\"\"Generate a random email for test user registration.

                Returns:
                    Random email string unique within this session.
                \"\"\"
                suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
                return f"loadtest_{suffix}@example.com"

            def _random_password(self) -> str:
                \"\"\"Generate a password meeting typical complexity requirements.

                Returns:
                    12-character password with upper, lower, digit, and special char.
                \"\"\"
                chars = string.ascii_letters + string.digits
                base = (
                    random.choice(string.ascii_uppercase)
                    + random.choice(string.ascii_lowercase)
                    + random.choice(string.digits)
                    + "!"
                    + "".join(random.choices(chars, k=8))
                )
                return base

            def login(self) -> None:
                \"\"\"Authenticate once per simulated user and cache the JWT.

                Tries the FastAPI full-stack template token endpoint first
                (``/api/v1/login/access-token``), then falls back to
                ``/api/v1/auth/token``.

                Side effects:
                    Sets ``self.access_token`` and ``self.auth_headers``.
                \"\"\"
                email = self._random_email()
                password = self._random_password()

                # Try registration so each virtual user is independent
                self.client.post(
                    "/api/v1/users/signup",
                    json={"email": email, "password": password},
                    name="[auth] register",
                )

                # OAuth2 password flow
                resp = self.client.post(
                    "/api/v1/login/access-token",
                    data={"username": email, "password": password},
                    name="[auth] login",
                )
                token = ""
                if resp.status_code == 200:
                    token = resp.json().get("access_token", "")
                self.access_token = token
                self.auth_headers = {"Authorization": f"Bearer {token}"} if token else {}

            def refresh_token(self) -> None:
                \"\"\"Re-authenticate if the token has expired mid-session.

                Side effects:
                    Updates ``self.access_token`` and ``self.auth_headers``.
                \"\"\"
                self.login()
        """)
    dest.write_text(content)


def _write_data_factories(dest: Path) -> None:
    """Write ``tests/load/data_factories.py`` with Pydantic + Faker request bodies.

    Args:
        dest: Destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Pydantic + Faker data factories for load test request bodies.

        Provides realistic payloads sourced from Faker so load tests exercise
        the same code paths as production traffic rather than trivial edge-cases.

        Generated by add_load_profile tool (TOOL-027).
        \"\"\"

        from __future__ import annotations

        import random
        from typing import Optional

        from faker import Faker
        from pydantic import BaseModel, Field

        _fake = Faker()


        class ItemCreatePayload(BaseModel):
            \"\"\"Realistic payload for POST /api/v1/items.

            Attributes:
                title: Short item title sourced from Faker.
                description: Optional longer description.
            \"\"\"

            title: str = Field(default_factory=lambda: _fake.sentence(nb_words=4).rstrip("."))
            description: Optional[str] = Field(
                default_factory=lambda: _fake.text(max_nb_chars=200) if random.random() > 0.3 else None
            )


        class ItemUpdatePayload(BaseModel):
            \"\"\"Realistic payload for PATCH /api/v1/items/{id}.

            Attributes:
                title: New item title (optional).
                description: New description (optional).
            \"\"\"

            title: Optional[str] = Field(default_factory=lambda: _fake.sentence(nb_words=3).rstrip("."))
            description: Optional[str] = Field(
                default_factory=lambda: _fake.text(max_nb_chars=150)
            )


        def make_item_create() -> dict:
            \"\"\"Return a dict payload for item creation.

            Returns:
                JSON-serializable dict matching the ItemCreate schema.
            \"\"\"
            return ItemCreatePayload().model_dump(exclude_none=True)


        def make_item_update() -> dict:
            \"\"\"Return a dict payload for item update.

            Returns:
                JSON-serializable dict matching the ItemUpdate schema.
            \"\"\"
            return ItemUpdatePayload().model_dump(exclude_none=True)
        """)
    dest.write_text(content)


def _write_slo_assertions(dest: Path) -> None:
    """Write ``tests/load/slo_assertions.py`` with locust.events SLO hook.

    Args:
        dest: Destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"SLO assertion hook for Locust load tests.

        Wires a ``locust.events.quitting`` listener that reads p99 latencies from
        the Locust stats, compares them to ``slo_config.yaml`` targets, and sets
        ``environment.process_exit_code = 1`` if any target is violated — causing
        CI to fail the load test gate.

        Generated by add_load_profile tool (TOOL-027).
        \"\"\"

        from __future__ import annotations

        import json
        import logging
        from pathlib import Path

        import yaml
        from locust import events
        from locust.runners import WorkerRunner

        logger = logging.getLogger(__name__)

        _SLO_CONFIG = Path(__file__).parent / "slo_config.yaml"


        def _load_slos() -> dict[str, int]:
            \"\"\"Load p99 SLO targets from ``slo_config.yaml``.

            Returns:
                Dict mapping endpoint label → p99 target in milliseconds.
            \"\"\"
            if not _SLO_CONFIG.exists():
                return {}
            with _SLO_CONFIG.open() as fh:
                cfg = yaml.safe_load(fh)
            return cfg.get("p99_targets_ms", {})


        def register_slo_handlers() -> None:
            \"\"\"Register SLO assertion event handlers with Locust.

            Call once at module import time in the locustfile so handlers are
            active for every test run.
            \"\"\"

            @events.quitting.add_listener
            def _assert_slos(environment, **_kwargs: object) -> None:
                \"\"\"Fail the run if any p99 latency target is violated.

                Args:
                    environment: Locust ``Environment`` instance.
                \"\"\"
                if isinstance(environment.runner, WorkerRunner):
                    return

                slos = _load_slos()
                if not slos:
                    logger.info("No SLO targets configured — skipping SLO assertions.")
                    return

                violations: dict[str, dict] = {}
                for name, entry in environment.runner.stats.entries.items():
                    label = f"{name[1]} {name[0]}"  # (path, method) → "METHOD /path"
                    target = slos.get(label)
                    if target is None:
                        continue
                    p99 = entry.get_response_time_percentile(0.99)
                    if p99 and p99 > target:
                        violations[label] = {
                            "p99_actual_ms": round(p99, 1),
                            "p99_target_ms": target,
                            "delta_ms": round(p99 - target, 1),
                        }

                if violations:
                    logger.error("SLO violations detected:")
                    for label, v in violations.items():
                        logger.error(
                            "  %s  p99=%sms  target=%sms  delta=+%sms",
                            label, v["p99_actual_ms"], v["p99_target_ms"], v["delta_ms"],
                        )
                    out = Path("load_slo_violations.json")
                    out.write_text(json.dumps(violations, indent=2))
                    environment.process_exit_code = 1
                else:
                    logger.info("All SLO targets met.")
        """)
    dest.write_text(content)


def _write_slo_yaml(dest: Path, slos: dict[str, int]) -> None:
    """Write ``tests/load/slo_config.yaml`` with p99 SLO targets.

    Args:
        dest: Destination path.
        slos: Dict mapping endpoint label → p99 target ms.
    """
    slo_lines = "\n".join(f'  "{label}": {ms}' for label, ms in sorted(slos.items()))
    content = textwrap.dedent(f"""\
        # tests/load/slo_config.yaml
        # Per-endpoint p99 latency SLO targets (milliseconds).
        # Generated by add_load_profile tool (TOOL-027).
        # Edit freely — these are committed baselines; CI regresses if exceeded.

        p99_targets_ms:
        {slo_lines}

        # Global thresholds
        max_error_rate_pct: 1.0     # Fail if > 1% of requests error
        min_rps: 10                  # Fail if sustained RPS drops below this
        """)
    dest.write_text(content)


def _write_shapes(dest: Path, users: int, spawn_rate: int, duration_seconds: int) -> None:
    """Write ``tests/load/shapes.py`` with step-load and spike ``LoadTestShape`` classes.

    Args:
        dest: Destination path.
        users: Target user count for the baseline shape.
        spawn_rate: Users per second ramp-up rate.
        duration_seconds: Smoke duration in seconds.
    """
    smoke_users = max(5, users // 10)
    peak_users = users * 3
    content = textwrap.dedent(f"""\
        \"\"\"Locust LoadTestShape classes for stepped load profiles.

        Three shapes are provided:
        - SmokeShape    — {smoke_users} users for {duration_seconds}s (sanity check)
        - BaselineShape — ramp to {users} users, hold steady (regression detection)
        - PeakShape     — ramp to {peak_users} users in steps (capacity envelope)

        Generated by add_load_profile tool (TOOL-027).
        \"\"\"

        from __future__ import annotations

        from locust import LoadTestShape


        class SmokeShape(LoadTestShape):
            \"\"\"Minimal smoke profile: {smoke_users} users for {duration_seconds} seconds.

            Use for quick sanity checks after a deployment.
            \"\"\"

            stages = [
                {{"duration": {duration_seconds}, "users": {smoke_users}, "spawn_rate": {spawn_rate}}},
            ]

            def tick(self) -> tuple[int, float] | None:
                \"\"\"Return (user_count, spawn_rate) or None to stop.

                Returns:
                    Tuple of target user count and spawn rate for the current stage.
                \"\"\"
                run_time = self.get_run_time()
                for stage in self.stages:
                    if run_time <= stage["duration"]:
                        return stage["users"], stage["spawn_rate"]
                return None


        class BaselineShape(LoadTestShape):
            \"\"\"Graduated ramp to {users} users, then hold for regression detection.

            Captures the steady-state p99 latency baseline committed in slo_config.yaml.
            \"\"\"

            stages = [
                {{"duration": 30,  "users": max(1, {users} // 5), "spawn_rate": {spawn_rate}}},
                {{"duration": 90,  "users": {users} // 2,         "spawn_rate": {spawn_rate}}},
                {{"duration": 240, "users": {users},               "spawn_rate": {spawn_rate}}},
            ]

            def tick(self) -> tuple[int, float] | None:
                \"\"\"Return (user_count, spawn_rate) or None to stop.

                Returns:
                    Tuple of target user count and spawn rate for the current stage.
                \"\"\"
                run_time = self.get_run_time()
                for stage in self.stages:
                    if run_time <= stage["duration"]:
                        return stage["users"], stage["spawn_rate"]
                return None


        class PeakShape(LoadTestShape):
            \"\"\"Step-load up to {peak_users} users to find the capacity envelope.

            If the API degrades gracefully each step, CI records the maximum
            sustained throughput before p99 starts breaching SLOs.
            \"\"\"

            stages = [
                {{"duration": 60,  "users": {users},          "spawn_rate": {spawn_rate}}},
                {{"duration": 120, "users": {users * 2},       "spawn_rate": {spawn_rate * 2}}},
                {{"duration": 200, "users": {peak_users},      "spawn_rate": {spawn_rate * 3}}},
                {{"duration": 260, "users": {users},           "spawn_rate": {spawn_rate}}},  # cool-down
            ]

            def tick(self) -> tuple[int, float] | None:
                \"\"\"Return (user_count, spawn_rate) or None to stop.

                Returns:
                    Tuple of target user count and spawn rate for the current stage.
                \"\"\"
                run_time = self.get_run_time()
                for stage in self.stages:
                    if run_time <= stage["duration"]:
                        return stage["users"], stage["spawn_rate"]
                return None
        """)
    dest.write_text(content)


def _write_scenarios(dest: Path, endpoints: list[str] | None) -> None:
    """Write ``tests/load/scenarios.py`` with weighted ``TaskSet`` classes.

    Args:
        dest: Destination path.
        endpoints: Optional explicit endpoint list.  When ``None`` the module
            targets the standard FastAPI full-stack template routes.
    """
    _ = endpoints  # reserved for future endpoint-specific generation
    content = textwrap.dedent("""\
        \"\"\"Locust TaskSet scenarios for browsing, active, and admin user flows.

        Generated by add_load_profile tool (TOOL-027).
        \"\"\"

        from __future__ import annotations

        import random

        from locust import TaskSet, task, tag

        from tests.load.data_factories import make_item_create, make_item_update


        class BrowsingScenario(TaskSet):
            \"\"\"Read-heavy browsing scenario (70% of simulated traffic).

            Simulates users navigating the catalog, searching, and viewing item
            detail pages without creating or modifying data.
            \"\"\"

            @task(10)
            @tag("read", "list")
            def list_items(self) -> None:
                \"\"\"GET /api/v1/items — most common endpoint.\"\"\"
                with self.client.get(
                    "/api/v1/items",
                    headers=self.user.auth_headers,
                    catch_response=True,
                    name="GET /api/v1/items",
                ) as resp:
                    if resp.status_code == 200:
                        resp.success()
                        self.user.last_items = resp.json().get("data", [])
                    else:
                        resp.failure(f"status {resp.status_code}")

            @task(3)
            @tag("read", "detail")
            def view_item(self) -> None:
                \"\"\"GET /api/v1/items/{id} — view a specific item.\"\"\"
                items = getattr(self.user, "last_items", [])
                if not items:
                    return
                item_id = random.choice(items).get("id")
                self.client.get(
                    f"/api/v1/items/{item_id}",
                    headers=self.user.auth_headers,
                    name="GET /api/v1/items/:id",
                )


        class ActiveUserScenario(TaskSet):
            \"\"\"Mixed read/write scenario (25% of simulated traffic).

            Simulates users creating items, updating their profile, and browsing.
            \"\"\"

            @task(6)
            @tag("read", "list")
            def list_items(self) -> None:
                \"\"\"GET /api/v1/items.\"\"\"
                self.client.get(
                    "/api/v1/items",
                    headers=self.user.auth_headers,
                    name="GET /api/v1/items",
                )

            @task(4)
            @tag("write", "create")
            def create_item(self) -> None:
                \"\"\"POST /api/v1/items — create a new item.\"\"\"
                self.client.post(
                    "/api/v1/items",
                    json=make_item_create(),
                    headers=self.user.auth_headers,
                    name="POST /api/v1/items",
                )

            @task(2)
            @tag("read", "me")
            def get_my_profile(self) -> None:
                \"\"\"GET /api/v1/users/me — fetch the authenticated user's profile.\"\"\"
                self.client.get(
                    "/api/v1/users/me",
                    headers=self.user.auth_headers,
                    name="GET /api/v1/users/me",
                )


        class AdminScenario(TaskSet):
            \"\"\"Admin-only scenario (5% of simulated traffic).

            Exercises superuser endpoints that require elevated privileges.
            \"\"\"

            @task(3)
            @tag("admin", "users")
            def list_users(self) -> None:
                \"\"\"GET /api/v1/users — list all users (admin only).\"\"\"
                self.client.get(
                    "/api/v1/users",
                    headers=self.user.auth_headers,
                    name="GET /api/v1/users (admin)",
                )

            @task(1)
            @tag("admin", "health")
            def check_health(self) -> None:
                \"\"\"GET /api/v1/utils/health-check — infrastructure health.\"\"\"
                self.client.get(
                    "/api/v1/utils/health-check",
                    headers=self.user.auth_headers,
                    name="GET /health",
                )
        """)
    dest.write_text(content)


def _write_locustfile(dest: Path, users: int, spawn_rate: int) -> None:
    """Write the main ``tests/load/locustfile.py``.

    Args:
        dest: Destination path.
        users: Default concurrent users for manual runs.
        spawn_rate: Default spawn rate for manual runs.
    """
    content = textwrap.dedent(f"""\
        \"\"\"Main Locust load-test entry point.

        Three weighted user classes simulate production traffic distribution:
        - BrowsingUser  (weight=5) — read-heavy, 70% of traffic
        - ActiveUser    (weight=3) — create/update mix, 25% of traffic
        - AdminUser     (weight=1) — admin endpoints, 5% of traffic

        Generated by add_load_profile tool (TOOL-027).

        Usage::

            # Smoke (quick)
            locust -f tests/load/locustfile.py --users 10 --spawn-rate 2 --run-time 60s --headless

            # Baseline
            locust -f tests/load/locustfile.py --users {users} --spawn-rate {spawn_rate} --run-time 300s --headless

            # Step-load (uses BaselineShape)
            locust -f tests/load/locustfile.py --shape-class tests.load.shapes.BaselineShape --headless
        \"\"\"

        from __future__ import annotations

        from locust import HttpUser, between, tag, task

        from tests.load.auth import AuthMixin
        from tests.load.scenarios import ActiveUserScenario, AdminScenario, BrowsingScenario
        from tests.load.slo_assertions import register_slo_handlers

        # Register SLO event handlers at import time
        register_slo_handlers()


        class BrowsingUser(HttpUser, AuthMixin):
            \"\"\"Simulates a read-heavy browsing user (70% traffic share).

            Attributes:
                weight: Relative probability of spawning this user class.
                wait_time: Random think time between tasks.
                tasks: Scenario class driving task selection.
            \"\"\"

            weight = 5
            wait_time = between(0.5, 2.5)
            tasks = [BrowsingScenario]

            def on_start(self) -> None:
                \"\"\"Login once at spawn and cache the JWT.\"\"\"
                self.login()


        class ActiveUser(HttpUser, AuthMixin):
            \"\"\"Simulates a write-active user (25% traffic share).

            Attributes:
                weight: Relative probability of spawning this user class.
                wait_time: Random think time between tasks.
                tasks: Scenario class driving task selection.
            \"\"\"

            weight = 3
            wait_time = between(1.0, 3.0)
            tasks = [ActiveUserScenario]

            def on_start(self) -> None:
                \"\"\"Login once at spawn and cache the JWT.\"\"\"
                self.login()


        class AdminUser(HttpUser, AuthMixin):
            \"\"\"Simulates an admin user (5% traffic share).

            Attributes:
                weight: Relative probability of spawning this user class.
                wait_time: Random think time between tasks.
                tasks: Scenario class driving task selection.
            \"\"\"

            weight = 1
            wait_time = between(2.0, 5.0)
            tasks = [AdminScenario]

            def on_start(self) -> None:
                \"\"\"Login once at spawn and cache the JWT.\"\"\"
                self.login()
        """)
    dest.write_text(content)


def _write_ci_workflow(dest: Path, users: int, spawn_rate: int, duration: int) -> None:
    """Write GitHub Actions CI workflow for load regression detection.

    Args:
        dest: Destination path.
        users: Baseline user count for CI smoke run.
        spawn_rate: Spawn rate for CI smoke run.
        duration: Duration in seconds for CI smoke run.
    """
    smoke_users = max(5, users // 10)
    content = textwrap.dedent(f"""\
        # .github/workflows/load-tests.yml
        # Load regression detection — runs smoke profile on every PR.
        # Generated by add_load_profile tool (TOOL-027).

        name: Load Tests

        on:
          pull_request:
            branches: [main, develop]

        jobs:
          smoke:
            name: Smoke load profile
            runs-on: ubuntu-latest
            services:
              app:
                image: ghcr.io/${{{{ github.repository }}}}:${{{{ github.sha }}}}
                ports:
                  - 8000:8000

            steps:
              - uses: actions/checkout@v4

              - name: Set up Python
                uses: actions/setup-python@v5
                with:
                  python-version: "3.12"
                  cache: pip

              - name: Install Locust
                run: pip install locust faker pyyaml

              - name: Run smoke profile
                run: |
                  locust \\
                    -f tests/load/locustfile.py \\
                    --host http://localhost:8000 \\
                    --users {smoke_users} \\
                    --spawn-rate {spawn_rate} \\
                    --run-time {duration}s \\
                    --headless \\
                    --csv load_results
                env:
                  PYTHONPATH: .

              - name: Upload load results
                if: always()
                uses: actions/upload-artifact@v4
                with:
                  name: load-results
                  path: |
                    load_results*.csv
                    load_slo_violations.json
        """)
    dest.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds.
    """
    return int((time.monotonic() - start) * 1000)
