"""`fastapi_testing` — the testing-domain tree dispatcher.

ONE MCP tool that routes to slice tool(s) + primitive(s) under the `testing` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical template this file mirrors.

M3.2 fan-out: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing, and primitive copy live in ``hugr_core.dispatch`` — the generic
engine shared by every domain. The data tables (SLICES / PRIMITIVES /
BUNDLE_SLICES / MCP_TOOL) are unchanged, so the public contract is
byte-identical to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "testing"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


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


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="testing",
    tool_name="fastapi_testing",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="testing domain tree (7 bundle + 11 slices)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    toolinput_factory=_toolinput_factory,
    bundle_missing_output_dir_next_steps=(
        "Pass params={'output_dir':'/path/to/project'}.",
    ),
)

fastapi_testing = make_dispatcher(_CONFIG)
