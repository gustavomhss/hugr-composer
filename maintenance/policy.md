# Policy Domain — Maintenance Skill

> **Crate**: 1 (`PolicyEngine`) | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Policy engine for authorization, feature flags, rate limiting, and business rules.

---

## Crate: `PolicyEngine`

**Location**: `core/venous/policy/PolicyEngine/`

**Purpose**: Centralized policy evaluation engine for authorization, feature flags, rate limiting, and business rules with OPA-style policy language.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    POLICY ENGINE                            │
├─────────────────────────────────────────────────────────────┤
│  Request → PolicyEngine → PolicyEvaluation → Decision      │
│       ↓                                                      │
│  Policy Store (OPA/Rego or Cedar)                          │
│       ↓                                                      │
│  Cache (LRU + TTL)                                         │
│       ↓                                                      │
│  Audit Log                                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Crate: `PolicyEngine`

**Purpose**: Centralized policy evaluation engine supporting multiple policy languages (OPA Rego, Cedar) with caching, audit logging, and hot-reload.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    POLICY ENGINE                            │
├─────────────────────────────────────────────────────────────┤
│  Request → PolicyEngine → PolicyEvaluation → Decision      │
│       ↓                                                      │
│  Policy Store (OPA/Rego or Cedar)                          │
│       ↓                                                      │
│  Cache (LRU + TTL)                                         │
│       ↓                                                      │
│  Audit Log                                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 1. Policy Evaluation

```python
from generators.policy.engine import PolicyEngine

engine = PolicyEngine(
    policy_store=OpaPolicyStore(path="policies/"),
    cache_ttl=300,  # 5 minutes
    audit_log=audit_logger,
)

# Evaluate policy
result = await engine.evaluate(
    policy="rbac/access",
    input={
        "user": {"id": "user-123", "roles": ["admin"], "department": "engineering"},
        "resource": {"type": "document", "id": "doc-123", "owner": "user-456"},
        "action": "read",
        "context": {"ip": "10.0.0.1", "time": "2026-09-04T10:00:00Z"},
    },
)

# Result
if result.allowed:
    # Access granted
    pass
else:
    # Denied with reason
    raise Forbidden(result.reason)
```

---

### 2. Policy Language (Rego)

```rego
# policies/rbac/access.rego
package rbac.access

default allow = false

allow {
    input.user.roles[_] == "admin"
}

allow {
    input.action == "read"
    input.resource.owner == input.user.id
}

allow {
    input.action == "write"
    input.user.roles[_] == "editor"
    input.resource.department == input.user.department
}

# Deny with reason
deny[msg] {
    input.action == "delete"
    not input.user.roles[_] == "admin"
    msg := "Only admins can delete resources"
}
```

### 3. Policy Evaluation with Context

```python
# Rich context for complex decisions
result = await engine.evaluate(
    policy="abac/document_access",
    input={
        "subject": {
            "id": "user-123",
            "roles": ["engineer"],
            "department": "engineering",
            "clearance": "confidential",
            "location": "us-east-1",
        },
        "resource": {
            "type": "document",
            "id": "doc-123",
            "classification": "confidential",
            "owner": "user-456",
            "department": "engineering",
            "tags": ["project-alpha", "pii"],
        },
        "action": "read",
        "environment": {
            "time": "2026-09-04T10:00:00Z",
            "ip": "10.0.0.1",
            "device_trusted": true,
            "mfa_verified": true,
        },
    },
)

# Result
if result.allowed:
    # Access granted with obligations
    obligations = result.obligations  # e.g., ["log_access", "watermark"]
else:
    # Denied with detailed reason
    deny_reasons = result.deny_reasons
```

---

## Common Patterns

### 1. RBAC with ABAC Extensions

```rego
package rbac.access

default allow = false

# Role-based access
allow {
    input.user.roles[_] == "admin"
}

# Attribute-based access
allow {
    input.action == "read"
    input.resource.owner == input.user.id
}

allow {
    input.action == "read"
    input.user.roles[_] == "viewer"
    input.resource.department == input.user.department
}

# Time-based access
allow {
    input.action == "read"
    input.environment.time >= "09:00:00"
    input.environment.time <= "18:00:00"
    input.user.roles[_] == "contractor"
}

# MFA required for sensitive actions
allow {
    input.action == "write"
    input.environment.mfa_verified == true
    input.user.roles[_] == "engineer"
}

deny[msg] {
    input.action == "delete"
    not input.user.roles[_] == "admin"
    msg := "Only admins can delete resources"
}

deny[msg] {
    input.resource.classification == "top_secret"
    input.user.clearance != "top_secret"
    msg := "Insufficient clearance for top secret resource"
}
```

---

### 2. Rate Limiting Policy

```rego
package ratelimit.policy

default allow = false

allow {
    input.client.tier == "premium"
    input.requests_last_minute < 1000
}

allow {
    input.client.tier == "standard"
    input.requests_last_minute < 100
}

allow {
    input.client.tier == "free"
    input.requests_last_minute < 10
}

deny[msg] {
    input.client.tier == "premium"
    input.requests_last_minute >= 1000
    msg := "Premium rate limit exceeded (1000/min)"
}

deny[msg] {
    input.client.tier == "standard"
    input.requests_last_minute >= 100
    msg := "Standard rate limit exceeded (100/min)"
}

deny[msg] {
    input.client.tier == "free"
    input.requests_last_minute >= 10
    msg := "Free tier rate limit exceeded (10/min)"
}
```

---

### 3. Feature Flag Policy

