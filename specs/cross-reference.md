# HuGR Arsenal — Cross-Reference Index

**Generated**: 2026-08-11T16:51:11.329035+00:00
**Version**: 1.0.0

## Summary

| Metric | Count |
|--------|------:|
| Total entries | 288 |
| Specs (TOOL-NNN-*.md) | 124 |
| MCP tools | 125 |
| Registered primitives | 124 |
| Generators | 65 |
| **Full linkage** (spec+tool+primitive) | 23 |
| Partial linkage (spec+tool) | 101 |
| Spec only (no tool found) | 0 |
| Tool only (no spec) | 1 |
| Primitive only (no tool/spec) | 102 |
| Generator only (no tool/spec) | 61 |

## Full Index

| Spec | Tool | Primitive | Generator | Linkage | Confidence |
|------|------|-----------|-----------|---------|------------|
| TOOL-001 | `fastapi_data_add_soft_delete` | — | — | ⚠️ Partial | high |
| TOOL-002 | `fastapi_data_add_cursor_pagination` | — | — | ⚠️ Partial | high |
| TOOL-003 | `fastapi_data_add_file_upload` | — | — | ⚠️ Partial | high |
| TOOL-004 | `fastapi_data_add_search` | — | — | ⚠️ Partial | high |
| TOOL-005 | `fastapi_data_add_audit_log` | `compliance/AuditEvent` | — | ✅ Full | high |
| TOOL-006 | `fastapi_data_add_data_export` | — | — | ⚠️ Partial | high |
| TOOL-007 | `fastapi_data_add_bulk_operations` | — | — | ⚠️ Partial | high |
| TOOL-008 | `fastapi_auth_add_multi_tenancy` | — | — | ⚠️ Partial | high |
| TOOL-009 | `fastapi_auth_add_feature_flags` | `flags/FeatureToggle` | — | ✅ Full | high |
| TOOL-010 | `fastapi_auth_add_api_key_auth` | — | — | ⚠️ Partial | high |
| TOOL-011 | `fastapi_auth_add_oauth2_provider` | `auth/TokenIntrospector` | — | ✅ Full | high |
| TOOL-012 | `fastapi_auth_add_rbac` | `auth/RequestGuard` | — | ✅ Full | high |
| TOOL-013 | `fastapi_auth_add_mfa` | `auth/TotpVerifier` | — | ✅ Full | high |
| TOOL-014 | `fastapi_realtime_add_sse` | — | — | ⚠️ Partial | high |
| TOOL-015 | `fastapi_realtime_add_webhook_sender` | `security/SignatureVerifier` | — | ✅ Full | high |
| TOOL-016 | `fastapi_realtime_add_webhook_receiver` | `security/SignatureVerifier` | — | ✅ Full | high |
| TOOL-017 | `fastapi_api_add_api_versioning` | — | — | ⚠️ Partial | high |
| TOOL-018 | `fastapi_api_add_graphql` | — | — | ⚠️ Partial | high |
| TOOL-019 | `fastapi_api_add_batch_endpoint` | — | generators/tools/add_endpoint.py | ⚠️ Partial | high |
| TOOL-020 | `fastapi_api_add_long_running_task` | `jobs/WorkflowRun` | — | ✅ Full | high |
| TOOL-021 | `fastapi_resiliency_add_cache_layer` | `cache/KeyValueBucket` | — | ✅ Full | high |
| TOOL-022 | `fastapi_resiliency_add_circuit_breaker` | `resiliency/CircuitBreaker` | — | ✅ Full | high |
| TOOL-023 | `fastapi_data_add_outbox_pattern` | `events/TransactionalOutbox` | — | ✅ Full | high |
| TOOL-024 | `fastapi_data_add_saga` | `events/SagaOrchestrator` | — | ✅ Full | high |
| TOOL-025 | `fastapi_testing_add_factory` | — | — | ⚠️ Partial | high |
| TOOL-026 | `fastapi_testing_add_contract_tests` | — | — | ⚠️ Partial | high |
| TOOL-027 | `fastapi_testing_add_load_profile` | — | — | ⚠️ Partial | high |
| TOOL-028 | `fastapi_resiliency_analyze_detect_n_plus_one` | — | — | ⚠️ Partial | high |
| TOOL-029 | `fastapi_resiliency_analyze_security_scan` | — | — | ⚠️ Partial | high |
| TOOL-030 | `fastapi_compliance_analyze_dependency_audit` | — | — | ⚠️ Partial | high |
| TOOL-031 | `fastapi_resiliency_analyze_schema_coverage` | — | — | ⚠️ Partial | high |
| TOOL-032 | `fastapi_testing_verify_coverage_gaps` | — | — | ⚠️ Partial | high |
| TOOL-033 | `fastapi_resiliency_analyze_api_spec_compliance` | — | — | ⚠️ Partial | high |
| TOOL-034 | `fastapi_resiliency_analyze_performance_baseline` | — | — | ⚠️ Partial | high |
| TOOL-035 | `fastapi_resiliency_analyze_blast_radius` | — | — | ⚠️ Partial | high |
| TOOL-036 | `fastapi_resiliency_analyze_migration_diff` | — | — | ⚠️ Partial | high |
| TOOL-037 | `fastapi_resiliency_analyze_dead_code_finder` | — | — | ⚠️ Partial | high |
| TOOL-038 | `fastapi_observability_analyze_api_changelog` | — | — | ⚠️ Partial | high |
| TOOL-039 | `fastapi_resiliency_analyze_dependency_graph` | — | — | ⚠️ Partial | high |
| TOOL-040 | `fastapi_resiliency_analyze_connection_pool_monitor` | — | — | ⚠️ Partial | high |
| TOOL-041 | `fastapi_resiliency_analyze_error_rate_analyzer` | — | — | ⚠️ Partial | high |
| TOOL-042 | `fastapi_resiliency_analyze_sla_reporter` | — | — | ⚠️ Partial | high |
| TOOL-043 | `fastapi_resiliency_add_migration_data` | — | — | ⚠️ Partial | high |
| TOOL-044 | `fastapi_resiliency_analyze_refactor_model` | — | generators/tools/add_model.py | ⚠️ Partial | high |
| TOOL-045 | `fastapi_resiliency_analyze_extract_service` | — | — | ⚠️ Partial | high |
| TOOL-046 | `fastapi_data_add_event_driven` | — | — | ⚠️ Partial | high |
| TOOL-047 | `fastapi_resiliency_generate_sdk` | — | — | ⚠️ Partial | high |
| TOOL-048 | `fastapi_resiliency_generate_admin_panel` | — | — | ⚠️ Partial | high |
| TOOL-049 | `fastapi_resiliency_generate_docs` | — | — | ⚠️ Partial | high |
| TOOL-050 | `fastapi_resiliency_add_i18n` | — | — | ⚠️ Partial | high |
| TOOL-051 | `fastapi_resiliency_analyze_doctor` | — | — | ⚠️ Partial | high |
| TOOL-052 | `fastapi_realtime_add_websocket_chat` | — | generators/tools/add_websocket.py | ⚠️ Partial | high |
| TOOL-053 | `fastapi_resiliency_add_arq_worker` | — | — | ⚠️ Partial | high |
| TOOL-054 | `fastapi_resiliency_add_stripe_checkout` | — | — | ⚠️ Partial | high |
| TOOL-055 | `fastapi_resiliency_add_email_templates` | — | — | ⚠️ Partial | high |
| TOOL-056 | `fastapi_resiliency_add_sqladmin` | — | — | ⚠️ Partial | high |
| TOOL-057 | `fastapi_resiliency_add_rate_limiting` | `resiliency/RateLimiter` | — | ✅ Full | high |
| TOOL-058 | `fastapi_resiliency_add_scheduled_tasks` | — | — | ⚠️ Partial | high |
| TOOL-059 | `fastapi_resiliency_add_celery_beat` | — | — | ⚠️ Partial | high |
| TOOL-060 | `fastapi_resiliency_add_s3_storage` | — | — | ⚠️ Partial | high |
| TOOL-061 | `fastapi_resiliency_add_health_deep` | — | — | ⚠️ Partial | high |
| TOOL-062 | `fastapi_realtime_add_websocket_presence` | — | generators/tools/add_websocket.py | ⚠️ Partial | high |
| TOOL-063 | `fastapi_resiliency_add_notifications` | — | — | ⚠️ Partial | high |
| TOOL-064 | `fastapi_auth_add_feature_toggles_api` | `flags/FeatureToggle` | — | ✅ Full | high |
| TOOL-065 | `fastapi_resiliency_add_stripe_subscription` | `billing/Billing` | — | ✅ Full | high |
| TOOL-066 | `fastapi_resiliency_add_stripe_refund_flow` | — | — | ⚠️ Partial | high |
| TOOL-067 | `fastapi_resiliency_add_temporal_workflow` | — | — | ⚠️ Partial | high |
| TOOL-068 | `fastapi_resiliency_add_ml_model_server` | — | generators/tools/add_model.py | ⚠️ Partial | high |
| TOOL-069 | `fastapi_resiliency_add_ml_gpu_inference` | — | — | ⚠️ Partial | high |
| TOOL-070 | `fastapi_resiliency_add_ml_model_registry` | — | generators/tools/add_model.py | ⚠️ Partial | high |
| TOOL-071 | `fastapi_auth_add_cedar_policies` | — | — | ⚠️ Partial | high |
| TOOL-072 | `fastapi_auth_add_opa_integration` | — | generators/tools/add_integration.py | ⚠️ Partial | high |
| TOOL-073 | `fastapi_api_add_graphql_subscriptions` | `events/PubSub` | — | ✅ Full | high |
| TOOL-074 | `fastapi_auth_add_social_login` | — | — | ⚠️ Partial | high |
| TOOL-075 | `fastapi_auth_add_passkey_auth` | — | — | ⚠️ Partial | high |
| TOOL-076 | `fastapi_auth_add_sms_otp` | — | — | ⚠️ Partial | high |
| TOOL-077 | `fastapi_data_add_data_import` | — | — | ⚠️ Partial | high |
| TOOL-078 | `fastapi_data_add_data_versioning` | — | — | ⚠️ Partial | high |
| TOOL-079 | `fastapi_data_add_event_sourcing` | `events/EventSourcedStore` | — | ✅ Full | high |
| TOOL-080 | `fastapi_api_add_cqrs` | — | — | ⚠️ Partial | high |
| TOOL-081 | `fastapi_resiliency_add_transactional_email` | — | — | ⚠️ Partial | high |
| TOOL-082 | `fastapi_resiliency_add_push_notifications_native` | — | — | ⚠️ Partial | high |
| TOOL-083 | `fastapi_resiliency_add_pdf_reports` | — | — | ⚠️ Partial | high |
| TOOL-084 | `fastapi_resiliency_add_excel_export` | — | — | ⚠️ Partial | high |
| TOOL-085 | `fastapi_observability_add_opentelemetry` | — | — | ⚠️ Partial | high |
| TOOL-086 | `fastapi_observability_add_prometheus_metrics` | — | — | ⚠️ Partial | high |
| TOOL-087 | `fastapi_observability_add_structured_logging` | — | — | ⚠️ Partial | high |
| TOOL-088 | `fastapi_resiliency_add_cors_config` | — | — | ⚠️ Partial | high |
| TOOL-089 | `fastapi_resiliency_add_csrf_protection` | — | — | ⚠️ Partial | high |
| TOOL-090 | `fastapi_resiliency_add_input_sanitization` | — | — | ⚠️ Partial | high |
| TOOL-091 | `fastapi_testing_add_database_migrations_ci` | — | — | ⚠️ Partial | high |
| TOOL-092 | `fastapi_deployment_add_docker_production` | — | — | ⚠️ Partial | high |
| TOOL-093 | `fastapi_resiliency_add_kubernetes_manifests` | — | — | ⚠️ Partial | high |
| TOOL-094 | `fastapi_testing_add_e2e_test_suite` | — | — | ⚠️ Partial | high |
| TOOL-095 | `fastapi_resiliency_add_load_shedding` | `resiliency/LoadShedder` | — | ✅ Full | high |
| TOOL-096 | `fastapi_resiliency_add_adaptive_timeouts` | `resiliency/TimeoutBudget` | — | ✅ Full | high |
| TOOL-097 | `fastapi_resiliency_add_bulkhead_isolation` | `resiliency/Bulkhead` | — | ✅ Full | high |
| TOOL-098 | `fastapi_resiliency_add_retry_budget` | `resiliency/RetryPolicy` | — | ✅ Full | high |
| TOOL-099 | `fastapi_testing_add_chaos_testing` | — | — | ⚠️ Partial | high |
| TOOL-100 | `fastapi_resiliency_add_graceful_shutdown` | `resiliency/GracefulShutdown` | — | ✅ Full | high |
| TOOL-101 | `fastapi_resiliency_add_api_replay_debugger` | — | — | ⚠️ Partial | high |
| TOOL-102 | `fastapi_resiliency_add_anomaly_detector` | — | — | ⚠️ Partial | high |
| TOOL-103 | `fastapi_resiliency_add_request_fingerprint` | — | — | ⚠️ Partial | high |
| TOOL-104 | `fastapi_testing_add_schema_evolution_guard` | — | — | ⚠️ Partial | high |
| TOOL-105 | `fastapi_testing_add_data_seeder` | — | — | ⚠️ Partial | high |
| TOOL-106 | `fastapi_api_add_api_deprecation` | — | — | ⚠️ Partial | high |
| TOOL-107 | `fastapi_auth_add_request_signing` | — | — | ⚠️ Partial | high |
| TOOL-108 | `fastapi_resiliency_add_dlp_shield` | — | — | ⚠️ Partial | high |
| TOOL-109 | `fastapi_resiliency_add_canary_tokens` | — | — | ⚠️ Partial | high |
| TOOL-110 | `fastapi_testing_add_sbom_guardian` | — | — | ⚠️ Partial | high |
| TOOL-111 | `fastapi_resiliency_add_runtime_sentinel` | — | — | ⚠️ Partial | high |
| TOOL-112 | `fastapi_auth_add_bola_guard` | — | — | ⚠️ Partial | high |
| TOOL-113 | `fastapi_resiliency_add_compliance_engine` | — | — | ⚠️ Partial | high |
| TOOL-114 | `fastapi_resiliency_add_secret_rotation` | — | — | ⚠️ Partial | high |
| TOOL-115 | `fastapi_auth_add_dpop_tokens` | — | — | ⚠️ Partial | high |
| TOOL-116 | `fastapi_resiliency_add_adaptive_throttle` | — | — | ⚠️ Partial | high |
| TOOL-117 | `fastapi_testing_add_schema_enforcer` | — | — | ⚠️ Partial | high |
| TOOL-118 | `fastapi_resiliency_add_response_armor` | — | — | ⚠️ Partial | high |
| TOOL-119 | `fastapi_resiliency_add_api_monetization` | — | — | ⚠️ Partial | high |
| TOOL-120 | `fastapi_resiliency_add_cost_tracker` | `resiliency/CostTracker` | — | ✅ Full | high |
| TOOL-121 | `fastapi_resiliency_add_tenant_onboarding` | — | — | ⚠️ Partial | high |
| TOOL-122 | `fastapi_deployment_add_request_tracing_ui` | — | — | ⚠️ Partial | high |
| TOOL-123 | `fastapi_resiliency_add_dependency_health_map` | — | — | ⚠️ Partial | high |
| TOOL-124 | `fastapi_testing_add_api_fuzzer` | — | — | ⚠️ Partial | high |
| — | `fastapi_data_add_read_model_projection` | `data/MaterializedView` | generators/tools/add_model.py | 🔧 Tool | high |
| — | — | `api/BatchCore` | — | ⚙️ Primitive | none |
| — | — | `api/CommandBus` | — | ⚙️ Primitive | none |
| — | — | `api/CommandQuerySeparator` | — | ⚙️ Primitive | none |
| — | — | `api/ContextMap` | — | ⚙️ Primitive | none |
| — | — | `api/DataLoader` | — | ⚙️ Primitive | none |
| — | — | `api/DeprecationEntry` | — | ⚙️ Primitive | none |
| — | — | `api/DeprecationRegistry` | — | ⚙️ Primitive | none |
| — | — | `api/DeprecationReporter` | — | ⚙️ Primitive | none |
| — | — | `api/IdempotencyStore` | — | ⚙️ Primitive | none |
| — | — | `api/InboundVerifier` | — | ⚙️ Primitive | none |
| — | — | `api/MemoryPubSubBackend` | — | ⚙️ Primitive | none |
| — | — | `api/MiddlewarePipeline` | — | ⚙️ Primitive | none |
| — | — | `api/PersistedQueryRegistry` | — | ⚙️ Primitive | none |
| — | — | `api/QueryBus` | — | ⚙️ Primitive | none |
| — | — | `api/RequestContext` | — | ⚙️ Primitive | none |
| — | — | `api/RouterPipeline` | — | ⚙️ Primitive | none |
| — | — | `api/ValueTransform` | — | ⚙️ Primitive | none |
| — | — | `auth/AuthorizationCodeFlow` | — | ⚙️ Primitive | none |
| — | — | `auth/CurrentPrincipal` | — | ⚙️ Primitive | none |
| — | — | `auth/FeatureFlagCache` | — | ⚙️ Primitive | none |
| — | — | `auth/SessionStore` | — | ⚙️ Primitive | none |
| — | — | `auth/WebAuthnAuthenticator` | — | ⚙️ Primitive | none |
| — | — | `cache/DistributedLock` | — | ⚙️ Primitive | none |
| — | — | `cache/SessionCache` | — | ⚙️ Primitive | none |
| — | — | `compliance/BreachNotificationQueue` | — | ⚙️ Primitive | none |
| — | — | `compliance/ConsentLedger` | — | ⚙️ Primitive | none |
| — | — | `compliance/DataSubjectRequest` | — | ⚙️ Primitive | none |
| — | — | `compliance/ProcessingRecord` | — | ⚙️ Primitive | none |
| — | — | `compliance/RetentionPolicy` | — | ⚙️ Primitive | none |
| — | — | `compliance/TamperEvidentAuditLog` | — | ⚙️ Primitive | none |
| — | — | `data/Aggregate` | — | ⚙️ Primitive | none |
| — | — | `data/AntiCorruptionLayer` | — | ⚙️ Primitive | none |
| — | — | `data/BoundedContext` | — | ⚙️ Primitive | none |
| — | — | `data/ChangeDataCapture` | — | ⚙️ Primitive | none |
| — | — | `data/ConfigBinding` | — | ⚙️ Primitive | none |
| — | — | `data/DataMapper` | — | ⚙️ Primitive | none |
| — | — | `data/DiContainer` | — | ⚙️ Primitive | none |
| — | — | `data/IdentityMap` | — | ⚙️ Primitive | none |
| — | — | `data/LegalHold` | — | ⚙️ Primitive | none |
| — | — | `data/LifetimeScope` | — | ⚙️ Primitive | none |
| — | — | `data/OptimisticConcurrency` | — | ⚙️ Primitive | none |
| — | — | `data/PiiClassification` | — | ⚙️ Primitive | none |
| — | — | `data/Repository` | — | ⚙️ Primitive | none |
| — | — | `data/ShardedCounter` | — | ⚙️ Primitive | none |
| — | — | `data/Specification` | — | ⚙️ Primitive | none |
| — | — | `data/TransactionalBatch` | — | ⚙️ Primitive | none |
| — | — | `data/UnitOfWork` | — | ⚙️ Primitive | none |
| — | — | `data/ValueObject` | — | ⚙️ Primitive | none |
| — | — | `events/CausalReorderBuffer` | — | ⚙️ Primitive | none |
| — | — | `events/DeadLetterRoute` | — | ⚙️ Primitive | none |
| — | — | `events/DomainEvent` | — | ⚙️ Primitive | none |
| — | — | `events/EventEnvelope` | — | ⚙️ Primitive | none |
| — | — | `events/EventStream` | — | ⚙️ Primitive | none |
| — | — | `events/IdempotentConsumer` | — | ⚙️ Primitive | none |
| — | — | `events/InboxDeduplicator` | — | ⚙️ Primitive | none |
| — | — | `events/StreamSubject` | — | ⚙️ Primitive | none |
| — | — | `events/TopicBus` | — | ⚙️ Primitive | none |
| — | — | `extras/OutboundBinding` | — | ⚙️ Primitive | none |
| — | — | `extras/RequestShape` | — | ⚙️ Primitive | none |
| — | — | `extras/RpcInterceptor` | — | ⚙️ Primitive | none |
| — | — | `extras/SchemaComparator` | — | ⚙️ Primitive | none |
| — | — | `extras/VirtualActor` | — | ⚙️ Primitive | none |
| — | — | `jobs/ActivityCall` | — | ⚙️ Primitive | none |
| — | — | `jobs/DurableTimer` | — | ⚙️ Primitive | none |
| — | — | `llm/InputGuardrail` | — | ⚙️ Primitive | none |
| — | — | `llm/OutputGuardrail` | — | ⚙️ Primitive | none |
| — | — | `llm/PromptInjectionFilter` | — | ⚙️ Primitive | none |
| — | — | `llm/PromptTemplate` | — | ⚙️ Primitive | none |
| — | — | `obs/AccessLog` | — | ⚙️ Primitive | none |
| — | — | `obs/CardinalityGuard` | — | ⚙️ Primitive | none |
| — | — | `obs/CorrelationContext` | — | ⚙️ Primitive | none |
| — | — | `obs/CorrelationId` | — | ⚙️ Primitive | none |
| — | — | `obs/ErrorSink` | — | ⚙️ Primitive | none |
| — | — | `obs/EventBus` | — | ⚙️ Primitive | none |
| — | — | `obs/HealthProbe` | — | ⚙️ Primitive | none |
| — | — | `obs/HistogramBuckets` | — | ⚙️ Primitive | none |
| — | — | `obs/LifecycleHook` | — | ⚙️ Primitive | none |
| — | — | `obs/LlmTrace` | — | ⚙️ Primitive | none |
| — | — | `obs/MetricMeter` | — | ⚙️ Primitive | none |
| — | — | `obs/ResourceDescriptor` | — | ⚙️ Primitive | none |
| — | — | `obs/SamplingPolicy` | — | ⚙️ Primitive | none |
| — | — | `obs/SemanticAttributes` | — | ⚙️ Primitive | none |
| — | — | `obs/StructuredLogger` | — | ⚙️ Primitive | none |
| — | — | `obs/TelemetryExporter` | — | ⚙️ Primitive | none |
| — | — | `obs/Tracer` | — | ⚙️ Primitive | none |
| — | — | `policy/CorsPolicy` | — | ⚙️ Primitive | none |
| — | — | `policy/DataResidencyPolicy` | — | ⚙️ Primitive | none |
| — | — | `policy/EncryptionPolicy` | — | ⚙️ Primitive | none |
| — | — | `policy/KeyRotationSchedule` | — | ⚙️ Primitive | none |
| — | — | `resiliency/ExcelExporter` | — | ⚙️ Primitive | none |
| — | — | `resiliency/HeterogeneousWorkerPool` | — | ⚙️ Primitive | none |
| — | — | `resiliency/ModelRegistry` | — | ⚙️ Primitive | none |
| — | — | `resiliency/Redactor` | — | ⚙️ Primitive | none |
| — | — | `resiliency/RetryBudget` | — | ⚙️ Primitive | none |
| — | — | `resiliency/TracingBuffer` | — | ⚙️ Primitive | none |
| — | — | `security/ContentSecurityPolicy` | — | ⚙️ Primitive | none |
| — | — | `security/CryptoEnvelope` | — | ⚙️ Primitive | none |
| — | — | `security/CsrfGuard` | — | ⚙️ Primitive | none |
| — | — | `security/InputValidator` | — | ⚙️ Primitive | none |
| — | — | `security/OutputEncoder` | — | ⚙️ Primitive | none |
| — | — | `security/PasswordHasher` | — | ⚙️ Primitive | none |
| — | — | `security/SecretsVault` | — | ⚙️ Primitive | none |
| — | — | — | generators/database/alembic.py | 📦 Gen | none |
| — | — | — | generators/database/alembic_migration.py | 📦 Gen | none |
| — | — | — | generators/observability/alerting.py | 📦 Gen | none |
| — | — | — | generators/observability/alerting__impl1.py | 📦 Gen | none |
| — | — | — | generators/observability/alerting__impl2.py | 📦 Gen | none |
| — | — | — | generators/observability/alerting__impl3.py | 📦 Gen | none |
| — | — | — | generators/observability/alerting__impl4.py | 📦 Gen | none |
| — | — | — | generators/infra/app.py | 📦 Gen | none |
| — | — | — | generators/tools/add_background_job.py | 📦 Gen | none |
| — | — | — | generators/middleware/body_size.py | 📦 Gen | none |
| — | — | — | generators/infra/config.py | 📦 Gen | none |
| — | — | — | generators/testing/conftest.py | 📦 Gen | none |
| — | — | — | generators/middleware/correlation.py | 📦 Gen | none |
| — | — | — | generators/middleware/cors.py | 📦 Gen | none |
| — | — | — | generators/database/crud.py | 📦 Gen | none |
| — | — | — | generators/database/crud_base.py | 📦 Gen | none |
| — | — | — | generators/endpoints/crud_routes.py | 📦 Gen | none |
| — | — | — | generators/auth/deps.py | 📦 Gen | none |
| — | — | — | generators/deployment/docker_compose.py | 📦 Gen | none |
| — | — | — | generators/infra/dockerfile.py | 📦 Gen | none |
| — | — | — | generators/deployment/dockerfile_lint.py | 📦 Gen | none |
| — | — | — | generators/infra/email.py | 📦 Gen | none |
| — | — | — | generators/database/encryption.py | 📦 Gen | none |
| — | — | — | generators/database/engine.py | 📦 Gen | none |
| — | — | — | generators/infra/env_example.py | 📦 Gen | none |
| — | — | — | generators/endpoints/errors.py | 📦 Gen | none |
| — | — | — | generators/deployment/github_actions.py | 📦 Gen | none |
| — | — | — | generators/infra/gitignore.py | 📦 Gen | none |
| — | — | — | generators/auth/hasher.py | 📦 Gen | none |
| — | — | — | generators/endpoints/health.py | 📦 Gen | none |
| — | — | — | generators/middleware/idempotency.py | 📦 Gen | none |
| — | — | — | generators/infra/initial_data.py | 📦 Gen | none |
| — | — | — | generators/schemas/input_schema.py | 📦 Gen | none |
| — | — | — | generators/auth/jwt.py | 📦 Gen | none |
| — | — | — | generators/deployment/k6_loadtest.py | 📦 Gen | none |
| — | — | — | generators/deployment/k8s.py | 📦 Gen | none |
| — | — | — | generators/schemas/list_response.py | 📦 Gen | none |
| — | — | — | generators/infra/logging.py | 📦 Gen | none |
| — | — | — | generators/tools/add_middleware.py | 📦 Gen | none |
| — | — | — | generators/orchestrator.py | 📦 Gen | none |
| — | — | — | generators/orchestrator__impl1.py | 📦 Gen | none |
| — | — | — | generators/orchestrator__impl2.py | 📦 Gen | none |
| — | — | — | generators/orchestrator__impl3.py | 📦 Gen | none |
| — | — | — | generators/orchestrator__impl4.py | 📦 Gen | none |
| — | — | — | generators/observability/otel.py | 📦 Gen | none |
| — | — | — | generators/schemas/output_schema.py | 📦 Gen | none |
| — | — | — | generators/infra/precommit.py | 📦 Gen | none |
| — | — | — | generators/infra/prestart.py | 📦 Gen | none |
| — | — | — | generators/observability/prometheus.py | 📦 Gen | none |
| — | — | — | generators/auth/rate_limit.py | 📦 Gen | none |
| — | — | — | generators/infra/readme.py | 📦 Gen | none |
| — | — | — | generators/middleware/request_logging.py | 📦 Gen | none |
| — | — | — | generators/database/rls.py | 📦 Gen | none |
| — | — | — | generators/auth/routes.py | 📦 Gen | none |
| — | — | — | generators/scaffold_venous.py | 📦 Gen | none |
| — | — | — | generators/auth/schemas.py | 📦 Gen | none |
| — | — | — | generators/middleware/security_headers.py | 📦 Gen | none |
| — | — | — | generators/database/session.py | 📦 Gen | none |
| — | — | — | generators/middleware/stack.py | 📦 Gen | none |
| — | — | — | generators/testing/test_suite.py | 📦 Gen | none |
| — | — | — | generators/endpoints/user_routes.py | 📦 Gen | none |

## Confidence Legend

- **high** — direct match (name/FQN/exact import)
- **medium** — heuristic/partial name overlap
- **low** — uncertain mapping
- **none** — no match found

## Linkage Types

- ✅ **Full** — spec + tool + primitive mapped
- ⚠️ **Partial** — spec + tool (no primitive)
- 📄 **Spec only** — spec exists, no matching tool found
- 🔧 **Tool only** — tool exists, no matching spec
- ⚙️ **Primitive only** — primitive not referenced by any tool
- 📦 **Generator only** — generator not mapped to any tool
