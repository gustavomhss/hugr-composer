# Promotion Ledger

**Generated:** 2026-04-21T14:03:22+00:00 · **Classifier:** v1.0 · **Total:** 229 (182 staged + 47 quarantined)

> **How to use this ledger.** Each entry proposes a path to
> functionality. Tick the checkbox to mark it approved; un-ticked =
> not yet approved. PROMOTE_* entries have a copy-paste `Run:`
> command. Default stance is **make it work, not delete** —
> REDUNDANT entries stay in place unless you explicitly opt-in to
> remove them. §A12 discipline is intact.

## Summary

| Verdict | Count | Gustavo's next step |
|---|---:|---|
| promote_as_adapter | 2 | Review + approve individually; executor ships each. |
| promote_as_primitive | 0 | Ratify §B1.7 (for lite) → review + approve. |
| fill_and_promote | 0 | Fill REPLACE_ME + invariant tests; reclassify. |
| extract_motor_pair | 118 | Refactoring sprint — ~2-4h per item. |
| needs_review | 3 | Adjudicate manually; reclassify. |
| redundant | 2 | Leave in place, or opt-in delete for cleanup. |
| needs_caller | 104 | No action. Revisit when a caller appears. |

## Promote as FastAPI adapter — 2 primitive(s)

Each item's motor is already registered under `core/venous/<ns>/<Motor>/` but the matching `_adapters/fastapi/<Motor>Adapter.py` is missing. The staged code can become that adapter. `promotion_target` gives the exact destination path. Approve to run:

```
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --from-ledger <NAME>
```

### 1. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette). Motor `Bulkhead` registered but `BulkheadAdapter.py` is MISSING. Promote this staged item as `core/venous/_adapters/fastapi/BulkheadAdapter.py` — completes the motor+adapter pair.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Target:** `core/venous/_adapters/fastapi/BulkheadAdapter.py`
  - **Run:** `python -m engine.promotion.promote --from-ledger BulkheadMiddleware`

### 2. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette). Motor `Bulkhead` registered but `BulkheadAdapter.py` is MISSING. Promote this staged item as `core/venous/_adapters/fastapi/BulkheadAdapter.py` — completes the motor+adapter pair.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Target:** `core/venous/_adapters/fastapi/BulkheadAdapter.py`
  - **Run:** `python -m engine.promotion.promote --from-ledger BulkheadMiddleware`

---

## Extract motor+adapter pair (re-factor required) — 118 primitive(s)

Framework-coupled with no motor registered. Cannot be promoted as-is (§B1.0.1 bars framework imports in registered primitives). Required work per item: split into (framework-free motor primitive under `core/venous/<ns>/<Motor>/`) + (FastAPI adapter under `_adapters/fastapi/<Motor>Adapter.py`). ~2-4h per item depending on complexity. No one-shot command — this is a refactoring sprint, not an executor call.

### 1. [ ] `Event` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=4908
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py` · `benchmark_ref`: `benchmarks/specs/mid/03_event_sourced_orders.md`

### 2. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Deprecation`.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8384
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_deprecation.py`

### 3. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Deprecation`.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=8384
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_deprecation.py`

### 4. [ ] `GitHubVerifier` (api)

  - **Rationale:** Framework-coupled (fastapi) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=5 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=28144
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`

### 5. [ ] `InternalVerifier` (api)

  - **Rationale:** Framework-coupled (fastapi) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=5 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=175744
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`

### 6. [ ] `ReadReplicaSession` (api)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=7264
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_cqrs.py`

### 7. [ ] `ReadReplicaSession` (api)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=7264
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_cqrs.py`

### 8. [ ] `StripeVerifier` (api)

  - **Rationale:** Framework-coupled (fastapi) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=5 · loc=41 · tla=n · concurrency=n · mutable=n · tests=y · score=35140
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`

### 9. [ ] `UserPresence` (api)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=4044
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_presence.py`

### 10. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `VersionResolver`.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=75000
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`

