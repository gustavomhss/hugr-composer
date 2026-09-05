# Promotion Ledger

**Generated:** 2026-09-05T22:36:49+00:00 · **Classifier:** v1.0 · **Total:** 41 (0 staged + 41 quarantined)

> **How to use this ledger.** Each entry proposes a path to
> functionality. Tick the checkbox to mark it approved; un-ticked =
> not yet approved. PROMOTE_* entries have a copy-paste `Run:`
> command. Default stance is **make it work, not delete** —
> REDUNDANT entries stay in place unless you explicitly opt-in to
> remove them. §A12 discipline is intact.

## Summary

| Verdict | Count | Gustavo's next step |
|---|---:|---|
| promote_as_adapter | 0 | Review + approve individually; executor ships each. |
| promote_as_primitive | 0 | Ratify §B1.8 (for lite) → review + approve. |
| fill_and_promote | 0 | Fill REPLACE_ME + invariant tests; reclassify. |
| extract_motor_pair | 41 | Refactoring sprint — ~2-4h per item. |
| needs_review | 0 | Adjudicate manually; reclassify. |
| redundant | 0 | Leave in place, or opt-in delete for cleanup. |
| needs_caller | 0 | No action. Revisit when a caller appears. |

## Extract motor+adapter pair (re-factor required) — 41 primitive(s)

Framework-coupled with no motor registered. Cannot be promoted as-is (§B1.0.1 bars framework imports in registered primitives). Required work per item: split into (framework-free motor primitive under `core/venous/<ns>/<Motor>/`) + (FastAPI adapter under `_adapters/fastapi/<Motor>Adapter.py`). ~2-4h per item depending on complexity. No one-shot command — this is a refactoring sprint, not an executor call.

### 1. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Deprecation`.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8384
  - **Signals:** _No signals._

### 2. [ ] `ReadReplicaSession` (api)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=7264
  - **Signals:** _No signals._

### 3. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `VersionResolver`.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=75000
  - **Signals:** _No signals._

### 4. [ ] `CedarAuthzMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CedarAuthz`.
  - **State:** REPLACE_ME=7 · loc=72 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=167700
  - **Signals:** _No signals._

### 5. [ ] `OPAMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `OPA`.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=12792
  - **Signals:** _No signals._

### 6. [ ] `OwnershipVerifier` (auth)

  - **Rationale:** Framework-coupled (fastapi, sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200016
  - **Signals:** _No signals._

### 7. [ ] `RequestSigningMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `RequestSigning`.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=101920
  - **Signals:** _No signals._

### 8. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8856
  - **Signals:** _No signals._

### 9. [ ] `TenantMiddleware` (auth)

  - **Rationale:** Framework-coupled (fastapi, sqlalchemy, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Tenant`.
  - **State:** REPLACE_ME=7 · loc=67 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=258336
  - **Signals:** _No signals._

### 10. [ ] `CursorPaginator` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=880488
  - **Signals:** _No signals._

### 11. [ ] `EventStore` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=198520
  - **Signals:** _No signals._

### 12. [ ] `ImportProcessor` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200580
  - **Signals:** _No signals._

### 13. [ ] `VersioningService` (data)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Versioning`.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=2873280
  - **Signals:** _No signals._

### 14. [ ] `DataSeeder` (extras)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=110064
  - **Signals:** _No signals._

### 15. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `SchemaEnforcer`.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=27520
  - **Signals:** _No signals._

### 16. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `AdaptiveThrottle`.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=21408
  - **Signals:** _No signals._

### 17. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `AdminAuth`.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=181296
  - **Signals:** _No signals._

### 18. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Anomaly`.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=29760
  - **Signals:** _No signals._

### 19. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CORSConfig`.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10128
  - **Signals:** _No signals._

### 20. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `CSRF`.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=135072
  - **Signals:** _No signals._

### 21. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Chaos`.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10992
  - **Signals:** _No signals._

### 22. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Cost`.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=41952
  - **Signals:** _No signals._

### 23. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `DLP`.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=64160
  - **Signals:** _No signals._

### 24. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=23772
  - **Signals:** _No signals._

### 25. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=809472
  - **Signals:** _No signals._

### 26. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Fingerprint`.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=513504
  - **Signals:** _No signals._

### 27. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `LeakDetector`.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=91200
  - **Signals:** _No signals._

### 28. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `LoadShedding`.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=11544
  - **Signals:** _No signals._

### 29. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Metering`.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45384
  - **Signals:** _No signals._

### 30. [ ] `NotificationService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Notification`.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45648
  - **Signals:** _No signals._

### 31. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `OTEL`.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=31632
  - **Signals:** _No signals._

### 32. [ ] `OutboxService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Outbox`.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=30672
  - **Signals:** _No signals._

### 33. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Prometheus`.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8704
  - **Signals:** _No signals._

### 34. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Recorder`.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=186420
  - **Signals:** _No signals._

### 35. [ ] `RegistryService` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Registry`.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=119280
  - **Signals:** _No signals._

### 36. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `ResponseArmor`.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=175120
  - **Signals:** _No signals._

### 37. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** Framework-coupled (sqlalchemy) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. No common framework suffix; motor name must be chosen manually.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=706944
  - **Signals:** _No signals._

### 38. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Sanitize`.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=88956
  - **Signals:** _No signals._

### 39. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Shutdown`.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10792
  - **Signals:** _No signals._

### 40. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `Tracing`.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=29040
  - **Signals:** _No signals._

### 41. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) with no registered motor. Requires re-extraction into (framework-free motor primitive + FastAPI adapter) per §B1.0.1. Suggested motor name: `UploadSize`.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=51840
  - **Signals:** _No signals._

---
