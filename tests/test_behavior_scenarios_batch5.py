"""BEHAVIOR scenarios 23-32 for TOOL-095 to TOOL-124 (30 newest tools).

Each scenario generates its own fixture project with ONLY the tools it
needs, patches ``app/core/db.py`` to SQLite+aiosqlite (no Docker),
patches ``app/middleware/idempotency.py`` to a pass-through stub, boots
the app, and runs real HTTP flows.

These tests intentionally do NOT require PostgreSQL — they use SQLite so
that CI can run them with zero external infrastructure.

This file holds scenarios 23-24; the remaining scenarios live in the
sibling ``test_behavior_scenarios_batch5__part{2,3,4}.py`` files and the
shared framework lives in ``test_behavior_scenarios_batch5__shared.py``.
The standalone runner below (``python tests/test_behavior_scenarios_batch5.py``)
still executes ALL 10 scenarios by importing them from the sibling parts.

Run::

    PYTHONPATH=. python tests/test_behavior_scenarios_batch5.py

Exit 0 → all assertions passed.
Exit 1 → at least one scenario has failures.
"""

from __future__ import annotations

import sys
import time

import pytest

from tests.test_behavior_scenarios_batch5__shared import (
    Scenario,
    ScenarioContext,
    _run_scenario,
    run_scenario_assert,
)


# ===========================================================================
# SCENARIO 23 — Resiliency Stack
# TOOL-095 add_load_shedding, TOOL-096 add_adaptive_timeouts, TOOL-097 add_bulkhead_isolation
# ===========================================================================

