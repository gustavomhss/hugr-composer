# Example 05 — RBAC with tamper-evident audit

**Tier:** mid · **Benchmark spec:** `mid/04_rbac_with_audit.md`

Role-based access control with hash-chained audit and a bounded-TTL
break-glass role. Demonstrates the **`RequestGuard` + `TamperEvidentAuditLog`
+ `AuditEvent`** recipe.

## What this example shows

- 403 on denied access returned **without** leaking resource existence
  (generator enforces the 404-vs-403 distinction where appropriate;
  here the resource itself is visible by role, so 403 is correct).
- Every permission check — allow **and** deny — recorded as an `AuditEvent`.
- Hash-chain verification: altering any audit record breaks the chain.
- Break-glass role auto-expires; cannot be renewed without a fresh reason.

## How to run

```bash
cd examples/05-rbac-audit
python3.12 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                | Role                                            |
| ----------------------------------- | ----------------------------------------------- |
| `fastapi_add_rbac`                  | Role + permission matrix + edge check.          |
| `fastapi_add_audit_log`             | Chained audit record emitter.                   |
| `fastapi_add_break_glass_role`      | TTL-bounded emergency escalation.               |

## Primitives imported

| Primitive                  | Role                                               |
| -------------------------- | -------------------------------------------------- |
| `RequestGuard`             | Edge check: role+resource → allow/deny.            |
| `AuditEvent`               | Structured per-check record.                       |
| `TamperEvidentAuditLog`    | SHA-256 hash chain over audit records.             |
| `CurrentPrincipal`         | Resolved caller — role set resolved per request.   |
| `FeatureToggle`            | Emergency kill-switch for break-glass policy.      |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