```rego
package featureflags

default enabled = false

enabled {
    input.flag.enabled == true
    input.flag.rollout_percentage >= input.user.rollout_bucket
}

enabled {
    input.flag.enabled == true
    some rule in input.flag.targeting_rules
    rule_matches(rule, input.user)
    rule.rollout_percentage >= input.user.rollout_bucket
}

rule_matches(rule, user) {
    rule.attribute == "plan"
    rule.operator == "in"
    user.plan in rule.values
}

rule_matches(rule, user) {
    rule.attribute == "country"
    rule.operator == "in"
    user.country in rule.values
}

rule_matches(rule, user) {
    rule.attribute == "email"
    rule.operator == "ends_with"
    endswith(user.email, rule.values[_])
}
```

---

## Common Patterns

### 1. Feature Flag Evaluation

```python
# In your application
async def is_feature_enabled(user: User, flag_key: str) -> bool:
    result = await policy_engine.evaluate(
        policy="featureflags/enabled",
        input={
            "flag": await get_flag(flag_key),
            "user": {
                "id": user.id,
                "plan": user.plan,
                "country": user.country,
                "email": user.email,
                "rollout_bucket": user.rollout_bucket,  # 0-99
            },
        },
    )
    return result.allowed
```

### 2. Rate Limiting Middleware

```python
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client = identify_client(request)
    
    result = await policy_engine.evaluate(
        policy="ratelimit/policy",
        input={
            "client": {"tier": client.tier, "id": client.id},
            "requests_last_minute": await get_request_count(client.id),
        },
    )
    
    if not result.allowed:
        return JSONResponse(
            status_code=429,
            content={"error": result.deny_reasons[0]},
            headers={"Retry-After": "60"},
        )
    
    return await call_next(request)
```

---

## Common Operations

### 1. Policy Evaluation

```python
result = await engine.evaluate(
    policy="rbac/access",
    input={
        "user": {"id": "user-123", "roles": ["admin"], "department": "engineering"},
        "resource": {"type": "document", "id": "doc-123", "owner": "user-456"},
        "action": "read",
        "context": {"ip": "10.0.0.1", "time": "2026-09-04T10:00:00Z"},
    },
)

if result.allowed:
    # Access granted
    pass
else:
    raise Forbidden(result.reason)
```

### 2. Batch Evaluation

```python
results = await engine.evaluate_batch(
    policy="rbac/access",
    inputs=[
        {"user": {"id": "u1", "roles": ["admin"]}, "action": "read", "resource": {"id": "d1"}},
        {"user": {"id": "u2", "roles": ["viewer"]}, "action": "write", "resource": {"id": "d2"}},
    ],
)
```

### 3. Policy Composition

```python
# Combine policies
combined = PolicyEngine(
    policies=["rbac/access", "ratelimit/policy", "featureflags/enabled"],
    combine="all",  # or "any"
)

result = await combined.evaluate(input)
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Policy too permissive** | Security holes | Default deny; explicit allow |
| **Policy too restrictive** | False positives | Test with real data; add exceptions |
| **Policy too complex** | Hard to debug | Split into smaller policies |
| **No cache** | High latency | Enable caching with TTL |
| **No audit log** | Can't debug denials | Enable audit logging |
| **Policy drift** | Inconsistent decisions | Version control + CI tests |
| **No default deny** | Accidental allow | Default deny = false |
| **Policy too broad** | Over-permission | Principle of least privilege |

---

## Evolution Without Breaking Contracts

### Adding a New Rule

```rego
# Non-breaking: add new rule (default deny)
allow {
    input.action == "new_action"
    input.user.roles[_] == "new_role"
}
```

### Adding New Attribute

```rego
# Non-breaking: use optional attribute
allow {
    input.user.new_attribute == "value"
}
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing default deny/allow | **REVIEW** — Security impact |
| Adding new policy | **REVIEW** — Security review |
| Changing default behavior | **REVIEW** — Breaking change risk |
| Removing a rule | **REVIEW** — May grant access |
| Changing default deny/allow | **STOP** — Security critical |

---

## Health Checks & Monitoring

```python
@app.get("/health/policy")
async def policy_health():
    return {
        "status": "healthy",
        "checks": {
            "policy_store": await check_policy_store(),
            "cache": await check_cache_health(),
            "evaluation_latency": await check_eval_latency(),
        }
    }

# Metrics:
# - policy.evaluation.latency.p99
# - policy.allowed.rate
# - policy.denied.rate
# - policy.cache.hit_rate
# - policy.errors.rate
```

---

## Debugging Quick Reference

```bash
# Test policy evaluation
python -c "
from app.policy import PolicyEngine
engine = PolicyEngine()
result = engine.evaluate('rbac/access', {'user': {'roles': ['admin']}, 'action': 'read', 'resource': {'owner': 'user-123'}})
print(f'Allowed: {result.allowed}, Reason: {result.reason}')
"

# Test policy with input file
opa eval -i input.json -d policies/ -q 'data.rbac.access.allow'

# Trace evaluation
opa eval --trace -i input.json -d policies/ 'data.rbac.access.allow'

# List all policies
ls policies/
"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Cache TTL | `cache_ttl` | 300s (5 min) |
| Cache size | `max_entries` | 10000 |
| Evaluation timeout | `timeout` | 100ms |
| Concurrent evaluations | `max_concurrent` | 100 |

---

## Security Checklist

- [ ] Default deny
- [ ] All policies version controlled
- [ ] CI tests for policies
- [ ] Audit log for all decisions
- [ ] Cache invalidation on policy change
- [ ] Rate limiting on policy API
- [ ] Input validation on policy API
- [ ] No secrets in policies
- [ ] Regular policy review (quarterly)

---

*Policy Domain Maintenance Skill v1.0 | Maintained by Platform Team | Next review: 2026-12-04*