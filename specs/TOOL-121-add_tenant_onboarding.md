---
spec_id: "TOOL-121"
tool_name: "add_tenant_onboarding"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-OB-001"
  - "INV-OB-002"
  - "INV-OB-003"
  - "INV-OB-004"
  - "INV-OB-005"
  - "INV-OB-006"
  - "INV-OB-007"
  - "INV-OB-008"
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
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
tags:
  - "performance"
  - "payments"
  - "data"
  - "realtime"
  - "api"
---
# TOOL-121 — add_tenant_onboarding

## 1. Overview

| Field | Value |
|---|---|
| **Tool ID** | TOOL-121 |
| **MCP name** | `fastapi_add_tenant_onboarding` |
| **Entry point** | `adapt/extend/infrastructure/add_tenant_onboarding.py::add_tenant_onboarding` |
| **Tags** | `multi-tenant`, `onboarding`, `saga`, `compensation`, `workflow` |
| **Input** | `ToolInput(project_dir, dry_run=False)` |
| **Output** | `ToolResult(status, files_created, files_modified, notes, next_steps, execution_time_ms)` |
| **Idempotency fingerprint** | `"OnboardingOrchestrator" in app/onboarding/orchestrator.py` |
| **Prerequisite check** | `app/` directory exists |
| **Files created (min)** | 4 (`orchestrator.py`, `steps.py`, `onboarding.py` schema, `onboarding.py` route) |
| **Files modified (min)** | 2 (`app/core/config.py`, routes `__init__.py`) |
| **Test file** | `adapt/extend/infrastructure/test_add_tenant_onboarding.py` |

---

## 2. Purpose

Creating a new tenant involves multiple operations that must succeed atomically or roll back cleanly. `add_tenant_onboarding` implements a saga-style orchestrator with compensating transactions:

1. **`app/onboarding/orchestrator.py`** — Saga engine:
   - `OnboardingOrchestrator` — runs steps in sequence; on failure calls `_compensate()` to reverse completed steps in LIFO order.
   - `OnboardingProgress` — tracks step completion, current step index, and saga status.
   - `OnboardingStatus` — enum: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `COMPENSATING`, `COMPENSATED`, `FAILED`.
   - `_compensate()` method iterates completed steps in reverse and calls `step.compensate()` on each.

2. **`app/onboarding/steps.py`** — Five built-in steps and a Protocol:
   - `OnboardingStep` — `typing.Protocol` with `execute(context)` and `compensate(context)` abstract methods.
   - `CreateTenantStep` — creates the tenant record; compensate deletes it.
   - `CreateAdminUserStep` — creates the admin user; compensate removes them.
   - `SeedDataStep` — seeds default data; compensate removes the seed.
   - `ConfigureBillingStep` — sets up billing configuration; compensate tears it down.
   - `SendWelcomeEmailStep` — sends welcome email (fire-and-forget; compensate is a no-op).
   - `build_steps_from_config(config)` — factory that reads `ONBOARDING_STEPS` list from settings and returns the ordered step instances.

3. **`app/schemas/onboarding.py`** — Three Pydantic schemas:
   - `OnboardingRequest` — fields: `tenant_name`, `admin_email`, `plan`.
   - `OnboardingStatusResponse` — fields: `onboarding_id`, `status`, `completed_steps`, `current_step`.
   - `OnboardingStartResponse` — fields: `onboarding_id`, `status`, `message`.

4. **`app/api/routes/onboarding.py`** — Two endpoints:
   - `POST /onboarding/start` — starts a new onboarding saga; returns `onboarding_id`.
   - `GET /onboarding/{id}/status` — returns the current progress.

Config fields (`ONBOARDING_STEPS`, `ONBOARDING_WELCOME_EMAIL_TEMPLATE`) are injected with 4-space indent. The onboarding router is registered in `app/routes/__init__.py`.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| Tool execution time | < 2 s on a cold fixture project |
| `execution_time_ms` field | > 0 (always recorded) |
| Step execution time | Bounded by I/O operations per step |
| Compensation time | Linear in number of completed steps |
| Files created | ≥ 4 |
| Files modified | ≥ 2 |
| Max function LOC in generated `app/` | ≤ 50 |

---

## 4. Before / After

### 4.1 Project state — before

```
app/
  core/
    config.py    # No ONBOARDING_* fields
  routes/
    __init__.py
```

### 4.2 Project state — after