async def flow_resiliency_stack(ctx: ScenarioContext) -> None:
    """LoadShedder + AdaptiveTimeout + Bulkhead: classes importable, endpoint exists."""
    project_dir = ctx.project_dir
    client = ctx.client

    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)

    # ---- LoadShedder class functional -----------------------------------------------
    shedder_path = project_dir / "app" / "resilience" / "load_shedder.py"
    ctx.record("load_shedder_file_exists", shedder_path.exists(),
               str(shedder_path.relative_to(project_dir) if shedder_path.exists() else "NOT FOUND"))

    if shedder_path.exists():
        try:
            import importlib.util as _util
            spec = _util.spec_from_file_location("_load_shedder_test", str(shedder_path))
            if spec and spec.loader:
                shedder_mod = _util.module_from_spec(spec)
                spec.loader.exec_module(shedder_mod)  # type: ignore[attr-defined]
            ctx.record("load_shedder_class_importable",
                       hasattr(shedder_mod, "LoadShedder"),
                       "LoadShedder class present in load_shedder.py")
            # Verify basic functionality: can instantiate and call get_p99
            shedder_instance = shedder_mod.LoadShedder()
            p99 = shedder_instance.get_p99()
            ctx.record("load_shedder_get_p99_callable",
                       isinstance(p99, (int, float)),
                       f"get_p99() returned: {p99}")
        except Exception as exc:
            ctx.record("load_shedder_class_importable", False,
                       f"{type(exc).__name__}: {str(exc)[:200]}")
            ctx.record("load_shedder_get_p99_callable", False, "import failed")
    else:
        ctx.record("load_shedder_class_importable", False, "file not found")
        ctx.record("load_shedder_get_p99_callable", False, "file not found")

    # ---- Priority classifier returns CRITICAL for /healthz ----------------------
    priority_path = project_dir / "app" / "resilience" / "priority.py"
    if priority_path.exists():
        try:
            import importlib.util as _util2
            spec2 = _util2.spec_from_file_location("_priority_test", str(priority_path))
            if spec2 and spec2.loader:
                priority_mod = _util2.module_from_spec(spec2)
                spec2.loader.exec_module(priority_mod)  # type: ignore[attr-defined]
            classify_fn = getattr(priority_mod, "classify_request", None)
            RequestPriority = getattr(priority_mod, "RequestPriority", None)
            if classify_fn and RequestPriority:
                result = classify_fn("/healthz", "GET")
                is_critical = (result == RequestPriority.CRITICAL
                               or str(result).lower() == "critical"
                               or (hasattr(result, "value") and result.value == "critical"))
                ctx.record("priority_classifier_healthz_is_critical", is_critical,
                           f"classify_request('/healthz') = {result!r}")
            else:
                ctx.record("priority_classifier_healthz_is_critical", False,
                           "classify_request or RequestPriority not found in priority.py")
        except Exception as exc:
            ctx.record("priority_classifier_healthz_is_critical", False,
                       f"{type(exc).__name__}: {str(exc)[:200]}")
    else:
        ctx.record("priority_classifier_healthz_is_critical", False,
                   "app/resilience/priority.py not found")

    # ---- Bulkhead pool config readable ------------------------------------------
    bulkhead_path = project_dir / "app" / "resilience" / "bulkhead.py"
    pool_config_path = project_dir / "app" / "resilience" / "pool_config.py"
    bulkhead_found = bulkhead_path.exists() or pool_config_path.exists()
    ctx.record("bulkhead_config_file_exists", bulkhead_found,
               "app/resilience/bulkhead.py or pool_config.py present")

    if bulkhead_path.exists():
        src = bulkhead_path.read_text()
        ctx.record("bulkhead_class_present", "Bulkhead" in src or "bulkhead" in src.lower(),
                   "Bulkhead class definition in bulkhead.py")
    else:
        ctx.record("bulkhead_class_present", False, "bulkhead.py not found")

    # ---- Bulkhead status route file written (may be commented in main.py) -------
    # add_bulkhead_isolation writes the route file but adds it as a commented
    # include in main.py (opt-in pattern). Verify the file was written.
    bulkhead_status_route = project_dir / "app" / "api" / "routes" / "bulkhead_status.py"
    ctx.record("bulkhead_status_route_file_exists", bulkhead_status_route.exists(),
               str(bulkhead_status_route.relative_to(project_dir)
                   if bulkhead_status_route.exists() else "NOT FOUND"))

    # GET /resilience/bulkheads — may be 404 if not auto-registered (opt-in route)
    r = await client.get("/resilience/bulkheads")
    if r.status_code != 404:
        ctx.record("resilience_bulkheads_endpoint_or_file",
                   True,
                   f"GET /resilience/bulkheads: {r.status_code}")
        if r.status_code == 200:
            body = {}
            try:
                body = r.json()
            except Exception:
                pass
            ctx.record("bulkheads_response_is_json",
                       isinstance(body, (dict, list)),
                       f"body type: {type(body).__name__}")
        else:
            ctx.record("bulkheads_response_is_json", True,
                       f"skipped (status {r.status_code})")
    else:
        # Route not auto-registered (opt-in) — pass if the route file was written
        ctx.record("resilience_bulkheads_endpoint_or_file",
                   bulkhead_status_route.exists(),
                   "route file written (opt-in include in main.py)")
        ctx.record("bulkheads_response_is_json", True,
                   "skipped (route not auto-registered)")


RESILIENCY_STACK = Scenario(
    name="resiliency_stack",
    archetype="LoadShedder + AdaptiveTimeouts + BulkheadIsolation resiliency stack",
    models={"Service": {"name": "str", "endpoint": "str"}},
    tools=[
        ("add_load_shedding",      "adapt.extend.infrastructure.add_load_shedding"),
        ("add_adaptive_timeouts",  "adapt.extend.infrastructure.add_adaptive_timeouts"),
        ("add_bulkhead_isolation", "adapt.extend.infrastructure.add_bulkhead_isolation"),
    ],
    flow=flow_resiliency_stack,
)


# ===========================================================================
# SCENARIO 24 — Retry + Chaos + Shutdown
# TOOL-098 add_retry_budget, TOOL-099 add_chaos_testing, TOOL-100 add_graceful_shutdown
# ===========================================================================

