# Promotion Ledger

**Generated:** 2026-04-21T13:49:09+00:00 · **Classifier:** v1.0 · **Total:** 229 (182 staged + 47 quarantined)

> **How to use this ledger.** Each entry is a proposed verdict, not a
> decided action. Tick the checkbox of an entry to mark it approved;
> un-ticked = not yet approved. The `Run:` line gives the exact
> command to execute an approved entry. §A12 discipline is intact —
> the executor refuses any entry whose verdict isn't PROMOTE_* or
> DELETE, or which still has unresolved blockers.

## Summary

| Verdict | Count | Gustavo's next step |
|---|---:|---|
| delete | 4 | Review + approve individually; executor removes each. |
| promote_full | 0 | Review + approve individually; executor runs each. |
| promote_lite | 0 | Ratify §B1.7 first; then review + approve. |
| needs_decision | 118 | Human call: re-extract as motor+adapter, or delete. |
| needs_review | 0 | Resolve blockers, then re-run classifier. |
| keep_staged | 107 | No action required. Revisit on next triage pass. |

## Delete (redundant or not salvageable) — 4 primitive(s)

Either duplicates of a registered primitive (registered version is canonical), or quarantined with non-fixable framework coupling. Approve to run:

```
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --delete <NAME>
```

### 1. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) AND its motor `FeatureToggle` is already registered. This staged item is just the framework plugin — the registered motor already ships with its canonical adapter under _adapters/fastapi/. Redundant.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Delete reason:** Framework plugin whose motor `FeatureToggle` is registered at core/venous/*/FeatureToggle/. Staged copy adds no value.
  - **Run:** `python -m engine.promotion.promote --delete FeatureToggleService`

### 2. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Framework-coupled (sqlalchemy) AND its motor `FeatureToggle` is already registered. This staged item is just the framework plugin — the registered motor already ships with its canonical adapter under _adapters/fastapi/. Redundant.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Delete reason:** Framework plugin whose motor `FeatureToggle` is registered at core/venous/*/FeatureToggle/. Staged copy adds no value.
  - **Run:** `python -m engine.promotion.promote --delete FeatureToggleService`

### 3. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) AND its motor `Bulkhead` is already registered. This staged item is just the framework plugin — the registered motor already ships with its canonical adapter under _adapters/fastapi/. Redundant.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Delete reason:** Framework plugin whose motor `Bulkhead` is registered at core/venous/*/Bulkhead/. Staged copy adds no value.
  - **Run:** `python -m engine.promotion.promote --delete BulkheadMiddleware`

### 4. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Framework-coupled (fastapi, starlette) AND its motor `Bulkhead` is already registered. This staged item is just the framework plugin — the registered motor already ships with its canonical adapter under _adapters/fastapi/. Redundant.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Delete reason:** Framework plugin whose motor `Bulkhead` is registered at core/venous/*/Bulkhead/. Staged copy adds no value.
  - **Run:** `python -m engine.promotion.promote --delete BulkheadMiddleware`

---

## Keep staged (awaiting signal or re-extraction) — 107 primitive(s)

No current §A12(b) signal, OR signal present but the shell requires re-extraction. Leave in `_extracted/` with the recorded staging_reason. Each entry's `staging_reason` line documents why the primitive stays put.

### 1. [ ] `PubSubManager` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_graphql_subscriptions.py`. Re-extract or waive the gate rule that rejected it.

### 2. [ ] `PubSubManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_graphql_subscriptions.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 3. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_graphql_subscriptions.py`. Re-extract or waive the gate rule that rejected it.

