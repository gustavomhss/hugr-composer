"""Boot test — verifies every adapt tool produces a bootable FastAPI app.

Runs as a standalone script:
    PYTHONPATH=. python3 tests/test_boot.py

Each test case:
1. Generates a fresh base project via ``generators.orchestrator.generate_project``
2. Applies the adapt tool under test
3. Launches a subprocess: ``python -c "from app.main import app; print('BOOT OK')"``
4. Asserts "BOOT OK" appears in stdout (no ImportError / TypeError at import time)

Exit code 0  → all tools boot cleanly
Exit code 1  → one or more tools failed to boot (details printed per-tool)
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Tool registry — (display_name, dotted_module, function_name)
# ---------------------------------------------------------------------------

EXTEND_TOOLS: list[tuple[str, str, str]] = [
    # api_design
    ("add_api_versioning",  "adapt.extend.api_design.add_api_versioning",  "add_api_versioning"),
    ("add_batch_endpoint",  "adapt.extend.api_design.add_batch_endpoint",  "add_batch_endpoint"),
    ("add_graphql",         "adapt.extend.api_design.add_graphql",         "add_graphql"),
    ("add_long_running_task","adapt.extend.api_design.add_long_running_task","add_long_running_task"),
    # auth_access
    ("add_api_key_auth",    "adapt.extend.auth_access.add_api_key_auth",   "add_api_key_auth"),
    ("add_feature_flags",   "adapt.extend.auth_access.add_feature_flags",  "add_feature_flags"),
    ("add_mfa",             "adapt.extend.auth_access.add_mfa",            "add_mfa"),
    ("add_multi_tenancy",   "adapt.extend.auth_access.add_multi_tenancy",  "add_multi_tenancy"),
    ("add_oauth2_provider", "adapt.extend.auth_access.add_oauth2_provider","add_oauth2_provider"),
    ("add_rbac",            "adapt.extend.auth_access.add_rbac",           "add_rbac"),
    # crud_data
    ("add_audit_log",       "adapt.extend.crud_data.add_audit_log",        "add_audit_log"),
    ("add_bulk_operations", "adapt.extend.crud_data.add_bulk_operations",  "add_bulk_operations"),
    ("add_cursor_pagination","adapt.extend.crud_data.add_cursor_pagination","add_cursor_pagination"),
    ("add_data_export",     "adapt.extend.crud_data.add_data_export",      "add_data_export"),
    ("add_file_upload",     "adapt.extend.crud_data.add_file_upload",      "add_file_upload"),
    ("add_search",          "adapt.extend.crud_data.add_search",           "add_search"),
    ("add_soft_delete",     "adapt.extend.crud_data.add_soft_delete",      "add_soft_delete"),
    # infrastructure
    ("add_cache_layer",      "adapt.extend.infrastructure.add_cache_layer",      "add_cache_layer"),
    ("add_circuit_breaker",  "adapt.extend.infrastructure.add_circuit_breaker",  "add_circuit_breaker"),
    ("add_outbox_pattern",   "adapt.extend.infrastructure.add_outbox_pattern",   "add_outbox_pattern"),
    ("add_saga",             "adapt.extend.infrastructure.add_saga",             "add_saga"),
    ("add_arq_worker",       "adapt.extend.infrastructure.add_arq_worker",       "add_arq_worker"),
    ("add_stripe_checkout",  "adapt.extend.infrastructure.add_stripe_checkout",  "add_stripe_checkout"),
    ("add_email_templates",  "adapt.extend.infrastructure.add_email_templates",  "add_email_templates"),
    ("add_sqladmin",         "adapt.extend.infrastructure.add_sqladmin",         "add_sqladmin"),
    # realtime
    ("add_sse",              "adapt.extend.realtime.add_sse",                    "add_sse"),
    ("add_webhook_receiver", "adapt.extend.realtime.add_webhook_receiver",       "add_webhook_receiver"),
    ("add_webhook_sender",   "adapt.extend.realtime.add_webhook_sender",         "add_webhook_sender"),
    ("add_websocket_chat",   "adapt.extend.realtime.add_websocket_chat",         "add_websocket_chat"),
    # testing_tools
    ("add_contract_tests",  "adapt.extend.testing_tools.add_contract_tests","add_contract_tests"),
    ("add_factory",         "adapt.extend.testing_tools.add_factory",      "add_factory"),
    ("add_load_profile",    "adapt.extend.testing_tools.add_load_profile", "add_load_profile"),
]


# ---------------------------------------------------------------------------
# Boot runner
# ---------------------------------------------------------------------------

def _run_tool_boot_test(
    tool_name: str,
    module_path: str,
    fn_name: str,
) -> tuple[bool, str]:
    """Generate base project, apply tool, attempt boot.

    Args:
        tool_name: Human-readable tool name for error messages.
        module_path: Dotted import path for the tool module.
        fn_name: Name of the tool function to call.

    Returns:
        Tuple of (passed: bool, error_message: str).
        ``error_message`` is empty when ``passed`` is True.
    """
    try:
        mod = importlib.import_module(module_path)
        fn = getattr(mod, fn_name)
    except Exception as exc:
        return False, f"Import failed: {exc}"

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = create_fixture_project(
                name=f"boot_{tool_name}",
                tmp_dir=Path(tmp_dir),
            )
            result = fn(ToolInput(project_dir=str(project_dir)))
            if result.status == "error":
                return False, f"Tool error: {result.error}"

            r = subprocess.run(
                [sys.executable, "-c", "from app.main import app; print('BOOT OK')"],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if "BOOT OK" in r.stdout:
                return True, ""

            # Extract first meaningful error line from stderr
            for line in r.stderr.splitlines():
                stripped = line.strip()
                if stripped and any(
                    kw in stripped for kw in ("Error", "error", "Exception", "Traceback")
                ):
                    # Skip noise lines from pydantic/otel
                    if any(skip in stripped for skip in ("pydantic", "opentelemetry", "logfire", "UserWarning")):
                        continue
                    return False, stripped
            return False, f"returncode={r.returncode}, no error line found"

    except subprocess.TimeoutExpired:
        return False, "Boot subprocess timed out (>30s)"
    except Exception as exc:
        return False, f"Unexpected exception: {exc}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all boot tests and print a summary.

    Returns:
        0 if all tools pass, 1 if any fail.
    """
    total = len(EXTEND_TOOLS)
    passed = 0
    failed: list[tuple[str, str]] = []

    print(f"Running boot tests for {total} adapt tools ...\n")

    for tool_name, module_path, fn_name in EXTEND_TOOLS:
        ok, error_msg = _run_tool_boot_test(tool_name, module_path, fn_name)
        if ok:
            passed += 1
            print(f"  PASS  {tool_name}")
        else:
            failed.append((tool_name, error_msg))
            print(f"  FAIL  {tool_name} — {error_msg}")

    print(f"\n{'='*60}")
    print(f"Boot test result: {passed}/{total} tools boot cleanly")
    if failed:
        print(f"\nFailed tools ({len(failed)}):")
        for name, msg in failed:
            print(f"  {name}: {msg}")
        return 1
    print("All tools boot cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
