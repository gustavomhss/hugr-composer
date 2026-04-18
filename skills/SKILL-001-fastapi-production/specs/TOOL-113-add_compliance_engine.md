# TOOL-113: add_compliance_engine

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_compliance_engine` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, cryptography (lazy) |
| Signature | `add_compliance_engine(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_compliance_engine", "description": "Add declarative data-governance at ORM level: PII detection, retention enforcer, right-to-erasure endpoint, Fernet field encryption, access logging, SOC2 exporter, GDPR Article 30 generator, and Alembic migration.", "tags": ["extend", "infrastructure"], "entry": "add_compliance_engine"}` |
| Files created (typical) | 7 — `app/core/compliance_engine.py`, `app/models/compliance_event.py`, `app/schemas/compliance.py`, `app/crud/compliance.py`, `app/api/routes/compliance.py`, `app/workers/retention_worker.py`, `alembic/versions/add_compliance_engine.py` |
| Files modified (typical) | 4 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_compliance_engine` tool installs a production-grade, declarative data-governance layer into an existing FastAPI project. It solves the compliance scaffold problem: every serious SaaS eventually needs GDPR right-to-erasure (`DELETE /compliance/erasure/{user_id}`), SOC2-auditable event logs, a GDPR Article 30 record-of-processing document, and field-level encryption for PII — but assembling these by hand from primitives is slow, error-prone, and consistently under-tested. The tool generates the entire compliance surface in a single invocation.

**Core components generated:**

`app/core/compliance_engine.py` is the central engine. It contains a `ComplianceEngine` class that orchestrates the full data-governance lifecycle: a column-name/type heuristic registry that auto-detects PII fields (e.g. columns named `email`, `phone`, `ssn`, `dob`), Fernet symmetric-encryption helpers (`encrypt_field` / `decrypt_field`) that wrap `cryptography.fernet.Fernet` behind a lazy import so the app boots without the library on machines where GDPR features are toggled off, and a `RetentionPolicy` dataclass that ties a model class to a `retention_days` window and a `delete_mode` (`SOFT` or `HARD`).

`app/models/compliance_event.py` is an append-only SQLAlchemy audit model (`ComplianceEvent`) that records every PII-touching operation: column, action, actor, timestamp, and request correlation ID. The table intentionally lacks an `UPDATE` semantic — rows are insert-only so audit trails cannot be tampered with post-fact.

`app/api/routes/compliance.py` exposes three HTTP routes: `DELETE /compliance/erasure/{user_id}` implements the GDPR Article 17 right-to-erasure by cascading anonymisation across all registered PII models, writing a signed `ErasureCertificate` to the `compliance_events` table and returning it to the caller; `GET /compliance/evidence/soc2` exports the last N `ComplianceEvent` rows formatted for a SOC2 Type II evidence package; `GET /compliance/article30` auto-generates a machine-readable GDPR Article 30 record-of-processing from the PII registry, listing data category, purpose, retention period, and processing basis for each detected field.

`app/workers/retention_worker.py` runs as a coroutine started by `schedule_retention_worker(app)` inside the FastAPI lifespan. It wakes every `COMPLIANCE_RETENTION_DEFAULT_DAYS` hours, scans registered retention policies, and soft-deletes or hard-deletes rows past their retention window. Using `asyncio.sleep` for the loop cadence keeps it off the FastAPI event loop without requiring a separate process.

The tool patches `app/core/config.py` with three `COMPLIANCE_*` fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`, registers `ComplianceEvent` in `app/models/__init__.py`, registers the compliance router in `app/routes/__init__.py`, adds `cryptography>=42.0.0` to `requirements.txt`, and generates an Alembic migration chained to the current migration head.

Idempotency fingerprint: `"ComplianceEngine" in app/core/compliance_engine.py` → `status="no_op"`. Cryptography is imported **lazily** inside `encrypt_field` / `decrypt_field` so the app boots cleanly on machines without the package.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` |
| Files created | ≥ 6 | Engine, model, schemas, CRUD, routes, retention worker (migration optional if no alembic dir) |
| Files modified | ≥ 2 | Config + at least one of: models init, routes init, requirements |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree |
| `DELETE /compliance/erasure/{user_id}` latency | < 200 ms | Bounded by number of PII models; cascades within single DB transaction |
| `GET /compliance/evidence/soc2` latency | < 100 ms | Single paginated query against `compliance_events` |
| `GET /compliance/article30` latency | < 10 ms | Pure in-process PII registry scan — no DB query |
| Retention worker cycle | ≤ `COMPLIANCE_RETENTION_DEFAULT_DAYS * 24 * 3600` s | Cadence driven by `asyncio.sleep` |
| Fernet encrypt/decrypt | < 1 ms | Single AES-128-CBC operation per field |
| Migration runtime | < 1 s | Single `CREATE TABLE` + indexes |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/config.py          # Settings class, no COMPLIANCE_* fields
│   ├── models/
│   │   ├── __init__.py         # Base + User imports only
│   │   └── base.py
│   └── routes/__init__.py      # api_router, no compliance router
├── alembic/versions/
└── requirements.txt            # no cryptography
```

No PII is detected or encrypted. No audit log records data access. No erasure capability exists. SOC2 auditors have no evidence package. GDPR Article 30 record requires manual maintenance.

### 4.2 Compliance engine core: AFTER

```python
# app/core/compliance_engine.py  (excerpt)
class ComplianceEngine:
    """Central compliance orchestrator.

    Attributes:
        _pii_registry: Mapping of model class to detected PII field names.
        _retention_policies: Active retention policies per model.
    """

    def __init__(self) -> None:
        self._pii_registry: dict[type, list[str]] = {}
        self._retention_policies: list[RetentionPolicy] = []

    def register_model(self, model_cls: type, retention_days: int = 365) -> None:
        """Scan model_cls for PII columns and register a retention policy."""
        pii_fields = _detect_pii_columns(model_cls)
        self._pii_registry[model_cls] = pii_fields
        self._retention_policies.append(
            RetentionPolicy(model=model_cls, retention_days=retention_days)
        )

    def encrypt_field(self, value: str) -> str:
        """Fernet-encrypt value using COMPLIANCE_ENCRYPTION_KEY (lazy import)."""
        from cryptography.fernet import Fernet  # lazy import
        key = settings.COMPLIANCE_ENCRYPTION_KEY.encode()
        return Fernet(key).encrypt(value.encode()).decode()

    def decrypt_field(self, token: str) -> str:
        """Fernet-decrypt token using COMPLIANCE_ENCRYPTION_KEY (lazy import)."""
        from cryptography.fernet import Fernet  # lazy import
        key = settings.COMPLIANCE_ENCRYPTION_KEY.encode()
        return Fernet(key).decrypt(token.encode()).decode()
```

### 4.3 Right-to-erasure endpoint: AFTER

```python
# app/api/routes/compliance.py  (excerpt)
@router.delete(
    "/erasure/{user_id}",
    response_model=ErasureCertificate,
    status_code=200,
    summary="GDPR Article 17 right-to-erasure",
)
async def erase_user_data(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(),
) -> ErasureCertificate:
    """Cascade anonymisation across all registered PII models.

    Writes a signed ErasureCertificate to compliance_events.
    """
    cert = await crud_compliance.cascade_anonymise(db, user_id)
    return cert
```

### 4.4 Config patch: AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- Compliance engine — added by add_compliance_engine tool ---
    COMPLIANCE_ENABLED: bool = True
    COMPLIANCE_RETENTION_DEFAULT_DAYS: int = 365
    COMPLIANCE_ENCRYPTION_KEY: str = ""  # Fernet key (base64url, 32 bytes)
```

### 4.5 Retention worker: AFTER

```python
# app/workers/retention_worker.py  (excerpt)
async def run_retention_cycle(db_session_factory: Any) -> int:
    """Run one retention enforcement cycle. Returns rows deleted/anonymised."""
    engine = get_compliance_engine()
    deleted = 0
    async with db_session_factory() as db:
        for policy in engine.retention_policies:
            deleted += await _enforce_policy(db, policy)
    return deleted

async def schedule_retention_worker(app: Any) -> None:
    """Coroutine to schedule in FastAPI lifespan. Loops forever via asyncio.sleep."""
    while True:
        await asyncio.sleep(settings.COMPLIANCE_RETENTION_DEFAULT_DAYS * 86400)
        try:
            await run_retention_cycle(app.state.db_session_factory)
        except Exception:
            logger.error("retention_cycle_failed", exc_info=True)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | Tool is idempotent on second run | `"ComplianceEngine" in app/core/compliance_engine.py` → `status="no_op"` |
| QS-2 | `dry_run=True` writes zero files | Early return with notes before any write |
| QS-3 | Every generated `.py` AST-parses | `ast.parse` loop over `files_created` before returning success |
| QS-4 | No generated function exceeds 50 LOC | Enforced by AST walk in test T-07 |
| QS-5 | Fernet imported lazily | `from cryptography.fernet import Fernet` inside function body only |
| QS-6 | `COMPLIANCE_*` fields inside `class Settings` body | Anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-7 | `ComplianceEvent` registered in `app/models/__init__.py` | `_patch_models_init` appends import idempotently |
| QS-8 | Compliance router registered in `app/routes/__init__.py` | `_patch_routes_init` appends include idempotently |
| QS-9 | `cryptography>=42.0.0` in `requirements.txt` | `_patch_requirements` appends when absent |
| QS-10 | Alembic migration chained to current head | `find_migration_head(versions_dir)` used in `_write_migration` |
| QS-11 | `ErasureCertificate` returned from erasure endpoint | Pydantic schema in `app/schemas/compliance.py` |
| QS-12 | CRUD helpers are all `async def` | `_COMPLIANCE_CRUD_TEMPLATE` uses `async def` for all four helpers |
| QS-13 | Retention worker uses `asyncio.sleep` (not blocking sleep) | `asyncio.sleep` in `schedule_retention_worker` |
| QS-14 | SOC2 evidence + Article 30 routes present | `soc2` and `article30` paths in compliance routes |
| QS-15 | Prerequisites validated before any write | `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` |
| QS-16 | `execution_time_ms` set on every return path | `_elapsed_ms(start)` on success, no_op, dry_run, error |
| QS-17 | `next_steps` includes `alembic upgrade head` | Hard-coded string in success branch |
| QS-18 | Second run leaves project AST-parseable | Idempotency path touches no file |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_compliance_engine.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | CC-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | CC-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | CC-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 6 new files | `len(result.files_created) >= 6` and each path exists | CC-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | CC-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | CC-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | CC-07 (`test_no_function_over_50_loc`) |
| CC-08 | `COMPLIANCE_ENABLED`, `COMPLIANCE_RETENTION_DEFAULT_DAYS`, `COMPLIANCE_ENCRYPTION_KEY` exist inside `class Settings` with 4-space indent | String scan + indent check | CC-08 (`test_config_fields_patched`) |
| CC-09 | `ComplianceEvent` registered in `app/models/__init__.py` | `"ComplianceEvent" in content` | CC-09 (`test_models_init_patched`) |
| CC-10 | Compliance router registered in `app/routes/__init__.py` | `"compliance" in content.lower()` | CC-10 (`test_routes_registered`) |
| CC-11 | `app/core/compliance_engine.py` contains `ComplianceEngine`, `encrypt_field`, `decrypt_field` | File exists + substring checks | CC-11 (`test_compliance_engine_file_exists`) |
| CC-12 | `app/models/compliance_event.py` contains `class ComplianceEvent` with `event_type` column | File exists + `"class ComplianceEvent"` + `"event_type"` | CC-12 (`test_compliance_event_model_created`) |
| CC-13 | `app/crud/compliance.py` contains ≥ 4 `async def` helpers | `content.count("async def ") >= 4` | CC-13 (`test_compliance_crud_created`) |
| CC-14 | `app/api/routes/compliance.py` contains erasure endpoint with `ErasureCertificate` | `"erasure" in content.lower()` + `"ErasureCertificate" in content` | CC-14 (`test_erasure_route_present`) |
| CC-15 | `app/workers/retention_worker.py` contains `schedule_retention_worker` and `asyncio.sleep` | File exists + substring checks | CC-15 (`test_retention_worker_created`) |
| CC-16 | `cryptography` is NOT imported at module top level in `compliance_engine.py` | AST walk of top-level `ast.Import` / `ast.ImportFrom` nodes | CC-16 (`test_fernet_lazy_import`) |
| CC-17 | Compliance routes include GDPR Article 30 endpoint | `"article30" in content.lower()` | CC-17 (`test_article30_route_present`) |
| CC-18 | Compliance routes include SOC2 evidence export endpoint | `"soc2" in content.lower() or "evidence" in content.lower()` | CC-18 (`test_soc2_evidence_route_present`) |
| CC-19 | `requirements.txt` contains `cryptography` | `"cryptography" in requirements.read_text()` | CC-19 (`test_requirements_cryptography`) |
| CC-20 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | CC-20 (`test_execution_time_recorded`) |
| CC-21 | `next_steps` non-empty and mentions `alembic` | `"alembic" in joined.lower()` | CC-21 (`test_next_steps_present`) |
| CC-22 | Running tool twice leaves project AST-parseable | `ast.parse` over all `.py` after two runs | CC-22 (`test_idempotent_project_still_parses`) |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_compliance_engine.py`
- [ ] `add_compliance_engine.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint check `"ComplianceEngine" in engine_file.read_text()` → `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `cryptography` imported lazily inside `encrypt_field` / `decrypt_field`
- [ ] `COMPLIANCE_*` settings injected inside `class Settings` body (4-space indent)
- [ ] `ComplianceEvent` registered in `app/models/__init__.py` via `_patch_models_init`
- [ ] Compliance router registered in `app/routes/__init__.py` via `_patch_routes_init`
- [ ] `cryptography>=42.0.0` added to `requirements.txt`
- [ ] Alembic migration chained to current head via `find_migration_head`
- [ ] Erasure endpoint returns `ErasureCertificate` schema
- [ ] SOC2 evidence + Article 30 routes present
- [ ] CRUD helpers all `async def`, ≥ 4 functions
- [ ] Retention worker uses `asyncio.sleep` — never blocking
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-COMP-01 | Tool is ALWAYS idempotent on second invocation | `"ComplianceEngine" in engine_file.read_text()` short-circuits | CC-02, CC-22 |
| INV-COMP-02 | `dry_run=True` NEVER writes to disk | Early return before any write | CC-03 |
| INV-COMP-03 | Every generated `.py` MUST parse as valid Python | Final `ast.parse` loop over `files_created` | CC-06, CC-22 |
| INV-COMP-04 | Fernet MUST be imported lazily (never at module top level) | `from cryptography.fernet import Fernet` inside function body | CC-16 |
| INV-COMP-05 | `COMPLIANCE_*` settings MUST live inside `class Settings` | Anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | CC-08 |
| INV-COMP-06 | `ComplianceEvent` MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends idempotently | CC-09 |
| INV-COMP-07 | Erasure endpoint MUST return `ErasureCertificate` | Pydantic response model on DELETE route | CC-14 |
| INV-COMP-08 | Retention worker MUST use `asyncio.sleep` (not `time.sleep`) | Template enforces `asyncio.sleep` in loop | CC-15 |
| INV-COMP-09 | GDPR Article 30 route MUST be present | `"article30" in content.lower()` | CC-17 |
| INV-COMP-10 | SOC2 evidence route MUST be present | `"soc2" or "evidence" in content.lower()` | CC-18 |
| INV-COMP-11 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on all branches | CC-20 |
| INV-COMP-12 | `next_steps` MUST reference `alembic upgrade head` | Hard-coded in success branch | CC-21 |

---

## 9. User Stories

### 9.1 Core install flow

**US-01: Install compliance engine into a clean FastAPI project**
- **As a** backend engineer who needs GDPR compliance
- **I want** to run one tool call and get a compliance kit
- **So that** I stop hand-rolling erasure and audit log glue
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_compliance_engine(ToolInput(project_dir=...))`
- **Then:** `status="success"`, `files_created >= 6`, `files_modified >= 2` (CC-01, CC-04, CC-05)

**US-02: Re-run tool on already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **Given:** Project where `app/core/compliance_engine.py` already contains `ComplianceEngine`
- **When:** `add_compliance_engine(...)` invoked a second time
- **Then:** `status="no_op"`, both file lists empty, all `.py` still parse (CC-02, CC-22)

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **Given:** Fresh FastAPI fixture project
- **When:** `add_compliance_engine(ToolInput(project_dir=..., dry_run=True))`
- **Then:** `status="success"`, `files_created == []`, filesystem unchanged (CC-03)

**US-04: GDPR right-to-erasure via HTTP**
- **As a** data subject exercising their GDPR Article 17 right
- **I want** a `DELETE /compliance/erasure/{user_id}` endpoint
- **So that** my data is anonymised across all PII models
- **Given:** Compliance engine installed with at least one registered model
- **When:** Authenticated `DELETE /compliance/erasure/{user_id}`
- **Then:** Returns `ErasureCertificate` JSON; `compliance_events` row written (CC-14)

**US-05: Export SOC2 evidence package**
- **As a** SOC2 auditor
- **I want** `GET /compliance/evidence/soc2` to return structured event logs
- **Given:** `compliance_events` table populated from prior PII operations
- **When:** Auditor calls the endpoint
- **Then:** JSON response with event type, actor, timestamp, and model columns (CC-18)

### 9.2 Encryption and retention

**US-06: Encrypt a PII field before storage**
- **As a** developer persisting email addresses
- **I want** `compliance_engine.encrypt_field(value)` to return an opaque token
- **Given:** `COMPLIANCE_ENCRYPTION_KEY` set in env
- **When:** `encrypt_field("user@example.com")` called
- **Then:** Returns Fernet token; `cryptography` not imported at module load time (CC-16)

**US-07: Run retention enforcement cycle**
- **As a** platform operator enforcing data minimisation
- **I want** the retention worker to automatically purge stale rows
- **Given:** `schedule_retention_worker(app)` wired into FastAPI lifespan
- **When:** `COMPLIANCE_RETENTION_DEFAULT_DAYS` hours elapse
- **Then:** Rows past retention window are soft/hard deleted; event logged (CC-15)

---

## 10. Design Decisions

| Decision | Rationale |
|----------|-----------|
| Fernet symmetric encryption for PII fields | Simple, auditable, Python-native. Key rotation requires a re-encrypt pass but avoids KMS dependency in dev. |
| Append-only `ComplianceEvent` model | Audit trails must be tamper-evident. No `UPDATE` semantic on the table. |
| Retention worker as `asyncio.sleep` loop | Avoids Celery/arq dependency. For high-frequency jobs, operators can wire into an existing scheduler. |
| `ErasureCertificate` as response schema | Provides legally defensible proof of deletion with timestamp and scope. |
| GDPR Article 30 generated from PII registry | Keeps the record-of-processing in sync with the actual code; eliminates manual documentation drift. |
| Lazy `cryptography` import | App boots on machines without the library. COMPLIANCE_ENABLED=false skips all crypto paths. |
| Config anchored on `ACCESS_TOKEN_EXPIRE_MINUTES` | Guarantees injection inside `class Settings` body at 4-space indent, picked up by pydantic-settings. |

---

## 11. Dependencies

| Dependency | Version | Required | Notes |
|------------|---------|----------|-------|
| FastAPI | ≥ 0.100 | Yes | Route definitions |
| SQLAlchemy | ≥ 2.0 | Yes | `ComplianceEvent` model, async session |
| Alembic | ≥ 1.13 | Yes | Migration generation |
| pydantic-settings | ≥ 2.0 | Yes | `COMPLIANCE_*` config fields |
| cryptography | ≥ 42.0.0 | No (lazy) | Fernet field encryption; optional at boot |
| asyncio | stdlib | Yes | Retention worker sleep loop |

---

## 12. Error Handling

| Scenario | Behaviour |
|----------|-----------|
| `project_dir` does not exist or is not a directory | `status="error"`, `error="..."` from `validate_project_dir` |
| Prerequisites not met (no `app/core/config.py`, etc.) | `status="error"`, lists missing prereqs, hints at `fastapi_generate_project` |
| Generated file fails `ast.parse` | `status="error"`, `error=f"Generated file has syntax error: {path}: {exc}"` |
| `dry_run=True` | `status="success"`, notes listing would-be changes, no writes |
| Second invocation (fingerprint found) | `status="no_op"`, no files touched |
| `COMPLIANCE_ENCRYPTION_KEY` is empty at runtime | `encrypt_field` / `decrypt_field` raise `ValueError` at call time, not at import |

---

## 13. Security Considerations

- Fernet key (`COMPLIANCE_ENCRYPTION_KEY`) must never appear in logs. Template does not log it.
- `ErasureCertificate` endpoint is authenticated via `CurrentUser` dependency.
- SOC2 evidence endpoint must be restricted to admin roles in production (noted in `next_steps`).
- The `_WEAK_PATTERNS` constant in `secret_rotation.py` (if co-installed) will flag empty encryption keys at startup.
- `ComplianceEvent` rows are insert-only; the SQLAlchemy model does not expose `update` or `delete` operations.

---

## 14. Testing Guide

```bash
# Run structural tests
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_compliance_engine.py -v

# Run standalone (no pytest)
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_compliance_engine.py

# Run with coverage
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_compliance_engine.py \
  --cov=adapt.extend.infrastructure.add_compliance_engine \
  --cov-report=term-missing
```

**Test fixture naming convention:** `comp_t01` through `comp_t_last`. Each test creates an isolated fixture project via `create_fixture_project(name=...)` so tests are fully independent and parallelisable.

---

## 15. Files Reference

| File | Role |
|------|------|
| `adapt/extend/infrastructure/add_compliance_engine.py` | Tool implementation |
| `adapt/extend/infrastructure/test_add_compliance_engine.py` | Structural test suite (22 tests) |
| `adapt/extend/infrastructure/test_add_compliance_engine_behavior.py` | Behaviour-level tests (if present) |
| Generated: `app/core/compliance_engine.py` | PII registry, Fernet helpers, retention logic |
| Generated: `app/models/compliance_event.py` | Append-only audit model |
| Generated: `app/schemas/compliance.py` | `ErasureCertificate`, `ComplianceEventOut` |
| Generated: `app/crud/compliance.py` | Async CRUD: `cascade_anonymise`, `record_event`, etc. |
| Generated: `app/api/routes/compliance.py` | Erasure, SOC2 evidence, Article 30 routes |
| Generated: `app/workers/retention_worker.py` | Background retention enforcement loop |
| Generated: `alembic/versions/add_compliance_engine.py` | DB migration for `compliance_events` |

---

## 16. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-04-15 | Initial spec — TOOL-113 |
