# GraphQL layer over existing REST

## Requirements

- Expose a GraphQL endpoint that resolves queries by calling the existing internal REST services.
- A single GraphQL query that touches N resources must batch downstream REST calls per service and execute the batches concurrently.
- Field-level authorization: some fields are visible only to specific roles; unauthorized fields return null with an explanatory error, not 403.
- Depth and complexity limits prevent abusive queries.
- Persisted queries: clients can register a query by id and send the id + variables in production, for cache and auditability.

## Acceptance criteria

- A query requesting 50 orders with their customers and products issues 3 batched calls (orders, customers, products), not 101 serial calls.
- A query 40 levels deep is rejected with a clear error before execution.
- An unauthorized field returns `null` and an error entry; no 403 at the HTTP level.
- A persisted query id not present in the registry is rejected in production mode.

## Non-requirements

- No mutations — read-only.
- No subscriptions.
- No federation.
- No built-in caching between GraphQL and REST; that is the REST tier's concern.