```
app/
  core/
    config.py                       # ONBOARDING_STEPS, ONBOARDING_WELCOME_EMAIL_TEMPLATE
  onboarding/
    orchestrator.py                 # OnboardingOrchestrator, OnboardingProgress,
                                    # OnboardingStatus
    steps.py                        # OnboardingStep Protocol, 5 built-in steps,
                                    # build_steps_from_config factory
  schemas/
    onboarding.py                   # OnboardingRequest, OnboardingStatusResponse,
                                    # OnboardingStartResponse
  api/
    routes/
      onboarding.py                 # POST /onboarding/start,
                                    # GET /onboarding/{id}/status
  routes/
    __init__.py                     # onboarding_router registered
```

### 4.3 OnboardingStatus enum

```python
# app/onboarding/orchestrator.py (generated)
import enum


class OnboardingStatus(enum.Enum):
    """Lifecycle states of an onboarding saga."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"
```

### 4.4 OnboardingOrchestrator with _compensate

```python
class OnboardingOrchestrator:
    """Saga-style orchestrator for multi-step tenant onboarding."""

    def __init__(self, steps: list[OnboardingStep]) -> None:
        self._steps = steps

    async def run(self, context: dict) -> OnboardingProgress:
        progress = OnboardingProgress(status=OnboardingStatus.IN_PROGRESS)
        for i, step in enumerate(self._steps):
            try:
                await step.execute(context)
                progress.completed_steps.append(type(step).__name__)
                progress.current_step = i + 1
            except Exception as exc:
                progress.status = OnboardingStatus.COMPENSATING
                await self._compensate(progress.completed_steps, context)
                progress.status = OnboardingStatus.COMPENSATED
                progress.error = str(exc)
                return progress
        progress.status = OnboardingStatus.COMPLETED
        return progress

    async def _compensate(self, completed: list[str], context: dict) -> None:
        """Reverse completed steps in LIFO order."""
        for step_name in reversed(completed):
            step = self._find_step(step_name)
            if step:
                try:
                    await step.compensate(context)
                except Exception:
                    pass  # best-effort compensation
```

### 4.5 OnboardingStep Protocol

```python
# app/onboarding/steps.py (generated)
from typing import Protocol


class OnboardingStep(Protocol):
    """Protocol for saga steps with execute and compensate methods."""

    async def execute(self, context: dict) -> None:
        """Execute the step."""
        ...

    async def compensate(self, context: dict) -> None:
        """Reverse this step's effects."""
        ...
```

### 4.6 Config patch

```python
    # --- Tenant onboarding — added by add_tenant_onboarding tool ---
    ONBOARDING_STEPS: list[str] = [
        "CreateTenantStep",
        "CreateAdminUserStep",
        "SeedDataStep",
        "ConfigureBillingStep",
        "SendWelcomeEmailStep",
    ]
    ONBOARDING_WELCOME_EMAIL_TEMPLATE: str = "welcome"
```

---

## 5. Quality Standards

| ID | Standard |
|---|---|
| QS-1 | `status == "success"` on first run against a fresh fixture project |
| QS-2 | Second run returns `status == "no_op"` |
| QS-3 | `dry_run=True` returns success without writing any bytes |
| QS-4 | `files_created` contains ≥ 4 entries; all paths exist on disk |
| QS-5 | `files_modified` contains ≥ 2 entries; all paths exist on disk |
| QS-6 | Every generated `.py` file passes `ast.parse()` |
| QS-7 | No function in `app/` exceeds 50 LOC |
| QS-8 | `ONBOARDING_STEPS`, `ONBOARDING_WELCOME_EMAIL_TEMPLATE` in `config.py` with 4-space indent |
| QS-9 | `onboarding_router` or `onboarding` in `app/routes/__init__.py` |
| QS-10 | `OnboardingOrchestrator`, `OnboardingProgress`, `OnboardingStatus` in `orchestrator.py` |
| QS-11 | All 5 built-in step classes in `steps.py` |
| QS-12 | `OnboardingRequest`, `OnboardingStatusResponse`, `OnboardingStartResponse` in schemas |
| QS-13 | `/start` and `status` in `onboarding.py` route |
| QS-14 | ≥ 5 `def execute(` and ≥ 5 `def compensate(` in `steps.py` |
| QS-15 | `_compensate` and `COMPENSATING` and `COMPENSATED` in `orchestrator.py` |
| QS-16 | `build_steps_from_config` factory function in `steps.py` |
| QS-17 | `class OnboardingStep` and `Protocol` in `steps.py` |

