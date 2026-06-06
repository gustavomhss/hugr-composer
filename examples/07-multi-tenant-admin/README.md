# Example 07 — Multi-tenant admin backend

**Tier:** baseline · **Benchmark spec:** `baseline/05_multi_tenant_admin.md`

Tenant-scoped rows + super-admin impersonation with full audit.
Demonstrates the **`CurrentPrincipal` + `RequestGuard` +
`TamperEvidentAuditLog`** recipe for tenanted SaaS.

## What this example shows

- Cross-tenant read returns 404 (never 403 — anti-enumeration).
- Super-admin impersonation produces an audit entry with BOTH the
  real super-admin identity and the impersonated tenant.
- Every mutation records who/when/tenant/row/before/after.
- Tenant-purge job leaves zero rows in any table referencing the
  purged `tenant_id`.

## How to run

```bash
cd examples/07-multi-tenant-admin
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                           | Role                                          |
| ------------------------------ | --------------------------------------------- |
| `fastapi_add_multi_tenant`     | Tenant-scoping middleware + `tenant_id` FK.   |
| `fastapi_add_impersonation`    | Super-admin impersonation + audit wiring.     |
| `fastapi_add_audit_log`        | Before/after mutation record with hash chain. |
| `fastapi_add_tenant_purge_job` | Hard-delete job across all tenant tables.     |

## Primitives imported

| Primitive                 | Role                                           |
| ------------------------- | ---------------------------------------------- |
| `CurrentPrincipal`        | Resolved identity (+ impersonated tenant).     |
| `RequestGuard`            | Edge check: tenant match → allow/404.          |
| `TamperEvidentAuditLog`   | Hash-chained audit trail.                      |
| `DataResidencyPolicy`     | (Future) multi-region scoping; single-region here. |
| `RetentionPolicy`         | 7-day purge SLA enforcement.                   |
