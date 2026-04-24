# tenant-admin-dashboard

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: multi-tenant SaaS with admin endpoints scoped per tenant.
Dashboard shows usage + billing per tenant. Admin from tenant A cannot
see tenant B's data.]

## Acceptance criteria

- Admin from tenant A GET `/tenants/B/usage` returns 404 (not 403).
- Admin GET `/tenants/A/usage` returns metrics for tenant A only.
- A non-admin user GET on any admin endpoint returns 403.
- Tenant scope is bound to the JWT, not query params.

## Non-requirements

- No cross-tenant aggregation at v1.
- No admin role hierarchy beyond admin / non-admin.
