"""`fastapi_testing` — the testing-domain tree dispatcher.

ONE MCP tool that routes to 11 slice tool(s) under the `testing` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the testing domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_api_fuzzer": {
        "mod": "add_api_fuzzer",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add schema-aware API fuzzing: APIFuzzer reads OpenAPI schema, generates adversarial inputs p...",
    },
    "add_chaos_testing": {
        "mod": "add_chaos_testing",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add chaos engineering fault injection for dev/staging. Hardcoded guard: NEVER active in prod...",
    },
    "add_contract_tests": {
        "mod": "add_contract_tests",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add consumer-driven contract tests using Pact or Schemathesis",
    },
    "add_data_seeder": {
        "mod": "add_data_seeder",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add a smart test data seeder that respects FK relationships via topological sort",
    },
    "add_database_migrations_ci": {
        "mod": "add_database_migrations_ci",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add Alembic CI runner with rollback safety and schema diff to FastAPI",
    },
    "add_e2e_test_suite": {
        "mod": "add_e2e_test_suite",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Scaffold an async E2E test suite with httpx: conftest fixtures, auth flow, CRUD flow, and er...",
    },
    "add_factory": {
        "mod": "add_factory",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add factory_boy fixtures for all models to accelerate test authoring",
    },
    "add_load_profile": {
        "mod": "add_load_profile",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add k6 load test profiles (smoke, load, stress, soak) for the project's endpoints",
    },
    "add_sbom_guardian": {
        "mod": "add_sbom_guardian",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add CycloneDX SBOM generation, lockfile integrity verification, dependency confusion detecti...",
    },
    "add_schema_enforcer": {
        "mod": "add_schema_enforcer",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add OpenAPI schema enforcement middleware: validates every req/resp against the spec (reject...",
    },
    "add_schema_evolution_guard": {
        "mod": "add_schema_evolution_guard",
        "pkg": "adapt.extend.testing_tools",
        "desc": "Add CI OpenAPI schema compatibility checker that detects breaking changes",
    },
}

PRIMITIVES: dict[str, str] = {}

# Curated 'bundle' — 7 canonical testing slices.
# Rationale: Production test scaffolding: E2E suite, factories, seeders, contract tests, k6 load profiles, OpenAPI enforcement, and SBOM guardian.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_e2e_test_suite",
    "add_factory",
    "add_data_seeder",
    "add_contract_tests",
    "add_load_profile",
    "add_schema_enforcer",
    "add_sbom_guardian",
)


# ---------------------------------------------------------------------------
# Shared envelope (same shape as tier-1 meta tools)
# ---------------------------------------------------------------------------


def _envelope(*, ok: bool, what: str, result: Any, next_steps: list[str], t0: float) -> dict:
    return {
        "ok": ok,
        "what_happened": what,
        "result": result,
        "next_steps": next_steps[:5],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# Slice routing
# ---------------------------------------------------------------------------


def _call_slice(slice_name: str, **kwargs) -> dict:
    """Route to the underlying `<pkg>.<mod>` tool.

    Multi-bucket aware: each SLICES entry carries its own `pkg` because
    testing tools span multiple adapt/ subtrees. Routes through the
    shared `dispatch_via_toolinput` helper so the public contract stays
    uniform (closes Codex 3 F-001).
    """
    from mcp_tools._tree_dispatch import dispatch_via_toolinput

    meta = SLICES[slice_name]
    return dispatch_via_toolinput(
        module_path=f"{meta['pkg']}.{meta['mod']}",
        entry_name=meta["mod"],
        slice_name=slice_name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Primitive routing
# ---------------------------------------------------------------------------

# No PRIMITIVES for domain 'testing': action="primitive" returns a
# descriptive error pointing the caller at the other dispatchers.


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_testing",
    "description": (
        "Testing domain dispatcher (HuGR tree pattern). ONE tool that routes to every testing-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full testing tree.\n  • 'bundle' → one-shot: installs 7 curated testing slices (add_e2e_test_suite, add_factory, add_data_seeder, add_contract_tests, add_load_profile, add_schema_enforcer, ...).\n  • '<slice>' → install ONE slice (add_api_fuzzer, add_chaos_testing, add_contract_tests, add_data_seeder, add_database_migrations_ci, add_e2e_test_suite, add_factory, add_load_profile, add_sbom_guardian, add_schema_enforcer, add_schema_evolution_guard).\n  • 'primitive' → N/A (no core.venous primitives here).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["testing", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_testing",
}


def fastapi_testing(action: str, params: dict | None = None) -> dict:
    """See MCP_TOOL description.

    Signature note: `params` is a polymorphic dict whose expected keys
    depend on `action`. FastMCP doesn't support **kwargs in tool
    signatures, so a single `params` dict is the uniform contract.
    """
    t0 = time.perf_counter()
    params = params or {}

    if action == "list":
        return _envelope(
            ok=True,
            what="testing domain tree (7 bundle + 11 slices)",
            result={
                "domain": "testing",
                "bundle": {
                    "description": (
                        "Install the curated production testing stack: "
                        f"{len(BUNDLE_SLICES)} slices composed in order."
                    ),
                    "slices_installed": list(BUNDLE_SLICES),
                    "required_params": {"output_dir": "str"},
                },
                "slices": {
                    name: {"description": meta["desc"]} for name, meta in sorted(SLICES.items())
                },
                "usage_examples": [
                    "fastapi_testing(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_testing(action='add_e2e_test_suite', params={'output_dir':'/tmp/my-app'})",
                ],
            },
            next_steps=[
                "action='bundle' → install everything for a new project.",
                "action='<slice>' → install one slice for an existing project.",
            ],
            t0=t0,
        )

    if action == "bundle":
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what="bundle requires output_dir",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project'}."],
                t0=t0,
            )
        installed: list[dict] = []
        errors: list[str] = []
        for slice_name in BUNDLE_SLICES:
            try:
                res = _call_slice(slice_name, **{**params, "output_dir": output_dir})
                installed.append({"slice": slice_name, "result": res})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{slice_name}: {exc}")
        ok = not errors
        return _envelope(
            ok=ok,
            what=f"bundle: {len(installed)}/{len(BUNDLE_SLICES)} slices installed"
            + (f"; {len(errors)} failure(s)" if errors else ""),
            result={"installed": installed, "errors": errors},
            next_steps=(
                [
                    "Bundle complete. Boot the app and exercise the new endpoints.",
                    "For remaining slices, call action=<slice> individually.",
                    "Call fastapi_meta_audit() to verify the contract.",
                ]
                if ok
                else ["Fix errors above. Retry failing slices individually via action=<slice>."]
            ),
            t0=t0,
        )

    if action == "primitive":
        return _envelope(
            ok=False,
            what="domain 'testing' exposes no core.venous primitives",
            result={},
            next_steps=[
                "Use action='<slice>' to install a slice tool instead.",
                "Call other dispatchers (fastapi_auth / fastapi_data / etc.) for primitives.",
            ],
            t0=t0,
        )

    if action in SLICES:
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what=f"slice {action!r} requires output_dir in params",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project', ...}."],
                t0=t0,
            )
        try:
            res = _call_slice(action, **params)
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                ok=False,
                what=f"slice {action!r} failed: {exc}",
                result={},
                next_steps=[
                    f"Check params for {action!r}. "
                    f"Call fastapi_meta_describe(name='fastapi_{SLICES[action]['mod']}') for the schema."
                ],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"slice {action} installed",
            result=res if isinstance(res, dict) else {"raw": repr(res)[:500]},
            next_steps=[
                "Boot the emitted app + hit the new endpoints to verify.",
                "Additional features? call fastapi_testing(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_testing(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
