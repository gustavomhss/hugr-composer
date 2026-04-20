# Maestro session — 13-graphql-over-rest

Plan-level transcript for `mid/08_graphql_over_rest.md`.

## Requirement → kit mapping

1. **Batched REST calls per service.**
   → `DataLoader` dedup + bulk fetch per tick — N resolvers → 1 call.
2. **Depth + complexity caps.**
   → `InputValidator` walks the query AST; rejects > depth_limit.
3. **Field-level ACL → null + error.**
   → `RequestGuard` returns `(null, error_entry)` instead of HTTP 403.
4. **Persisted queries.**
   → `PersistedQueryRegistry` keyed by SHA-256; unknown id rejected in prod.

## Tool call sequence

```
1. fastapi_generate_project(name="gql_svc")
2. fastapi_add_graphql_endpoint()
3. fastapi_add_dataloader(batch_window_ms=1)
4. fastapi_add_query_depth_limit(max_depth=15)
5. fastapi_add_persisted_queries(prod_only=True)
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
