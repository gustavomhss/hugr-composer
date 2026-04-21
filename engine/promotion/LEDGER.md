# Promotion Ledger

**Generated:** 2026-04-21T13:42:52+00:00 · **Classifier:** v1.0 · **Total:** 229 (182 staged + 47 quarantined)

> **How to use this ledger.** Each entry is a proposed verdict, not a
> decided action. Tick the checkbox of an entry to mark it approved;
> un-ticked = not yet approved. The `Run:` line gives the exact
> command to execute an approved entry. §A12 discipline is intact —
> the executor refuses any entry whose verdict isn't PROMOTE_* or
> DELETE, or which still has unresolved blockers.

## Summary

| Verdict | Count | Gustavo's next step |
|---|---:|---|
| delete | 0 | Review + approve individually; executor removes each. |
| promote_full | 0 | Review + approve individually; executor runs each. |
| promote_lite | 0 | Ratify §B1.7 first; then review + approve. |
| needs_review | 0 | Resolve blockers, then re-run classifier. |
| keep_staged | 229 | No action required. Revisit on next triage pass. |

## Keep staged (awaiting signal or re-extraction) — 229 primitive(s)

No current §A12(b) signal, OR signal present but the shell requires re-extraction. Leave in `_extracted/` with the recorded staging_reason. Each entry's `staging_reason` line documents why the primitive stays put.

### 1. [ ] `Event` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=4908
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py` · `benchmark_ref`: `benchmarks/specs/mid/03_event_sourced_orders.md`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 2. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8384
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_deprecation.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 3. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=8384
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_deprecation.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 4. [ ] `GitHubVerifier` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=5 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=28144
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** Framework-coupled: imports fastapi. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 5. [ ] `InternalVerifier` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=5 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=175744
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** Framework-coupled: imports fastapi. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 6. [ ] `PubSubManager` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_graphql_subscriptions.py`. Re-extract or waive the gate rule that rejected it.

