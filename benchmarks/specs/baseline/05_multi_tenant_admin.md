# Multi-tenant admin backend

## Requirements

- Multiple organizations share the same deployment; rows are scoped per `tenant_id`.
- An admin user belongs to exactly one tenant and can only view or edit that tenant's rows.
- A super-admin (platform operator) can impersonate into any tenant for support; impersonation is logged.
- Every mutation records: who, when, which tenant, which row, before/after state.
- Deleting a tenant purges all its data within 7 days, including cached views.

## Acceptance criteria

- A cross-tenant read (admin A requests tenant B's data) returns 404 and is logged as a suspicious event.
- Impersonation entries appear in the audit trail with the super-admin's real identity AND the impersonated tenant.
- The purge job, run for a deleted tenant, leaves zero rows across all tables referencing that `tenant_id`.
- Audit entries are tamper-evident: modifying a stored entry makes its hash verification fail.

## Non-requirements

- No per-tenant custom domains.
- No billing or subscription state.
- No tenant-level feature flags.
- No data residency constraints (single region OK).
