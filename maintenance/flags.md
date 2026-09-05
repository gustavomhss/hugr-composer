# Flags Domain — Maintenance Skill

> **Crates**: 1 (`FeatureFlagCache`) | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Distributed feature flag cache with TTL, targeting, and real-time updates.

---

## Crate: `FeatureFlagCache`

**Location**: `core/venous/auth/FeatureFlagCache/`

**Purpose**: High-performance distributed feature flag cache with targeting rules, gradual rollout, and real-time updates.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FEATURE FLAG CACHE                       │
├─────────────────────────────────────────────────────────────┤
│  Request → Cache → Targeting Rules → Flag Value            │
│       ↓                                                      │
│  Redis (distributed) + Local Cache (LRU)                   │
│       ↓                                                      │
│  Real-time Updates (Pub/Sub)                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Flag Definition

```python
@dataclass
class FeatureFlag:
    key: str                          # Unique flag key
    name: str                         # Human-readable name
    description: str
    enabled: bool                     # Global on/off
    default_value: Any                # Default when no targeting matches
    targeting_rules: list[TargetingRule]
    rollout_percentage: int = 0       # 0-100 gradual rollout
    variants: dict[str, Any] = {}     # A/B test variants
    created_at: datetime
    updated_at: datetime
    created_by: str
```

### Targeting Rules

```python
@dataclass
class TargetingRule:
    attribute: str                    # User attribute (e.g., "email", "country", "plan")
    operator: Operator                # equals, in, not_in, contains, gt, lt, etc.
    values: list[Any]                 # Values to match
    rollout_percentage: int = 100     # Percentage of matching users
    variants: dict[str, int] = {}     # Variant weights for A/B
```

---

## Common Operations

### 1. Feature Flag Evaluation

```python
from core.venous.auth.FeatureFlagCache import FeatureFlagCache

cache = FeatureFlagCache(redis_client)

# Simple boolean flag
async def is_feature_enabled(user: User, flag_key: str) -> bool:
    return await cache.is_enabled(flag_key, context={
        "user_id": user.id,
        "email": user.email,
        "plan": user.plan,
        "country": user.country,
        "role": user.role,
    })

# Variant for A/B testing
async def get_variant(user: User, flag_key: str) -> str:
    return await cache.get_variant(flag_key, context={
        "user_id": user.id,
        "email": user.email,
        "plan": user.plan,
    })

# With default
enabled = await cache.is_enabled("new_checkout", context=user_context, default=False)
```

---

### 2. Flag Management (Admin)

```python
# Create flag
await flag_admin.create_flag(
    key="new_checkout_flow",
    name="New Checkout Flow",
    description="Enables the redesigned checkout flow",
    enabled=True,
    default_value=False,
    targeting_rules=[
        TargetingRule(
            attribute="plan",
            operator="in",
            values=["premium", "enterprise"],
            rollout_percentage=100,
        ),
        TargetingRule(
            attribute="country",
            operator="in",
            values=["US", "CA", "GB"],
            rollout_percentage=50,
        ),
    ],
    variants={
        "control": 50,
        "variant_a": 25,
        "variant_b": 25,
    },
)

# Update flag
await flag_admin.update_flag("new_checkout_flow", rollout_percentage=75)

# Rollback
await flag_admin.disable("new_checkout_flow")

# Archive
await flag_admin.archive("old_feature")
```

---

### 3. Client-Side Usage

```python
# Frontend SDK
const flags = await featureFlags.initialize({
    apiUrl: '/api/flags',
    userId: 'user-123',
    attributes: { plan: 'premium', country: 'US' }
});

// Check flag
if (flags.isEnabled('new_checkout_flow')) {
    renderNewCheckout();
}

// Get variant
const variant = flags.getVariant('new_checkout_flow'); // 'control' | 'variant_a' | 'variant_b'
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Cache stampede** | All instances hit DB on cache miss | Use `DistributedLock` for cache warming |
| **Stale flags** | Users see old values | TTL ≤ 60s; pub/sub invalidation |
| **Targeting rule conflicts** | Unexpected flag values | Rules evaluated in order; first match wins |
| **Rollout too aggressive** | Bugs affect many users | Start small (1-5%); monitor; increase gradually |
| **No rollback plan** | Bug affects all users | Always have kill switch (`enabled: false`) |
| **Cache inconsistency** | Different values across instances | Pub/sub invalidation + local TTL |
| **Targeting rule conflicts** | Wrong users get flag | Test rules with sample users before deploy |

---

## Evolution Without Breaking Contracts

### Adding a New Feature Flag

```python
# Non-breaking: add new flag with default off
await flag_admin.create_flag(
    key="new_feature",
    name="New Feature",
    description="Enables the new feature",
    enabled=True,
    default_value=False,
    targeting_rules=[
        TargetingRule(
            attribute="plan",
            operator="in",
            values=["premium", "enterprise"],
            rollout_percentage=100,
        ),
    ],
)
```

### Changing Rollout Percentage

```python
# Non-breaking: adjust rollout percentage
await flag_admin.update("new_feature", rollout_percentage=75)
```

### Adding Targeting Rule

```python
# Non-breaking: add targeting rule
await flag_admin.update("feature_key", targeting_rules=[
    TargetingRule(attribute="plan", operator="in", values=["premium"]),
])
```

### Removing a Flag

```python
# Non-breaking: disable first, then archive
await flag_admin.disable("feature_key")
await flag_admin.archive("feature_key")
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing default value | **REVIEW** — Affects all users |
| Removing a flag | **REVIEW** — Cleanup required |
| Changing targeting rules | **REVIEW** — Affects user segments |
| Changing rollout percentage | **REVIEW** — Monitor error rates |
| Adding targeting rule | **REVIEW** — Test with sample users first |

---

*Flags Domain Maintenance Skill v1.0 | Maintained by Platform Team | Next review: 2026-12-04*