---

## 6. Completeness Criteria

| ID | Test function | What it verifies |
|---|---|---|
| CC-01 | `test_success_status` | Tool returns `status='success'` on a fresh project |
| CC-02 | `test_idempotent` | Second run returns `status='no_op'`; no files created or modified |
| CC-03 | `test_dry_run` | `dry_run=True` returns success without writing any bytes |
| CC-04 | `test_files_created_count` | At least 4 files created; all exist on disk |
| CC-05 | `test_files_modified_count` | At least 2 files modified; all exist on disk |
| CC-06 | `test_all_py_parse` | Every generated `.py` file AST-parses clean |
| CC-07 | `test_no_function_over_50_loc` | No function in `app/` exceeds 50 LOC |
| CC-08 | `test_config_fields_patched` | `ONBOARDING_STEPS`, `ONBOARDING_WELCOME_EMAIL_TEMPLATE` with 4-space indent |
| CC-09 | `test_routes_registered` | `onboarding_router` or `onboarding` in routes `__init__` |
| CC-10 | `test_orchestrator_created` | `OnboardingOrchestrator`, `OnboardingProgress`, `OnboardingStatus` present |
| CC-11 | `test_steps_file_created` | All 5 built-in step classes present in `steps.py` |
| CC-12 | `test_onboarding_schemas_created` | All 3 schemas present |
| CC-13 | `test_onboarding_routes_endpoints` | `/start` and `status` endpoints present |
| CC-14 | `test_step_compensation_present` | ≥ 5 `execute()` and ≥ 5 `compensate()` methods |
| CC-15 | `test_orchestrator_compensates_on_failure` | `_compensate`, `COMPENSATING`, `COMPENSATED` present |
| CC-16 | `test_build_steps_from_config_factory` | `build_steps_from_config` factory function present |
| CC-17 | `test_onboarding_step_protocol` | `OnboardingStep` and `Protocol` present in `steps.py` |
| CC-18 | `test_execution_time_recorded` | `execution_time_ms > 0` |
| CC-19 | `test_next_steps_present` | `next_steps` non-empty; mentions `onboarding` or `step` |
| CC-20 | `test_idempotent_project_still_parses` | All `.py` files parse after two consecutive runs |

---

## 7. Definition of Done

- [ ] All 20 tests in `test_add_tenant_onboarding.py` pass
- [ ] `OnboardingOrchestrator` with saga pattern, `_compensate()` LIFO rollback
- [ ] `OnboardingStatus` enum includes `COMPENSATING` and `COMPENSATED`
- [ ] All 5 built-in steps: `CreateTenantStep`, `CreateAdminUserStep`, `SeedDataStep`, `ConfigureBillingStep`, `SendWelcomeEmailStep`
- [ ] Each step has `execute()` and `compensate()` methods
- [ ] `OnboardingStep` Protocol with `execute` and `compensate` signatures
- [ ] `build_steps_from_config()` factory reads `ONBOARDING_STEPS` from settings
- [ ] All 3 Pydantic schemas generated
- [ ] `POST /onboarding/start` and `GET /onboarding/{id}/status` routes
- [ ] Config injected with 4-space indent; router registered

---

## 8. Invariants

| ID | Invariant |
|---|---|
| INV-OB-001 | `_compensate()` MUST execute compensation steps in LIFO order |
| INV-OB-002 | Compensation is best-effort — exceptions inside `compensate()` MUST NOT re-raise |
| INV-OB-003 | `OnboardingStatus.COMPENSATING` MUST be set before compensation begins |
| INV-OB-004 | `OnboardingStatus.COMPENSATED` MUST be set after compensation completes |
| INV-OB-005 | `OnboardingStep` MUST use `typing.Protocol` — not ABC |
| INV-OB-006 | `build_steps_from_config()` MUST read from `ONBOARDING_STEPS` config |
| INV-OB-007 | Idempotency fingerprint is `"OnboardingOrchestrator" in app/onboarding/orchestrator.py` |
| INV-OB-008 | All generated `.py` files pass `ast.parse()` before `ToolResult` is returned |

---

## 9. User Stories

