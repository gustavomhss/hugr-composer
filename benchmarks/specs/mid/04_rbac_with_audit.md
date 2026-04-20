# RBAC with audit trail

## Requirements

- Users are assigned one or more roles; roles grant permissions on resources.
- Permissions are checked at the edge; unauthorized calls return 403 without leaking resource existence.
- Every permission check (allow AND deny) is recorded for audit.
- Audit records are tamper-evident; altering a record breaks verification.
- A "break glass" emergency role grants temporary super-user access with mandatory reason and automatic expiry.

## Acceptance criteria

- Role assignment changes take effect on the next request without requiring the user to re-authenticate.
- An auditor exporting yesterday's deny events sees reason, user, resource, role set at time of denial.
- Tampering with an audit record (changing a reason field) is detected by a hash-chain verifier.
- Break-glass sessions expire within the declared TTL and cannot be renewed without a new reason.

## Non-requirements

- No attribute-based access control (ABAC); role-based only.
- No self-service role requests.
- No SIEM integration.
- No SAML or SSO.
