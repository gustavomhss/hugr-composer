# Example 13 — GraphQL layer over existing REST

**Tier:** mid · **Benchmark spec:** `mid/08_graphql_over_rest.md`

Read-only GraphQL resolvers that batch downstream REST calls, enforce
depth/complexity caps, and gate fields by role. Demonstrates the
**`DataLoader` + `PersistedQueryRegistry` + `RequestGuard`** recipe.

## What this example shows

- `50 orders → customers → products` issues 3 batched calls, not 101 serial.
- A 40-level deep query is rejected before execution.
- Unauthorized fields return `null` + an error entry (not 403 at HTTP).
- Persisted-query id unknown to the registry is rejected in production mode.

## How to run

```bash
cd examples/13-graphql-over-rest
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_graphql_endpoint`       | POST /graphql entrypoint.                       |
| `fastapi_add_dataloader`             | Per-request batching across N resolvers.        |
| `fastapi_add_query_depth_limit`      | Depth + complexity cap.                         |
| `fastapi_add_persisted_queries`      | Allow-list keyed by SHA-256 of the query.       |

## Primitives imported

| Primitive                  | Role                                             |
| -------------------------- | ------------------------------------------------ |
| `DataLoader`               | Per-tick batched fetch per key-type.             |
| `PersistedQueryRegistry`   | SHA-256 allow-list for production clients.       |
| `RequestGuard`             | Field-level ACL returning `null` + error.        |
| `InputValidator`           | Depth + complexity analyser.                     |
| `QueryBus`                 | Read-path dispatcher.                            |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