| ID | Story |
|---|---|
| US-01 | As a platform engineer, I want compensating transactions so that partial onboarding failures leave no orphaned records. |
| US-02 | As a developer, I want `OnboardingStep` Protocol so that I can add custom steps without modifying the orchestrator. |
| US-03 | As a product manager, I want `POST /onboarding/start` so that new tenant sign-up is a single API call. |
| US-04 | As an operator, I want `GET /onboarding/{id}/status` so that I can monitor long-running onboarding sagas. |
| US-05 | As a developer, I want `build_steps_from_config()` so that the step sequence is configurable without code changes. |
| US-06 | As an SRE, I want `COMPENSATING`/`COMPENSATED` status fields so that I can distinguish rollback-in-progress from rollback-complete in dashboards. |

---

## 10. Design Decisions

| Decision | Rationale |
|---|---|
| Saga pattern with compensating transactions | Distributed operations cannot use database transactions |
| `typing.Protocol` for `OnboardingStep` | Structural typing — steps do not need to inherit from a base class |
| LIFO compensation order | Reverses side effects in the correct order |
| Best-effort compensation (exception swallowing) | Compensation must not fail the saga status update |
| `build_steps_from_config()` factory | Enables step ordering from `.env` without code changes |
| `COMPENSATING` and `COMPENSATED` as distinct states | Enables alerting if a saga is stuck in `COMPENSATING` |
| `SendWelcomeEmailStep.compensate()` is a no-op | Emails cannot be unsent — log and move on |

---

## 11. Dependencies

| Package | Version | Purpose | Import style |
|---|---|---|---|
| `pydantic` | `>=2.0` | Schema models | Top-level |
| `enum` | stdlib | `OnboardingStatus` enum | Top-level |
| `typing` | stdlib | `Protocol` for `OnboardingStep` | Top-level |

---

## 12. Error Handling

| Scenario | Behavior |
|---|---|
| `orchestrator.py` already contains `OnboardingOrchestrator` | Return `status="no_op"` |
| `app/` directory missing | Return `status="error"` |
| Generated `.py` has `SyntaxError` | Return `status="error"`; file NOT committed |
| Step raises exception during `execute()` | Orchestrator triggers `_compensate()`; saga ends in `COMPENSATED` state |
| Step raises exception during `compensate()` | Exception caught and swallowed; compensation continues |
| `build_steps_from_config()` encounters unknown step class name | Skips unknown steps with a warning log |

---

## 13. Security Considerations

- `POST /onboarding/start` must be authenticated — anyone who can call it can create a tenant.
- `GET /onboarding/{id}/status` must validate that the requesting user owns the onboarding session.
- `CreateAdminUserStep` must hash passwords before storage — the step should delegate to the existing auth system.
- `ConfigureBillingStep` must not store payment details in the saga context — use Stripe's client-only token flow.

---

## 14. Testing Guide

```bash
# Run full test suite
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_tenant_onboarding.py -v

# Run standalone
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_tenant_onboarding.py

# Verify all 5 built-in step classes
python3 -c "
from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_tenant_onboarding import add_tenant_onboarding
from tests.common.fixture_factory import create_fixture_project
p = create_fixture_project(name='ob_manual')
add_tenant_onboarding(ToolInput(project_dir=str(p)))
content = (p / 'app' / 'onboarding' / 'steps.py').read_text()
for step in ['CreateTenantStep','CreateAdminUserStep','SeedDataStep','ConfigureBillingStep','SendWelcomeEmailStep']:
    print(step, step in content)
"
```

---

## 15. Files Reference

| File | Role |
|---|---|
| `adapt/extend/infrastructure/add_tenant_onboarding.py` | Tool entry point |
| `adapt/extend/infrastructure/test_add_tenant_onboarding.py` | 20-test structural test suite |
| `app/onboarding/orchestrator.py` | OnboardingOrchestrator, OnboardingProgress, OnboardingStatus |
| `app/onboarding/steps.py` | OnboardingStep Protocol, 5 built-in steps, build_steps_from_config |
| `app/schemas/onboarding.py` | OnboardingRequest, OnboardingStatusResponse, OnboardingStartResponse |
| `app/api/routes/onboarding.py` | POST /onboarding/start, GET /onboarding/{id}/status |
| `app/core/config.py` | Patched with ONBOARDING_STEPS, ONBOARDING_WELCOME_EMAIL_TEMPLATE |
| `app/routes/__init__.py` | Patched with onboarding_router |

---

## 16. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-04-15 | Initial spec — 20 CCs, saga orchestrator, LIFO compensation, 5 built-in steps |
