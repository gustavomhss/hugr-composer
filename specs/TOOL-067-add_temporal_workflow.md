---
spec_id: "TOOL-067"
tool_name: "add_temporal_workflow"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-TMP-01"
  - "INV-TMP-02"
  - "INV-TMP-03"
  - "INV-TMP-04"
  - "INV-TMP-05"
  - "INV-TMP-06"
  - "INV-TMP-07"
  - "INV-TMP-08"
  - "INV-TMP-09"
  - "INV-TMP-10"
  - "INV-TMP-11"
  - "INV-TMP-12"
  - "INV-TMP-13"
  - "INV-TMP-14"
  - "INV-TMP-15"
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
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
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
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-067: add_temporal_workflow

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_temporal_workflow` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, temporalio SDK, pydantic-settings |
| Signature | `add_temporal_workflow(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_temporal_workflow", "description": "Add a Temporal.io durable workflow engine with order-processing example, compensation pattern, signal support, and REST companion routes.", "tags": ["extend", "infrastructure"], "entry": "add_temporal_workflow"}` |
| Files created (typical) | 7+ — `app/workflows/__init__.py`, `app/workflows/client.py`, `app/workflows/worker.py`, `app/workflows/activities.py`, `app/workflows/example_workflow.py`, `app/api/routes/workflows.py`, `Dockerfile.temporal-worker` |
| Files modified (typical) | 3 — `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_temporal_workflow` tool installs a Temporal.io durable workflow engine into a FastAPI project. Teams reach for arq or Celery for background jobs, but those queues share a fundamental limitation: if the worker process restarts mid-job, the job is either lost (arq with no DB audit) or must be reconstructed from scratch (Celery with a result backend). Temporal solves the durability problem at the platform level: every activity execution, signal, and state transition is persisted as an event in Temporal's journal — the workflow resumes from the last committed event after any process restart, network failure, or deploy cycle. This makes Temporal the right choice for long-running business processes (order fulfilment, multi-step payments, subscription provisioning) where losing work mid-flight has business cost.

The tool generates the full Temporal integration: (a) `app/workflows/client.py` — a `TemporalClientFactory` class with a `connect()` method that imports `temporalio.client.Client` lazily and a `get_client()` module-level singleton function so the FastAPI app and REST routes share one connection; (b) `app/workflows/worker.py` — a `WorkerFactory` class whose `create(client)` method applies `@activity.defn` to the four activity functions and returns a configured `Worker`, plus `start_worker()` and `stop_worker()` lifecycle helpers and a `main()` entry point for `python -m app.workflows.worker`; (c) `app/workflows/activities.py` — four `async def` activity functions (`validate_order`, `charge_payment`, `fulfil_order`, `compensate_payment`) each with a lazy `from temporalio import activity` import inside their bodies and retry metadata applied via `_apply_retry_policy(fn, schedule_to_close=N)` helper so they are importable without the SDK; (d) `app/workflows/example_workflow.py` — `OrderProcessingWorkflow` with three sequential activity phases and a compensation-on-failure pattern in `_fulfil()` that calls `compensate_payment` when `fulfil_order` raises, a `cancel` signal handler, a `status` query handler, and a `try/except ModuleNotFoundError` block at module level so the class is importable without the SDK for unit tests; (e) `app/api/routes/workflows.py` — four REST endpoints (`POST /workflows/start`, `GET /workflows/{id}/status`, `POST /workflows/{id}/signal`, `POST /workflows/{id}/cancel`) that import the Temporal client lazily and return HTTP 503 when the SDK is unavailable; (f) `Dockerfile.temporal-worker` — a `python:3.12-slim` base image that creates a non-root user `worker` with UID 1000 and runs `CMD ["python", "-m", "app.workflows.worker"]`; and (g) patches to `app/core/config.py` (three `TEMPORAL_*` settings inside `class Settings`), `app/routes/__init__.py`, and `requirements.txt`.

Key design decisions: **durable execution** — Temporal's server persists every event; the workflow resumes from the last committed state after any restart without application-level checkpointing code. **Compensation pattern** — `OrderProcessingWorkflow._fulfil()` wraps `fulfil_order` in `try/except` and calls `compensate_payment` on failure, guaranteeing no phantom charges. **Signals + queries** — `cancel` signal aborts mid-flight execution between phases; `status` query returns the current phase without polling the DB. **Separate worker process** — `app/main.py` is NOT modified; the FastAPI app and the Temporal worker are completely decoupled so a memory leak in an activity cannot take down the API tier. **Lazy SDK import** — `temporalio` is imported inside function bodies throughout so `app.main` boots without the optional SDK installed; verified by an AST-based test. **Non-root container** — `Dockerfile.temporal-worker` runs as UID 1000 for least-privilege execution. The tool is idempotent: it detects `TemporalClientFactory` in `app/workflows/client.py` and returns `status="no_op"` on second invocation.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-13) |
| Files created | ≥ 6 | Workflows package init, client, worker, activities, example workflow, REST routes, Dockerfile (CC-04) |
| Files modified | ≥ 2 | Config and requirements — at least two must exist (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (CC-07) |
| `POST /workflows/start` latency | < 100 ms | Single Temporal `client.start_workflow` call; bounded by network RTT to Temporal server |
| `GET /workflows/{id}/status` latency | < 50 ms | Single `handle.query(lambda wf: wf.status())` Temporal gRPC call |
| `POST /workflows/{id}/signal` latency | < 50 ms | Single `handle.signal("cancel")` gRPC call |
| Worker cold start | < 30 s | Slim Python 3.12 base + `pip install -r requirements.txt` |
| Workflow resume after restart | < 2 s | Temporal replays journal events from last committed state |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no workflow engine
│   ├── core/
│   │   └── config.py        # Settings class, no TEMPORAL_* fields
│   ├── routes/
│   │   └── __init__.py      # api_router, no workflows router
│   └── api/
│       └── deps.py          # CurrentUser dependency
└── requirements.txt         # no temporalio
```

Long-running business processes are implemented as synchronous request handlers or arq jobs. A mid-deploy restart loses in-flight order processing. Compensation logic is ad-hoc and often absent.

### 4.2 Temporal client factory (lazy singleton): AFTER

```python
# app/workflows/client.py
"""Temporal client factory with lazy SDK import and singleton caching."""
from __future__ import annotations
import logging
from typing import Any
from app.core.config import settings

logger = logging.getLogger(__name__)
_client: Any | None = None


class TemporalClientFactory:
    """Factory that creates and caches a Temporal client singleton."""

    def __init__(self, host: str, namespace: str) -> None:
        self.host = host
        self.namespace = namespace

    async def connect(self) -> Any:
        from temporalio.client import Client  # lazy SDK import
        client = await Client.connect(self.host, namespace=self.namespace)
        logger.info(
            "Temporal client connected",
            extra={"host": self.host, "namespace": self.namespace},
        )
        return client


async def get_client() -> Any:
    """Return the process-wide Temporal client, creating it lazily."""
    global _client
    if _client is None:
        factory = TemporalClientFactory(
            host=settings.TEMPORAL_HOST,
            namespace=settings.TEMPORAL_NAMESPACE,
        )
        _client = await factory.connect()
    return _client
```

### 4.3 Compensation workflow (OrderProcessingWorkflow): AFTER

```python
# app/workflows/example_workflow.py  (excerpt)
class OrderProcessingWorkflow:
    """Durable order processing with compensation pattern."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._cancelled: bool = False

    async def _fulfil(self, workflow: Any, order_id: str, charge_id: str) -> dict:
        """Phase 3: fulfil with compensation on failure."""
        from app.workflows.activities import compensate_payment, fulfil_order

        if self._cancelled:
            self._status = "cancelled"
            await workflow.execute_activity(
                compensate_payment, order_id, charge_id,
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {"order_id": order_id, "status": "cancelled"}

        self._status = "fulfilling"
        try:
            result = await workflow.execute_activity(
                fulfil_order, order_id, charge_id,
                start_to_close_timeout=timedelta(seconds=120),
            )
        except Exception:  # noqa: BLE001
            logger.warning("fulfil_order failed, compensating order=%s", order_id)
            await workflow.execute_activity(
                compensate_payment, order_id, charge_id,
                start_to_close_timeout=timedelta(seconds=30),
            )
            self._status = "failed"
            return {"order_id": order_id, "status": "failed", "compensated": True}

        self._status = "completed"
        return {"order_id": order_id, "status": "completed", "charge_id": charge_id,
                "fulfillment_id": result.get("fulfillment_id")}
```

### 4.4 Worker factory (separate process): AFTER

```python
# app/workflows/worker.py  (excerpt)
class WorkerFactory:
    def __init__(self, task_queue: str) -> None:
        self.task_queue = task_queue

    async def create(self, client: Any) -> Any:
        from temporalio import activity as _act  # lazy SDK import
        from temporalio.worker import Worker
        import app.workflows.activities as _acts
        from app.workflows.example_workflow import OrderProcessingWorkflow

        activity_fns = [
            _acts.validate_order,
            _acts.charge_payment,
            _acts.fulfil_order,
            _acts.compensate_payment,
        ]
        registered = [_act.defn(fn) for fn in activity_fns]
        worker = Worker(
            client,
            task_queue=self.task_queue,
            workflows=[OrderProcessingWorkflow],
            activities=registered,
        )
        return worker
```

### 4.5 REST companion routes (start + status): AFTER

```python
# app/api/routes/workflows.py  (excerpts)
@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
async def start_workflow(
    body: StartWorkflowRequest,
    current_user: CurrentUser,
) -> dict:
    _ = current_user  # auth gate only
    try:
        from app.workflows.client import get_client
        from app.workflows.example_workflow import OrderProcessingWorkflow

        client = await get_client()
        workflow_id = f"order-{body.order_id}-{uuid.uuid4().hex[:8]}"
        handle = await client.start_workflow(
            OrderProcessingWorkflow.run, body.order_id, body.amount_cents,
            id=workflow_id, task_queue=_get_task_queue(),
        )
        return {"workflow_id": handle.id, "status": "started"}
    except (ModuleNotFoundError, Exception) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal client unavailable",
        ) from exc
```

### 4.6 Config patch (settings inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "main-queue"
```

The tool inserts these fields before `settings = Settings()` (or appends) so pydantic-settings picks them up from environment variables. `app/main.py` is NOT modified.

### 4.7 Dockerfile.temporal-worker (non-root): AFTER

```dockerfile
# Dockerfile.temporal-worker
FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root user (UID 1000)
RUN adduser --disabled-password --gecos "" --uid 1000 worker
USER 1000

CMD ["python", "-m", "app.workflows.worker"]
```

### 4.8 Typical caller usage (after install)

```python
# From any authenticated route:
from app.workflows.client import get_client
from app.workflows.example_workflow import OrderProcessingWorkflow

client = await get_client()
handle = await client.start_workflow(
    OrderProcessingWorkflow.run,
    order_id,
    amount_cents,
    id=f"order-{order_id}",
    task_queue=settings.TEMPORAL_TASK_QUEUE,
)
# Poll status: GET /workflows/{handle.id}/status
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Pre-flight checks `"TemporalClientFactory" in app/workflows/client.py` and returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return guarded by `if inp.dry_run:` before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | Final loop runs `ast.parse` on each created `.py`; tool returns `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | Every helper in `client.py`, `worker.py`, `activities.py`, `example_workflow.py`, `routes/workflows.py` kept small; asserted by AST walk |
| QS-5 | **`temporalio` SDK never imported at module top level** | All `from temporalio import ...` statements live inside method/function bodies; verified by the AST-based `test_lazy_sdk_import_in_generated_code` test |
| QS-6 | **Compensation pattern implemented** | `_fulfil()` wraps `fulfil_order` in `try/except` and calls `compensate_payment` on failure |
| QS-7 | **`cancel` signal aborts mid-flight execution** | `_cancelled` flag checked between phases; if set, `compensate_payment` is run and workflow exits |
| QS-8 | **Worker runs as a SEPARATE process from FastAPI** | `app/main.py` is NOT in `files_modified`; worker has its own `python -m app.workflows.worker` entry point |
| QS-9 | **`TEMPORAL_*` settings inside `class Settings`** | `_patch_config` inserts fields before `settings = Settings()` with 4-space indent |
| QS-10 | **Worker runs as non-root (UID 1000)** | `Dockerfile.temporal-worker` declares `USER 1000` before `CMD` |
| QS-11 | **All REST routes require `CurrentUser` authentication** | `current_user: CurrentUser` declared on all four endpoints |
| QS-12 | **REST routes return HTTP 503 when Temporal unavailable** | `except (ModuleNotFoundError, Exception)` catches SDK absence and connection failure |
| QS-13 | **`temporalio>=1.7.0` added to requirements** | `_patch_requirements` appends when `"temporalio"` absent |
| QS-14 | **`get_client()` is a lazy singleton** | Module-level `_client: Any | None = None`; cached on first call, reused on subsequent calls |
| QS-15 | **`OrderProcessingWorkflow` is importable without SDK** | `try/except ModuleNotFoundError` block applies Temporal decorators only when SDK is available |
| QS-16 | **Activity functions have retry metadata** | `_apply_retry_policy(fn, schedule_to_close=N)` tags each activity; `WorkerFactory.create` applies `activity.defn` lazily |
| QS-17 | **Tool records execution time** | `ToolResult.execution_time_ms` computed via `_elapsed_ms(start)` on every return path; minimum 1 ms |
| QS-18 | **Next steps mention Temporal start action** | `next_steps` includes `"Start a Temporal server"` and SDK install instruction |
| QS-19 | **Second run keeps the project parseable** | No-op path corrupts no file; all `.py` remain AST-valid after two invocations |
| QS-20 | **`app/workflows/__init__.py` re-exports the public API** | Re-exports `TemporalClientFactory`, `get_client`, `WorkerFactory`, `start_worker`, `stop_worker` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_temporal_workflow.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run_writes_nothing`) |
| CC-04 | Tool creates at least 6 new files | `len(result.files_created) >= 6` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-08 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-09 (`test_no_function_over_50_loc`) |
| CC-08 | `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE` exist inside `class Settings` body with 4-space indent | String scan + indent check on line containing `TEMPORAL_HOST` | T-10 (`test_config_fields_patched`) |
| CC-09 | `app/main.py` is NOT in `files_modified` | `"main.py" not in [Path(p).name for p in result.files_modified]` | T-21 (`test_main_py_not_modified`) |
| CC-10 | Workflows router is registered in `app/routes/__init__.py` when that file exists | `"workflows" in content.lower()` of `routes/__init__.py` | T-19 (`test_routes_registered_in_routes_init`) |
| CC-11 | All domain-specific files exist with correct content | Multiple sub-assertions per domain file (see section 10.3) | T-12..T-18 |
| CC-12 | `requirements.txt` contains `temporalio>=` pin | `"temporalio>=" in content` of `requirements.txt` | T-11 (`test_requirements_patched`) |
| CC-13 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-06 (`test_execution_time_recorded`) |
| CC-14 | `next_steps` is non-empty and mentions `temporal` | Lowercased join of `next_steps` contains `"temporal"` | T-07 (`test_next_steps_present`) |
| CC-15 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` after two runs | T-22 (`test_idempotent_project_still_parses`) |
| CC-16 | `app/workflows/client.py` contains `TemporalClientFactory` and `get_client` | File exists + both names present | T-13 (`test_client_module_created`) |
| CC-17 | `temporalio` is NOT imported at module top level in any generated workflow file | AST scan: no unindented `from temporalio` or `import temporalio` outside a `try:` block | T-20 (`test_lazy_sdk_import_in_generated_code`) |
| CC-18 | `app/workflows/activities.py` contains all 4 activities including `compensate_payment` | Substring checks for all four function names | T-16 (`test_activities_module_created`) |
| CC-19 | `Dockerfile.temporal-worker` runs as non-root (UID 1000) | File exists + `"USER"` + `"1000"` in content | T-18 (`test_dockerfile_temporal_worker_created`) |
| CC-20 | `app/api/routes/workflows.py` contains all 4 REST route handlers | Substring checks for `start_workflow`, `get_workflow_status`, `signal_workflow`, `cancel_workflow` | T-17 (`test_workflow_routes_created`) |

---

## 7. Definition of Done (DoD)

- [ ] All 22 tests in `test_add_temporal_workflow.py` pass
- [ ] `add_temporal_workflow.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_temporal_workflow.py` detects `"TemporalClientFactory"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] All `from temporalio import ...` statements are inside function/method bodies — never at module top level
- [ ] `OrderProcessingWorkflow._fulfil()` calls `compensate_payment` when `fulfil_order` raises
- [ ] `cancel` signal handler sets `_cancelled = True`; checked between workflow phases
- [ ] `app/main.py` is NOT in `files_modified`
- [ ] `Dockerfile.temporal-worker` declares `USER 1000` before `CMD`
- [ ] `TEMPORAL_*` fields are inside `class Settings` with 4-space indent
- [ ] `get_client()` caches connection in module-level `_client` singleton
- [ ] All four REST routes declare `current_user: CurrentUser`
- [ ] `_elapsed_ms(start)` returns minimum 1 (never 0)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-TMP-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"TemporalClientFactory" in client_file.read_text()` short-circuits to `status="no_op"` | T-02, T-22 |
| INV-TMP-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-TMP-03 | Every generated `.py` file MUST parse as valid Python | Final loop `ast.parse(p.read_text())` for each created `.py` | T-08, T-22 |
| INV-TMP-04 | `temporalio` MUST be imported lazily inside function bodies throughout | No unindented `from temporalio` or `import temporalio` outside a `try:` block in any generated workflow file | T-20 |
| INV-TMP-05 | Compensation MUST run when `fulfil_order` raises | `_fulfil()` wraps activity in `try/except` and calls `compensate_payment` on failure | T-16 (review of example_workflow) |
| INV-TMP-06 | `app/main.py` MUST NOT be modified | `"main.py"` absent from `files_modified` | T-21 |
| INV-TMP-07 | Worker container MUST run as non-root (UID 1000) | `Dockerfile.temporal-worker` declares `USER 1000` before `CMD` | T-18 |
| INV-TMP-08 | `TEMPORAL_*` settings MUST live inside `class Settings` body | `_patch_config` inserts before `settings = Settings()` with 4-space indent | T-10 |
| INV-TMP-09 | All REST routes MUST require `CurrentUser` authentication | `current_user: CurrentUser` declared on all four endpoints | T-10 (routes review) |
| INV-TMP-10 | `get_client()` MUST be a lazy singleton | Module-level `_client` cached on first call; never reconnects on subsequent calls | T-13 |
| INV-TMP-11 | `OrderProcessingWorkflow` MUST be importable without SDK | `try/except ModuleNotFoundError` block at module level | T-15 (workflow review), T-20 |
| INV-TMP-12 | Alembic is NOT required | TOOL-067 has no Alembic dependency — it writes no DB models | None (by design; confirmed by file list) |
| INV-TMP-13 | `ToolResult.execution_time_ms` MUST be positive (≥ 1) on every return path | `_elapsed_ms(start)` returns `max(1, int(...))` | T-06 |
| INV-TMP-14 | `next_steps` MUST reference Temporal start action | Hard-coded string in the success branch | T-07 |
| INV-TMP-15 | `temporalio>=1.7.0` MUST be added to `requirements.txt` | `_patch_requirements` appends when `"temporalio"` absent | T-11 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install Temporal into a clean FastAPI project**
- **As a** backend engineer adding durable workflows
- **I want** to run one tool call and get the full Temporal kit
- **So that** I stop hand-rolling compensating transactions
- **Given:** A FastAPI project with `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt`
- **When:** `add_temporal_workflow(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-TMP-01)
  - `files_created` contains ≥ 6 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - `app/main.py` is NOT in `files_modified` (INV-TMP-06)
  - Verified by T-01, T-04, T-05, T-21

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **Given:** Project where `app/workflows/client.py` already contains `TemporalClientFactory`
- **When:** `add_temporal_workflow(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-TMP-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-TMP-03)
  - Verified by T-02, T-22

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **Given:** Fresh FastAPI fixture project
- **When:** `add_temporal_workflow(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-TMP-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **Given:** Tool just emitted `client.py`, `worker.py`, `activities.py`, `example_workflow.py`, `routes/workflows.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-09

**US-05: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `TEMPORAL_HOST=temporal:7233` in `.env` to take effect
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `TEMPORAL_HOST` inside `class Settings` picks up env var (INV-TMP-08)
  - Verified by T-10

### 9.2 Workflow execution and compensation (US-06 .. US-10)

**US-06: Start an order-processing workflow via REST**
- **As a** checkout service
- **I want** `POST /workflows/start` with `order_id` and `amount_cents`
- **So that** the order is processed durably regardless of restarts
- **Given:** Temporal server running at `TEMPORAL_HOST`
- **When:** Authenticated POST to `/workflows/start`
- **Then:**
  - `get_client()` returns the singleton client (INV-TMP-10)
  - `client.start_workflow(OrderProcessingWorkflow.run, ...)` enqueues the workflow
  - Returns `{"workflow_id": "order-...", "status": "started"}` with HTTP 202
  - Verified by T-17 (routes review)

**US-07: Workflow compensates on fulfilment failure**
- **As a** payment system
- **I want** a captured charge to be voided if fulfilment fails
- **So that** no phantom charges appear on customer statements
- **Given:** `fulfil_order` activity raises an exception
- **When:** Temporal executes `_fulfil()`
- **Then:**
  - `compensate_payment(order_id, charge_id)` is called (INV-TMP-05)
  - Workflow sets `_status = "failed"` and returns `{"compensated": True}` (CC-18, QS-6)
  - Verified by T-16

**US-08: Cancel a running workflow via signal**
- **As a** user who changes their mind
- **I want** `POST /workflows/{id}/signal` to cancel the workflow
- **So that** I do not pay for an order I cancelled
- **Given:** Workflow is between phases (e.g. between validate and charge)
- **When:** Signal arrives
- **Then:**
  - `handle.signal("cancel")` delivers the `cancel` signal
  - `_cancelled` is set to `True`; next phase check triggers `compensate_payment` (QS-7)
  - Returns `{"workflow_id": ..., "status": "signal_sent"}` HTTP 200
  - Verified by T-17

**US-09: Query workflow status without polling DB**
- **As a** frontend polling for order status
- **I want** `GET /workflows/{id}/status`
- **So that** I avoid a DB round-trip on every poll
- **Given:** Workflow is in `"fulfilling"` phase
- **When:** GET request arrives
- **Then:**
  - `handle.query(lambda wf: wf.status())` returns `"fulfilling"` from Temporal's in-memory state
  - Response is `{"workflow_id": ..., "status": "fulfilling"}` (CC-20)
  - Verified by T-17 (routes review)

**US-10: Workflow survives a worker restart**
- **As a** reliability engineer
- **I want** in-flight workflows to resume after a `docker restart myapp-temporal-worker`
- **So that** no order is lost during deploys
- **Given:** Temporal server has the event journal for `order-123-abc`
- **When:** Worker restarts
- **Then:**
  - Worker reconnects via `start_worker()` → `get_client()` → `WorkerFactory.create(client)`
  - Temporal replays the event journal; workflow resumes from the last committed activity
  - No application-level checkpoint code required
  - Verified by Temporal platform design (external to tool scope)

### 9.3 Lazy SDK and separate process (US-11 .. US-15)

**US-11: API container boots without temporalio installed**
- **As a** container health-checker
- **I want** `app.main` to import without `temporalio` on the API container
- **So that** the API tier does not depend on the Temporal SDK at boot
- **Given:** `from temporalio import ...` lives inside function bodies only
- **When:** `python -c "import app.main"` on a machine without `temporalio`
- **Then:**
  - No `ImportError` raised (INV-TMP-04)
  - Verified by T-20

**US-12: REST routes return 503 when Temporal is down**
- **As a** resilient client
- **I want** a clear error when the Temporal server is unreachable
- **Given:** `get_client()` raises `ConnectionError`
- **When:** `POST /workflows/start`
- **Then:**
  - Route catches `(ModuleNotFoundError, Exception)` → HTTP 503 "Temporal client unavailable"
  - API tier continues serving non-workflow requests (QS-12)
  - Verified by T-17 (route signature)

**US-13: Worker process runs as non-root**
- **As an** ops engineer with a security policy
- **I want** the worker container to run as UID 1000
- **Given:** `Dockerfile.temporal-worker` generated
- **When:** `docker build -f Dockerfile.temporal-worker -t worker . && docker run worker`
- **Then:**
  - `USER 1000` declared before `CMD` (INV-TMP-07, QS-10)
  - Verified by T-18

**US-14: No SDK import contaminates `app/main.py`**
- **As a** developer who deploys API and worker separately
- **I want** to confirm `app/main.py` was not modified
- **Given:** Worker runs via `python -m app.workflows.worker`
- **When:** Tool completes
- **Then:**
  - `"main.py"` absent from `result.files_modified` (INV-TMP-06)
  - Verified by T-21

**US-15: requirements.txt gets the new dep**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `temporalio>=1.7.0` to appear
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `temporalio>=1.7.0` (idempotent: appended only if absent) (INV-TMP-15)
  - Verified by T-11

### 9.4 Workflows package (US-16 .. US-20)

**US-16: `__init__.py` re-exports the public surface area**
- **As a** caller importing from `app.workflows`
- **I want** `from app.workflows import get_client, WorkerFactory` to work
- **Given:** `app/workflows/__init__.py` with re-exports
- **When:** Import statement executes
- **Then:**
  - `TemporalClientFactory`, `get_client`, `WorkerFactory`, `start_worker`, `stop_worker` all importable
  - Verified by T-12

**US-17: Activities have retry metadata without requiring SDK at import time**
- **As a** unit test that imports `app.workflows.activities`
- **I want** to import the module without the Temporal SDK
- **Given:** `_apply_retry_policy` tags functions with `__temporal_*` attributes; SDK imported lazily inside bodies
- **When:** `import app.workflows.activities` on a machine without `temporalio`
- **Then:**
  - No `ImportError`
  - All four activity functions importable
  - Verified by T-16 (module existence check), T-20 (lazy import scan)

**US-18: `OrderProcessingWorkflow` importable without SDK**
- **As a** unit test
- **I want** to instantiate `OrderProcessingWorkflow` without `temporalio`
- **Given:** `try/except ModuleNotFoundError` block at module level in `example_workflow.py`
- **When:** `from app.workflows.example_workflow import OrderProcessingWorkflow`
- **Then:**
  - Class importable; Temporal decorators not applied (no error) (INV-TMP-11)
  - Verified by T-15, T-20

**US-19: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to tell me how to start the Temporal server and worker
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains Temporal server start command and SDK install instruction (INV-TMP-14)
  - Verified by T-07

**US-20: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-TMP-13)
  - Verified by T-06

---

## 10. Test Plan

All 22 tests live in `adapt/extend/infrastructure/test_add_temporal_workflow.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-07)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `tw_t01` | `add_temporal_workflow(ToolInput(project_dir))` | `result.status == "success"` (INV-TMP-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `tw_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-TMP-01, CC-02) |
| T-03 | `test_dry_run_writes_nothing` | Fixture `tw_t03`; snapshot all `.py` | `add_temporal_workflow(ToolInput(dry_run=True))` | `status == "success"`; empty lists; filesystem byte-identical (INV-TMP-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `tw_t04` | Run tool | `len(files_created) >= 6`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `tw_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |
| T-06 | `test_execution_time_recorded` | Fixture `tw_t06`; run tool | Read `result.execution_time_ms` | `> 0` (INV-TMP-13, CC-13) |
| T-07 | `test_next_steps_present` | Fixture `tw_t07`; run tool | Lowercase-join `result.next_steps` | Non-empty; contains `"temporal"` (INV-TMP-14, CC-14) |

### 10.2 Category B — Generated code quality (T-08 .. T-11)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-08 | `test_all_py_parse` | Fixture `tw_t08`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-TMP-03, CC-06) |
| T-09 | `test_no_function_over_50_loc` | Fixture `tw_t09`; run tool | AST walk `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-10 | `test_config_fields_patched` | Fixture `tw_t10`; run tool | Read `app/core/config.py` | Contains all 3 `TEMPORAL_*` fields; `TEMPORAL_HOST` line starts with 4-space indent (INV-TMP-08, CC-08) |
| T-11 | `test_requirements_patched` | Fixture `tw_t11`; run tool | Read `requirements.txt` | Contains `"temporalio>="` (INV-TMP-15, CC-12) |

### 10.3 Category C — Domain-specific modules (T-12 .. T-21)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-12 | `test_workflows_init_created` | Fixture `tw_t12`; run tool | Read `app/workflows/__init__.py` | File exists; `TemporalClientFactory` and `get_client` re-exported (CC-11) |
| T-13 | `test_client_module_created` | Fixture `tw_t13`; run tool | Read `app/workflows/client.py` | File exists; contains `TemporalClientFactory` and `get_client` (INV-TMP-10, CC-16) |
| T-14 | `test_worker_module_created` | Fixture `tw_t14`; run tool | Read `app/workflows/worker.py` | File exists; contains `WorkerFactory`, `start_worker`, `stop_worker` |
| T-15 | `test_example_workflow_created` | Fixture `tw_t15`; run tool | Read `app/workflows/example_workflow.py` | File exists; contains `OrderProcessingWorkflow` (INV-TMP-11, CC-11) |
| T-16 | `test_activities_module_created` | Fixture `tw_t16`; run tool | Read `app/workflows/activities.py` | File exists; all 4 functions present: `validate_order`, `charge_payment`, `fulfil_order`, `compensate_payment` (INV-TMP-05, CC-18) |
| T-17 | `test_workflow_routes_created` | Fixture `tw_t17`; run tool | Read `app/api/routes/workflows.py` | File exists; all 4 handler names present: `start_workflow`, `get_workflow_status`, `signal_workflow`, `cancel_workflow` (CC-20) |
| T-18 | `test_dockerfile_temporal_worker_created` | Fixture `tw_t18`; run tool | Read `Dockerfile.temporal-worker` | File exists; `"USER"` and `"1000"` in content (INV-TMP-07, QS-10, CC-19) |
| T-19 | `test_routes_registered_in_routes_init` | Fixture `tw_t19`; run tool | Read `app/routes/__init__.py` if it exists | Contains `"workflows"` (case-insensitive) (CC-10) |
| T-20 | `test_lazy_sdk_import_in_generated_code` | Fixture `tw_t20`; run tool | Scan all `app/workflows/*.py` lines | No unindented `from temporalio` or `import temporalio` outside a `try:` block in any file (INV-TMP-04, CC-17) |
| T-21 | `test_main_py_not_modified` | Fixture `tw_t21`; run tool | Inspect `result.files_modified` | `"main.py"` absent from modified file names (INV-TMP-06, CC-09) |

### 10.4 Category D — Meta (T-22)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | `test_idempotent_project_still_parses` | Fixture `tw_t22`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-TMP-01, INV-TMP-03, CC-15) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_temporal_workflow.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_temporal_workflow.py
```

Target: 22/22 passed, 0 failed. The standalone runner prints `TOOL-067 add_temporal_workflow: 22 passed, 0 failed`.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible — complementary tools | arq is best for fire-and-forget short jobs; Temporal is best for long-running durable processes. Both can coexist. arq `enqueue()` can start a Temporal workflow via `POST /workflows/start` |
| `add_stripe_subscription` (TOOL-065) | No | ✅ Compatible | Subscription provisioning (creating features, sending emails, setting quotas) is a multi-step process that benefits from Temporal's compensation pattern |
| `add_stripe_refund_flow` (TOOL-066) | No | ✅ Compatible | A Temporal workflow can orchestrate: record refund → confirm webhook → trigger fulfilment reversal |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Payment success can start an `OrderProcessingWorkflow` for fulfilment |
| `add_multi_tenancy` (TOOL-008) | No | ✅ Compatible | Temporal task queues can be namespaced per tenant via `TEMPORAL_TASK_QUEUE=tenant-{id}-queue` env var |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | RBAC can add `require("workflows:write")` to `POST /workflows/start`; current version only enforces `CurrentUser` |
| `add_audit_log` (TOOL-005) | No | ⚠️ Caveat | Temporal events are their own audit trail; avoid double-logging activity transitions in both Temporal and the application audit log |
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | An activity function can send transactional emails as part of the workflow |
| `add_sqladmin` (TOOL-056) | No | ⚠️ Caveat | Temporal has its own UI (`temporal server` exposes a web UI on port 8088); SQLAdmin is not needed for workflow observability |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API keys resolve to a `CurrentUser` identity; can start and signal workflows with the same key |
| `add_sse` (TOOL-014) | No | ✅ Compatible | SSE endpoint can push workflow status updates to clients as an alternative to polling `GET /workflows/{id}/status` |
| `add_cursor_pagination` (TOOL-002) | No | ⚠️ Not applicable | TOOL-067 generates no paginated list endpoint; Temporal's built-in UI and API handle workflow listing |

**Conflicts:** None. `add_temporal_workflow` never modifies `app/main.py` (by design — INV-TMP-06). It is safe to run alongside any other SKILL-001 tool.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/routes/__init__.py \
  requirements.txt

rm -rf app/workflows/
rm -f \
  app/api/routes/workflows.py \
  Dockerfile.temporal-worker
```

### 12.2 No database rollback required

TOOL-067 creates no Alembic migration and no database tables. There is nothing to downgrade.

### 12.3 Temporal server cleanup (optional)

In-flight workflow executions that were started before rollback will fail when the worker is stopped. Operators can cancel them via the Temporal web UI or CLI:

```bash
temporal workflow list --query "ExecutionStatus='Running'"
temporal workflow cancel --workflow-id order-123-abc
```

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

### 12.5 Emergency: Temporal server down

1. Stop the Temporal worker container: `docker stop myapp-temporal-worker`.
2. Comment out `include_router(workflows_router)` in `app/routes/__init__.py`.
3. Restart the FastAPI app; non-workflow routes continue serving normally.
4. Routes return HTTP 503 if any code path still reaches the Temporal client.
5. On Temporal recovery, revert step 2 and restart the worker.

### 12.6 Uninstall validator

```bash
test ! -d app/workflows || (echo "app/workflows still present" && exit 1)
test ! -f app/api/routes/workflows.py || (echo "workflows routes still present" && exit 1)
test ! -f Dockerfile.temporal-worker || (echo "Dockerfile still present" && exit 1)
grep -q "TEMPORAL_HOST" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms >= 1` |
| EC-02 | Tool runs on a project missing `CONFIG_SETTINGS` prerequisite | `ensure_prerequisites` returns errors → `status="error"` with hint to run `fastapi_generate_project` first |
| EC-03 | `app/workflows/client.py` already contains `TemporalClientFactory` | Early return `status="no_op"` — zero file writes (INV-TMP-01) |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-TMP-02) |
| EC-05 | `app/workflows/` directory does not exist | Created via `mkdir(parents=True, exist_ok=True)` before writing any workflow file |
| EC-06 | `app/core/config.py` already contains `TEMPORAL_HOST` | `_patch_config` field-by-field check; only missing fields are added; no duplicate insertion |
| EC-07 | `app/core/config.py` lacks `settings = Settings()` anchor | Fields appended at EOF (`content += "\n".join(new_lines) + "\n"`) |
| EC-08 | `requirements.txt` already contains `temporalio` | `_patch_requirements` returns without modification |
| EC-09 | `app/routes/__init__.py` already contains `workflows_router` | `_patch_routes_init` early-returns — no duplicate call |
| EC-10 | `app/routes/__init__.py` does not exist | Routes patch step is skipped; router must be registered manually |
| EC-11 | `Dockerfile.temporal-worker` already exists | `if not dockerfile.exists():` guard — Dockerfile is NOT overwritten; no second copy in `files_created` |
| EC-12 | `app/workflows/__init__.py` already exists | `if not workflows_init.exists():` guard — init file is NOT overwritten |
| EC-13 | Temporal server not running when `POST /workflows/start` is called | Route catches `Exception` → HTTP 503 "Temporal client unavailable" (QS-12) |
| EC-14 | `temporalio` not installed when any route is called | `except ModuleNotFoundError` → HTTP 503 (QS-12) |
| EC-15 | Generated `example_workflow.py` fails `ast.parse` | Final validation loop returns `status="error"` with syntax error details |
| EC-16 | `app/api/routes/` directory missing | `_write_workflow_routes` creates directory via `mkdir(parents=True, exist_ok=True)` |
| EC-17 | `fulfil_order` activity fails after `charge_payment` succeeds | `_fulfil()` calls `compensate_payment` and returns `{"status": "failed", "compensated": True}` (INV-TMP-05) |
| EC-18 | `cancel` signal arrives after `charge_payment` but before `fulfil_order` | `_cancelled` is `True` entering `_fulfil()`; `compensate_payment` runs before exit |
| EC-19 | `cancel` signal arrives after `fulfil_order` completes | `_cancelled` check in `run()` after `_fulfil()` has already returned; workflow completes normally |
| EC-20 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-22) |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 22 tests in `test_add_temporal_workflow.py` pass
2. ✅ Tool execution time < 5 s measured on reference hardware
3. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-TMP-01)
4. ✅ `dry_run=True` produces zero filesystem writes (INV-TMP-02)
5. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-TMP-03)
6. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
7. ✅ No unindented `from temporalio` or `import temporalio` outside a `try:` block in any generated file (INV-TMP-04)
8. ✅ `_fulfil()` calls `compensate_payment` when `fulfil_order` raises (INV-TMP-05)
9. ✅ `app/main.py` is NOT in `files_modified` (INV-TMP-06)
10. ✅ `Dockerfile.temporal-worker` declares `USER 1000` before `CMD` (INV-TMP-07)
11. ✅ `TEMPORAL_*` settings live inside `class Settings` body with 4-space indentation (INV-TMP-08)
12. ✅ All four REST routes declare `current_user: CurrentUser` (INV-TMP-09)
13. ✅ `get_client()` caches in module-level `_client` singleton (INV-TMP-10)
14. ✅ `next_steps` includes Temporal start action and SDK install (INV-TMP-14)
15. ✅ Developer successfully starts a workflow, queries its status, sends a cancel signal, and verifies compensation

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, ROUTES_INIT, REQUIREMENTS_TXT)` passes
- [ ] `app/workflows/client.py` does NOT contain `"TemporalClientFactory"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Workflows package

- [ ] `mkdir -p app/workflows` if missing
- [ ] Write `app/workflows/__init__.py` via `_write_workflows_init` if not exists — re-exports `TemporalClientFactory`, `get_client`, `WorkerFactory`, `start_worker`, `stop_worker`
- [ ] Write `app/workflows/client.py` via `_write_client_module` — `TemporalClientFactory`, `get_client()` singleton with `_client` global

### 15.3 Worker module

- [ ] Write `app/workflows/worker.py` via `_write_worker_module`
- [ ] `WorkerFactory` class with `create(client)` method — lazy SDK import; applies `activity.defn`; registers `OrderProcessingWorkflow` and 4 activities
- [ ] `start_worker()` — creates client, creates worker, starts polling
- [ ] `stop_worker()` — graceful shutdown, no-op if not started
- [ ] `main()` entry point with `asyncio.run(_run())`
- [ ] `if __name__ == "__main__": main()`

### 15.4 Activities module

- [ ] Write `app/workflows/activities.py` via `_write_activities_module`
- [ ] `_apply_retry_policy(fn, *, schedule_to_close)` helper — tags `__temporal_schedule_to_close__` and `__temporal_max_attempts__`
- [ ] `validate_order(order_id)` — lazy `from temporalio import activity`; 60s schedule_to_close
- [ ] `charge_payment(order_id, amount_cents)` — lazy import; 30s schedule_to_close
- [ ] `fulfil_order(order_id, charge_id)` — lazy import; 120s schedule_to_close
- [ ] `compensate_payment(order_id, charge_id)` — lazy import; 30s schedule_to_close

### 15.5 Example workflow

- [ ] Write `app/workflows/example_workflow.py` via `_write_example_workflow`
- [ ] `OrderProcessingWorkflow` class with `__init__`, `run`, `_validate`, `_charge`, `_fulfil`, `cancel`, `status` methods
- [ ] `_fulfil()` wraps `fulfil_order` in `try/except`; calls `compensate_payment` on failure
- [ ] `cancel` signal sets `_cancelled = True`; checked between phases
- [ ] `try/except ModuleNotFoundError` at module level applies `@workflow.defn`, `@workflow.run`, `@workflow.signal`, `@workflow.query` lazily

### 15.6 REST routes

- [ ] Write `app/api/routes/workflows.py` via `_write_workflow_routes`
- [ ] `APIRouter(prefix="/workflows", tags=["workflows"])`
- [ ] `POST "/start"` — requires `CurrentUser`; lazy `get_client` import; HTTP 202 on success; HTTP 503 on SDK absence or connection failure
- [ ] `GET "/{workflow_id}/status"` — requires `CurrentUser`; `handle.query(lambda wf: wf.status())`; HTTP 404 on not found; HTTP 503 on SDK absence
- [ ] `POST "/{workflow_id}/signal"` — requires `CurrentUser`; `handle.signal("cancel")`; HTTP 404 on not found; HTTP 503 on SDK absence
- [ ] `POST "/{workflow_id}/cancel"` — requires `CurrentUser`; `handle.cancel()`; HTTP 404 on not found; HTTP 503 on SDK absence
- [ ] `_get_task_queue()` helper reads `settings.TEMPORAL_TASK_QUEUE` lazily

### 15.7 Dockerfile.temporal-worker

- [ ] Write `Dockerfile.temporal-worker` via `_write_dockerfile` if not exists
- [ ] `FROM python:3.12-slim AS base`
- [ ] `COPY requirements.txt .` then `pip install --no-cache-dir -r requirements.txt`
- [ ] `COPY . .`
- [ ] `RUN adduser --disabled-password --gecos "" --uid 1000 worker`
- [ ] `USER 1000`
- [ ] `CMD ["python", "-m", "app.workflows.worker"]`

### 15.8 Config patch

- [ ] Check each of `TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE` individually; only add missing ones
- [ ] 4-space indent (class body)
- [ ] Insert before `settings = Settings()` line; last-resort append at EOF
- [ ] Idempotent: no duplicate fields on repeated runs

### 15.9 Routes init patch

- [ ] Early-return if `"workflows_router" in content`
- [ ] Append `from app.api.routes.workflows import router as workflows_router`
- [ ] Append `api_router.include_router(workflows_router)`
- [ ] Preserve trailing newline

### 15.10 Requirements patch

- [ ] Add `temporalio>=1.7.0` if `"temporalio"` absent
- [ ] Preserve trailing newline

### 15.11 Validation

- [ ] Loop over `files_created`; for every `.py` call `ast.parse(p.read_text())`
- [ ] Return `status="error"` with file path on `SyntaxError`

### 15.12 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain TemporalClientFactory singleton, WorkerFactory, OrderProcessingWorkflow with compensation, lazy SDK, non-root container
- [ ] `next_steps` contains Temporal server start command, `TEMPORAL_HOST` env var, SDK install, worker start commands, API restart hint

### 15.13 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring explains why Temporal vs arq/Celery, lists all emitted files, and documents the 4 security/correctness guarantees
- [ ] `add_temporal_workflow` docstring documents the function signature and return type

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/workflows/__init__.py",
    "/tmp/fixture/app/workflows/client.py",
    "/tmp/fixture/app/workflows/worker.py",
    "/tmp/fixture/app/workflows/activities.py",
    "/tmp/fixture/app/workflows/example_workflow.py",
    "/tmp/fixture/app/api/routes/workflows.py",
    "/tmp/fixture/Dockerfile.temporal-worker"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/requirements.txt",
    "/tmp/fixture/app/routes/__init__.py"
  ],
  "notes": [
    "Temporal workflow engine added: TemporalClientFactory singleton, WorkerFactory, OrderProcessingWorkflow with compensation pattern.",
    "Activities: validate_order, charge_payment, fulfil_order (each with retry policy + compensation).",
    "REST routes: POST /workflows/start, GET /workflows/{id}/status, POST /workflows/{id}/signal, POST /workflows/{id}/cancel.",
    "Worker runs as a separate process — app/main.py is NOT modified.",
    "temporalio imported lazily so app boots without the SDK installed.",
    "Dockerfile.temporal-worker generated (non-root USER 1000)."
  ],
  "next_steps": [
    "Start a Temporal server: docker run --rm -p 7233:7233 temporalio/auto-setup:latest",
    "Set TEMPORAL_HOST in .env (default: localhost:7233).",
    "Set TEMPORAL_NAMESPACE (default: default) and TEMPORAL_TASK_QUEUE (default: main-queue).",
    "Install the SDK: pip install 'temporalio>=1.7.0'",
    "Start the worker: docker build -f Dockerfile.temporal-worker -t myapp-temporal-worker . && docker run --rm --env-file .env myapp-temporal-worker",
    "Or locally: python -m app.workflows.worker",
    "Restart the FastAPI app so the /workflows/* routes are active.",
    "Verify: POST /workflows/start with an order_id payload."
  ],
  "execution_time_ms": 211
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "TemporalClientFactory already present — Temporal workflow engine is already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 1
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/workflows/ package (client.py, worker.py, example_workflow.py, activities.py),",
    "         POST /workflows/start, GET /workflows/{id}/status, POST /workflows/{id}/signal, POST /workflows/{id}/cancel,",
    "         Dockerfile.temporal-worker.",
    "[dry_run] Would patch app/core/config.py with TEMPORAL_HOST, TEMPORAL_NAMESPACE, TEMPORAL_TASK_QUEUE.",
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
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing\n  - REQUIREMENTS_TXT: requirements.txt missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 1
}
```

---