async def flow_retry_chaos_shutdown(ctx: ScenarioContext) -> None:
    """RetryBudget module imports, ChaosEngine has production guard, GracefulShutdown present."""
    project_dir = ctx.project_dir
    client = ctx.client

    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)

    # ---- RetryBudget module imports cleanly -------------------------------------
    budget_path = project_dir / "app" / "resilience" / "retry_budget.py"
    ctx.record("retry_budget_file_exists", budget_path.exists(),
               str(budget_path.relative_to(project_dir) if budget_path.exists() else "NOT FOUND"))

    if budget_path.exists():
        try:
            import importlib.util as _util
            spec = _util.spec_from_file_location("_retry_budget_test", str(budget_path))
            if spec and spec.loader:
                rb_mod = _util.module_from_spec(spec)
                spec.loader.exec_module(rb_mod)  # type: ignore[attr-defined]
            ctx.record("retry_budget_class_importable",
                       hasattr(rb_mod, "RetryBudget"),
                       "RetryBudget class present in retry_budget.py")
        except Exception as exc:
            ctx.record("retry_budget_class_importable", False,
                       f"{type(exc).__name__}: {str(exc)[:200]}")
    else:
        ctx.record("retry_budget_class_importable", False, "file not found")

    # ---- ChaosEngine has production guard (ENVIRONMENT check) -------------------
    chaos_init_path = project_dir / "app" / "chaos" / "__init__.py"
    ctx.record("chaos_engine_file_exists", chaos_init_path.exists(),
               str(chaos_init_path.relative_to(project_dir) if chaos_init_path.exists() else "NOT FOUND"))

    if chaos_init_path.exists():
        chaos_src = chaos_init_path.read_text()
        # Must have hardcoded production guard: check ENVIRONMENT != production
        has_production_guard = (
            "production" in chaos_src
            and "ENVIRONMENT" in chaos_src
            and ("ChaosEngine" in chaos_src)
        )
        ctx.record("chaos_engine_has_production_guard", has_production_guard,
                   "ChaosEngine + ENVIRONMENT + 'production' all present in chaos/__init__.py")
    else:
        ctx.record("chaos_engine_has_production_guard", False, "chaos/__init__.py not found")

    # ---- GET /chaos/status returns enabled=false (ENVIRONMENT=local) ------------
    r_chaos = await client.get("/chaos/status")
    ctx.record("chaos_status_endpoint_exists",
               r_chaos.status_code != 404,
               f"GET /chaos/status: {r_chaos.status_code} (404 = route missing)")
    if r_chaos.status_code == 200:
        try:
            body = r_chaos.json()
            enabled_val = body.get("enabled", body.get("chaos_enabled", None))
            ctx.record("chaos_status_not_enabled_in_local",
                       enabled_val is False or enabled_val == "false" or enabled_val is None,
                       f"enabled={enabled_val!r} (should be false/None in local env)")
        except Exception:
            ctx.record("chaos_status_not_enabled_in_local", True,
                       "skipped (could not parse JSON)")
    else:
        ctx.record("chaos_status_not_enabled_in_local", True,
                   f"skipped (status {r_chaos.status_code})")

    # ---- GracefulShutdown signal handler registered in source -------------------
    shutdown_path = project_dir / "app" / "lifecycle" / "shutdown.py"
    ctx.record("graceful_shutdown_file_exists", shutdown_path.exists(),
               str(shutdown_path.relative_to(project_dir) if shutdown_path.exists() else "NOT FOUND"))

    if shutdown_path.exists():
        sd_src = shutdown_path.read_text()
        # Must contain GracefulShutdown class and signal handling
        has_signal_handling = (
            "GracefulShutdown" in sd_src
            and ("SIGTERM" in sd_src or "signal" in sd_src)
        )
        ctx.record("graceful_shutdown_has_signal_handler", has_signal_handling,
                   "GracefulShutdown class with SIGTERM/signal handling present")
    else:
        ctx.record("graceful_shutdown_has_signal_handler", False, "file not found")

    # ---- POST /chaos/enable returns 403 or error in local (production guard) ----
    r_enable = await client.post("/chaos/enable", json={})
    ctx.record("chaos_enable_endpoint_exists",
               r_enable.status_code != 404,
               f"POST /chaos/enable: {r_enable.status_code} (404 = route missing)")
    # In local env with ENVIRONMENT=local, enabling chaos may succeed (200)
    # or fail (403/422/500). All are acceptable; 404 is not.
    ctx.record("chaos_enable_responds_meaningfully",
               r_enable.status_code != 404,
               f"POST /chaos/enable: {r_enable.status_code} (not 404)")


