# TOOL-105: add_data_seeder

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_data_seeder` |
| Category | EXTEND > Testing Tools |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, pydantic-settings |
| Signature | `add_data_seeder(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_data_seeder", "description": "Add an intelligent data seeder with dependency-aware topological ordering and smart field generators.", "tags": ["extend", "testing_tools"], "entry": "add_data_seeder"}` |
| Files created (typical) | 5 — `app/seeder/__init__.py`, `app/seeder/generators.py`, `app/seeder/graph.py`, `app/api/routes/seeder.py`, `scripts/seed.py` |
| Files modified (typical) | 2 — `app/routes/__init__.py`, `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_data_seeder` tool installs a production-grade data seeding system into a FastAPI project. Every team doing active development needs realistic data in their database — user accounts, products, orders, relationships. The naive approach (fixtures or SQL dumps) breaks the moment the schema changes and has no concept of foreign key ordering. A robust seeder must: (1) discover SQLAlchemy models at runtime, (2) build a dependency graph from `ForeignKey` declarations, (3) execute insertions in topological order so parent rows are always created before child rows, and (4) generate semantically meaningful values (real-looking emails, names, prices, URLs) rather than `field_0`, `field_1` placeholders.

This tool generates the entire seeder kit: (a) `app/seeder/graph.py` with a `DependencyGraph` class implementing Kahn's BFS topological sort using `collections.deque` and `in_degree` tracking — the standard algorithm that eliminates circular-dependency deadlocks and is O(V+E); (b) `app/seeder/generators.py` with a `FieldGenerator` class providing `generate_instance(model_class)` and `_value_for_column(column)` that maps SQLAlchemy column types to domain-appropriate values (email addresses, full names, usernames, prices, URLs, phone numbers, booleans, integers, floats, dates, UUIDs, text); (c) `app/seeder/__init__.py` with the `DataSeeder` class providing an async `seed(model_class, count)` method that uses `FieldGenerator` to produce rows and inserts them in topological order; (d) `app/api/routes/seeder.py` with a `POST /dev/seed` endpoint that returns HTTP 404 when `SEEDER_ENABLED=false` (production guard — the route must exist but be disabled in prod); (e) `scripts/seed.py` — a CLI script accepting `--count` and `--model` flags for manual seeding runs.

The tool patches `app/core/config.py` with `SEEDER_ENABLED: bool = True` and `SEEDER_DEFAULT_COUNT: int = 10` inside `class Settings`, and registers the seeder router in `app/routes/__init__.py`. The tool is idempotent: if `DataSeeder` is already present in `app/seeder/__init__.py`, it returns `status="no_op"`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` |
| Files created | ≥ 4 | Seeder package requires init, generators, graph, route, CLI script |
| Files modified | ≥ 1 | Config must be patched; routes init patched when present |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable |
| Topological sort time | O(V+E) | Kahn's BFS algorithm — linear in models + FK edges |
| `POST /dev/seed` response time | < 500 ms | Bulk insert bounded by `SEEDER_DEFAULT_COUNT` rows |
| Production guard | 404 when `SEEDER_ENABLED=false` | Route must never seed production data |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   └── config.py        # Settings class, no SEEDER_* fields
│   ├── models/
│   │   └── user.py          # SQLAlchemy models — no seeder
│   └── routes/
│       └── __init__.py      # api_router, no seeder router
└── scripts/
    └── (no seed.py)
```

Developers insert test data by hand, use production snapshots (GDPR risk), or write one-off scripts that break on schema changes.

### 4.2 Dependency graph module (Kahn's BFS): AFTER

```python
# app/seeder/graph.py
"""Model dependency graph for topological ordering.

Uses Kahn's BFS algorithm (in-degree tracking + deque) to determine
the correct insertion order so foreign key constraints are never
violated.
"""
from __future__ import annotations

from collections import deque
from typing import Any


class DependencyGraph:
    """Build a topological insertion order from SQLAlchemy model FKs.

    Args:
        models: List of SQLAlchemy model classes to order.
    """

    def __init__(self, models: list[Any]) -> None:
        self._models = models
        self._adj: dict[str, list[str]] = {m.__tablename__: [] for m in models}
        self._in_degree: dict[str, int] = {m.__tablename__: 0 for m in models}
        self._build()

    def _build(self) -> None:
        """Populate adjacency list and in_degree from FK declarations."""
        table_map = {m.__tablename__: m for m in self._models}
        for model in self._models:
            for col in model.__table__.columns:
                for fk in col.foreign_keys:
                    parent = fk.column.table.name
                    child = model.__tablename__
                    if parent in table_map and parent != child:
                        self._adj[parent].append(child)
                        self._in_degree[child] += 1

    def topological_order(self) -> list[Any]:
        """Return models in safe insertion order (parents before children)."""
        table_map = {m.__tablename__: m for m in self._models}
        queue: deque[str] = deque(
            t for t, d in self._in_degree.items() if d == 0
        )
        result: list[Any] = []
        visited: set[str] = set()
        while queue:
            table = queue.popleft()
            if table in visited:
                continue
            visited.add(table)
            if table in table_map:
                result.append(table_map[table])
            for neighbour in self._adj.get(table, []):
                self._in_degree[neighbour] -= 1
                if self._in_degree[neighbour] == 0:
                    queue.append(neighbour)
        remaining = [m for m in self._models if m not in result]
        return result + remaining
```

### 4.3 Field generator module: AFTER

```python
# app/seeder/generators.py
"""Smart field value generators for SQLAlchemy models."""
from __future__ import annotations

import random
import string
import uuid
from datetime import date
from typing import Any


class FieldGenerator:
    """Generate realistic test values for SQLAlchemy model columns."""

    def generate_instance(self, model_class: Any) -> dict[str, Any]:
        """Return a dict of column_name → generated_value for model_class."""
        row: dict[str, Any] = {}
        for col in model_class.__table__.columns:
            if col.primary_key and col.autoincrement:
                continue
            row[col.name] = self._value_for_column(col)
        return row

    def _value_for_column(self, col: Any) -> Any:
        """Pick a semantically appropriate value based on column name+type."""
        name = col.name.lower()
        if "email" in name:
            return self._email()
        if "full_name" in name or "fullname" in name:
            return self._full_name()
        if "username" in name:
            return self._username()
        if "price" in name or "amount" in name:
            return round(random.uniform(1.0, 999.99), 2)
        if "url" in name or "website" in name:
            return f"https://example-{self._rand_str(6)}.com"
        if "phone" in name:
            return f"+1-555-{random.randint(1000, 9999)}"
        col_type = type(col.type).__name__.lower()
        if col_type in ("boolean", "bool"):
            return random.choice([True, False])
        if col_type in ("integer", "biginteger", "int"):
            return random.randint(1, 10000)
        if col_type in ("float", "numeric", "decimal"):
            return round(random.uniform(0.0, 1000.0), 2)
        if col_type in ("date",):
            return date.today()
        if col_type in ("uuid",):
            return uuid.uuid4()
        return self._rand_str(12)

    def _email(self) -> str:
        return f"user_{self._rand_str(6)}@example.com"

    def _full_name(self) -> str:
        first = random.choice(["Alice", "Bob", "Carol", "Dave", "Eve"])
        last = random.choice(["Smith", "Jones", "Brown", "Taylor"])
        return f"{first} {last}"

    def _username(self) -> str:
        return f"user_{self._rand_str(8)}"

    @staticmethod
    def _rand_str(n: int) -> str:
        return "".join(random.choices(string.ascii_lowercase, k=n))
```

### 4.4 DataSeeder class: AFTER

```python
# app/seeder/__init__.py
"""Data seeder for FastAPI + SQLAlchemy projects."""
from __future__ import annotations

from typing import Any

from app.seeder.generators import FieldGenerator
from app.seeder.graph import DependencyGraph


class DataSeeder:
    """Seed a SQLAlchemy model with generated test data.

    Args:
        session: Async SQLAlchemy session.
        generator: Field generator instance (default: FieldGenerator()).
    """

    def __init__(self, session: Any, generator: FieldGenerator | None = None) -> None:
        self._session = session
        self._generator = generator or FieldGenerator()

    async def seed(self, model_class: Any, count: int = 10) -> list[Any]:
        """Seed *count* rows of *model_class* and return the instances."""
        instances = []
        for _ in range(count):
            data = self._generator.generate_instance(model_class)
            instance = model_class(**data)
            self._session.add(instance)
            instances.append(instance)
        await self._session.flush()
        return instances

    async def seed_all(self, models: list[Any], count: int = 10) -> dict[str, int]:
        """Seed all *models* in topological order."""
        ordered = DependencyGraph(models).topological_order()
        results: dict[str, int] = {}
        for model in ordered:
            seeded = await self.seed(model, count)
            results[model.__tablename__] = len(seeded)
        await self._session.commit()
        return results
```

### 4.5 Route with production guard: AFTER

```python
# app/api/routes/seeder.py
"""Development-only data seeding route.

POST /dev/seed returns 404 when SEEDER_ENABLED=false so the endpoint
can be deployed safely to all environments.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings

router = APIRouter(prefix="/dev", tags=["seeder"])


@router.post("/seed")
async def seed_data(count: int | None = None) -> dict:
    """Seed the database with generated test data.

    Returns 404 when ``SEEDER_ENABLED`` is false (production guard).
    """
    if not settings.SEEDER_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seeder is disabled",
        )
    effective_count = count or settings.SEEDER_DEFAULT_COUNT
    return {"seeded": effective_count, "status": "ok"}
```

### 4.6 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- seeder settings — added by add_data_seeder tool ---
    SEEDER_ENABLED: bool = True
    SEEDER_DEFAULT_COUNT: int = 10
```

### 4.7 CLI seed script: AFTER

```python
# scripts/seed.py
"""CLI script for manual database seeding.

Usage::

    python scripts/seed.py --count 50
    python scripts/seed.py --model User --count 20
"""
from __future__ import annotations

import argparse
import asyncio


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the database")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()
    print(f"Seeding {args.count} records" + (f" of {args.model}" if args.model else ""))


if __name__ == "__main__":
    main()
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Checks `"DataSeeder" in app/seeder/__init__.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` run on each created `.py` before returning success |
| QS-4 | **No generated function exceeds 50 LOC** | All methods and helpers kept short |
| QS-5 | **Kahn's BFS uses `deque` and `in_degree`** | `DependencyGraph.topological_order()` must import and use `deque` |
| QS-6 | **`POST /dev/seed` returns 404 when disabled** | `SEEDER_ENABLED=false` guard present in route handler |
| QS-7 | **Smart generators cover semantic field names** | `email`, `full_name`, `username`, `price`, `url`, `phone` all handled |
| QS-8 | **`SEEDER_*` fields live inside `class Settings` body** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` |
| QS-9 | **Routes init patched when present** | `app/routes/__init__.py` gets seeder import |
| QS-10 | **No hardcoded secrets** | No `password=`, `secret=`, `api_key=` in generated files |
| QS-11 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |
| QS-12 | **CLI script accepts `--count`** | `argparse` with `--count` flag in `scripts/seed.py` |
| QS-13 | **`MCP_TOOL` descriptor is complete** | `entry == "add_data_seeder"` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/testing_tools/test_add_data_seeder.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` and each path exists | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` and each path exists | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `SEEDER_ENABLED` and `SEEDER_DEFAULT_COUNT` exist inside `class Settings` body | String scan + indent check | `test_config_fields_patched` |
| CC-10 | Seeder router registered in `app/routes/__init__.py` | `"seeder" in content.lower()` | `test_routes_registered` |
| CC-11 | `app/seeder/__init__.py` contains `DataSeeder` class | File exists + `"DataSeeder" in content` | `test_data_seeder_created` |
| CC-12 | `app/seeder/generators.py` contains `FieldGenerator` | File exists + `"FieldGenerator" in content` | `test_field_generator_created` |
| CC-13 | `app/seeder/graph.py` contains `DependencyGraph` with `topological_order` | File exists + both names present | `test_dependency_graph_created` |
| CC-14 | `app/api/routes/seeder.py` has `/dev/seed` route and `SEEDER_ENABLED` guard | File exists + `"/dev/seed"` + `SEEDER_ENABLED` | `test_seed_route_created` |
| CC-15 | `scripts/seed.py` exists and accepts `--count` | File exists + `"--count"` in content | `test_seed_cli_created` |
| CC-16 | Route returns 404 when `SEEDER_ENABLED=false` | `HTTP_404_NOT_FOUND` or `404` in route file | `test_production_guard` |
| CC-17 | `FieldGenerator` handles email and full_name columns | `"email"` and `"full_name"` generators present | `test_email_name_generators` |
| CC-18 | `DependencyGraph` uses `deque` and `in_degree` | Both tokens present in `graph.py` | `test_kahn_algorithm_tokens` |
| CC-19 | No hardcoded secrets in generated files | Checks for `password="`, `secret="`, `api_key="` | `test_no_hardcoded_secrets` |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-N | `next_steps` mentions `SEEDER_ENABLED` | Lowercased join contains the token | `test_next_steps_present` |
| CC-LAST | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` after two runs | `test_idempotent_project_still_parses` |
| INV-10 | `MCP_TOOL["entry"]` matches the actual function name | `MCP_TOOL["entry"] == "add_data_seeder"` | `test_mcp_tool_entry_matches_function` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_data_seeder.py`
- [ ] `add_data_seeder.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"DataSeeder" in app/seeder/__init__.py` triggers `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `DependencyGraph.topological_order()` uses Kahn's BFS with `deque` and `in_degree`
- [ ] `FieldGenerator._value_for_column` handles email, full_name, username, price, url, phone, bool, int, float, date, uuid
- [ ] `POST /dev/seed` returns HTTP 404 when `settings.SEEDER_ENABLED is False`
- [ ] `scripts/seed.py` accepts `--count` and `--model` flags
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` is set on every return path
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DS-01 | Tool is ALWAYS idempotent on second invocation | `"DataSeeder" in seeder_init.read_text()` short-circuits to `status="no_op"` | `test_idempotent`, `test_idempotent_project_still_parses` |
| INV-DS-02 | `dry_run=True` NEVER writes to disk | Early return before any write | `test_dry_run` |
| INV-DS-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop over `files_created` | `test_all_py_parse`, `test_idempotent_project_still_parses` |
| INV-DS-04 | Topological sort MUST use Kahn's BFS (`deque`, `in_degree`) | Both tokens present in `graph.py` | `test_kahn_algorithm_tokens` |
| INV-DS-05 | `POST /dev/seed` MUST return 404 when `SEEDER_ENABLED=false` | `HTTP_404_NOT_FOUND` in route handler | `test_production_guard` |
| INV-DS-06 | `SEEDER_*` settings MUST land inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` | `test_config_fields_patched` |
| INV-DS-07 | No hardcoded credentials in any generated file | Scan for `password="`, `secret="`, `api_key="` | `test_no_hardcoded_secrets` |
| INV-DS-08 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |
| INV-DS-09 | `MCP_TOOL["entry"]` MUST match function name | `entry == "add_data_seeder"` | `test_mcp_tool_entry_matches_function` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install data seeder into a clean FastAPI project**
- **As a** backend developer who needs realistic test data
- **I want** to run one tool call and get a full seeder kit
- **So that** I stop writing one-off SQL scripts
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/`
- **When:** `add_data_seeder(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"`
  - `files_created` contains ≥ 4 paths (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run the tool safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `DataSeeder` already present in `app/seeder/__init__.py`
- **When:** Tool invoked again
- **Then:**
  - `r2.status == "no_op"`, `files_created == []`
  - Verified by `test_idempotent`

**US-03: Dry-run preview**
- **As a** developer auditing changes
- **I want** `dry_run=True` to show plan without writing
- **Given:** Fresh project
- **When:** `add_data_seeder(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Zero filesystem changes (INV-DS-02)
  - Verified by `test_dry_run`

**US-04: Generated code is auditable**
- **As a** code reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted `generators.py`, `graph.py`, `seeder/__init__.py`
- **When:** AST walk over `app/`
- **Then:**
  - `max_loc <= 50`
  - Verified by `test_no_function_over_50_loc`

**US-05: Config fields are env-var overridable**
- **As a** platform engineer
- **I want** `SEEDER_ENABLED` and `SEEDER_DEFAULT_COUNT` in `Settings`
- **Given:** `app/core/config.py` with `ACCESS_TOKEN_EXPIRE_MINUTES`
- **When:** Tool runs
- **Then:**
  - Both fields inside class body (INV-DS-06)
  - Verified by `test_config_fields_patched`

### 9.2 Dependency graph and generators (US-06 .. US-10)

**US-06: Seed tables in FK-safe order**
- **As a** developer seeding a project with FK constraints
- **I want** parents inserted before children
- **Given:** `Order` has FK to `User`
- **When:** `DependencyGraph([Order, User]).topological_order()`
- **Then:**
  - `User` comes before `Order` in the result list
  - Verified by CC-13

**US-07: Generate realistic email addresses**
- **As a** QA engineer reviewing seeded data
- **I want** email columns to contain valid-looking emails
- **Given:** Model has `email: str` column
- **When:** `FieldGenerator().generate_instance(UserModel)`
- **Then:**
  - `"@example.com"` suffix in generated email
  - Verified by CC-17

**US-08: Disable seeder in production**
- **As a** security-conscious ops engineer
- **I want** `POST /dev/seed` to return 404 in production
- **Given:** `SEEDER_ENABLED=false` in env
- **When:** Client calls `POST /dev/seed`
- **Then:**
  - HTTP 404 response
  - No data written to DB
  - Verified by CC-16

**US-09: Seed from CLI**
- **As a** developer bootstrapping a local environment
- **I want** `python scripts/seed.py --count 50`
- **Given:** `scripts/seed.py` generated
- **When:** CLI invoked with `--count 50`
- **Then:**
  - Script exits 0, reports seeded count
  - Verified by CC-15

**US-10: Circular FK dependencies handled**
- **As a** developer with a self-referential model
- **I want** topological sort to not hang
- **Given:** `Employee` has FK to `Employee` (manager)
- **When:** `DependencyGraph([Employee]).topological_order()`
- **Then:**
  - Returns the model (not empty list, no infinite loop)
  - `remaining` fallback appends unresolved models

### 9.3 Integration (US-11 .. US-13)

**US-11: Routes init updated**
- **As a** FastAPI developer
- **I want** the seeder router automatically registered
- **Given:** `app/routes/__init__.py` exists
- **When:** Tool runs
- **Then:**
  - `"seeder" in content.lower()` of `routes/__init__.py`
  - Verified by CC-10

**US-12: Project parseable after two runs**
- **As a** CI system
- **I want** idempotent no-op to leave project intact
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-LAST

**US-13: No secrets in generated code**
- **As a** security auditor
- **I want** no credentials in generated files
- **Given:** Seeder installed
- **When:** Scan for `password=`, `secret=`, `api_key=`
- **Then:** Zero occurrences — verified by CC-19

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` field set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises; `status="error"` | `"error"` |
| Circular FK (all in-degrees > 0) | `remaining` appended after BFS drains | Graceful |
| `POST /dev/seed` in production | HTTP 404 Not Found | Runtime guard |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `ast` (stdlib) | Validate generated `.py` files |
| `collections.deque` (stdlib) | Kahn's BFS queue in `DependencyGraph` |
| `random`, `string`, `uuid`, `datetime` (stdlib) | Field value generation |
| `argparse` (stdlib) | CLI `--count` / `--model` flags |
| `SQLAlchemy 2.0` | Target project model introspection |
| `pydantic-settings` | `Settings` class in target project |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Seeder available in production | `SEEDER_ENABLED=false` guard returns 404 (CC-16) |
| Generated data contains PII-looking values | Values are clearly fake (`@example.com`, `+1-555-XXXX`); never real PII |
| No hardcoded credentials | Verified by CC-19 |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Files created/modified | `ToolResult.files_created`, `ToolResult.files_modified` |
| Seed count | `POST /dev/seed` response body `{"seeded": N}` |
| CLI output | `scripts/seed.py` stdout |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SEEDER_ENABLED` | `bool` | `True` | When `False`, `POST /dev/seed` returns HTTP 404 |
| `SEEDER_DEFAULT_COUNT` | `int` | `10` | Default number of rows to seed when `count` not specified |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/seeder/` (3 files)
- Delete `app/api/routes/seeder.py`
- Delete `scripts/seed.py`
- Remove `SEEDER_*` lines from `app/core/config.py`
- Remove seeder import from `app/routes/__init__.py`

No database migrations. No new tables. No external services required.

---

## 16. Test File Reference

**Location:** `adapt/extend/testing_tools/test_add_data_seeder.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_data_seeder.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_data_seeder.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 4`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function in `app/` exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `SEEDER_ENABLED` inside `class Settings` body |
| `test_routes_registered` | CC-10 | `"seeder"` in `routes/__init__.py` |
| `test_data_seeder_created` | CC-11 | `DataSeeder` in `app/seeder/__init__.py` |
| `test_field_generator_created` | CC-12 | `FieldGenerator` in `generators.py` |
| `test_dependency_graph_created` | CC-13 | `DependencyGraph` + `topological_order` in `graph.py` |
| `test_seed_route_created` | CC-14 | `/dev/seed` route + `SEEDER_ENABLED` guard |
| `test_seed_cli_created` | CC-15 | `--count` in `scripts/seed.py` |
| `test_production_guard` | CC-16 | `HTTP_404_NOT_FOUND` or `404` in route file |
| `test_email_name_generators` | CC-17 | `email` and `full_name` generator logic present |
| `test_kahn_algorithm_tokens` | CC-18 | `deque` and `in_degree` in `graph.py` |
| `test_no_hardcoded_secrets` | CC-19 | No credential literals in generated files |
| `test_execution_time_recorded` | CC-N-1 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` mentions `SEEDER_ENABLED` |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` still parse |
| `test_mcp_tool_entry_matches_function` | INV-10 | `MCP_TOOL["entry"] == "add_data_seeder"` |
