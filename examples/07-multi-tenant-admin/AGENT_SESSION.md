# agent session — 07-multi-tenant-admin

Plan-level transcript for `baseline/05_multi_tenant_admin.md`.

## Requirement → kit mapping

1. **Tenant-scoped rows (admin A ≠ tenant B).**
   → `CurrentPrincipal` resolves `admin.tenant_id`. `RequestGuard`
     returns 404 (not 403) when the requested resource's
     `tenant_id` ≠ principal's.
2. **Super-admin impersonation with audit.**
   → Impersonation sets `principal.impersonated_tenant_id`; every
     audit record carries both `real_user_id` and `tenant_id`.
3. **Mutations carry before/after.**
   → Generator emits an audit hook around every `POST/PATCH/DELETE`.
4. **Tenant purge SLA (7 days).**
   → `RetentionPolicy` schedules a cascading hard-delete 7 days
     post-flag; job is idempotent.
5. **Audit tamper-evident.**
   → Hash chain over audit records (reuses 05-rbac-audit recipe).

## Tool call sequence

```
1. fastapi_generate_project(name="mt_admin")
2. fastapi_add_multi_tenant(scope_column="tenant_id",
                             not_found_on_cross_tenant=True)
3. fastapi_add_impersonation(
     audit=True, requires_role="super_admin")
4. fastapi_add_audit_log(chained=True, hook_on=["POST","PATCH","DELETE"])
5. fastapi_add_tenant_purge_job(ttl_days=7)
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