### 4. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_graphql_subscriptions.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 5. [ ] `SignatureHeader` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=1940
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 6. [ ] `TaskManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=151 · tla=n · concurrency=n · mutable=n · tests=y · score=999520
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 7. [ ] `TaskRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=113280
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 8. [ ] `TokenBucket` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=y · mutable=y · tests=y · score=20160
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_sse.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_sse.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 9. [ ] `VerifiedEvent` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1560
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_receiver.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 10. [ ] `VersionInfo` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=4020
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 11. [ ] `VersionRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=23800
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 12. [ ] `WebSocketManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=113 · tla=n · concurrency=y · mutable=n · tests=y · score=1125800
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_chat.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_websocket_chat.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 13. [ ] `WebhookEndpointCreated` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 14. [ ] `WorkerSettings` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2496
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 15. [ ] `FeatureFlagPublic` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1576
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 16. [ ] `FlagContext` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3204
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 17. [ ] `OAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=20940
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 18. [ ] `OAuthTokens` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1628
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 19. [ ] `OAuthUserInfo` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1788
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 20. [ ] `PermissionCache` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=99 · tla=n · concurrency=y · mutable=y · tests=y · score=1065168
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 21. [ ] `ResourceAccessPolicy` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=14352
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_bola_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 22. [ ] `RoleNode` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 23. [ ] `ScopeCheckResult` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=16 · tla=n · concurrency=n · mutable=n · tests=y · score=1408
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_api_key_auth.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 24. [ ] `SocialAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=70 · tla=n · concurrency=n · mutable=n · tests=y · score=144336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_social_login.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 25. [ ] `LocalStorage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=78 · tla=n · concurrency=y · mutable=n · tests=y · score=247680
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 26. [ ] `LocalStorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=24064
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_export.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_export.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 27. [ ] `S3Storage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=19800
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 28. [ ] `StorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=12828
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 29. [ ] `VerificationResult` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1960
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_audit_log.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 30. [ ] `APIFuzzer` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=y · tests=y · score=153152
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 31. [ ] `ActiveUserScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=12648
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 32. [ ] `AdminScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 33. [ ] `AuthMixin` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=40400
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 34. [ ] `BrowsingScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=29064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 35. [ ] `ComparisonResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=3088
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_evolution_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_schema_evolution_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 36. [ ] `DependencyGraph` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=89 · tla=n · concurrency=n · mutable=n · tests=y · score=694096
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 37. [ ] `FieldGenerator` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=140 · tla=n · concurrency=n · mutable=n · tests=y · score=2991816
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 38. [ ] `FuzzResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=38328
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 39. [ ] `FuzzRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=328992
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 40. [ ] `MigrationCIRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=76600
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_database_migrations_ci.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 41. [ ] `SafetyChecker` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=262080
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_database_migrations_ci.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 42. [ ] `APICostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4240
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 43. [ ] `APNsProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21636
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 44. [ ] `AdaptiveTimeout` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=y · tests=y · score=170940
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_timeouts.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 45. [ ] `AlertDispatcher` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=32736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 46. [ ] `AnomalyDetector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=116964
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 47. [ ] `AttackPatternRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=75776
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_runtime_sentinel.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 48. [ ] `AwsSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=y · tests=y · score=82752
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 49. [ ] `BulkheadConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4256
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_bulkhead_isolation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 50. [ ] `CacheBackend` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=79 · tla=n · concurrency=n · mutable=n · tests=y · score=414000
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cache_layer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cache_layer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 51. [ ] `CanaryRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=18312
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_canary_tokens.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 52. [ ] `CanaryToken` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=2732
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_canary_tokens.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 53. [ ] `ChaosEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=y · tests=y · score=95200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 54. [ ] `ComplianceEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=77360
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_compliance_engine.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 55. [ ] `ConfigureBillingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 56. [ ] `CostEstimate` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=1852
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 57. [ ] `CostEstimatorProtocol` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=2952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 58. [ ] `CreateAdminUserStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=7048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 59. [ ] `CreateTenantStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=5536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 60. [ ] `DBQueryCostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4272
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 61. [ ] `DegradationManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=y · tests=y · score=28720
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_load_shedding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 62. [ ] `DeviceManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=y · tests=y · score=246708
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_gpu_inference.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 63. [ ] `EmailProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2024
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 64. [ ] `EnvSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=6528
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 65. [ ] `FCMProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=51 · tla=n · concurrency=n · mutable=n · tests=y · score=69600
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 66. [ ] `FingerprintStore` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=32640
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 67. [ ] `HealthMapBuilder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=54 · tla=n · concurrency=y · mutable=n · tests=y · score=122816
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dependency_health_map.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 68. [ ] `HealthRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=87 · tla=n · concurrency=y · mutable=n · tests=y · score=209832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_health_deep.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_health_deep.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 69. [ ] `InputSanitizer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=35088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_input_sanitization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 70. [ ] `JobStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 71. [ ] `LatencyInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=y · mutable=n · tests=y · score=4968
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 72. [ ] `MODEL_NAMEAdmin` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=11 · tla=n · concurrency=n · mutable=n · tests=y · score=1608
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_sqladmin.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 73. [ ] `MemoryGuard` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · score=159696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_gpu_inference.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 74. [ ] `MeterEventBuffer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=n · mutable=y · tests=y · score=14208
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_monetization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 75. [ ] `OnboardingOrchestrator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=207424
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 76. [ ] `OnboardingProgress` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=23 · tla=n · concurrency=n · mutable=n · tests=y · score=8904
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 77. [ ] `OnboardingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=5148
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 78. [ ] `PushService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=31264
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 79. [ ] `RefundStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=1356
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_refund_flow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 80. [ ] `ReportEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=82 · tla=n · concurrency=y · mutable=n · tests=y · score=97440
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_pdf_reports.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_pdf_reports.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 81. [ ] `RequestFingerprinter` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=56 · tla=n · concurrency=n · mutable=n · tests=y · score=61280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 82. [ ] `RequestMetrics` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=y · tests=y · score=78948
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_prometheus_metrics.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 83. [ ] `RequestRecorder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=105 · tla=n · concurrency=n · mutable=n · tests=y · score=733320
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 84. [ ] `RequestReplayer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=33536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 85. [ ] `ResendProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=4628
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 86. [ ] `S3Client` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=81 · tla=n · concurrency=n · mutable=n · tests=y · score=86736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 87. [ ] `S3CostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4480
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 88. [ ] `SMTPProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=12 · tla=n · concurrency=y · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 89. [ ] `Saga` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=24496
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_saga.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 90. [ ] `SchedulerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=11152
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_scheduled_tasks.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_scheduled_tasks.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 91. [ ] `SecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=16008
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 92. [ ] `SecurityEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=2604
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_runtime_sentinel.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 93. [ ] `SeedDataStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=5696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 94. [ ] `SendWelcomeEmailStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 95. [ ] `SendgridProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=12400
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_transactional_email.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 96. [ ] `SensitivePattern` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1268
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dlp_shield.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 97. [ ] `StorageConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=5788
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 98. [ ] `StripeBilling` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_stripe_subscription.py`. Re-extract or waive the gate rule that rejected it.

### 99. [ ] `StripeBilling` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_subscription.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 100. [ ] `TemplateName` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2244
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 101. [ ] `TemporalClientFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=11624
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_temporal_workflow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 102. [ ] `TimeoutInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=y · mutable=n · tests=y · score=7832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 103. [ ] `TimeoutRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=31376
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_timeouts.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 104. [ ] `TimingCollector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=31740
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_tracing_ui.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 105. [ ] `VaultSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=96576
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 106. [ ] `WorkerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=12552
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_temporal_workflow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 107. [ ] `WorkerSettings` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=3932
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

---
