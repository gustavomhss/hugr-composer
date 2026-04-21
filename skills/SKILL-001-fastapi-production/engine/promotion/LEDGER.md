# Promotion Ledger

**Generated:** 2026-04-21T06:06:01+00:00 · **Classifier:** v1.0 · **Total:** 242 (195 staged + 47 quarantined)

> **How to use this ledger.** Each entry is a proposed verdict, not a
> decided action. Tick the checkbox of an entry to mark it approved;
> un-ticked = not yet approved. The `Run:` line gives the exact
> command to execute an approved entry. §A12 discipline is intact —
> the executor refuses any entry whose verdict isn't PROMOTE_* or
> DELETE, or which still has unresolved blockers.

## Summary

| Verdict | Count | Gustavo's next step |
|---|---:|---|
| delete | 13 | Review + approve individually; executor removes each. |
| promote_full | 0 | Review + approve individually; executor runs each. |
| promote_lite | 0 | Ratify §B1.7 first; then review + approve. |
| needs_review | 1 | Resolve blockers, then re-run classifier. |
| keep_staged | 228 | No action required. Revisit on next triage pass. |

## Delete (redundant or not salvageable) — 13 primitive(s)

Either duplicates of a registered primitive (registered version is canonical), or quarantined with non-fixable framework coupling. Approve to run:

```
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --delete <NAME>
```

### 1. [ ] `FeatureToggle` (auth)

  - **Rationale:** Duplicate of registered primitive `FeatureToggle`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=FeatureToggle · score=6020
  - **Signals:** `tool_import`: `adapt/extend/auth_access/add_feature_flags.py` · `tool_import`: `adapt/extend/auth_access/add_feature_toggles_api.py` · `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py` · `module_ref`: `adapt/extend/auth_access/test_add_feature_flags.py` · `module_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Delete reason:** Redundant with core/venous/*/FeatureToggle/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete FeatureToggle`

### 2. [ ] `FeatureFlagCache` (auth)

  - **Rationale:** Duplicate of registered primitive `FeatureFlagCache`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=y · mutable=y · tests=y · dup_of=FeatureFlagCache · score=1114932
  - **Signals:** `tool_import`: `adapt/extend/auth_access/add_feature_flags.py` · `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py` · `module_ref`: `adapt/extend/auth_access/test_add_feature_flags.py` · `module_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Delete reason:** Redundant with core/venous/*/FeatureFlagCache/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete FeatureFlagCache`

### 3. [ ] `Bulkhead` (resiliency)

  - **Rationale:** Duplicate of registered primitive `Bulkhead`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=Bulkhead · score=21132
  - **Signals:** `tool_import`: `adapt/extend/infrastructure/add_bulkhead_isolation.py` · `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py` · `module_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py` · `module_ref`: `adapt/extend/infrastructure/test_add_bulkhead_isolation.py`
  - **Delete reason:** Redundant with core/venous/*/Bulkhead/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete Bulkhead`

### 4. [ ] `CostTracker` (resiliency)

  - **Rationale:** Duplicate of registered primitive `CostTracker`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=72 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=CostTracker · score=882552
  - **Signals:** `tool_import`: `adapt/extend/infrastructure/add_cost_tracker.py` · `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Delete reason:** Redundant with core/venous/*/CostTracker/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete CostTracker`

### 5. [ ] `GracefulShutdown` (resiliency)

  - **Rationale:** Duplicate of registered primitive `GracefulShutdown`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=y · mutable=y · tests=y · dup_of=GracefulShutdown · score=870688
  - **Signals:** `tool_import`: `adapt/extend/infrastructure/add_graceful_shutdown.py` · `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Delete reason:** Redundant with core/venous/*/GracefulShutdown/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete GracefulShutdown`

### 6. [ ] `LoadShedder` (resiliency)

  - **Rationale:** Duplicate of registered primitive `LoadShedder`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=76 · tla=n · concurrency=n · mutable=y · tests=y · dup_of=LoadShedder · score=521472
  - **Signals:** `tool_import`: `adapt/extend/infrastructure/add_load_shedding.py` · `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Delete reason:** Redundant with core/venous/*/LoadShedder/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete LoadShedder`

### 7. [ ] `SchemaComparator` (extras)

  - **Rationale:** Duplicate of registered primitive `SchemaComparator`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=119 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=SchemaComparator · score=1737400
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_evolution_guard.py`
  - **Delete reason:** Redundant with core/venous/*/SchemaComparator/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete SchemaComparator`

### 8. [ ] `ExcelExporter` (resiliency)

  - **Rationale:** Duplicate of registered primitive `ExcelExporter`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=5 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=ExcelExporter · score=392880
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_excel_export.py`
  - **Delete reason:** Redundant with core/venous/*/ExcelExporter/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete ExcelExporter`

### 9. [ ] `ModelRegistry` (resiliency)

  - **Rationale:** Duplicate of registered primitive `ModelRegistry`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=5 · loc=84 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=ModelRegistry · score=260560
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_server.py`
  - **Delete reason:** Redundant with core/venous/*/ModelRegistry/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete ModelRegistry`

### 10. [ ] `Redactor` (resiliency)

  - **Rationale:** Duplicate of registered primitive `Redactor`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=Redactor · score=5800
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_structured_logging.py`
  - **Delete reason:** Redundant with core/venous/*/Redactor/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete Redactor`

### 11. [ ] `RequestContext` (resiliency)

  - **Rationale:** Duplicate of registered primitive `RequestContext`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=RequestContext · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Delete reason:** Redundant with core/venous/*/RequestContext/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete RequestContext`

