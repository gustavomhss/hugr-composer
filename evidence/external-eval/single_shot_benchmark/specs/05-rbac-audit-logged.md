# rbac-audit-logged

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: role-based access with audit log for every privileged action.
Roles: viewer / editor / admin. Audit log captures actor, action, target,
timestamp.]

## Acceptance criteria

- A viewer GET on a public resource returns 200.
- A viewer POST on the same resource returns 403.
- An admin DELETE produces an audit entry within 1s.
- The audit log is append-only (DELETE on audit table returns 405).

## Non-requirements

- No fine-grained permissions beyond role at v1.
- No external SIEM integration.