### 7. [ ] `PubSubManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_graphql_subscriptions.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 8. [ ] `ReadReplicaSession` (api)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=7264
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_cqrs.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 9. [ ] `ReadReplicaSession` (api)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=7264
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_cqrs.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 10. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_graphql_subscriptions.py`. Re-extract or waive the gate rule that rejected it.

### 11. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_graphql_subscriptions.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 12. [ ] `SignatureHeader` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=1940
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 13. [ ] `StripeVerifier` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=5 · loc=41 · tla=n · concurrency=n · mutable=n · tests=y · score=35140
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** Framework-coupled: imports fastapi. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 14. [ ] `TaskManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=151 · tla=n · concurrency=n · mutable=n · tests=y · score=999520
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 15. [ ] `TaskRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=113280
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 16. [ ] `TokenBucket` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=y · mutable=y · tests=y · score=20160
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_sse.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_sse.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 17. [ ] `UserPresence` (api)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=4044
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_presence.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 18. [ ] `VerifiedEvent` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1560
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_receiver.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 19. [ ] `VersionInfo` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=4020
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 20. [ ] `VersionRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=23800
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 21. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=75000
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 22. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · score=75000
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 23. [ ] `WebSocketManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=113 · tla=n · concurrency=y · mutable=n · tests=y · score=1125800
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_chat.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_websocket_chat.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 24. [ ] `WebhookDelivery` (api)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=7516
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 25. [ ] `WebhookEndpoint` (api)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=7948
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 26. [ ] `WebhookEndpointCreated` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 27. [ ] `WorkerSettings` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2496
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 28. [ ] `APIKey` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9420
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 29. [ ] `CedarAuthzMiddleware` (auth)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=72 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=167700
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_cedar_policies.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 30. [ ] `CedarEngine` (auth)

  - **Rationale:** Primary .py imports framework module(s) (starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=71 · tla=n · concurrency=n · mutable=y · tests=y · score=176520
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_cedar_policies.py`
  - **Staging reason:** Framework-coupled: imports starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 31. [ ] `FeatureFlag` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=11324
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 32. [ ] `FeatureFlagAudit` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=5472
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 33. [ ] `FeatureFlagPublic` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1576
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 34. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 35. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 36. [ ] `FlagContext` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3204
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 37. [ ] `MFADevice` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6996
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_mfa.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 38. [ ] `MFARecoveryCode` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3728
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_mfa.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 39. [ ] `OAuthAccount` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=8632
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 40. [ ] `OAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=20940
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 41. [ ] `OAuthTokens` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1628
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 42. [ ] `OAuthUserInfo` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1788
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 43. [ ] `OPAMiddleware` (auth)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=12792
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_opa_integration.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 44. [ ] `OPAMiddleware` (auth)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=12792
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_opa_integration.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 45. [ ] `OtpCode` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=4440
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_sms_otp.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 46. [ ] `OwnershipVerifier` (auth)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200016
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** Framework-coupled: imports fastapi, sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 47. [ ] `Passkey` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6456
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_passkey_auth.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 48. [ ] `Permission` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=3548
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 49. [ ] `PermissionCache` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=99 · tla=n · concurrency=y · mutable=y · tests=y · score=1065168
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 50. [ ] `RequestSigningMiddleware` (auth)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=101920
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_request_signing.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 51. [ ] `ResourceAccessPolicy` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=14352
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_bola_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 52. [ ] `RoleNode` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 53. [ ] `RolePermission` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=3300
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 54. [ ] `ScopeCheckResult` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=16 · tla=n · concurrency=n · mutable=n · tests=y · score=1408
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_api_key_auth.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 55. [ ] `SocialAccount` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=6648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 56. [ ] `SocialAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=70 · tla=n · concurrency=n · mutable=n · tests=y · score=144336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_social_login.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 57. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8856
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 58. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=8856
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 59. [ ] `TenantMiddleware` (auth)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, sqlalchemy, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=67 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=258336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_multi_tenancy.py`
  - **Staging reason:** Framework-coupled: imports fastapi, sqlalchemy, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 60. [ ] `TenantScopedMixin` (auth)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2252
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_multi_tenancy.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 61. [ ] `AuditLog` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=11676
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 62. [ ] `ContentVersion` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=7204
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 63. [ ] `CursorPaginator` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=880488
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_cursor_pagination.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 64. [ ] `CursorPaginator` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · score=880488
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_cursor_pagination.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 65. [ ] `EventStore` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=198520
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 66. [ ] `EventStore` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · score=198520
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 67. [ ] `ImportJob` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6924
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 68. [ ] `ImportProcessor` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200580
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 69. [ ] `ImportProcessor` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · score=200580
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 70. [ ] `LocalStorage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=78 · tla=n · concurrency=y · mutable=n · tests=y · score=247680
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 71. [ ] `LocalStorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=24064
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_export.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_export.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 72. [ ] `Projector` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=112600
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 73. [ ] `S3Storage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=19800
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 74. [ ] `SoftDeleteMixin` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=12612
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_soft_delete.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 75. [ ] `StorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=12828
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 76. [ ] `VerificationResult` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1960
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_audit_log.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 77. [ ] `VersioningService` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=2873280
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 78. [ ] `VersioningService` (data)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · score=2873280
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 79. [ ] `APIFuzzer` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=y · tests=y · score=153152
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 80. [ ] `ActiveUserScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=12648
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 81. [ ] `AdminScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 82. [ ] `AuthMixin` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=40400
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 83. [ ] `BrowsingScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=29064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 84. [ ] `ComparisonResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=3088
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_evolution_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_schema_evolution_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 85. [ ] `DataSeeder` (extras)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=110064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 86. [ ] `DataSeeder` (extras)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · score=110064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 87. [ ] `DependencyGraph` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=89 · tla=n · concurrency=n · mutable=n · tests=y · score=694096
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 88. [ ] `FieldGenerator` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=140 · tla=n · concurrency=n · mutable=n · tests=y · score=2991816
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 89. [ ] `FuzzResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=38328
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 90. [ ] `FuzzRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=328992
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 91. [ ] `MigrationCIRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=76600
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_database_migrations_ci.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 92. [ ] `SafetyChecker` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=262080
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_database_migrations_ci.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 93. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=27520
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_enforcer.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 94. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=27520
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_enforcer.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 95. [ ] `APICostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4240
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 96. [ ] `APNsProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21636
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 97. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=21408
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_throttle.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 98. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21408
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_throttle.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 99. [ ] `AdaptiveTimeout` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=y · tests=y · score=170940
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_timeouts.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 100. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=181296
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 101. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · score=181296
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 102. [ ] `AlertDispatcher` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=32736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 103. [ ] `AnomalyDetector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=116964
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 104. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=29760
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 105. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · score=29760
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 106. [ ] `AttackPatternRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=75776
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_runtime_sentinel.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 107. [ ] `AwsSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=y · tests=y · score=82752
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 108. [ ] `BulkheadConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4256
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_bulkhead_isolation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 109. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 110. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 111. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10128
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cors_config.py`
  - **Staging reason:** Framework-coupled: imports starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 112. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=10128
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cors_config.py`
  - **Staging reason:** Framework-coupled: imports starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 113. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=135072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 114. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · score=135072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 115. [ ] `CSRFProtection` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · score=269920
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`
  - **Staging reason:** Framework-coupled: imports fastapi. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 116. [ ] `CacheBackend` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=79 · tla=n · concurrency=n · mutable=n · tests=y · score=414000
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cache_layer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cache_layer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 117. [ ] `CanaryRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=18312
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_canary_tokens.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 118. [ ] `CanaryToken` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=2732
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_canary_tokens.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 119. [ ] `ChaosEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=y · tests=y · score=95200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 120. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10992
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 121. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=10992
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 122. [ ] `ComplianceEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=77360
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_compliance_engine.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 123. [ ] `ComplianceEvent` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=5072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 124. [ ] `ConfigureBillingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 125. [ ] `CostEstimate` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=1852
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 126. [ ] `CostEstimatorProtocol` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=2952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 127. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=41952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 128. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=41952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 129. [ ] `CreateAdminUserStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=7048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 130. [ ] `CreateTenantStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=5536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 131. [ ] `DBQueryCostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4272
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 132. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=64160
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 133. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · score=64160
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 134. [ ] `DegradationManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=y · tests=y · score=28720
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_load_shedding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 135. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=23772
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 136. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=23772
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 137. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=809472
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 138. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · score=809472
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 139. [ ] `DeviceManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=y · tests=y · score=246708
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_gpu_inference.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 140. [ ] `DeviceToken` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=2460
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 141. [ ] `EmailEvent` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=14 · tla=n · concurrency=n · mutable=n · tests=y · score=2068
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 142. [ ] `EmailProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2024
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 143. [ ] `EnvSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=6528
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 144. [ ] `ErrorInjector` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=6832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** Framework-coupled: imports fastapi. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 145. [ ] `FCMProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=51 · tla=n · concurrency=n · mutable=n · tests=y · score=69600
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 146. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=513504
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 147. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=513504
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 148. [ ] `FingerprintStore` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=32640
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 149. [ ] `HealthMapBuilder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=54 · tla=n · concurrency=y · mutable=n · tests=y · score=122816
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dependency_health_map.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 150. [ ] `HealthRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=87 · tla=n · concurrency=y · mutable=n · tests=y · score=209832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_health_deep.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_health_deep.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 151. [ ] `InputSanitizer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=35088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_input_sanitization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 152. [ ] `Job` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9404
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 153. [ ] `JobStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 154. [ ] `LatencyInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=y · mutable=n · tests=y · score=4968
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 155. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=91200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 156. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=91200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 157. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=11544
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 158. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=11544
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 159. [ ] `MLModel` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=7364
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 160. [ ] `MODEL_NAMEAdmin` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=11 · tla=n · concurrency=n · mutable=n · tests=y · score=1608
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_sqladmin.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 161. [ ] `MemoryGuard` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · score=159696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_gpu_inference.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 162. [ ] `MeterEventBuffer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=n · mutable=y · tests=y · score=14208
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_monetization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 163. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45384
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 164. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=45384
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 165. [ ] `Notification` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=4868
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 166. [ ] `NotificationService` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45648
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 167. [ ] `NotificationService` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=45648
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 168. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=31632
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_opentelemetry.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 169. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · score=31632
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_opentelemetry.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 170. [ ] `OnboardingOrchestrator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=207424
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 171. [ ] `OnboardingProgress` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=23 · tla=n · concurrency=n · mutable=n · tests=y · score=8904
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 172. [ ] `OnboardingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=5148
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 173. [ ] `OutboxDlq` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=3920
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 174. [ ] `OutboxEvent` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9324
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 175. [ ] `OutboxService` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=30672
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 176. [ ] `OutboxService` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=30672
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 177. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8704
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 178. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=8704
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 179. [ ] `PushService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=31264
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 180. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=186420
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 181. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · score=186420
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 182. [ ] `Refund` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=7144
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 183. [ ] `RefundStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=1356
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_refund_flow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 184. [ ] `RegistryService` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=119280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 185. [ ] `RegistryService` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · score=119280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 186. [ ] `ReportEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=82 · tla=n · concurrency=y · mutable=n · tests=y · score=97440
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_pdf_reports.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_pdf_reports.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 187. [ ] `RequestFingerprinter` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=56 · tla=n · concurrency=n · mutable=n · tests=y · score=61280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 188. [ ] `RequestMetrics` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=y · tests=y · score=78948
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_prometheus_metrics.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 189. [ ] `RequestRecorder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=105 · tla=n · concurrency=n · mutable=n · tests=y · score=733320
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 190. [ ] `RequestReplayer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=33536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 191. [ ] `ResendProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=4628
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 192. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=175120
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_response_armor.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 193. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · score=175120
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_response_armor.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 194. [ ] `S3Client` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=81 · tla=n · concurrency=n · mutable=n · tests=y · score=86736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 195. [ ] `S3CostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4480
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 196. [ ] `SMTPProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=12 · tla=n · concurrency=y · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 197. [ ] `Saga` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=24496
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_saga.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 198. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=706944
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 199. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · score=706944
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 200. [ ] `SagaInstance` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=7696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 201. [ ] `SagaStepExecution` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=7104
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 202. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=88956
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 203. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · score=88956
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 204. [ ] `SchedulerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=11152
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_scheduled_tasks.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_scheduled_tasks.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 205. [ ] `SecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=16008
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 206. [ ] `SecurityEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=2604
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_runtime_sentinel.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 207. [ ] `SeedDataStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=5696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 208. [ ] `SendWelcomeEmailStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 209. [ ] `SendgridProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=12400
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_transactional_email.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 210. [ ] `SensitivePattern` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1268
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dlp_shield.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 211. [ ] `ShutdownHealthGate` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=7616
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Staging reason:** Framework-coupled: imports fastapi. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 212. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10792
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 213. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=10792
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 214. [ ] `StorageConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=5788
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 215. [ ] `StripeBilling` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_stripe_subscription.py`. Re-extract or waive the gate rule that rejected it.

### 216. [ ] `StripeBilling` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_subscription.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 217. [ ] `TemplateName` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2244
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 218. [ ] `TemporalClientFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=11624
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_temporal_workflow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 219. [ ] `TimeoutInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=y · mutable=n · tests=y · score=7832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 220. [ ] `TimeoutRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=31376
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_timeouts.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 221. [ ] `TimingCollector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=31740
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_tracing_ui.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 222. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=29040
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 223. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=29040
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 224. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=51840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 225. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (fastapi, starlette). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=51840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** Framework-coupled: imports fastapi, starlette. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 226. [ ] `UsageRecord` (resiliency)

  - **Rationale:** Primary .py imports framework module(s) (sqlalchemy). CONTRACT §B1.0.1 bars framework imports from registered primitives. Must be re-extracted as a framework-free primitive (with adapter under _adapters/fastapi/ if the FastAPI surface is needed) before promotion.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=4596
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** Framework-coupled: imports sqlalchemy. Requires re-extraction with adapter pattern (CONTRACT §B1.0.1) before promotion.

### 227. [ ] `VaultSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=96576
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 228. [ ] `WorkerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=12552
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_temporal_workflow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 229. [ ] `WorkerSettings` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=3932
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

---