### 12. [ ] `RetryBudget` (resiliency)

  - **Rationale:** Duplicate of registered primitive `RetryBudget`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=108 · tla=n · concurrency=y · mutable=n · tests=y · dup_of=RetryBudget · score=1036224
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_retry_budget.py`
  - **Delete reason:** Redundant with core/venous/*/RetryBudget/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete RetryBudget`

### 13. [ ] `TracingBuffer` (resiliency)

  - **Rationale:** Duplicate of registered primitive `TracingBuffer`. Staged copy adds no value; registered canonical version already ships.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · dup_of=TracingBuffer · score=315840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Delete reason:** Redundant with core/venous/*/TracingBuffer/ (same name; registered version is canonical).
  - **Run:** `python -m engine.promotion.promote --delete TracingBuffer`

---

## Needs human review (ambiguous state) — 1 primitive(s)

Classifier found strong signals but the shell is incomplete (REPLACE_ME markers or stub tests). Each entry lists blockers that a human must resolve before the classifier can upgrade the verdict to PROMOTE_*.

### 1. [ ] `Event` (data)

  - **Rationale:** Caller exists (1 signal(s)), but shell incomplete: 7 REPLACE_ME marker(s) + stubbed invariants. Fill placeholders and write real invariant tests before promotion.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=4908
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py` · `benchmark_ref`: `benchmarks/specs/mid/03_event_sourced_orders.md`
  - Blockers:
    - Resolve 7 REPLACE_ME marker(s) across the primitive tree (invariant text, stub tests).
    - Implement the three invariant tests (confirms / prevents / under_failure) with real assertions.

---

## Keep staged (awaiting signal or re-extraction) — 228 primitive(s)

No current §A12(b) signal, OR signal present but the shell requires re-extraction. Leave in `_extracted/` with the recorded staging_reason. Each entry's `staging_reason` line documents why the primitive stays put.

### 1. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8384
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_deprecation.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_api_deprecation.py`. Re-extract or waive the gate rule that rejected it.

### 2. [ ] `DeprecationMiddleware` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=8384
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_deprecation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_deprecation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 3. [ ] `GitHubVerifier` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=28144
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_receiver.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 4. [ ] `InternalVerifier` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=175744
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_receiver.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 5. [ ] `PubSubManager` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_graphql_subscriptions.py`. Re-extract or waive the gate rule that rejected it.

### 6. [ ] `PubSubManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=85200
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_graphql_subscriptions.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 7. [ ] `ReadReplicaSession` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=7264
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_cqrs.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_cqrs.py`. Re-extract or waive the gate rule that rejected it.

### 8. [ ] `ReadReplicaSession` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=7264
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_cqrs.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_cqrs.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 9. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_graphql_subscriptions.py`. Re-extract or waive the gate rule that rejected it.

### 10. [ ] `RedisPubSubBackend` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=y · tests=y · score=123776
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_graphql_subscriptions.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_graphql_subscriptions.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 11. [ ] `SignatureHeader` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=1940
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 12. [ ] `StripeVerifier` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=41 · tla=n · concurrency=n · mutable=n · tests=y · score=35140
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_receiver.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 13. [ ] `TaskManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=151 · tla=n · concurrency=n · mutable=n · tests=y · score=999520
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 14. [ ] `TaskRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=113280
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 15. [ ] `TokenBucket` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=y · mutable=y · tests=y · score=20160
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_sse.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_sse.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 16. [ ] `UserPresence` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=4044
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_presence.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_websocket_presence.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 17. [ ] `VerifiedEvent` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1560
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_receiver.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_receiver.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 18. [ ] `VersionInfo` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=4020
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 19. [ ] `VersionRegistry` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=23800
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 20. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=75000
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `api_design/add_api_versioning.py`. Re-extract or waive the gate rule that rejected it.

### 21. [ ] `VersionResolverMiddleware` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=48 · tla=n · concurrency=n · mutable=n · tests=y · score=75000
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_api_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_api_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 22. [ ] `WebSocketManager` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=113 · tla=n · concurrency=y · mutable=n · tests=y · score=1125800
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_websocket_chat.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_websocket_chat.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 23. [ ] `WebhookDelivery` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=7516
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 24. [ ] `WebhookEndpoint` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=7948
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 25. [ ] `WebhookEndpointCreated` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/realtime/add_webhook_sender.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`realtime/add_webhook_sender.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 26. [ ] `WorkerSettings` (api)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2496
  - **Signals:** `generator_ref`: `adapt/extend/api_design/add_long_running_task.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`api_design/add_long_running_task.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 27. [ ] `APIKey` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9420
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_api_key_auth.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 28. [ ] `CedarAuthzMiddleware` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=72 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=167700
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_cedar_policies.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_cedar_policies.py`. Re-extract or waive the gate rule that rejected it.

### 29. [ ] `CedarEngine` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=71 · tla=n · concurrency=n · mutable=y · tests=y · score=176520
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_cedar_policies.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_cedar_policies.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 30. [ ] `FeatureFlag` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=11324
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 31. [ ] `FeatureFlagAudit` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=5472
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 32. [ ] `FeatureFlagPublic` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1576
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 33. [ ] `FeatureToggleService` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_feature_toggles_api.py`. Re-extract or waive the gate rule that rejected it.

### 34. [ ] `FeatureToggleService` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=n · mutable=n · tests=y · score=491904
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_toggles_api.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_toggles_api.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 35. [ ] `FlagContext` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3204
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_feature_flags.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_feature_flags.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 36. [ ] `MFADevice` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6996
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_mfa.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_mfa.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 37. [ ] `MFARecoveryCode` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=3728
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_mfa.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_mfa.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 38. [ ] `OAuthAccount` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=8632
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 39. [ ] `OAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=20940
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 40. [ ] `OAuthTokens` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1628
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 41. [ ] `OAuthUserInfo` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=1788
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_oauth2_provider.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_oauth2_provider.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 42. [ ] `OPAMiddleware` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=12792
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_opa_integration.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_opa_integration.py`. Re-extract or waive the gate rule that rejected it.

### 43. [ ] `OPAMiddleware` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=12792
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_opa_integration.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_opa_integration.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 44. [ ] `OtpCode` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=4440
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_sms_otp.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_sms_otp.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 45. [ ] `OwnershipVerifier` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200016
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_bola_guard.py`. Re-extract or waive the gate rule that rejected it.

### 46. [ ] `Passkey` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6456
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_passkey_auth.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_passkey_auth.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 47. [ ] `Permission` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=3548
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 48. [ ] `PermissionCache` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=99 · tla=n · concurrency=y · mutable=y · tests=y · score=1065168
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 49. [ ] `RequestSigningMiddleware` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=101920
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_request_signing.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_request_signing.py`. Re-extract or waive the gate rule that rejected it.

### 50. [ ] `ResourceAccessPolicy` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=14352
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_bola_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 51. [ ] `RoleNode` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 52. [ ] `RolePermission` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=3300
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_rbac.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_rbac.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 53. [ ] `ScopeCheckResult` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=16 · tla=n · concurrency=n · mutable=n · tests=y · score=1408
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_api_key_auth.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_api_key_auth.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 54. [ ] `SocialAccount` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=6648
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_social_login.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 55. [ ] `SocialAuthProvider` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=70 · tla=n · concurrency=n · mutable=n · tests=y · score=144336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_social_login.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_social_login.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 56. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8856
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_bola_guard.py`. Re-extract or waive the gate rule that rejected it.

### 57. [ ] `TenantIsolationFilter` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=8856
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_bola_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_bola_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 58. [ ] `TenantMiddleware` (auth)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=67 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=258336
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_multi_tenancy.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `auth_access/add_multi_tenancy.py`. Re-extract or waive the gate rule that rejected it.

### 59. [ ] `TenantScopedMixin` (auth)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2252
  - **Signals:** `generator_ref`: `adapt/extend/auth_access/add_multi_tenancy.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`auth_access/add_multi_tenancy.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 60. [ ] `AuditLog` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=11676
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_audit_log.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 61. [ ] `ContentVersion` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=7204
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 62. [ ] `CursorPaginator` (data)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=880488
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_cursor_pagination.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `crud_data/add_cursor_pagination.py`. Re-extract or waive the gate rule that rejected it.

### 63. [ ] `CursorPaginator` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=126 · tla=n · concurrency=n · mutable=n · tests=y · score=880488
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_cursor_pagination.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_cursor_pagination.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 64. [ ] `EventStore` (data)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=198520
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `crud_data/add_event_sourcing.py`. Re-extract or waive the gate rule that rejected it.

### 65. [ ] `EventStore` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=107 · tla=n · concurrency=n · mutable=n · tests=y · score=198520
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_event_sourcing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 66. [ ] `ImportJob` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=6924
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_import.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 67. [ ] `ImportProcessor` (data)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=200580
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `crud_data/add_data_import.py`. Re-extract or waive the gate rule that rejected it.

### 68. [ ] `ImportProcessor` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · score=200580
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_import.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_import.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 69. [ ] `LocalStorage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=78 · tla=n · concurrency=y · mutable=n · tests=y · score=247680
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 70. [ ] `LocalStorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=24064
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_export.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_export.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 71. [ ] `Projector` (data)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=y · tests=y · quarantined · score=112600
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_event_sourcing.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `crud_data/add_event_sourcing.py`. Re-extract or waive the gate rule that rejected it.

### 72. [ ] `S3Storage` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=47 · tla=n · concurrency=n · mutable=n · tests=y · score=19800
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 73. [ ] `SoftDeleteMixin` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=12612
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_soft_delete.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_soft_delete.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 74. [ ] `StorageBackend` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=12828
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_file_upload.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_file_upload.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 75. [ ] `VerificationResult` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=1960
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_audit_log.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_audit_log.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 76. [ ] `VersioningService` (data)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=2873280
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `crud_data/add_data_versioning.py`. Re-extract or waive the gate rule that rejected it.

### 77. [ ] `VersioningService` (data)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=200 · tla=n · concurrency=n · mutable=n · tests=y · score=2873280
  - **Signals:** `generator_ref`: `adapt/extend/crud_data/add_data_versioning.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`crud_data/add_data_versioning.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 78. [ ] `APIFuzzer` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=y · tests=y · score=153152
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 79. [ ] `ActiveUserScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=12648
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 80. [ ] `AdminScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 81. [ ] `AuthMixin` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=40400
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 82. [ ] `BrowsingScenario` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=29064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_load_profile.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_load_profile.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 83. [ ] `ComparisonResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=3088
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_evolution_guard.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_schema_evolution_guard.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 84. [ ] `DataSeeder` (extras)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=110064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `testing_tools/add_data_seeder.py`. Re-extract or waive the gate rule that rejected it.

### 85. [ ] `DataSeeder` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · score=110064
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 86. [ ] `DependencyGraph` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=89 · tla=n · concurrency=n · mutable=n · tests=y · score=694096
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 87. [ ] `FieldGenerator` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=140 · tla=n · concurrency=n · mutable=n · tests=y · score=2991816
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_data_seeder.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_data_seeder.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 88. [ ] `FuzzResult` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=38328
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 89. [ ] `FuzzRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=328992
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_api_fuzzer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_api_fuzzer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 90. [ ] `MigrationCIRunner` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=83 · tla=n · concurrency=n · mutable=n · tests=y · score=76600
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_database_migrations_ci.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 91. [ ] `SafetyChecker` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=62 · tla=n · concurrency=n · mutable=n · tests=y · score=262080
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_database_migrations_ci.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_database_migrations_ci.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 92. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=27520
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_enforcer.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `testing_tools/add_schema_enforcer.py`. Re-extract or waive the gate rule that rejected it.

### 93. [ ] `SchemaEnforcerMiddleware` (extras)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=27520
  - **Signals:** `generator_ref`: `adapt/extend/testing_tools/add_schema_enforcer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`testing_tools/add_schema_enforcer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 94. [ ] `APICostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4240
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 95. [ ] `APNsProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21636
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 96. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=21408
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_throttle.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_adaptive_throttle.py`. Re-extract or waive the gate rule that rejected it.

### 97. [ ] `AdaptiveThrottleMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=21408
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_throttle.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_throttle.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 98. [ ] `AdaptiveTimeout` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=y · tests=y · score=170940
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_timeouts.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 99. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=181296
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_sqladmin.py`. Re-extract or waive the gate rule that rejected it.

### 100. [ ] `AdminAuthBackend` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=73 · tla=n · concurrency=n · mutable=n · tests=y · score=181296
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_sqladmin.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 101. [ ] `AlertDispatcher` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=32736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 102. [ ] `AnomalyDetector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=116964
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 103. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=29760
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_anomaly_detector.py`. Re-extract or waive the gate rule that rejected it.

### 104. [ ] `AnomalyMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=35 · tla=n · concurrency=y · mutable=n · tests=y · score=29760
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_anomaly_detector.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_anomaly_detector.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 105. [ ] `AttackPatternRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=60 · tla=n · concurrency=n · mutable=y · tests=y · score=75776
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_runtime_sentinel.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 106. [ ] `AwsSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=y · tests=y · score=82752
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 107. [ ] `BulkheadConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4256
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_bulkhead_isolation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 108. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_bulkhead_isolation.py`. Re-extract or waive the gate rule that rejected it.

### 109. [ ] `BulkheadMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=16116
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_bulkhead_isolation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_bulkhead_isolation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 110. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10128
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cors_config.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_cors_config.py`. Re-extract or waive the gate rule that rejected it.

### 111. [ ] `CORSConfigMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=29 · tla=n · concurrency=n · mutable=n · tests=y · score=10128
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cors_config.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cors_config.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 112. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=135072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_csrf_protection.py`. Re-extract or waive the gate rule that rejected it.

### 113. [ ] `CSRFMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=78 · tla=n · concurrency=n · mutable=n · tests=y · score=135072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_csrf_protection.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 114. [ ] `CSRFProtection` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=92 · tla=n · concurrency=n · mutable=n · tests=y · score=269920
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_csrf_protection.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_csrf_protection.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 115. [ ] `CacheBackend` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=79 · tla=n · concurrency=n · mutable=n · tests=y · score=414000
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cache_layer.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cache_layer.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 116. [ ] `CanaryRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=18312
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_canary_tokens.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 117. [ ] `CanaryToken` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=2732
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_canary_tokens.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_canary_tokens.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 118. [ ] `ChaosEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=58 · tla=n · concurrency=n · mutable=y · tests=y · score=95200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 119. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10992
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_chaos_testing.py`. Re-extract or waive the gate rule that rejected it.

### 120. [ ] `ChaosMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=39 · tla=n · concurrency=n · mutable=n · tests=y · score=10992
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 121. [ ] `ComplianceEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=77360
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_compliance_engine.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 122. [ ] `ComplianceEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=5072
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_compliance_engine.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_compliance_engine.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 123. [ ] `ConfigureBillingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6056
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 124. [ ] `CostEstimate` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=1852
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 125. [ ] `CostEstimatorProtocol` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=2952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 126. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=41952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_cost_tracker.py`. Re-extract or waive the gate rule that rejected it.

### 127. [ ] `CostMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=41952
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 128. [ ] `CreateAdminUserStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=7048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 129. [ ] `CreateTenantStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=20 · tla=n · concurrency=n · mutable=n · tests=y · score=5536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 130. [ ] `DBQueryCostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=4272
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 131. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=64160
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_dlp_shield.py`. Re-extract or waive the gate rule that rejected it.

### 132. [ ] `DLPMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · score=64160
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dlp_shield.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 133. [ ] `DegradationManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=y · tests=y · score=28720
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_load_shedding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 134. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=23772
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_transactional_email.py`. Re-extract or waive the gate rule that rejected it.

### 135. [ ] `DeliveryTracker` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=44 · tla=n · concurrency=n · mutable=n · tests=y · score=23772
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_transactional_email.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 136. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=809472
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_dependency_health_map.py`. Re-extract or waive the gate rule that rejected it.

### 137. [ ] `DependencyChecker` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=101 · tla=n · concurrency=y · mutable=n · tests=y · score=809472
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dependency_health_map.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 138. [ ] `DeviceManager` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=y · tests=y · score=246708
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_gpu_inference.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 139. [ ] `DeviceToken` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=13 · tla=n · concurrency=n · mutable=n · tests=y · score=2460
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 140. [ ] `EmailEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=14 · tla=n · concurrency=n · mutable=n · tests=y · score=2068
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_transactional_email.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 141. [ ] `EmailProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=2024
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 142. [ ] `EnvSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=30 · tla=n · concurrency=n · mutable=n · tests=y · score=6528
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 143. [ ] `ErrorInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=6832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 144. [ ] `FCMProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=51 · tla=n · concurrency=n · mutable=n · tests=y · score=69600
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 145. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=513504
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_request_fingerprint.py`. Re-extract or waive the gate rule that rejected it.

### 146. [ ] `FingerprintMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=74 · tla=n · concurrency=n · mutable=n · tests=y · score=513504
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 147. [ ] `FingerprintStore` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=37 · tla=n · concurrency=n · mutable=n · tests=y · score=32640
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 148. [ ] `HealthMapBuilder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=54 · tla=n · concurrency=y · mutable=n · tests=y · score=122816
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dependency_health_map.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dependency_health_map.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 149. [ ] `HealthRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=87 · tla=n · concurrency=y · mutable=n · tests=y · score=209832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_health_deep.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_health_deep.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 150. [ ] `InputSanitizer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=35088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_input_sanitization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 151. [ ] `Job` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9404
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 152. [ ] `JobStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2088
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 153. [ ] `LatencyInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=y · mutable=n · tests=y · score=4968
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 154. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=91200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_secret_rotation.py`. Re-extract or waive the gate rule that rejected it.

### 155. [ ] `LeakDetectorMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=55 · tla=n · concurrency=n · mutable=n · tests=y · score=91200
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 156. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=11544
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_load_shedding.py`. Re-extract or waive the gate rule that rejected it.

### 157. [ ] `LoadSheddingMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=11544
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_load_shedding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_load_shedding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 158. [ ] `MLModel` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=31 · tla=n · concurrency=n · mutable=n · tests=y · score=7364
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_model_registry.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 159. [ ] `MODEL_NAMEAdmin` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=11 · tla=n · concurrency=n · mutable=n · tests=y · score=1608
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_sqladmin.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_sqladmin.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 160. [ ] `MemoryGuard` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=60 · tla=n · concurrency=n · mutable=n · tests=y · score=159696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_gpu_inference.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_gpu_inference.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 161. [ ] `MeterEventBuffer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=n · mutable=y · tests=y · score=14208
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_monetization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 162. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45384
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_api_monetization.py`. Re-extract or waive the gate rule that rejected it.

### 163. [ ] `MeteringMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=45384
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_monetization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 164. [ ] `Notification` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=4868
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_notifications.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 165. [ ] `NotificationService` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=45648
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_notifications.py`. Re-extract or waive the gate rule that rejected it.

### 166. [ ] `NotificationService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=45648
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_notifications.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_notifications.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 167. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=31632
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_opentelemetry.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_opentelemetry.py`. Re-extract or waive the gate rule that rejected it.

### 168. [ ] `OTELMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=52 · tla=n · concurrency=n · mutable=n · tests=y · score=31632
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_opentelemetry.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_opentelemetry.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 169. [ ] `OnboardingOrchestrator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=68 · tla=n · concurrency=n · mutable=n · tests=y · score=207424
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 170. [ ] `OnboardingProgress` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=23 · tla=n · concurrency=n · mutable=n · tests=y · score=8904
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 171. [ ] `OnboardingStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=5148
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 172. [ ] `OutboxDlq` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=3920
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_outbox_pattern.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 173. [ ] `OutboxEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=38 · tla=n · concurrency=n · mutable=n · tests=y · score=9324
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_outbox_pattern.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 174. [ ] `OutboxService` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=30672
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_outbox_pattern.py`. Re-extract or waive the gate rule that rejected it.

### 175. [ ] `OutboxService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=30672
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_outbox_pattern.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_outbox_pattern.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 176. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=8704
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_prometheus_metrics.py`. Re-extract or waive the gate rule that rejected it.

### 177. [ ] `PrometheusMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=32 · tla=n · concurrency=n · mutable=n · tests=y · score=8704
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_prometheus_metrics.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 178. [ ] `PushService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=31264
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_push_notifications_native.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_push_notifications_native.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 179. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=186420
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_api_replay_debugger.py`. Re-extract or waive the gate rule that rejected it.

### 180. [ ] `RecorderMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=63 · tla=n · concurrency=y · mutable=n · tests=y · score=186420
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 181. [ ] `Refund` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=28 · tla=n · concurrency=n · mutable=n · tests=y · score=7144
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_refund_flow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 182. [ ] `RefundStatus` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=15 · tla=n · concurrency=n · mutable=n · tests=y · score=1356
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_refund_flow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_refund_flow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 183. [ ] `RegistryService` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=119280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_ml_model_registry.py`. Re-extract or waive the gate rule that rejected it.

### 184. [ ] `RegistryService` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=110 · tla=n · concurrency=n · mutable=n · tests=y · score=119280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_ml_model_registry.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_ml_model_registry.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 185. [ ] `ReportEngine` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=82 · tla=n · concurrency=y · mutable=n · tests=y · score=97440
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_pdf_reports.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_pdf_reports.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 186. [ ] `RequestFingerprinter` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=56 · tla=n · concurrency=n · mutable=n · tests=y · score=61280
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_fingerprint.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_fingerprint.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 187. [ ] `RequestMetrics` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=y · tests=y · score=78948
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_prometheus_metrics.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_prometheus_metrics.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 188. [ ] `RequestRecorder` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=105 · tla=n · concurrency=n · mutable=n · tests=y · score=733320
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 189. [ ] `RequestReplayer` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=43 · tla=n · concurrency=n · mutable=n · tests=y · score=33536
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_replay_debugger.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_replay_debugger.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 190. [ ] `ResendProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=22 · tla=n · concurrency=n · mutable=n · tests=y · score=4628
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 191. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=175120
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_response_armor.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_response_armor.py`. Re-extract or waive the gate rule that rejected it.

### 192. [ ] `ResponseArmorMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=61 · tla=n · concurrency=n · mutable=n · tests=y · score=175120
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_response_armor.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_response_armor.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 193. [ ] `S3Client` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=81 · tla=n · concurrency=n · mutable=n · tests=y · score=86736
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 194. [ ] `S3CostEstimator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=4480
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_cost_tracker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_cost_tracker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 195. [ ] `SMTPProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=12 · tla=n · concurrency=y · mutable=n · tests=y · score=1452
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 196. [ ] `Saga` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=24496
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_saga.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 197. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · quarantined · score=706944
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_saga.py`. Re-extract or waive the gate rule that rejected it.

### 198. [ ] `SagaCoordinator` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=117 · tla=n · concurrency=y · mutable=n · tests=y · score=706944
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_saga.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 199. [ ] `SagaInstance` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=7696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_saga.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 200. [ ] `SagaStepExecution` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=7104
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_saga.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_saga.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 201. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=88956
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_input_sanitization.py`. Re-extract or waive the gate rule that rejected it.

### 202. [ ] `SanitizeMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=69 · tla=n · concurrency=n · mutable=n · tests=y · score=88956
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_input_sanitization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_input_sanitization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 203. [ ] `SchedulerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=11152
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_scheduled_tasks.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_scheduled_tasks.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 204. [ ] `SecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=45 · tla=n · concurrency=n · mutable=n · tests=y · score=16008
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 205. [ ] `SecurityEvent` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=24 · tla=n · concurrency=n · mutable=n · tests=y · score=2604
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_runtime_sentinel.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_runtime_sentinel.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 206. [ ] `SeedDataStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=5696
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 207. [ ] `SendWelcomeEmailStep` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=18 · tla=n · concurrency=n · mutable=n · tests=y · score=6048
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_tenant_onboarding.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_tenant_onboarding.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 208. [ ] `SendgridProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=5 · loc=35 · tla=n · concurrency=n · mutable=n · tests=y · score=12400
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_transactional_email.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_transactional_email.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 209. [ ] `SensitivePattern` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=17 · tla=n · concurrency=n · mutable=n · tests=y · score=1268
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_dlp_shield.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_dlp_shield.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 210. [ ] `ShutdownHealthGate` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=26 · tla=n · concurrency=n · mutable=n · tests=y · score=7616
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_graceful_shutdown.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 211. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=10792
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_graceful_shutdown.py`. Re-extract or waive the gate rule that rejected it.

### 212. [ ] `ShutdownMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=33 · tla=n · concurrency=n · mutable=n · tests=y · score=10792
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_graceful_shutdown.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_graceful_shutdown.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 213. [ ] `StorageConfig` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=34 · tla=n · concurrency=n · mutable=n · tests=y · score=5788
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 214. [ ] `StripeBilling` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_stripe_subscription.py`. Re-extract or waive the gate rule that rejected it.

### 215. [ ] `StripeBilling` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=96 · tla=n · concurrency=n · mutable=n · tests=y · score=85656
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_stripe_subscription.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_stripe_subscription.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 216. [ ] `TemplateName` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=19 · tla=n · concurrency=n · mutable=n · tests=y · score=2244
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_email_templates.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_email_templates.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 217. [ ] `TemporalClientFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=42 · tla=n · concurrency=n · mutable=n · tests=y · score=11624
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_temporal_workflow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 218. [ ] `TimeoutInjector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=27 · tla=n · concurrency=y · mutable=n · tests=y · score=7832
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_chaos_testing.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_chaos_testing.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 219. [ ] `TimeoutRegistry` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=49 · tla=n · concurrency=n · mutable=n · tests=y · score=31376
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_adaptive_timeouts.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_adaptive_timeouts.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 220. [ ] `TimingCollector` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=57 · tla=n · concurrency=n · mutable=n · tests=y · score=31740
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_tracing_ui.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 221. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=29040
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_request_tracing_ui.py`. Re-extract or waive the gate rule that rejected it.

### 222. [ ] `TracingMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=29040
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_request_tracing_ui.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_request_tracing_ui.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 223. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** Quarantined (no explicit reason recorded; physical location in _quarantine/ indicates extraction-gate rejection). Not immediately promotable; requires re-extraction from the origin tool OR an explicit extraction-gate rule waiver before it can advance.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · quarantined · score=51840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** Physically quarantined under _extracted/_quarantine/. Extracted from `infrastructure/add_s3_storage.py`. Re-extract or waive the gate rule that rejected it.

### 224. [ ] `UploadSizeMiddleware` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=46 · tla=n · concurrency=n · mutable=n · tests=y · score=51840
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_s3_storage.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_s3_storage.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 225. [ ] `UsageRecord` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=21 · tla=n · concurrency=n · mutable=n · tests=y · score=4596
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_api_monetization.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_api_monetization.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 226. [ ] `VaultSecretProvider` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=59 · tla=n · concurrency=n · mutable=y · tests=y · score=96576
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_secret_rotation.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_secret_rotation.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 227. [ ] `WorkerFactory` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=40 · tla=n · concurrency=n · mutable=n · tests=y · score=12552
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_temporal_workflow.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_temporal_workflow.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

### 228. [ ] `WorkerSettings` (resiliency)

  - **Rationale:** No registered tool / module / benchmark spec currently imports or references this primitive. §A12(b) gate not met; leave staged until a caller appears.
  - **State:** REPLACE_ME=7 · loc=25 · tla=n · concurrency=n · mutable=n · tests=y · score=3932
  - **Signals:** `generator_ref`: `adapt/extend/infrastructure/add_arq_worker.py`
  - **Staging reason:** No §A12(b) signal yet. Primitive was extracted from a tool (`infrastructure/add_arq_worker.py`) but no current caller declares it in imports_primitives or imports from core.venous. Will re-evaluate on the next triage pass.

---