### 11. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `VersionResolver`.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · score=75000
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`

### 12. [ ] `WebhookDelivery` (api)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=7516
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`

### 13. [ ] `WebhookEndpoint` (api)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Webhook`.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=7948
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`

### 14. [ ] `APIKey` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9420
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`

### 15. [ ] `CedarAuthzMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CedarAuthz`.
  - **State:** REPLACE_ME=7 · loc=72 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=167700
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_cedar_policies.py`

### 16. [ ] `CedarEngine` (auth)

  - **Rationale:** Framework-coupled (starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=71 · tla=n · concurrency=n · mutable=y · tests=y · score=176520
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_cedar_policies.py`

### 17. [ ] `FeatureFlag` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=11324
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`

### 18. [ ] `FeatureFlagAudit` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=5472
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`

### 19. [ ] `MFADevice` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6996
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_mfa.py`

### 20. [ ] `MFARecoveryCode` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3728
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_mfa.py`

### 21. [ ] `OAuthAccount` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=8632
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`

### 22. [ ] `OPAMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `OPA`.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=12792
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_opa_integration.py`

### 23. [ ] `OPAMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `OPA`.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=12792
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_opa_integration.py`

### 24. [ ] `OtpCode` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=4440
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_sms_otp.py`

### 25. [ ] `OwnershipVerifier` (auth)

  - **Rationale:** Framework-coupled (fastapi, sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200016
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`

### 26. [ ] `Passkey` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6456
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_passkey_auth.py`

### 27. [ ] `Permission` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=3548
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`

### 28. [ ] `RequestSigningMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `RequestSigning`.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=101920
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_request_signing.py`

### 29. [ ] `RolePermission` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=3300
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`

### 30. [ ] `SocialAccount` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=6648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`

### 31. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8856
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`

### 32. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=8856
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`

### 33. [ ] `TenantMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, sqlalchemy, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Tenant`.
  - **State:** REPLACE_ME=7 · loc=67 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=258336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_multi_tenancy.py`

### 34. [ ] `TenantScopedMixin` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2252
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_multi_tenancy.py`

### 35. [ ] `AuditLog` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=11676
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`

### 36. [ ] `ContentVersion` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=7204
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`

### 37. [ ] `CursorPaginator` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=880488
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_cursor_pagination.py`

### 38. [ ] `CursorPaginator` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · score=880488
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_cursor_pagination.py`

### 39. [ ] `EventStore` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=198520
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`

### 40. [ ] `EventStore` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · score=198520
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`

### 41. [ ] `ImportJob` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6924
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`

### 42. [ ] `ImportProcessor` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200580
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`

### 43. [ ] `ImportProcessor` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · score=200580
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`

### 44. [ ] `Projector` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=112600
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`

### 45. [ ] `SoftDeleteMixin` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=12612
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_soft_delete.py`

### 46. [ ] `VersioningService` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Versioning`.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=2873280
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`

### 47. [ ] `VersioningService` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Versioning`.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · score=2873280
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`

### 48. [ ] `DataSeeder` (extras)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=110064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`

### 49. [ ] `DataSeeder` (extras)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · score=110064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`

### 50. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `SchemaEnforcer`.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=27520
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_enforcer.py`

### 51. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `SchemaEnforcer`.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=27520
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_enforcer.py`

### 52. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `AdaptiveThrottle`.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=21408
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_throttle.py`

### 53. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `AdaptiveThrottle`.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21408
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_throttle.py`

### 54. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `AdminAuth`.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=181296
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`

### 55. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `AdminAuth`.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · score=181296
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`

### 56. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Anomaly`.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=29760
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`

### 57. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Anomaly`.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · score=29760
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`

### 58. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CORSConfig`.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10128
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cors_config.py`

### 59. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CORSConfig`.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=10128
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cors_config.py`

### 60. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CSRF`.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=135072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`

### 61. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CSRF`.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · score=135072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`

### 62. [ ] `CSRFProtection` (resiliency)

  - **Rationale:** Framework-coupled (fastapi) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · score=269920
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`

### 63. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Chaos`.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10992
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`

### 64. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Chaos`.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=10992
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`

### 65. [ ] `ComplianceEvent` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=5072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`

### 66. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Cost`.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=41952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`

### 67. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Cost`.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=41952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`

### 68. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `DLP`.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=64160
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`

### 69. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `DLP`.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · score=64160
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`

### 70. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=23772
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`

### 71. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=23772
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`

### 72. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=809472
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`

### 73. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · score=809472
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`

### 74. [ ] `DeviceToken` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=2460
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`

### 75. [ ] `EmailEvent` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=14 · tla=n · concurrency=n · mutable=n · tests=y · score=2068
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`

### 76. [ ] `ErrorInjector` (resiliency)

  - **Rationale:** Framework-coupled (fastapi) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=6832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`

### 77. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Fingerprint`.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=513504
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`

### 78. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Fingerprint`.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=513504
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`

### 79. [ ] `Job` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9404
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`

### 80. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `LeakDetector`.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=91200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`

### 81. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `LeakDetector`.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=91200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`

### 82. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `LoadShedding`.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=11544
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`

### 83. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `LoadShedding`.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=11544
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`

### 84. [ ] `MLModel` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=7364
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`

### 85. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Metering`.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45384
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`

### 86. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Metering`.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=45384
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`

### 87. [ ] `Notification` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=4868
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`

### 88. [ ] `NotificationService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Notification`.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45648
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`

### 89. [ ] `NotificationService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Notification`.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=45648
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`

### 90. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `OTEL`.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=31632
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_opentelemetry.py`

### 91. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `OTEL`.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · score=31632
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_opentelemetry.py`

### 92. [ ] `OutboxDlq` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=3920
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`

### 93. [ ] `OutboxEvent` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9324
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`

### 94. [ ] `OutboxService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Outbox`.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=30672
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`

### 95. [ ] `OutboxService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Outbox`.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=30672
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`

### 96. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Prometheus`.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8704
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`

### 97. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Prometheus`.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=8704
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`

### 98. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Recorder`.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=186420
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`

### 99. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Recorder`.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · score=186420
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`

### 100. [ ] `Refund` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=7144
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`

### 101. [ ] `RegistryService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Registry`.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=119280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`

### 102. [ ] `RegistryService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Registry`.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · score=119280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`

### 103. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `ResponseArmor`.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=175120
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_response_armor.py`

### 104. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `ResponseArmor`.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · score=175120
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_response_armor.py`

### 105. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=706944
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`

### 106. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · score=706944
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`

### 107. [ ] `SagaInstance` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=7696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`

### 108. [ ] `SagaStepExecution` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=7104
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`

### 109. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Sanitize`.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=88956
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`

### 110. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Sanitize`.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · score=88956
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`

### 111. [ ] `ShutdownHealthGate` (resiliency)

  - **Rationale:** Framework-coupled (fastapi) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=7616
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`

### 112. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Shutdown`.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10792
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`

### 113. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Shutdown`.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=10792
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`

### 114. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Tracing`.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=29040
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`

### 115. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Tracing`.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=29040
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`

### 116. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `UploadSize`.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=51840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`

### 117. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `UploadSize`.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=51840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`

### 118. [ ] `UsageRecord` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=4596
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`

---

## Needs human review (ambiguous state) — 3 primitive(s)

Classifier heuristics disagreed or quarantine reason unclear. Each entry lists what the reviewer must adjudicate. Not executable until manually reclassified.

### 1. [ ] `PubSubManager` (api)

  - **Rationale:** Quarantined (extraction gate rejected it for an unrecorded reason) but no framework coupling detected. Needs human inspection: either waive the rejection reason, re-extract, or mark as keep-with-reason.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined with non-framework reason. Human inspection needed before any promotion path can be chosen.
  - Blockers:
    - Resolve 7 REPLACE_ME marker(s) across the primitive tree (invariant text, stub tests).
    - Implement the three invariant tests (confirms / prevents / under_failure) with real assertions.

### 2. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** Quarantined (extraction gate rejected it for an unrecorded reason) but no framework coupling detected. Needs human inspection: either waive the rejection reason, re-extract, or mark as keep-with-reason.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined with non-framework reason. Human inspection needed before any promotion path can be chosen.
  - Blockers:
    - Resolve 7 REPLACE_ME marker(s) across the primitive tree (invariant text, stub tests).
    - Implement the three invariant tests (confirms / prevents / under_failure) with real assertions.

### 3. [ ] `StripeBilling` (resiliency)

  - **Rationale:** Quarantined (extraction gate rejected it for an unrecorded reason) but no framework coupling detected. Needs human inspection: either waive the rejection reason, re-extract, or mark as keep-with-reason.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** Physically quarantined with non-framework reason. Human inspection needed before any promotion path can be chosen.
  - Blockers:
    - Resolve 7 REPLACE_ME marker(s) across the primitive tree (invariant text, stub tests).
    - Implement the three invariant tests (confirms / prevents / under_failure) with real assertions.

---

## Redundant (motor+adapter already ship) — 2 primitive(s)

Motor and adapter (or the registered primitive itself) already ship. Staged copy adds no unique value. Default: leave in place as reference. If you want to remove, run:

```
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --delete <NAME>
```

Delete is opt-in, never automatic.

### 1. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy). Motor `FeatureToggle` registered, AND `FeatureToggleAdapter.py` already ships under _adapters/fastapi/. Both halves of the pair exist — staged copy is pure redundancy.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Delete reason:** Motor `FeatureToggle` + `FeatureToggleAdapter.py` both registered. Staged `FeatureToggleService` duplicates shipped code.
  - **Run (opt-in):** `python -m engine.promotion.promote --delete FeatureToggleService`

### 2. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy). Motor `FeatureToggle` registered, AND `FeatureToggleAdapter.py` already ships under _adapters/fastapi/. Both halves of the pair exist — staged copy is pure redundancy.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Delete reason:** Motor `FeatureToggle` + `FeatureToggleAdapter.py` both registered. Staged `FeatureToggleService` duplicates shipped code.
  - **Run (opt-in):** `python -m engine.promotion.promote --delete FeatureToggleService`

---

## Wait for §A12(b) caller signal — 104 primitive(s)

No current §A12(b) signal — no registered tool, module, or benchmark spec references this primitive. §A12 discipline says: wait for a caller to appear before promoting. Leave in `_extracted/` with the recorded staging_reason.

### 1. [ ] `PubSubManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_graphql_subscriptions.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 2. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_graphql_subscriptions.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 3. [ ] `SignatureHeader` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=1940
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `realtime/add_webhook_sender.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 4. [ ] `TaskManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=151 · tla=n · concurrency=n · mutable=n · tests=y · score=999520
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_long_running_task.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 5. [ ] `TaskRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=113280
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_long_running_task.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 6. [ ] `TokenBucket` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=y · mutable=y · tests=y · score=20160
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_sse.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `realtime/add_sse.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 7. [ ] `VerifiedEvent` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1560
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `realtime/add_webhook_receiver.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 8. [ ] `VersionInfo` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=4020
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_api_versioning.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 9. [ ] `VersionRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=23800
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_api_versioning.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 10. [ ] `WebSocketManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=113 · tla=n · concurrency=y · mutable=n · tests=y · score=1125800
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_chat.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `realtime/add_websocket_chat.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 11. [ ] `WebhookEndpointCreated` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `realtime/add_webhook_sender.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 12. [ ] `WorkerSettings` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2496
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `api_design/add_long_running_task.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 13. [ ] `FeatureFlagPublic` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1576
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_feature_flags.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 14. [ ] `FlagContext` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3204
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_feature_flags.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 15. [ ] `OAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=20940
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_oauth2_provider.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 16. [ ] `OAuthTokens` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1628
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_oauth2_provider.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 17. [ ] `OAuthUserInfo` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1788
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_oauth2_provider.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 18. [ ] `PermissionCache` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=99 · tla=n · concurrency=y · mutable=y · tests=y · score=1065168
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_rbac.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 19. [ ] `ResourceAccessPolicy` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=14352
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_bola_guard.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 20. [ ] `RoleNode` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_rbac.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 21. [ ] `ScopeCheckResult` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=16 · tla=n · concurrency=n · mutable=n · tests=y · score=1408
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_api_key_auth.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 22. [ ] `SocialAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=70 · tla=n · concurrency=n · mutable=n · tests=y · score=144336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `auth_access/add_social_login.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 23. [ ] `LocalStorage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=78 · tla=n · concurrency=y · mutable=n · tests=y · score=247680
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `crud_data/add_file_upload.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 24. [ ] `LocalStorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=24064
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_export.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `crud_data/add_data_export.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 25. [ ] `S3Storage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=19800
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `crud_data/add_file_upload.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 26. [ ] `StorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=12828
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `crud_data/add_file_upload.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 27. [ ] `VerificationResult` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1960
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `crud_data/add_audit_log.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 28. [ ] `APIFuzzer` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=y · tests=y · score=153152
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_api_fuzzer.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 29. [ ] `ActiveUserScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=12648
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_load_profile.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 30. [ ] `AdminScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_load_profile.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 31. [ ] `AuthMixin` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=40400
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_load_profile.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 32. [ ] `BrowsingScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=29064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_load_profile.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 33. [ ] `ComparisonResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=3088
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_evolution_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_schema_evolution_guard.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 34. [ ] `DependencyGraph` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=89 · tla=n · concurrency=n · mutable=n · tests=y · score=694096
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_data_seeder.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 35. [ ] `FieldGenerator` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=140 · tla=n · concurrency=n · mutable=n · tests=y · score=2991816
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_data_seeder.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 36. [ ] `FuzzResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=38328
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_api_fuzzer.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 37. [ ] `FuzzRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=328992
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_api_fuzzer.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 38. [ ] `MigrationCIRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=76600
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_database_migrations_ci.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 39. [ ] `SafetyChecker` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=262080
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `testing_tools/add_database_migrations_ci.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 40. [ ] `APICostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4240
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_cost_tracker.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 41. [ ] `APNsProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21636
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_push_notifications_native.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 42. [ ] `AdaptiveTimeout` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=y · tests=y · score=170940
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_adaptive_timeouts.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 43. [ ] `AlertDispatcher` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=32736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_anomaly_detector.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 44. [ ] `AnomalyDetector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=116964
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_anomaly_detector.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 45. [ ] `AttackPatternRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=75776
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_runtime_sentinel.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 46. [ ] `AwsSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=y · tests=y · score=82752
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_secret_rotation.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 47. [ ] `BulkheadConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4256
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_bulkhead_isolation.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 48. [ ] `CacheBackend` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=79 · tla=n · concurrency=n · mutable=n · tests=y · score=414000
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cache_layer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_cache_layer.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 49. [ ] `CanaryRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=18312
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_canary_tokens.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 50. [ ] `CanaryToken` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=2732
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_canary_tokens.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 51. [ ] `ChaosEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=y · tests=y · score=95200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_chaos_testing.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 52. [ ] `ComplianceEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=77360
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_compliance_engine.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 53. [ ] `ConfigureBillingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 54. [ ] `CostEstimate` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=1852
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_cost_tracker.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 55. [ ] `CostEstimatorProtocol` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=2952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_cost_tracker.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 56. [ ] `CreateAdminUserStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=7048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 57. [ ] `CreateTenantStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=5536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 58. [ ] `DBQueryCostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4272
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_cost_tracker.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 59. [ ] `DegradationManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=y · tests=y · score=28720
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_load_shedding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 60. [ ] `DeviceManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=y · tests=y · score=246708
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_ml_gpu_inference.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 61. [ ] `EmailProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2024
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_email_templates.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 62. [ ] `EnvSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=6528
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_secret_rotation.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 63. [ ] `FCMProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=51 · tla=n · concurrency=n · mutable=n · tests=y · score=69600
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_push_notifications_native.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 64. [ ] `FingerprintStore` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=32640
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_request_fingerprint.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 65. [ ] `HealthMapBuilder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=54 · tla=n · concurrency=y · mutable=n · tests=y · score=122816
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_dependency_health_map.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 66. [ ] `HealthRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=87 · tla=n · concurrency=y · mutable=n · tests=y · score=209832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_health_deep.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_health_deep.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 67. [ ] `InputSanitizer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=35088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_input_sanitization.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 68. [ ] `JobStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_arq_worker.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 69. [ ] `LatencyInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=y · mutable=n · tests=y · score=4968
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_chaos_testing.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 70. [ ] `MODEL_NAMEAdmin` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=11 · tla=n · concurrency=n · mutable=n · tests=y · score=1608
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_sqladmin.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 71. [ ] `MemoryGuard` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · score=159696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_ml_gpu_inference.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 72. [ ] `MeterEventBuffer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=n · mutable=y · tests=y · score=14208
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_api_monetization.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 73. [ ] `OnboardingOrchestrator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=207424
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 74. [ ] `OnboardingProgress` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=23 · tla=n · concurrency=n · mutable=n · tests=y · score=8904
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 75. [ ] `OnboardingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=5148
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 76. [ ] `PushService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=31264
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_push_notifications_native.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 77. [ ] `RefundStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=1356
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_stripe_refund_flow.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 78. [ ] `ReportEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=82 · tla=n · concurrency=y · mutable=n · tests=y · score=97440
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_pdf_reports.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_pdf_reports.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 79. [ ] `RequestFingerprinter` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=56 · tla=n · concurrency=n · mutable=n · tests=y · score=61280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_request_fingerprint.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 80. [ ] `RequestMetrics` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=y · tests=y · score=78948
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_prometheus_metrics.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 81. [ ] `RequestRecorder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=105 · tla=n · concurrency=n · mutable=n · tests=y · score=733320
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_api_replay_debugger.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 82. [ ] `RequestReplayer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=33536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_api_replay_debugger.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 83. [ ] `ResendProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=4628
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_email_templates.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 84. [ ] `S3Client` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=81 · tla=n · concurrency=n · mutable=n · tests=y · score=86736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_s3_storage.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 85. [ ] `S3CostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4480
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_cost_tracker.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 86. [ ] `SMTPProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=12 · tla=n · concurrency=y · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_email_templates.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 87. [ ] `Saga` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=24496
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_saga.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 88. [ ] `SchedulerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=11152
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_scheduled_tasks.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_scheduled_tasks.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 89. [ ] `SecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=16008
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_secret_rotation.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 90. [ ] `SecurityEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=2604
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_runtime_sentinel.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 91. [ ] `SeedDataStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=5696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 92. [ ] `SendWelcomeEmailStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_tenant_onboarding.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 93. [ ] `SendgridProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=12400
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_transactional_email.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 94. [ ] `SensitivePattern` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1268
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_dlp_shield.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 95. [ ] `StorageConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=5788
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_s3_storage.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 96. [ ] `StripeBilling` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_stripe_subscription.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 97. [ ] `TemplateName` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2244
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_email_templates.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 98. [ ] `TemporalClientFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=11624
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_temporal_workflow.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 99. [ ] `TimeoutInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=y · mutable=n · tests=y · score=7832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_chaos_testing.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 100. [ ] `TimeoutRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=31376
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_adaptive_timeouts.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 101. [ ] `TimingCollector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=31740
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_request_tracing_ui.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 102. [ ] `VaultSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=96576
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_secret_rotation.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 103. [ ] `WorkerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=12552
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_temporal_workflow.py` but no current caller declares it. Re-evaluate on the next triage pass.

### 104. [ ] `WorkerSettings` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=3932
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from `infrastructure/add_arq_worker.py` but no current caller declares it. Re-evaluate on the next triage pass.

---
