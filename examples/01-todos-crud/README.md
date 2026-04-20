# Example 01 — Todos CRUD

**Tier:** baseline · **Benchmark spec:** `baseline/01_crud_todos.md`

A minimal per-user todos API with stable keyset pagination. Demonstrates the
smallest useful slice of SKILL-001: auth dependency + owned-resource access
control + cursor pagination that never duplicates or skips.

## What this example shows

- Owned-resource 404s (never leak existence with a 403).
- Keyset pagination (stable under concurrent inserts).
- A clean split between the generated scaffold (handled by the skill's
  `fastapi_generate_project` tool) and per-route business logic.

## How to run

```bash
cd examples/01-todos-crud
python3.12 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                         | What it generated / verified in this example      |
| ---------------------------- | ------------------------------------------------- |
| `fastapi_generate_project`   | Base app skeleton (conceptual — see MAESTRO_SESSION). |
| `fastapi_add_crud_resource`  | `todos` resource with owner-scoped list/get/patch/delete. |
| `fastapi_add_pagination`     | Keyset cursor over `(created_at, id)`.            |
| `fastapi_add_auth_jwt`       | Bearer JWT → `current_user` dependency.           |

## Primitives imported

| Primitive           | Role in this example                                       |
| ------------------- | ---------------------------------------------------------- |
| `Repository`        | Typed persistence boundary for `Todo`.                     |
| `UnitOfWork`        | Atomic write guard on create/update.                       |
| `CurrentPrincipal`  | Resolved caller identity, drives owner filtering.          |
| `RequestGuard`      | 401 on missing/invalid JWT.                                |

See each primitive's reference page at `docs.hugr.dev/primitive/<Name>`.
