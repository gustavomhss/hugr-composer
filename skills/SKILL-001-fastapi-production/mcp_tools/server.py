"""FastMCP application instance with SKILL-001 instructions."""
from __future__ import annotations

from fastmcp import FastMCP

from mcp_tools.auth_gate import HugrTokenVerifier, gate_enabled

# Subscription gate: when HUGR_GATE is enabled the server requires a valid HuGR
# license (bearer token) to expose any tool. Off by default → local stdio / OSS
# / test flows are unchanged. See mcp_tools/auth_gate.py.
_auth = HugrTokenVerifier() if gate_enabled() else None

mcp = FastMCP(
    "hugr-skill-fastapi",
    auth=_auth,
    instructions=(
        "FastAPI Production skill — generates SOTA production projects AND adapts existing ones.\n\n"
        "Convention over Configuration: generators deliver calibrated defaults "
        "(argon2id, async pools, security headers, multi-stage Docker), "
        "you customize business logic only.\n\n"
        "PRIMARY TOOL: fastapi_generate_project — one call, full project.\n"
        "GRANULAR: Use individual generate_* tools for specific components.\n"
        "VERIFY: Use fastapi_analyze to audit any FastAPI project (35 checks).\n\n"
        "ADAPT TOOLS (56 tools for existing projects):\n"
        "  EXTEND: fastapi_add_soft_delete, fastapi_add_cursor_pagination, "
        "fastapi_add_file_upload, fastapi_add_search, fastapi_add_audit_log, "
        "fastapi_add_data_export, fastapi_add_bulk_operations, "
        "fastapi_add_multi_tenancy, fastapi_add_feature_flags, "
        "fastapi_add_api_key_auth, fastapi_add_oauth2_provider, fastapi_add_rbac, "
        "fastapi_add_mfa, fastapi_add_sse, fastapi_add_webhook_sender, "
        "fastapi_add_webhook_receiver, fastapi_add_api_versioning, "
        "fastapi_add_graphql, fastapi_add_batch_endpoint, "
        "fastapi_add_long_running_task, fastapi_add_cache_layer, "
        "fastapi_add_circuit_breaker, fastapi_add_outbox_pattern, fastapi_add_saga, "
        "fastapi_add_factory, fastapi_add_contract_tests, fastapi_add_load_profile, "
        "fastapi_add_websocket_chat, fastapi_add_arq_worker, "
        "fastapi_add_stripe_checkout, fastapi_add_email_templates, "
        "fastapi_add_sqladmin.\n"
        "  VERIFY: fastapi_detect_n_plus_one, fastapi_security_scan, "
        "fastapi_dependency_audit, fastapi_schema_coverage, "
        "fastapi_test_coverage_gaps, fastapi_api_spec_compliance, "
        "fastapi_performance_baseline.\n"
        "  OPERATE: fastapi_blast_radius, fastapi_migration_diff, "
        "fastapi_dead_code_finder, fastapi_api_changelog, "
        "fastapi_dependency_graph, fastapi_connection_pool_monitor, "
        "fastapi_error_rate_analyzer, fastapi_sla_reporter.\n"
        "  EVOLVE: fastapi_add_migration_data, fastapi_refactor_model, "
        "fastapi_extract_service, fastapi_add_event_driven, "
        "fastapi_generate_sdk, fastapi_generate_admin_panel, "
        "fastapi_generate_docs, fastapi_add_i18n.\n"
        "  PROACTIVE: fastapi_doctor — runs all 7 verify tools, classifies "
        "findings by severity, and generates an ordered fix plan."
    ),
)
