"""Boot chain tests — verify that multiple adapt tools applied in sequence produce
a bootable FastAPI app at every step.

Runs as a standalone script or via pytest::

    # Standalone
    PYTHONPATH=. python3 tests/test_boot_chains.py

    # Via pytest
    PYTHONPATH=. pytest tests/test_boot_chains.py -v

Each chain test:
1. Generates a fresh base project via ``tests.common.fixture_factory.create_fixture_project``
2. Applies tools in the specified sequence, one at a time
3. After each tool, runs ``python -c "from app.main import app; print('BOOT_OK')"``
4. Asserts "BOOT_OK" appears in stdout at every step

Five chains are tested:
- Chain 1: CRUD (7 tools in natural order)
- Chain 2: Auth (6 tools in natural order)
- Chain 3: Realtime + Infrastructure (7 tools)
- Chain 4: Full 27 tools in forward order
- Chain 5: Full 27 tools in reverse order

Exit code 0 → all chains pass
Exit code 1 → one or more chains failed (details printed)
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from adapt.contracts import ToolInput
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Tool sequences
# ---------------------------------------------------------------------------

CRUD_CHAIN: list[tuple[str, str, str]] = [
    ("add_audit_log",        "adapt.extend.crud_data.add_audit_log",        "add_audit_log"),
    ("add_bulk_operations",  "adapt.extend.crud_data.add_bulk_operations",  "add_bulk_operations"),
    ("add_cursor_pagination","adapt.extend.crud_data.add_cursor_pagination","add_cursor_pagination"),
    ("add_data_export",      "adapt.extend.crud_data.add_data_export",      "add_data_export"),
    ("add_file_upload",      "adapt.extend.crud_data.add_file_upload",      "add_file_upload"),
    ("add_search",           "adapt.extend.crud_data.add_search",           "add_search"),
    ("add_soft_delete",      "adapt.extend.crud_data.add_soft_delete",      "add_soft_delete"),
]

AUTH_CHAIN: list[tuple[str, str, str]] = [
    ("add_api_key_auth",     "adapt.extend.auth_access.add_api_key_auth",   "add_api_key_auth"),
    ("add_feature_flags",    "adapt.extend.auth_access.add_feature_flags",  "add_feature_flags"),
    ("add_mfa",              "adapt.extend.auth_access.add_mfa",            "add_mfa"),
    ("add_multi_tenancy",    "adapt.extend.auth_access.add_multi_tenancy",  "add_multi_tenancy"),
    ("add_oauth2_provider",  "adapt.extend.auth_access.add_oauth2_provider","add_oauth2_provider"),
    ("add_rbac",             "adapt.extend.auth_access.add_rbac",           "add_rbac"),
]

RT_INFRA_CHAIN: list[tuple[str, str, str]] = [
    ("add_cache_layer",      "adapt.extend.infrastructure.add_cache_layer",      "add_cache_layer"),
    ("add_circuit_breaker",  "adapt.extend.infrastructure.add_circuit_breaker",  "add_circuit_breaker"),
    ("add_outbox_pattern",   "adapt.extend.infrastructure.add_outbox_pattern",   "add_outbox_pattern"),
    ("add_saga",             "adapt.extend.infrastructure.add_saga",             "add_saga"),
    ("add_arq_worker",       "adapt.extend.infrastructure.add_arq_worker",       "add_arq_worker"),
    ("add_stripe_checkout",  "adapt.extend.infrastructure.add_stripe_checkout",  "add_stripe_checkout"),
    ("add_email_templates",  "adapt.extend.infrastructure.add_email_templates",  "add_email_templates"),
    ("add_rate_limiting",    "adapt.extend.infrastructure.add_rate_limiting",    "add_rate_limiting"),
    ("add_scheduled_tasks",  "adapt.extend.infrastructure.add_scheduled_tasks",  "add_scheduled_tasks"),
    ("add_sqladmin",         "adapt.extend.infrastructure.add_sqladmin",         "add_sqladmin"),
    ("add_celery_beat",      "adapt.extend.infrastructure.add_celery_beat",      "add_celery_beat"),
    ("add_s3_storage",       "adapt.extend.infrastructure.add_s3_storage",       "add_s3_storage"),
    ("add_health_deep",      "adapt.extend.infrastructure.add_health_deep",      "add_health_deep"),
    ("add_notifications",    "adapt.extend.infrastructure.add_notifications",    "add_notifications"),
    ("add_stripe_subscription","adapt.extend.infrastructure.add_stripe_subscription","add_stripe_subscription"),
    ("add_stripe_refund_flow","adapt.extend.infrastructure.add_stripe_refund_flow","add_stripe_refund_flow"),
    ("add_temporal_workflow","adapt.extend.infrastructure.add_temporal_workflow","add_temporal_workflow"),
    ("add_ml_model_server","adapt.extend.infrastructure.add_ml_model_server","add_ml_model_server"),
    ("add_ml_gpu_inference","adapt.extend.infrastructure.add_ml_gpu_inference","add_ml_gpu_inference"),
    ("add_ml_model_registry","adapt.extend.infrastructure.add_ml_model_registry","add_ml_model_registry"),
    ("add_sse",              "adapt.extend.realtime.add_sse",                    "add_sse"),
    ("add_webhook_receiver", "adapt.extend.realtime.add_webhook_receiver",       "add_webhook_receiver"),
    ("add_webhook_sender",   "adapt.extend.realtime.add_webhook_sender",         "add_webhook_sender"),
    ("add_websocket_chat",   "adapt.extend.realtime.add_websocket_chat",         "add_websocket_chat"),
]

ALL_TOOLS_FORWARD: list[tuple[str, str, str]] = [
    # auth_access
    ("add_api_key_auth",      "adapt.extend.auth_access.add_api_key_auth",    "add_api_key_auth"),
    ("add_feature_flags",     "adapt.extend.auth_access.add_feature_flags",   "add_feature_flags"),
    ("add_mfa",               "adapt.extend.auth_access.add_mfa",             "add_mfa"),
    ("add_multi_tenancy",     "adapt.extend.auth_access.add_multi_tenancy",   "add_multi_tenancy"),
    ("add_oauth2_provider",   "adapt.extend.auth_access.add_oauth2_provider", "add_oauth2_provider"),
    ("add_rbac",              "adapt.extend.auth_access.add_rbac",            "add_rbac"),
    # crud_data
    ("add_audit_log",         "adapt.extend.crud_data.add_audit_log",         "add_audit_log"),
    ("add_bulk_operations",   "adapt.extend.crud_data.add_bulk_operations",   "add_bulk_operations"),
    ("add_cursor_pagination", "adapt.extend.crud_data.add_cursor_pagination", "add_cursor_pagination"),
    ("add_data_export",       "adapt.extend.crud_data.add_data_export",       "add_data_export"),
    ("add_file_upload",       "adapt.extend.crud_data.add_file_upload",       "add_file_upload"),
    ("add_search",            "adapt.extend.crud_data.add_search",            "add_search"),
    ("add_soft_delete",       "adapt.extend.crud_data.add_soft_delete",       "add_soft_delete"),
    # infrastructure
    ("add_cache_layer",       "adapt.extend.infrastructure.add_cache_layer",      "add_cache_layer"),
    ("add_circuit_breaker",   "adapt.extend.infrastructure.add_circuit_breaker",  "add_circuit_breaker"),
    ("add_outbox_pattern",    "adapt.extend.infrastructure.add_outbox_pattern",   "add_outbox_pattern"),
    ("add_saga",              "adapt.extend.infrastructure.add_saga",             "add_saga"),
    ("add_arq_worker",        "adapt.extend.infrastructure.add_arq_worker",       "add_arq_worker"),
    ("add_stripe_checkout",   "adapt.extend.infrastructure.add_stripe_checkout",  "add_stripe_checkout"),
    ("add_email_templates",   "adapt.extend.infrastructure.add_email_templates",  "add_email_templates"),
    ("add_rate_limiting",     "adapt.extend.infrastructure.add_rate_limiting",    "add_rate_limiting"),
    ("add_scheduled_tasks",   "adapt.extend.infrastructure.add_scheduled_tasks",  "add_scheduled_tasks"),
    ("add_sqladmin",          "adapt.extend.infrastructure.add_sqladmin",         "add_sqladmin"),
    ("add_celery_beat",       "adapt.extend.infrastructure.add_celery_beat",      "add_celery_beat"),
    ("add_s3_storage",        "adapt.extend.infrastructure.add_s3_storage",       "add_s3_storage"),
    ("add_health_deep",       "adapt.extend.infrastructure.add_health_deep",      "add_health_deep"),
    ("add_notifications",     "adapt.extend.infrastructure.add_notifications",    "add_notifications"),
    ("add_stripe_subscription","adapt.extend.infrastructure.add_stripe_subscription","add_stripe_subscription"),
    ("add_stripe_refund_flow","adapt.extend.infrastructure.add_stripe_refund_flow","add_stripe_refund_flow"),
    ("add_temporal_workflow", "adapt.extend.infrastructure.add_temporal_workflow","add_temporal_workflow"),
    ("add_ml_model_server","adapt.extend.infrastructure.add_ml_model_server","add_ml_model_server"),
    ("add_ml_gpu_inference","adapt.extend.infrastructure.add_ml_gpu_inference","add_ml_gpu_inference"),
    ("add_ml_model_registry","adapt.extend.infrastructure.add_ml_model_registry","add_ml_model_registry"),
    # auth_access (extended)
    ("add_feature_toggles_api","adapt.extend.auth_access.add_feature_toggles_api","add_feature_toggles_api"),
    # realtime
    ("add_sse",               "adapt.extend.realtime.add_sse",                    "add_sse"),
    ("add_webhook_receiver",  "adapt.extend.realtime.add_webhook_receiver",       "add_webhook_receiver"),
    ("add_webhook_sender",    "adapt.extend.realtime.add_webhook_sender",         "add_webhook_sender"),
    ("add_websocket_chat",    "adapt.extend.realtime.add_websocket_chat",         "add_websocket_chat"),
    ("add_websocket_presence","adapt.extend.realtime.add_websocket_presence",    "add_websocket_presence"),
    # api_design
    ("add_api_versioning",    "adapt.extend.api_design.add_api_versioning",       "add_api_versioning"),
    ("add_batch_endpoint",    "adapt.extend.api_design.add_batch_endpoint",       "add_batch_endpoint"),
    ("add_long_running_task", "adapt.extend.api_design.add_long_running_task",    "add_long_running_task"),
    ("add_graphql",           "adapt.extend.api_design.add_graphql",              "add_graphql"),
    # testing_tools
    ("add_contract_tests",    "adapt.extend.testing_tools.add_contract_tests",    "add_contract_tests"),
    ("add_factory",           "adapt.extend.testing_tools.add_factory",           "add_factory"),
    ("add_load_profile",      "adapt.extend.testing_tools.add_load_profile",      "add_load_profile"),
]

ALL_TOOLS_REVERSE: list[tuple[str, str, str]] = list(reversed(ALL_TOOLS_FORWARD))


# ---------------------------------------------------------------------------
# Core boot-check helper
# ---------------------------------------------------------------------------

def _boot_ok(project_dir: Path) -> tuple[bool, str]:
    """Return (True, '') if the project boots, else (False, first_error_line).

    Args:
        project_dir: Root directory of the generated project.

    Returns:
        Tuple of (passed, error_message).
    """
    try:
        r = subprocess.run(
            [sys.executable, "-c", "from app.main import app; print('BOOT_OK')"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "Boot subprocess timed out (>30s)"

    if "BOOT_OK" in r.stdout:
        return True, ""

    for line in r.stderr.splitlines():
        stripped = line.strip()
        if stripped and any(kw in stripped for kw in ("Error", "error", "Exception", "Traceback")):
            if any(skip in stripped for skip in ("pydantic", "opentelemetry", "logfire", "UserWarning")):
                continue
            return False, stripped
    return False, f"returncode={r.returncode}, no error line found in stderr"


def _run_chain(
    chain_name: str,
    tools: list[tuple[str, str, str]],
) -> tuple[bool, list[str]]:
    """Apply all tools in sequence to a fresh project, boot-checking after each.

    Args:
        chain_name: Human-readable label for this chain (for error messages).
        tools: List of (display_name, dotted_module, function_name) tuples.

    Returns:
        (all_passed, list_of_failures) where each failure is a descriptive string.
    """
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_dir = create_fixture_project(
            name=f"chain_{chain_name.replace(' ', '_').lower()}",
            tmp_dir=Path(tmp_dir),
        )

        for step, (tool_name, module_path, fn_name) in enumerate(tools, 1):
            try:
                mod = importlib.import_module(module_path)
                fn = getattr(mod, fn_name)
            except Exception as exc:
                failures.append(f"[{chain_name}] step {step} ({tool_name}): import failed — {exc}")
                break

            result = fn(ToolInput(project_dir=str(project_dir)))
            if result.status == "error":
                failures.append(
                    f"[{chain_name}] step {step} ({tool_name}): tool returned error — {result.error}"
                )
                break

            passed, error_msg = _boot_ok(project_dir)
            if not passed:
                failures.append(
                    f"[{chain_name}] step {step} ({tool_name}): boot failed — {error_msg}"
                )
                break

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Pytest parametrize
# ---------------------------------------------------------------------------

CHAINS = [
    ("crud",     "CRUD 7 tools (forward)",       CRUD_CHAIN),
    ("auth",     "Auth 6 tools (forward)",        AUTH_CHAIN),
    ("rt_infra", "RT+Infra 7 tools (forward)",    RT_INFRA_CHAIN),
    ("full_fwd", "Full 46 tools (forward)",        ALL_TOOLS_FORWARD),
    ("full_rev", "Full 46 tools (reverse)",        ALL_TOOLS_REVERSE),
]


@pytest.mark.parametrize("chain_id,chain_label,tools", CHAINS, ids=[c[0] for c in CHAINS])
def test_boot_chain(chain_id: str, chain_label: str, tools: list[tuple[str, str, str]]) -> None:
    """Boot-check a complete tool chain applied to a fresh project.

    Args:
        chain_id: Short identifier used by pytest parametrize.
        chain_label: Human-readable chain description.
        tools: Ordered list of (name, module, function) tuples.
    """
    passed, failures = _run_chain(chain_label, tools)
    assert passed, "\n".join(failures)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all five boot chains and print a summary.

    Returns:
        0 if all chains pass, 1 if any fail.
    """
    all_failures: list[str] = []

    for chain_id, chain_label, tools in CHAINS:
        print(f"Running {chain_label} ({len(tools)} tools)...", flush=True)
        passed, failures = _run_chain(chain_label, tools)
        if passed:
            print(f"  PASS  {chain_label}")
        else:
            all_failures.extend(failures)
            for f in failures:
                print(f"  FAIL  {f}")

    print(f"\n{'='*60}")
    if all_failures:
        print(f"Boot chain result: {len(CHAINS) - len(all_failures)}/{len(CHAINS)} chains passed")
        print(f"\nFailures ({len(all_failures)}):")
        for f in all_failures:
            print(f"  {f}")
        return 1

    print(f"Boot chain result: {len(CHAINS)}/{len(CHAINS)} chains pass — all tools compose cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