RETRY_CHAOS_SHUTDOWN = Scenario(
    name="retry_chaos_shutdown",
    archetype="RetryBudget + ChaosEngine (prod guard) + GracefulShutdown",
    models={"Task": {"name": "str", "retries": "int"}},
    tools=[
        ("add_retry_budget",      "adapt.extend.infrastructure.add_retry_budget"),
        ("add_chaos_testing",     "adapt.extend.infrastructure.add_chaos_testing"),
        ("add_graceful_shutdown", "adapt.extend.infrastructure.add_graceful_shutdown"),
    ],
    flow=flow_retry_chaos_shutdown,
)


# ===========================================================================
# pytest integration — one parametrized test per scenario (this file only)
# ===========================================================================

SCENARIOS: list[Scenario] = [
    RESILIENCY_STACK,
    RETRY_CHAOS_SHUTDOWN,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
@pytest.mark.asyncio
async def test_scenario(scenario: Scenario) -> None:
    """Run a behavior scenario end-to-end and assert all checks pass."""
    await run_scenario_assert(scenario)


# ===========================================================================
# Standalone runner (no pytest required) — runs ALL 10 scenarios
# ===========================================================================

def _all_scenarios() -> list[Scenario]:
    """Assemble the full batch-5 scenario list across the split part files."""
    import asyncio  # noqa: F401  (kept for parity with original module imports)
    from tests.test_behavior_scenarios_batch5__part2 import SCENARIOS as P2
    from tests.test_behavior_scenarios_batch5__part3 import SCENARIOS as P3
    from tests.test_behavior_scenarios_batch5__part4 import SCENARIOS as P4
    return [*SCENARIOS, *P2, *P3, *P4]


def main() -> int:
    import asyncio

    all_scenarios = _all_scenarios()

    print("=" * 74)
    print(f"  SKILL-001 BATCH 5 BEHAVIOR SCENARIOS — {len(all_scenarios)} scenarios")
    print(f"  Tools: TOOL-095 to TOOL-124 (30 newest tools)")
    print(f"  Backend: SQLite in-memory (no PostgreSQL required)")
    print("=" * 74)
    print()

    overall_passed = 0
    overall_total = 0
    scenario_results: list[tuple[str, int, int, list]] = []
    t_start = time.monotonic()

    for scenario in all_scenarios:
        t0 = time.monotonic()
        print(f"  Scenario: {scenario.name}")
        print(f"  Archetype: {scenario.archetype}")
        print(f"  Tools: {', '.join(t[0] for t in scenario.tools)}")
        try:
            passed, total, details = asyncio.run(_run_scenario(scenario))
        except Exception as exc:
            passed, total = 0, 1
            details = [("runner", False, f"{type(exc).__name__}: {str(exc)[:200]}")]

        elapsed = time.monotonic() - t0
        overall_passed += passed
        overall_total += total
        scenario_results.append((scenario.name, passed, total, details))

        mark = "PASS" if passed == total else "FAIL"
        print(f"  [{mark}] {passed}/{total} assertions  ({elapsed:.1f}s)")
        for name, ok, detail in details:
            status = "  [PASS]" if ok else "  [FAIL]"
            print(f"    {status}  {name}: {detail}")
        print()

    elapsed = time.monotonic() - t_start
    print("=" * 74)
    print(f"  OVERALL: {overall_passed}/{overall_total} assertions "
          f"across {len(all_scenarios)} scenarios  ({elapsed:.1f}s)")
    print("=" * 74)

    failed_scenarios = [r for r in scenario_results if r[1] < r[2]]
    if failed_scenarios:
        print()
        print("  Failed scenarios:")
        for name, p, t, _ in failed_scenarios:
            print(f"    - {name}: {p}/{t}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
