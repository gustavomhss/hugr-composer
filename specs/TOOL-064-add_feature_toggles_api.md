---
spec_id: "TOOL-064"
tool_name: "add_feature_toggles_api"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-FT-01"
  - "INV-FT-02"
  - "INV-FT-03"
  - "INV-FT-04"
  - "INV-FT-05"
  - "INV-FT-06"
  - "INV-FT-07"
  - "INV-FT-08"
  - "INV-FT-09"
  - "INV-FT-10"
  - "INV-FT-11"
  - "INV-FT-12"
  - "INV-FT-13"
  - "INV-FT-14"
  - "INV-FT-15"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-17"
  - "QS-18"
  - "QS-19"
  - "QS-2"
  - "QS-20"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
  - "T-31"
tags:
  - "performance"
  - "payments"
  - "data"
  - "realtime"
  - "compliance"
---
# TOOL-064: add_feature_toggles_api

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_feature_toggles_api` |
| Category | EXTEND > Auth / Access |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, pydantic-settings, hashlib (stdlib) |
| Signature | `add_feature_toggles_api(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_feature_toggles_api", "description": "Upgrade a FastAPI project to a full API-driven feature toggle system with DB persistence, percentage rollout, user allowlist, and environment gating.", "tags": ["extend", "auth_access"], "entry": "add_feature_toggles_api"}` |
| Files created (typical) | 8 — `app/models/feature_toggle.py`, `app/schemas/feature_toggle.py`, `app/crud/feature_toggle.py`, `app/features/evaluator.py`, `app/features/service.py`, `app/features/__init__.py`, `app/api/routes/feature_toggles.py`, `alembic/versions/0064_add_feature_toggles_api.py` |
| Files modified (typical) | 3 — `app/models/__init__.py`, `app/core/config.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_feature_toggles_api` tool upgrades a FastAPI project from environment-variable-based feature flags (installed by `add_feature_flags`, TOOL-009) to a **full API-driven feature toggle system** backed by a `feature_toggles` database table, with percentage rollout, per-user allowlist, environment gating, in-process TTL caching, and a full admin REST API.

The problem this solves: `add_feature_flags` (TOOL-009) provides feature flags as `bool` config values read from environment variables. That approach is sufficient for binary on/off flags controlled by a re-deploy or a config reload, but it fails the moment product teams need (a) gradual rollouts to 5% of users before expanding to 100%, (b) an allowlist of specific beta users who always get the feature regardless of percentage, (c) environment-scoped flags that are active in `staging` but blocked in `production`, or (d) flag management through a UI without modifying `.env` files or redeploying. This tool delivers all four capabilities without replacing the existing env-var layer: env-var flags **take priority** over DB toggles, so any flag previously set in the environment continues to work exactly as before.

The **evaluation chain** is the core design decision. It runs in a fixed, documented order: (1) toggle disabled → `False, "disabled"`; (2) user in `allowed_users` allowlist → `True, "allowlist"`; (3) `environments` list non-empty and current env not in list → `False, "environment_gate"`; (4) `rollout_percentage >= 100` → `True, "full_rollout"`; (5) `rollout_percentage <= 0` → `False, "zero_rollout"`; (6) compute `hash(user_id + toggle_name)` bucket → `True/False, "rollout:N%"`; (7) no `user_id` provided → `False, "no_user_id"`. This is deterministic: the same `(user_id, toggle_name)` pair always produces the same bucket, so a user does not toggle between enabled and disabled on page refresh.

The bucket function uses `hashlib.sha256(f"{user_id}{toggle_name}".encode("utf-8")).digest()[:4]` converted to a big-endian integer modulo 100. SHA-256 is used rather than Python's built-in `hash()` because `hash()` is randomized per-process by PYTHONHASHSEED and would produce different buckets across restarts, breaking the determinism guarantee.

The **in-memory TTL cache** (`_CACHE: dict[str, tuple[float, Any]]`) avoids a DB hit on every hot-path `is_enabled()` call. The TTL defaults to 60 seconds and is configurable via `FEATURE_TOGGLES_CACHE_TTL_SECONDS`. The cache is process-local (not shared across Gunicorn/uvicorn workers) which is intentional: the overhead of a Redis shared cache is not warranted for toggle evaluations that are read-heavy and can tolerate up to one TTL interval of stale state after an update. Cache invalidation happens immediately on `create_toggle` and `update_toggle` via `_invalidate(name)`.

The **env-var priority** design means `os.getenv(name.upper())` is checked first inside `is_enabled`. If the value is in `{"1", "true", "yes", "on"}` the method returns `True` without touching the DB or cache. If it is in `{"0", "false", "no", "off"}` the method returns `False`. Values outside these sets fall through to the DB path. This means operators can emergency-override any toggle via a `kubectl set env` or Heroku config var without a deploy, and the override takes effect within seconds.

The **admin REST API** is guarded by `CurrentSuperuser` throughout. This is a stronger requirement than `CurrentUser` because feature toggle administration is a privileged operation — enabling a half-baked feature for 100% of users, or deleting a toggle that active code paths reference, can cause user-visible regressions. The `POST /feature-toggles` endpoint checks for name uniqueness (409 on collision) because duplicate toggle names would produce ambiguous `get_by_name` queries. The `POST /{name}/evaluate` endpoint allows admin operators to test the evaluation logic for any `(user_id, environment)` pair without deploying code.

The tool is idempotent: if `app/models/feature_toggle.py` already contains `FeatureToggle`, the second invocation returns `status="no_op"` with zero writes.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-11) |
| Files created | ≥ 6 | Model, schemas, CRUD, evaluator, service, features init, routes, migration — at minimum 6 distinct files (T-02) |
| Files modified | ≥ 1 | `app/models/__init__.py` at minimum (T-03) |
| Max function LOC in generated code | ≤ 50 | Auditable by construction; enforced by AST walk in test harness |
| `is_enabled()` latency (cache hit) | < 1 ms | Pure in-process dict lookup + TTL comparison |
| `is_enabled()` latency (DB miss) | < 10 ms | Single `SELECT … WHERE name = ?` on indexed `name` column |
| `GET /feature-toggles` latency | < 20 ms | `SELECT * FROM feature_toggles ORDER BY name` — full table scan acceptable for toggle counts ≤ 1,000 |
| `POST /feature-toggles` latency | < 20 ms | Single `INSERT` + flush |
| `POST /{name}/evaluate` latency | < 15 ms | Single `SELECT` (cache miss) + deterministic bucket computation |
| `PUT /{name}` latency | < 15 ms | Single `UPDATE` + cache invalidation |
| `DELETE /{name}` latency | < 10 ms | Single `DELETE` + cache invalidation |
| Migration runtime | < 1 s | Single `CREATE TABLE` + 1 unique index + 1 CHECK constraint |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/
│   │   └── config.py        # FEATURE_NEW_DASHBOARD: bool = False
│   ├── models/
│   │   └── __init__.py      # No FeatureToggle
│   └── routes/
│       └── __init__.py      # No feature-toggles router
```

All flags are binary, deploy-coupled, and unauditable. A product manager who wants to roll out "new_checkout" to 10% of users must ask engineering to change an env var, deploy, verify, and bump the percentage incrementally over days.

### 4.2 FeatureToggle ORM model: AFTER

```python
# app/models/feature_toggle.py
class FeatureToggle(Base):
    """Persistent feature toggle with per-user and per-environment rules."""

    __tablename__ = "feature_toggles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(
        String(127), unique=True, nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    rollout_percentage: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="100"
    )
    allowed_users: Mapped[list] = mapped_column(
        JSON, nullable=False, server_default="[]"
    )
    environments: Mapped[list] = mapped_column(
        JSON, nullable=False, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

### 4.3 Rule evaluator (deterministic bucket): AFTER

```python
# app/features/evaluator.py
def evaluate(
    toggle: object,
    *,
    user_id: str | None = None,
    environment: str = "production",
) -> tuple[bool, str]:
    """Evaluate whether a toggle is active for a given context.

    Uses percentage rollout via ``hash(user_id + toggle.name) % 100``
    which is fully deterministic — the same user always gets the same
    bucket for a given toggle name.
    """
    if not toggle.enabled:
        return False, "disabled"

    if user_id and user_id in (toggle.allowed_users or []):
        return True, "allowlist"

    envs = toggle.environments or []
    if envs and environment not in envs:
        return False, "environment_gate"

    pct = toggle.rollout_percentage
    if pct >= 100:
        return True, "full_rollout"
    if pct <= 0:
        return False, "zero_rollout"

    if user_id:
        bucket = _bucket(toggle.name, user_id)
        if bucket < pct:
            return True, f"rollout:{pct}%"
        return False, f"rollout:{pct}%"

    return False, "no_user_id"


def _bucket(toggle_name: str, user_id: str) -> int:
    """Return a deterministic 0-99 bucket for (toggle_name, user_id)."""
    payload = f"{user_id}{toggle_name}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:4], "big", signed=False) % 100
```

### 4.4 FeatureToggleService (TTL cache + env-var priority): AFTER

```python
# app/features/service.py
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL: int = int(os.getenv("FEATURE_TOGGLES_CACHE_TTL_SECONDS", "60"))
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


class FeatureToggleService:
    """Service layer for feature toggle evaluation and administration."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_enabled(
        self,
        name: str,
        *,
        user_id: str | None = None,
        environment: str = "production",
        default: bool = False,
    ) -> bool:
        """Return whether a toggle is active for the given context.

        Checks env-var override first, then in-memory cache, then DB.
        """
        env_val = os.getenv(name.upper(), "").strip().lower()
        if env_val in _TRUTHY:
            return True
        if env_val in _FALSY:
            return False

        toggle = await self._load(name)
        if toggle is None:
            return default
        enabled, _ = evaluate(toggle, user_id=user_id, environment=environment)
        return enabled
```

### 4.5 Admin REST routes (superuser-only): AFTER

```python
# app/api/routes/feature_toggles.py
router = APIRouter(prefix="/feature-toggles", tags=["feature-toggles"])

@router.get("/", response_model=list[ToggleRead])
async def list_toggles(
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> list[ToggleRead]:
    """List all feature toggles. Superuser only."""
    svc = FeatureToggleService(session)
    return await svc.list_toggles()

@router.post("/", response_model=ToggleRead, status_code=status.HTTP_201_CREATED)
async def create_toggle(
    toggle_in: ToggleCreate,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> ToggleRead:
    """Create a new feature toggle. Superuser only."""
    from app.crud.feature_toggle import get_by_name
    existing = await get_by_name(session, name=toggle_in.name)
    if existing:
        raise HTTPException(status_code=409, detail="Toggle name already exists")
    svc = FeatureToggleService(session)
    return await svc.create_toggle(toggle_in)

@router.post("/{name}/evaluate", response_model=ToggleEvaluateResult)
async def evaluate_toggle(
    name: str,
    body: ToggleEvaluate,
    session: SessionDep,
    current_user: CurrentSuperuser,
) -> ToggleEvaluateResult:
    """Evaluate a toggle for a given user/environment context."""
    from app.crud.feature_toggle import get_by_name
    from app.features.evaluator import evaluate
    toggle = await get_by_name(session, name=name)
    if not toggle:
        raise HTTPException(status_code=404, detail="Toggle not found")
    enabled, reason = evaluate(
        toggle, user_id=body.user_id, environment=body.environment
    )
    return ToggleEvaluateResult(name=name, enabled=enabled, reason=reason)
```

### 4.6 Alembic migration (with rollout CHECK constraint): AFTER

```python
# alembic/versions/0064_add_feature_toggles_api.py
def upgrade() -> None:
    """Create feature_toggles table with index on name."""
    op.create_table(
        "feature_toggles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(127), unique=True, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("rollout_percentage", sa.Integer(), server_default="100", nullable=False),
        sa.Column("allowed_users", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("environments", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "rollout_percentage BETWEEN 0 AND 100",
            name="ck_feature_toggles_rollout_range",
        ),
    )
    op.create_index("ix_feature_toggles_name", "feature_toggles", ["name"], unique=True)


def downgrade() -> None:
    """Drop feature_toggles table and its index."""
    op.drop_index("ix_feature_toggles_name", "feature_toggles")
    op.drop_table("feature_toggles")
```

### 4.7 Config patch (FEATURE_TOGGLES_CACHE_TTL_SECONDS inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
class Settings(BaseSettings):
    FEATURE_TOGGLES_CACHE_TTL_SECONDS: int = 60
    ...
```

The `_patch_config` helper anchors on the `class Settings` line itself and inserts the field on the line immediately after the class definition header, ensuring pydantic-settings picks it up from the `FEATURE_TOGGLES_CACHE_TTL_SECONDS` environment variable.

### 4.8 `app/features/__init__.py` re-exports: AFTER

```python
# app/features/__init__.py
"""Feature toggle subsystem — public re-exports."""

from app.features.evaluator import evaluate  # noqa: F401
from app.features.service import FeatureToggleService  # noqa: F401

__all__ = ["FeatureToggleService", "evaluate"]
```

### 4.9 Typical hot-path caller usage (after install)

```python
# app/api/routes/checkout.py
from app.features import FeatureToggleService

@router.post("/checkout")
async def checkout(
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    svc = FeatureToggleService(session)
    use_new_checkout = await svc.is_enabled(
        "new_checkout",
        user_id=str(current_user.id),
        environment="production",
    )
    if use_new_checkout:
        return await _new_checkout_flow(session, current_user)
    return await _legacy_checkout_flow(session, current_user)
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint check `"FeatureToggle" in feature_toggle.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | Loop over `files_created`: `ast.parse(p.read_text())` for every `.py`; on failure returns `status="error"` |
| QS-4 | **No generated function exceeds 50 LOC** | Evaluator, service, CRUD, and route functions kept short by construction |
| QS-5 | **Evaluation order is documented and tested** | Docstring in `evaluator.py` lists all 7 steps; `"disabled"` must appear before `"allowlist"` in file order |
| QS-6 | **Bucket function uses `hashlib.sha256`** | `_bucket` imports `hashlib` and calls `.sha256(payload).digest()` — not `hash()` |
| QS-7 | **Env-var override is checked before DB** | `os.getenv(name.upper())` is the first check in `is_enabled` |
| QS-8 | **In-process TTL cache is used** | `_CACHE: dict` + `_CACHE_TTL` in `service.py`; `_CACHE` evicted on `create_toggle`/`update_toggle` |
| QS-9 | **All admin routes require `CurrentSuperuser`** | Every route handler declares `current_user: CurrentSuperuser` from `app.api.deps` |
| QS-10 | **`FeatureToggle` registered in `app/models/__init__.py`** | `_patch_models_init` appends `from app.models.feature_toggle import FeatureToggle  # noqa: F401` idempotently |
| QS-11 | **`FEATURE_TOGGLES_CACHE_TTL_SECONDS` inside `class Settings` body** | `_patch_config` inserts after `class Settings` header line |
| QS-12 | **Alembic migration has rollout CHECK constraint** | `ck_feature_toggles_rollout_range` CHECK `rollout_percentage BETWEEN 0 AND 100` in migration |
| QS-13 | **Migration chained to current head** | `find_migration_head(versions_dir) or "0001_initial"` |
| QS-14 | **`create_toggle` returns 409 on duplicate name** | `get_by_name` check before insert in `create_toggle` route |
| QS-15 | **`app/features/__init__.py` re-exports `FeatureToggleService` and `evaluate`** | `__all__ = ["FeatureToggleService", "evaluate"]` |
| QS-16 | **`ToggleUpdate` uses `exclude_unset=True`** | `toggle_in.model_dump(exclude_unset=True)` in CRUD `update` prevents clearing fields not sent in request |
| QS-17 | **Prerequisites validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT, BASE_MODEL, MODELS_INIT, ALEMBIC_VERSIONS)` runs first |
| QS-18 | **`execution_time_ms` is non-negative on every return path** | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches |
| QS-19 | **`next_steps` mention `alembic`, cache TTL, and superuser** | Hard-coded in the success branch |
| QS-20 | **`evaluate` is duck-typed (accepts any object with expected attrs)** | No `isinstance(toggle, FeatureToggle)` check — allows unit testing without DB setup |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_feature_toggles_api.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | `app/models/feature_toggle.py` exists with `class FeatureToggle` | File exists + `"class FeatureToggle" in content` | T-04 (`test_toggle_model_created`) |
| CC-01b | `FeatureToggle` has `name`, `enabled`, `rollout_percentage`, `allowed_users`, `environments` | Substring check for each field | T-05 (`test_toggle_model_fields`) |
| CC-01c | `FeatureToggle` is imported in `app/models/__init__.py` | `"FeatureToggle" in content` of `models/__init__.py` | T-06 (`test_toggle_model_registered_in_init`) |
| CC-02 | `app/schemas/feature_toggle.py` exists | File exists | T-07 (`test_schemas_created`) |
| CC-02b | Schemas have `ToggleCreate`, `ToggleUpdate`, `ToggleRead`, `ToggleEvaluate` | `f"class {cls}" in content` for each | T-08 (`test_schemas_classes`) |
| CC-03 | `app/crud/feature_toggle.py` exists | File exists | T-09 (`test_crud_created`) |
| CC-03b | CRUD has `get_by_name`, `list_toggles`, `create`, `update`, `delete` as `async def` | `f"async def {fn}" in content` for each | T-10 (`test_crud_functions`) |
| CC-04 | `app/features/evaluator.py` exists | File exists | T-11 (`test_evaluator_created`) |
| CC-04b | Evaluator uses `hashlib` and `sha256` for bucket computation | `"hashlib" in content` and `"sha256" in content` | T-12 (`test_evaluator_uses_hash_bucketing`) |
| CC-04c | Evaluator returns `False, "disabled"` when toggle is disabled | `"not toggle.enabled"` or `"toggle.enabled"` and `'"disabled"' in content` | T-13 (`test_evaluator_checks_disabled_first`) |
| CC-04d | Evaluator checks `allowed_users` allowlist and returns `"allowlist"` | `"allowed_users" in content` and `'"allowlist"' in content` | T-14 (`test_evaluator_allowlist_priority`) |
| CC-04e | Evaluator checks `environments` and returns `"environment_gate"` | `"environments" in content` and `"environment_gate" in content` | T-15 (`test_evaluator_environment_gate`) |
| CC-05 | `app/features/service.py` exists with `class FeatureToggleService` | File exists + `"class FeatureToggleService" in content` | T-16 (`test_service_created`) |
| CC-05b | Service has `async def is_enabled` | `"async def is_enabled" in content` | T-17 (`test_service_is_enabled`) |
| CC-05c | Service checks `os.getenv` before DB (env-var priority) | `"os.getenv" in content` | T-18 (`test_service_env_var_priority`) |
| CC-05d | Service uses in-memory TTL cache (`_CACHE`, `_CACHE_TTL`) | `"CACHE_TTL" in content` or `"_CACHE_TTL" in content`; `"_CACHE" in content` | T-19 (`test_service_ttl_cache`) |
| CC-05e | `app/features/__init__.py` re-exports `FeatureToggleService` and `evaluate` | File exists; both names in content | T-20 (`test_features_init_created`) |
| CC-06 | `app/api/routes/feature_toggles.py` exists | File exists | T-21 (`test_routes_created`) |
| CC-06b | Routes have `list_toggles`, `create_toggle`, `update_toggle`, `delete_toggle`, `evaluate_toggle` | `f"async def {fn}" in content` for each | T-22 (`test_routes_has_crud_endpoints`) |
| CC-06c | All routes require `CurrentSuperuser` | `"CurrentSuperuser" in content` | T-23 (`test_routes_require_superuser`) |
| CC-06d | Evaluate endpoint uses `POST /{name}/evaluate` and returns `ToggleEvaluateResult` | `"/evaluate" in content` and `"ToggleEvaluateResult" in content` | T-24 (`test_routes_evaluate_endpoint`) |
| CC-07 | Alembic migration file for `feature_toggles` is created | `glob("*feature_toggles*")` in `alembic/versions/` returns ≥ 1 file | T-25 (`test_migration_created`) |
| CC-07b | Migration has `upgrade`, `downgrade`, and `rollout_percentage` column | All three present in migration file content | T-26 (`test_migration_content`) |
| CC-08 | Second run returns `status="no_op"` | `r2.status == "no_op"` and `r2.files_created == []` | T-27 (`test_idempotent_returns_no_op`) |
| CC-08b | After two runs all generated files parse correctly | `ast.parse` over all `.py` in project | T-28 (`test_idempotent_project_parses`) |
| CC-09 | `dry_run=True` returns success with zero filesystem writes | `before == after` over every `.py` | T-29 (`test_dry_run_writes_nothing`) |
| CC-10 | All `.py` files in project parse without `SyntaxError` | `ast.parse` over all `.py` | T-30 (`test_all_py_files_parse`) |
| CC-11 | `execution_time_ms` is a non-negative integer | `isinstance(result.execution_time_ms, int)` and `>= 0` | T-31 (`test_execution_time_ms_populated`) |
| CC-12 | Every path in `files_created` exists on disk | `Path(p).exists()` for each | T-02 (`test_files_created_exist`) |
| CC-13 | Every path in `files_modified` exists on disk | `Path(p).exists()` for each | T-03 (`test_files_modified_exist`) |

---

## 7. Definition of Done (DoD)

- [ ] All 31 test cases in `test_add_feature_toggles_api.py` pass
- [ ] `add_feature_toggles_api.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_feature_toggles_api.py` detects `"FeatureToggle"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `_bucket` uses `hashlib.sha256` — not `hash()` — so buckets are stable across process restarts
- [ ] Evaluation order: disabled → allowlist → environment_gate → full_rollout → zero_rollout → hash_bucket → no_user_id
- [ ] `is_enabled` checks `os.getenv(name.upper())` before any DB or cache access
- [ ] `_CACHE` dict + `_CACHE_TTL` provides in-process TTL caching; `_invalidate(name)` called on create/update
- [ ] All 5 admin routes declare `current_user: CurrentSuperuser`
- [ ] `create_toggle` returns 409 if name already exists
- [ ] `ToggleUpdate.model_dump(exclude_unset=True)` prevents clearing fields not sent in PATCH
- [ ] `FeatureToggle` registered in `app/models/__init__.py` via `_patch_models_init`
- [ ] `FEATURE_TOGGLES_CACHE_TTL_SECONDS` inside `class Settings` body via `_patch_config`
- [ ] Migration has `ck_feature_toggles_rollout_range` CHECK constraint
- [ ] `find_migration_head` used to chain migration to current head
- [ ] `app/features/__init__.py` exposes `FeatureToggleService` and `evaluate` in `__all__`
- [ ] `execution_time_ms` set on every return path
- [ ] Tool completes in < 5 s on fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-FT-01 | Tool is ALWAYS idempotent: `FeatureToggle` fingerprint → `status="no_op"` | `toggle_model_file.exists() and "FeatureToggle" in toggle_model_file.read_text()` | T-27, T-28 |
| INV-FT-02 | `dry_run=True` NEVER writes to disk | Early return before any `dest.write_text(...)` call | T-29 |
| INV-FT-03 | Every generated `.py` file MUST parse as valid Python | `ast.parse(p.read_text())` loop; returns `status="error"` on failure | T-30, T-28 |
| INV-FT-04 | `_bucket` MUST use `hashlib.sha256` (deterministic across restarts) | `import hashlib` and `.sha256(payload).digest()` in `evaluator.py` | T-12 |
| INV-FT-05 | Evaluation order: `disabled` checked BEFORE `allowlist` | `not toggle.enabled` conditional precedes `allowed_users` check in `evaluate` function body | T-13, T-14 |
| INV-FT-06 | `allowed_users` allowlist MUST be checked BEFORE percentage rollout | `allowed_users` block precedes `_bucket` call in `evaluate` | T-14 |
| INV-FT-07 | Environment gate MUST fire when `environments` list is non-empty and current env not in list | `envs and environment not in envs → False, "environment_gate"` | T-15 |
| INV-FT-08 | `is_enabled` MUST check env-var override BEFORE DB and cache | `os.getenv(name.upper())` is first statement in `is_enabled` method | T-18 |
| INV-FT-09 | In-process TTL cache MUST be used to avoid per-call DB round trips | `_CACHE` dict checked before `get_by_name` in `_load`; TTL enforced via `time.monotonic()` | T-19 |
| INV-FT-10 | ALL admin routes MUST require `CurrentSuperuser` | Every route handler declares `current_user: CurrentSuperuser` parameter | T-23 |
| INV-FT-11 | `create_toggle` MUST return 409 if toggle name already exists | `get_by_name` check + `raise HTTPException(status_code=409, ...)` before create | T-22 (route function body) |
| INV-FT-12 | `FeatureToggle` MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends `from app.models.feature_toggle import FeatureToggle  # noqa: F401` | T-06 |
| INV-FT-13 | Migration MUST have rollout CHECK constraint (`BETWEEN 0 AND 100`) | `sa.CheckConstraint("rollout_percentage BETWEEN 0 AND 100", ...)` in `upgrade()` | T-26 |
| INV-FT-14 | Migration MUST be chained to current head | `find_migration_head(versions_dir) or "0001_initial"` | T-25, T-26 |
| INV-FT-15 | `ToolResult.execution_time_ms` MUST be non-negative on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-31 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install feature toggle API into a clean FastAPI project**
- **As a** product engineer who needs gradual rollouts
- **I want** to run one tool call and get a DB-backed toggle system
- **So that** I stop coordinating env-var deploys with product managers
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_feature_toggles_api(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-FT-01)
  - `files_created` paths all exist on disk (CC-12)
  - `files_modified` paths all exist on disk (CC-13)
  - Verified by T-01, T-02, T-03

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** the generated files are not overwritten
- **Given:** Project where `app/models/feature_toggle.py` already contains `FeatureToggle`
- **When:** `add_feature_toggles_api(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-FT-01)
  - `files_created == []`
  - All `.py` files still AST-parse (INV-FT-03)
  - Verified by T-27, T-28

**US-03: Dry-run to preview changes**
- **As a** developer reviewing what the tool would do
- **I want** `dry_run=True` to report the planned changes without touching files
- **So that** I can decide whether to apply
- **Given:** Fresh FastAPI fixture project
- **When:** `add_feature_toggles_api(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with `notes` listing what would be created
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical (INV-FT-02)
  - Verified by T-29

**US-04: Coexist with existing env-var feature flags**
- **As a** platform with `add_feature_flags` already applied
- **I want** existing `FEATURE_NEW_DASHBOARD=true` env vars to keep working
- **So that** migrating to DB-backed toggles does not break the running system
- **Given:** Some flags set via `os.getenv` in existing code
- **When:** `is_enabled("new_dashboard")` is called
- **Then:**
  - `os.getenv("NEW_DASHBOARD")` is checked first (INV-FT-08)
  - If set to a truthy value, returns `True` without DB access
  - Verified by T-18

**US-05: Generated project is auditable**
- **As a** code reviewer
- **I want** every generated function to be ≤ 50 LOC
- **So that** I can read and approve the generated code
- **Given:** Tool just emitted `evaluator.py`, `service.py`, `crud/feature_toggle.py`, `routes/feature_toggles.py`
- **When:** AST-walk over `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` exceeds 50 LOC (QS-4)
  - Verified by inspection of generated code

### 9.2 Rule evaluation (US-06 .. US-10)

**US-06: Toggle disabled master switch**
- **As a** product manager who needs to kill a feature immediately
- **I want** setting `enabled=false` to disable for all users regardless of other rules
- **So that** I can emergency-kill a bad feature without code changes
- **Given:** Toggle has `enabled=False` but `rollout_percentage=100`
- **When:** `evaluate(toggle, user_id="any", environment="production")`
- **Then:**
  - Returns `(False, "disabled")` — first check wins (INV-FT-05)
  - Verified by T-13

**US-07: User allowlist bypasses percentage rollout**
- **As a** product manager with a list of beta testers
- **I want** specific users always granted access
- **So that** my beta program is not subject to random bucket placement
- **Given:** Toggle `rollout_percentage=10`, `allowed_users=["user-id-123"]`
- **When:** `evaluate(toggle, user_id="user-id-123")`
- **Then:**
  - Returns `(True, "allowlist")` before any bucket computation (INV-FT-06)
  - Verified by T-14

**US-08: Environment gate blocks non-matching environments**
- **As a** release manager
- **I want** a toggle that only activates in `staging`
- **So that** I can test the feature before production exposure
- **Given:** Toggle `environments=["staging"]`, called with `environment="production"`
- **When:** `evaluate(toggle, environment="production")`
- **Then:**
  - Returns `(False, "environment_gate")` (INV-FT-07)
  - Verified by T-15

**US-09: Deterministic percentage rollout**
- **As a** product manager who wants stable user assignment
- **I want** user "abc123" to always be in the same bucket for toggle "checkout_v2"
- **So that** the feature does not flicker on for the same user on page refresh
- **Given:** `rollout_percentage=50`
- **When:** `_bucket("checkout_v2", "abc123")` is called twice
- **Then:**
  - Returns the same value both times (INV-FT-04)
  - `hashlib.sha256` used — not `hash()` which would differ across process restarts
  - Verified by T-12

**US-10: Missing toggle returns default**
- **As a** feature flag consumer
- **I want** `is_enabled("nonexistent_flag", default=False)` to return `False`
- **So that** code paths that reference toggles that haven't been created yet fail closed
- **Given:** Toggle name not in DB
- **When:** `await svc.is_enabled("nonexistent_flag", default=False)`
- **Then:**
  - `_load("nonexistent_flag")` returns `None`
  - Method returns `default=False` — no exception
  - Verified by service code: `if toggle is None: return default`

### 9.3 Admin API (US-11 .. US-15)

**US-11: Create a new toggle via REST**
- **As a** product manager using the admin UI
- **I want** `POST /feature-toggles` with `{name, rollout_percentage: 10}`
- **So that** I start a 10% rollout without touching code
- **Given:** Admin user with superuser role
- **When:** `POST /feature-toggles {"name": "new_checkout", "enabled": true, "rollout_percentage": 10}`
- **Then:**
  - Returns 201 with `ToggleRead` schema
  - Cache entry for `"new_checkout"` is invalidated (QS-8)
  - Verified by T-22

**US-12: Duplicate toggle name returns 409**
- **As an** admin who accidentally submits a create form twice
- **I want** a clear 409 Conflict, not a 500 DB unique violation
- **So that** the UI can display a helpful message
- **Given:** Toggle `"new_checkout"` already exists
- **When:** `POST /feature-toggles {"name": "new_checkout"}`
- **Then:**
  - `get_by_name` check returns existing row → `HTTPException(status_code=409, detail="Toggle name already exists")` (INV-FT-11)
  - Verified by T-22 (route function inspection)

**US-13: Update percentage via REST**
- **As a** product manager who wants to expand rollout from 10% to 50%**
- **I want** `PUT /feature-toggles/new_checkout {"rollout_percentage": 50}`
- **So that** I expand the rollout without touching any code
- **Given:** Toggle `new_checkout` exists with `rollout_percentage=10`
- **When:** `PUT /feature-toggles/new_checkout {"rollout_percentage": 50}`
- **Then:**
  - `ToggleUpdate.model_dump(exclude_unset=True)` only updates `rollout_percentage` (QS-16)
  - Cache invalidated immediately (QS-8)
  - Returns updated `ToggleRead`
  - Verified by T-22

**US-14: Evaluate a toggle for a specific user**
- **As an** admin debugging a rollout
- **I want** `POST /feature-toggles/new_checkout/evaluate {"user_id": "abc123"}`
- **So that** I can verify what bucket user "abc123" lands in
- **Given:** Toggle exists; admin has superuser role
- **When:** `POST /feature-toggles/new_checkout/evaluate {"user_id": "abc123", "environment": "production"}`
- **Then:**
  - Returns `{"name": "new_checkout", "enabled": true/false, "reason": "rollout:50%"}` (CC-06d)
  - Verified by T-24

**US-15: Non-superuser cannot access admin endpoints**
- **As a** security reviewer
- **I want** all toggle admin routes gated by `CurrentSuperuser`
- **So that** regular users cannot create or delete toggles
- **Given:** Routes declare `current_user: CurrentSuperuser`
- **When:** Regular user token hits `GET /feature-toggles`
- **Then:**
  - FastAPI DI resolves `CurrentSuperuser`, missing role → 403
  - Verified by T-23 (INV-FT-10)

### 9.4 Service and cache (US-16 .. US-20)

**US-16: Hot-path `is_enabled` avoids DB on repeated calls**
- **As a** high-traffic checkout page
- **I want** repeated `is_enabled("new_checkout")` calls to hit only the in-process cache
- **So that** the DB connection pool is not saturated by flag checks
- **Given:** Toggle loaded once into `_CACHE`
- **When:** `is_enabled("new_checkout")` called 100 times within `_CACHE_TTL` seconds
- **Then:**
  - `get_by_name` called only once; cache hit for the remaining 99 calls (INV-FT-09)
  - Verified by `_CACHE` and `_CACHE_TTL` presence (T-19)

**US-17: Cache TTL configurable via environment**
- **As an** ops engineer who wants a shorter cache window during flag changes
- **I want** `FEATURE_TOGGLES_CACHE_TTL_SECONDS=5` in `.env`
- **So that** toggle changes take effect within 5 seconds instead of 60
- **Given:** `FEATURE_TOGGLES_CACHE_TTL_SECONDS` inside `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `_CACHE_TTL = int(os.getenv("FEATURE_TOGGLES_CACHE_TTL_SECONDS", "60"))` reads env var (INV-FT-09)
  - Verified by T-18, T-19

**US-18: Cache is immediately invalidated on toggle update**
- **As a** product manager who just expanded rollout from 10% to 100%
- **I want** the change to take effect within one TTL window at most
- **So that** users see the new feature promptly
- **Given:** Toggle cached in `_CACHE` with stale `rollout_percentage=10`
- **When:** `await svc.update_toggle("new_checkout", ToggleUpdate(rollout_percentage=100))`
- **Then:**
  - `_invalidate("new_checkout")` evicts the cache entry
  - Next `is_enabled` call fetches from DB with the updated value
  - Verified by `_invalidate` call presence in `update_toggle`

**US-19: `features/__init__.py` provides clean public import**
- **As a** developer consuming the feature toggle system
- **I want** `from app.features import FeatureToggleService, evaluate`
- **So that** I do not need to know the internal module structure
- **Given:** `app/features/__init__.py` re-exports both names in `__all__`
- **When:** `from app.features import FeatureToggleService`
- **Then:**
  - Import succeeds without errors
  - Verified by T-20 (CC-05e)

**US-20: Tool execution time fits CI budget**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **So that** the build does not blow the budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms >= 0` and in practice < 5000 (INV-FT-15)
  - Verified by T-31

---

## 10. Test Plan

All 31 tests live in `adapt/extend/auth_access/test_add_feature_toggles_api.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Basic contract (T-01 .. T-03)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `ft01_success` | `add_feature_toggles_api(ToolInput(project_dir))` | `result.status == "success"` (CC-01) |
| T-02 | `test_files_created_exist` | Fixture `ft02_files_exist`; run tool | Check each path in `files_created` | Every path exists on disk (CC-12) |
| T-03 | `test_files_modified_exist` | Fixture `ft03_modified_exist`; run tool | Check each path in `files_modified` | Every path exists on disk (CC-13) |

### 10.2 Category B — FeatureToggle model (T-04 .. T-06)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-04 | `test_toggle_model_created` | Fixture `ft04_model`; run tool | Read `app/models/feature_toggle.py` | File exists; `"class FeatureToggle" in content` (CC-01) |
| T-05 | `test_toggle_model_fields` | Fixture `ft05_fields`; run tool | Read `app/models/feature_toggle.py` | Contains `name`, `enabled`, `rollout_percentage`, `allowed_users`, `environments` (CC-01b) |
| T-06 | `test_toggle_model_registered_in_init` | Fixture `ft06_models_init`; run tool | Read `app/models/__init__.py` | Contains `"FeatureToggle"` (INV-FT-12, CC-01c) |

### 10.3 Category C — Schemas (T-07 .. T-08)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | `test_schemas_created` | Fixture `ft07_schemas`; run tool | Check `app/schemas/feature_toggle.py` | File exists (CC-02) |
| T-08 | `test_schemas_classes` | Fixture `ft08_schema_classes`; run tool | Read `app/schemas/feature_toggle.py` | Contains `class ToggleCreate`, `class ToggleUpdate`, `class ToggleRead`, `class ToggleEvaluate` (CC-02b) |

### 10.4 Category D — CRUD (T-09 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | `test_crud_created` | Fixture `ft09_crud`; run tool | Check `app/crud/feature_toggle.py` | File exists (CC-03) |
| T-10 | `test_crud_functions` | Fixture `ft10_crud_fns`; run tool | Read `app/crud/feature_toggle.py` | Contains `async def get_by_name`, `async def list_toggles`, `async def create`, `async def update`, `async def delete` (CC-03b) |

### 10.5 Category E — Evaluator (T-11 .. T-15)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_evaluator_created` | Fixture `ft11_evaluator`; run tool | Check `app/features/evaluator.py` | File exists (CC-04) |
| T-12 | `test_evaluator_uses_hash_bucketing` | Fixture `ft12_hash`; run tool | Read `app/features/evaluator.py` | Contains `"hashlib"` and `"sha256"` (INV-FT-04, CC-04b) |
| T-13 | `test_evaluator_checks_disabled_first` | Fixture `ft13_disabled`; run tool | Read `app/features/evaluator.py` | Contains `"toggle.enabled"` and `'"disabled"'` (INV-FT-05, CC-04c) |
| T-14 | `test_evaluator_allowlist_priority` | Fixture `ft14_allowlist`; run tool | Read `app/features/evaluator.py` | Contains `"allowed_users"` and `'"allowlist"'` (INV-FT-06, CC-04d) |
| T-15 | `test_evaluator_environment_gate` | Fixture `ft15_envgate`; run tool | Read `app/features/evaluator.py` | Contains `"environments"` and `"environment_gate"` (INV-FT-07, CC-04e) |

### 10.6 Category F — Service (T-16 .. T-20)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-16 | `test_service_created` | Fixture `ft16_service`; run tool | Read `app/features/service.py` | File exists; contains `"class FeatureToggleService"` (CC-05) |
| T-17 | `test_service_is_enabled` | Fixture `ft17_is_enabled`; run tool | Read `app/features/service.py` | Contains `"async def is_enabled"` (CC-05b) |
| T-18 | `test_service_env_var_priority` | Fixture `ft18_envpriority`; run tool | Read `app/features/service.py` | Contains `"os.getenv"` (INV-FT-08, CC-05c) |
| T-19 | `test_service_ttl_cache` | Fixture `ft19_cache`; run tool | Read `app/features/service.py` | Contains `"CACHE_TTL"` or `"_CACHE_TTL"` and `"_CACHE"` (INV-FT-09, CC-05d) |
| T-20 | `test_features_init_created` | Fixture `ft20_init`; run tool | Read `app/features/__init__.py` | File exists; contains `"FeatureToggleService"` and `"evaluate"` (CC-05e) |

### 10.7 Category G — Routes (T-21 .. T-24)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-21 | `test_routes_created` | Fixture `ft21_routes`; run tool | Check `app/api/routes/feature_toggles.py` | File exists (CC-06) |
| T-22 | `test_routes_has_crud_endpoints` | Fixture `ft22_route_fns`; run tool | Read routes file | Contains `async def list_toggles`, `async def create_toggle`, `async def update_toggle`, `async def delete_toggle`, `async def evaluate_toggle` (CC-06b) |
| T-23 | `test_routes_require_superuser` | Fixture `ft23_superuser`; run tool | Read routes file | Contains `"CurrentSuperuser"` (INV-FT-10, CC-06c) |
| T-24 | `test_routes_evaluate_endpoint` | Fixture `ft24_evaluate_ep`; run tool | Read routes file | Contains `"/evaluate"` and `"ToggleEvaluateResult"` (CC-06d) |

### 10.8 Category H — Migration (T-25 .. T-26)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | `test_migration_created` | Fixture `ft25_migration`; run tool | `glob("*feature_toggles*")` in `alembic/versions/` | At least 1 file (INV-FT-14, CC-07) |
| T-26 | `test_migration_content` | Fixture `ft26_migration_content`; run tool | Read migration file | Contains `"def upgrade"`, `"def downgrade"`, `"feature_toggles"`, `"rollout_percentage"` (INV-FT-13, CC-07b) |

### 10.9 Category I — Meta (T-27 .. T-31)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-27 | `test_idempotent_returns_no_op` | Fixture `ft27_idempotent`; run tool twice | Check second result | `r2.status == "no_op"` and `r2.files_created == []` (INV-FT-01, CC-08) |
| T-28 | `test_idempotent_project_parses` | Fixture `ft28_idempotent_parse`; run tool twice | AST-parse all `.py` | No `SyntaxError` (INV-FT-01, INV-FT-03, CC-08b) |
| T-29 | `test_dry_run_writes_nothing` | Fixture `ft29_dry_run`; snapshot `.py` files | `add_feature_toggles_api(ToolInput(dry_run=True))` | `status == "success"`; empty lists; byte-identical (INV-FT-02, CC-09) |
| T-30 | `test_all_py_files_parse` | Fixture `ft30_parse_all`; run tool | AST-parse all `.py` | No `SyntaxError` (INV-FT-03, CC-10) |
| T-31 | `test_execution_time_ms_populated` | Fixture `ft31_elapsed`; run tool | Check `result.execution_time_ms` | `isinstance(int)` and `>= 0` (INV-FT-15, CC-11) |

### 10.10 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/auth_access/test_add_feature_toggles_api.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/auth_access/test_add_feature_toggles_api.py
```

Target: 31/31 passed, 0 failed. The standalone runner prints `31/31 passed`.

---

## 11. Interaction Matrix

How `add_feature_toggles_api` composes with other SKILL-001 tools. Tool IDs match `specs/` directory.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_feature_flags` (TOOL-009) | Yes | ✅ Compatible — feature_flags FIRST | `is_enabled` checks `os.getenv` before DB; env-var flags continue to work unchanged after TOOL-064 is applied |
| `add_rbac` (TOOL-012) | No | ✅ Compatible | RBAC roles can be used to restrict which users can call `is_enabled` with which toggle names; `CurrentSuperuser` on admin routes is already enforced |
| `add_multi_tenancy` (TOOL-008) | Yes | ⚠️ Caveat — tenancy FIRST | `FeatureToggle` model has no `tenant_id`; add it manually after multi-tenancy if per-tenant toggle isolation is required |
| `add_audit_log` (TOOL-005) | No | ✅ Compatible | `create_toggle`, `update_toggle`, `delete_toggle` admin route handlers should emit audit entries; use `updated_at` column as change timestamp |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | arq task handlers can call `await svc.is_enabled(...)` to gate task behaviour; pass a DB session opened in the worker `startup` hook |
| `add_notifications` (TOOL-063) | No | ✅ Compatible | Toggle `await svc.is_enabled("new_notification_type", user_id=...)` before calling `NotificationService.send()` to gate rollout of new notification categories |
| `add_cache_layer` (TOOL-021) | No | ⚠️ Caveat | `add_feature_toggles_api` ships its own in-process TTL cache; do NOT layer a separate Redis cache on top of `is_enabled` — double-caching complicates invalidation |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | Service-to-service API keys are `CurrentUser` identities; pass `user_id=str(api_key.id)` to `is_enabled` for per-key rollout |
| `add_webhook_receiver` (TOOL-016) | No | ✅ Compatible | Gate new webhook event types behind a toggle; failed toggles fall back to legacy handler path |
| `add_sse` (TOOL-014) | No | ✅ Compatible | Push `toggle.updated` SSE events to connected admins when `update_toggle` succeeds so UI refreshes without polling |
| `add_event_driven` (TOOL-046) | No | ✅ Compatible | Publish `toggle.created`/`toggle.updated`/`toggle.deleted` events from admin routes for audit consumers |
| `add_outbox_pattern` (TOOL-023) | No | ⚠️ Caveat | Toggle evaluation itself does not benefit from the outbox; only outbound side-effects triggered by the gated code paths might |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | Register `FeatureToggle` as a `ModelAdmin` with inline editing of `rollout_percentage`, `allowed_users` JSON, `environments` JSON; do NOT expose raw `id` editing |
| `add_rate_limiting` (TOOL-057) | No | ✅ Compatible | Rate-limit `POST /feature-toggles` admin endpoint to prevent accidental bulk creation; `GET /` and `POST /{name}/evaluate` have lower risk |
| `add_scheduled_tasks` (TOOL-058) | No | ✅ Compatible | Scheduled tasks can call `is_enabled` with a system service account `user_id` to gate new scheduled behaviour |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Gate new checkout flows via toggles; `await svc.is_enabled("new_checkout", user_id=...)` in the checkout route |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | `GET /feature-toggles` currently returns all rows; add cursor pagination by `name` when toggle count exceeds a few hundred |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `FeatureToggle` rows should NOT use soft-delete; physical delete via `DELETE /feature-toggles/{name}` is the intended lifecycle; keep audit via `add_audit_log` instead |
| `add_data_export` (TOOL-006) | No | ✅ Compatible | Exporting `feature_toggles` rows for compliance is safe; `allowed_users` JSON may contain user IDs — consider PII scrubbing before export |
| `add_search` (TOOL-004) | No | ✅ Compatible | Filter toggle list by `name` prefix; full-text search over `allowed_users` JSON is not recommended |

**Conflicts:** None identified. `add_feature_toggles_api` is a superset of `add_feature_flags` (TOOL-009); the two are designed to coexist with env-var flags taking priority.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/models/__init__.py \
  app/core/config.py \
  app/routes/__init__.py

rm -f \
  app/models/feature_toggle.py \
  app/schemas/feature_toggle.py \
  app/crud/feature_toggle.py \
  app/api/routes/feature_toggles.py

rm -rf \
  app/features/

# Remove the migration file
rm -f alembic/versions/0064_add_feature_toggles_api.py
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops feature_toggles table + ix_feature_toggles_name
```

The `downgrade()` function runs:

```python
op.drop_index("ix_feature_toggles_name", "feature_toggles")
op.drop_table("feature_toggles")
```

### 12.3 Data preservation rollback

If toggle configuration has operational significance, archive before downgrade:

```sql
CREATE TABLE feature_toggles_archive_<date> AS SELECT * FROM feature_toggles;
-- or: COPY feature_toggles TO '/backup/feature_toggles_<date>.csv' WITH CSV HEADER;
```

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -path '*/features/*.py' -newer alembic/versions/ -delete
find . -name 'feature_toggle.py' -delete
```

The tool writes files one at a time and validates syntax at the end. A mid-execution failure may leave partial files. `git checkout HEAD --` on modified files plus `rm` on newly-created paths restores the project.

### 12.5 Emergency: hot-disable all DB toggles without rollback

To bypass DB evaluation without removing the code:

1. Set env var overrides for critical toggles: `FEATURE_X=false` (env-var priority fires first, DB not consulted).
2. Set `FEATURE_TOGGLES_CACHE_TTL_SECONDS=1` to minimise stale cache window.
3. This is a non-destructive, reversible override — no migration, no rollback needed.

### 12.6 Uninstall validator

After rollback, verify:

```bash
test ! -d app/features || (echo "app/features still present" && exit 1)
test ! -f app/models/feature_toggle.py || (echo "FeatureToggle model still present" && exit 1)
grep -q "FeatureToggle" app/models/__init__.py && echo "models init still patched" && exit 1
grep -q "FEATURE_TOGGLES_CACHE_TTL_SECONDS" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", ...)` with `execution_time_ms > 0` |
| EC-02 | Prerequisites not met (`BASE_MODEL`, `MODELS_INIT`, etc.) | `ensure_prerequisites` returns errors → `status="error"` with list of missing prereqs |
| EC-03 | `app/models/feature_toggle.py` already contains `FeatureToggle` | Early return `status="no_op"` — zero file writes (INV-FT-01) |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with notes; NO file touched; `execution_time_ms` still recorded (INV-FT-02) |
| EC-05 | `app/core/config.py` already contains `FEATURE_TOGGLES_CACHE_TTL_SECONDS` | `_patch_config` early-returns; no duplicate field appended |
| EC-06 | `app/core/config.py` has no `class Settings` line | `_patch_config` early-returns silently (cannot anchor safely) |
| EC-07 | `app/models/__init__.py` already imports `FeatureToggle` | `_patch_models_init` early-returns after `marker in content` check — no duplicate import |
| EC-08 | `app/routes/__init__.py` already contains `feature_toggles` | `_patch_routes_init` early-returns after `"feature_toggles" in content` check |
| EC-09 | `app/routes/__init__.py` does not exist | Route registration step is skipped (`if routes_init.exists():`); router must be registered manually |
| EC-10 | `alembic/versions/` missing | Migration write step is skipped (`if versions_dir.exists():`); other writes proceed |
| EC-11 | `find_migration_head` returns `None` | Falls back to `"0001_initial"` in `down_revision` |
| EC-12 | Generated `evaluator.py` fails `ast.parse` (template bug) | Returns `status="error"` with path + syntax error message; partial files remain |
| EC-13 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `feature_toggle.py` |
| EC-14 | `app/crud/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-15 | `app/features/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` by each step helper |
| EC-16 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-17 | `_bucket` called with empty `user_id` | `_bucket("flag", "")` produces a deterministic bucket for the empty string; callers should pass `user_id=None` rather than `""` to trigger the `"no_user_id"` branch |
| EC-18 | `allowed_users` JSON column is `null` in DB (legacy row) | `toggle.allowed_users or []` guard in `evaluate` prevents `TypeError` on `in` check |
| EC-19 | `environments` JSON column is `null` in DB | `toggle.environments or []` guard prevents `TypeError` |
| EC-20 | Tool runs twice back-to-back in CI | Second run returns `no_op`; project AST remains parseable (T-27, T-28) |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 31 test cases verified via `test_add_feature_toggles_api.py` passing
2. ✅ `test_add_feature_toggles_api.py` reports `31/31 passed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created` (INV-FT-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-FT-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-FT-03)
7. ✅ `_bucket` uses `hashlib.sha256` — deterministic across restarts (INV-FT-04)
8. ✅ Evaluation order: `disabled` → `allowlist` → `environment_gate` → `full_rollout` → `zero_rollout` → `hash_bucket` → `no_user_id` (INV-FT-05, INV-FT-06, INV-FT-07)
9. ✅ `is_enabled` checks `os.getenv` before DB — env-var flags take priority (INV-FT-08)
10. ✅ In-process `_CACHE` dict provides TTL caching; `_invalidate` called on write operations (INV-FT-09)
11. ✅ All 5 admin routes declare `CurrentSuperuser` (INV-FT-10)
12. ✅ `create_toggle` returns 409 on duplicate name (INV-FT-11)
13. ✅ `FeatureToggle` registered in `app/models/__init__.py` (INV-FT-12)
14. ✅ Migration has `ck_feature_toggles_rollout_range` CHECK constraint (INV-FT-13)
15. ✅ Developer successfully creates a toggle, evaluates it for a user, verifies bucket is stable, updates percentage, and verifies cache invalidation

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT, BASE_MODEL, MODELS_INIT, ALEMBIC_VERSIONS)` passes
- [ ] `app/models/feature_toggle.py` does NOT contain `"FeatureToggle"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 FeatureToggle model

- [ ] `_write_toggle_model(toggle_model_file)` creates `app/models/feature_toggle.py`
- [ ] Model has `id` (UUID PK), `name` (String(127), unique, indexed), `enabled` (Boolean), `rollout_percentage` (Integer, default 100), `allowed_users` (JSON, default []), `environments` (JSON, default []), `created_at`, `updated_at`
- [ ] `_patch_models_init(app_dir / "models" / "__init__.py", "feature_toggle", "FeatureToggle")` appends import idempotently
- [ ] `app/models/__init__.py` appended to `files_modified`

### 15.3 Pydantic schemas

- [ ] `mkdir -p app/schemas`
- [ ] `_write_toggle_schemas(schema_file)` writes `app/schemas/feature_toggle.py`
- [ ] Schema file contains `ToggleCreate`, `ToggleUpdate`, `ToggleRead`, `ToggleEvaluate`, `ToggleEvaluateResult`
- [ ] `ToggleUpdate` uses `ConfigDict(from_attributes=True)` and all fields are `| None`
- [ ] `ToggleCreate` has `rollout_percentage: int = Field(default=100, ge=0, le=100)`

### 15.4 Async CRUD

- [ ] `mkdir -p app/crud`
- [ ] `_write_toggle_crud(crud_file)` writes `app/crud/feature_toggle.py`
- [ ] CRUD has `async def get_by_name`, `async def list_toggles`, `async def create`, `async def update`, `async def delete`
- [ ] `list_toggles` uses `ORDER BY FeatureToggle.name`
- [ ] `create` calls `session.add(toggle)`, `await session.flush()`, `await session.refresh(toggle)`
- [ ] `update` uses `toggle_in.model_dump(exclude_unset=True)` to avoid clearing unset fields
- [ ] `delete` calls `await session.delete(toggle)`, `await session.flush()`

### 15.5 Rule evaluator

- [ ] `mkdir -p app/features`
- [ ] `_write_toggle_evaluator(evaluator_file)` writes `app/features/evaluator.py`
- [ ] `evaluate(toggle, *, user_id, environment)` follows 7-step order
- [ ] `_bucket(toggle_name, user_id)` uses `hashlib.sha256` — NOT `hash()`
- [ ] `_bucket` returns `int.from_bytes(digest[:4], "big", signed=False) % 100`

### 15.6 FeatureToggleService

- [ ] `_write_toggle_service(service_file)` writes `app/features/service.py`
- [ ] `_CACHE: dict[str, tuple[float, Any]] = {}` at module level
- [ ] `_CACHE_TTL: int = int(os.getenv("FEATURE_TOGGLES_CACHE_TTL_SECONDS", "60"))`
- [ ] `_TRUTHY = {"1", "true", "yes", "on"}` and `_FALSY = {"0", "false", "no", "off"}`
- [ ] `is_enabled` checks env-var FIRST, then `_load(name)`
- [ ] `_load` checks `_CACHE` and respects TTL via `time.monotonic()`
- [ ] `_invalidate(name)` calls `_CACHE.pop(name, None)` — called from `create_toggle` and `update_toggle`
- [ ] `create_toggle`, `update_toggle`, `list_toggles` methods implemented

### 15.7 Features package init

- [ ] `_write_features_init(features_init)` writes `app/features/__init__.py`
- [ ] Re-exports `evaluate` from `app.features.evaluator`
- [ ] Re-exports `FeatureToggleService` from `app.features.service`
- [ ] `__all__ = ["FeatureToggleService", "evaluate"]`

### 15.8 Admin REST routes

- [ ] `mkdir -p app/api/routes`
- [ ] `_write_toggle_routes(routes_file)` writes `app/api/routes/feature_toggles.py`
- [ ] `APIRouter(prefix="/feature-toggles", tags=["feature-toggles"])`
- [ ] `GET /` → `list_toggles` (superuser)
- [ ] `POST /` → `create_toggle` (superuser; 409 on duplicate name)
- [ ] `PUT /{name}` → `update_toggle` (superuser; 404 if not found)
- [ ] `DELETE /{name}` → `delete_toggle` (superuser; 204; 404 if not found)
- [ ] `POST /{name}/evaluate` → `evaluate_toggle` (superuser; 404 if not found; returns `ToggleEvaluateResult`)

### 15.9 Config patch

- [ ] `_patch_config(config_file)` early-returns if `"FEATURE_TOGGLES_CACHE_TTL_SECONDS" in content`
- [ ] Inserts `\n    FEATURE_TOGGLES_CACHE_TTL_SECONDS: int = 60\n` after the `class Settings` header line
- [ ] `config_file` appended to `files_modified`

### 15.10 Routes init patch

- [ ] `_patch_routes_init(routes_init)` early-returns if `"feature_toggles" in content`
- [ ] Appends `# Feature Toggles API\nfrom app.api.routes import feature_toggles  # noqa: F401\napi_router.include_router(feature_toggles.router)`
- [ ] `routes_init` appended to `files_modified`

### 15.11 Alembic migration

- [ ] `_write_toggle_migration(versions_dir)` generates `0064_add_feature_toggles_api.py`
- [ ] `find_migration_head(versions_dir) or "0001_initial"` resolves `down_revision`
- [ ] Migration creates `feature_toggles` table with all columns
- [ ] `ck_feature_toggles_rollout_range` CHECK constraint on `rollout_percentage`
- [ ] `ix_feature_toggles_name` unique index
- [ ] `downgrade()` drops index first, then table

### 15.12 Validation

- [ ] Loop over `files_created`; for every `.py` that is a file, `ast.parse(p.read_text())`
- [ ] On `SyntaxError`: return `ToolResult(status="error", error=f"Generated file has syntax error: {p}: {exc}", ...)`

### 15.13 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` describe rollout mechanism, allowlist priority, environment gate, env-var priority, TTL cache
- [ ] `next_steps` contain `"alembic upgrade head"`, cache TTL env var hint, router wire hint, superuser dep hint, evaluate endpoint hint

### 15.14 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring explains env-var priority, bucket algorithm, TTL cache strategy
- [ ] `add_feature_toggles_api` docstring explains coexistence with `add_feature_flags`

---

## 16. Documentation Output

Example `ToolResult` JSON (success path, fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/models/feature_toggle.py",
    "/tmp/fixture/app/schemas/feature_toggle.py",
    "/tmp/fixture/app/crud/feature_toggle.py",
    "/tmp/fixture/app/features/evaluator.py",
    "/tmp/fixture/app/features/service.py",
    "/tmp/fixture/app/features/__init__.py",
    "/tmp/fixture/app/api/routes/feature_toggles.py",
    "/tmp/fixture/alembic/versions/0064_add_feature_toggles_api.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/models/__init__.py",
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py"
  ],
  "notes": [
    "Feature toggle API system added: model, schemas, CRUD, evaluator, service, routes.",
    "Percentage rollout uses hash(user_id + flag_name) % 100 — fully deterministic.",
    "User allowlist takes priority over percentage rollout.",
    "Environment gate blocks evaluation when app env is not in allowed list.",
    "Env-var flags (add_feature_flags) take priority over DB toggles.",
    "In-memory TTL cache avoids DB hit on hot paths (FEATURE_TOGGLES_CACHE_TTL_SECONDS)."
  ],
  "next_steps": [
    "alembic upgrade head",
    "Set FEATURE_TOGGLES_CACHE_TTL_SECONDS=60 in .env (default: 60)",
    "Wire router: include_router(feature_toggles.router) in app/routes/__init__.py",
    "Admin endpoints require superuser — use CurrentSuperuser dep.",
    "POST /feature-toggles/{name}/evaluate for client-side flag checks."
  ],
  "execution_time_ms": 103
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "FeatureToggle model already present — toggle API system already enabled, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 2
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create: FeatureToggle model, service, evaluator, CRUD, routes, schemas, migration.",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return (prereq failure):

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - BASE_MODEL: app/models/base.py missing\n  - CONFIG_SETTINGS: app/core/config.py missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 2
}
```

---
