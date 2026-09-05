# Cost Domain — Maintenance Skill

> **Crate**: 1 (`CostTracker`) | **Status**: Production-ready | **Owner**: FinOps Team | **Last Updated**: 2026-09-04

> **Purpose**: Cost tracking, budgeting, forecasting, and anomaly detection for cloud and API costs.

---

## Crate: `CostTracker`

**Location**: `core/venous/resiliency/CostTracker/`

**Purpose**: Comprehensive cost tracking, budgeting, forecasting, and anomaly detection for all cloud and API costs.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      COST TRACKER                           │
├─────────────────────────────────────────────────────────────┤
│  Events → Collectors → Aggregator → Budgets → Alerts       │
│       ↓                                                      │
│  Collectors: CloudWatch, GCP, Azure, APIs, LLM, DB         │
│       ↓                                                      │
│  Aggregator → Hourly/Daily/Monthly Rollups                 │
│       ↓                                                      │
│  Budgets → Thresholds → Alerts → Actions                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Crate: `CostTracker`

**Purpose**: End-to-end cost observability — tracking, budgeting, forecasting, and anomaly detection.

---

## Key Features

### 1. Multi-Source Cost Collection

```python
from core.venous.resiliency.CostTracker import CostTracker

tracker = CostTracker()

# Register collectors
tracker.register_collector("aws", AWSCollector(
    regions=["us-east-1", "eu-west-1"],
    credentials=aws_creds,
))

tracker.register_collector("gcp", GCPCollector(
    project_id="my-project",
    credentials=gcp_creds,
))

tracker.register_collector("llm", LLMCostCollector(
    pricing=llm_pricing,
))

tracker.register_collector("database", DatabaseCostCollector(
    connection_pool=pool,
))

# Run collection
await tracker.collect_all()
```

---

### 2. Budget Management

```python
# Define budgets
budgets = {
    "monthly_total": Budget(
        limit=10000.00,           # $10k/month
        period="monthly",
        alert_threshold=0.8,      # Alert at 80%
        action="alert",           # or "throttle", "block"
    ),
    "llm_daily": Budget(
        limit=100.00,             # $100/day for LLM
        period="daily",
        alert_threshold=0.9,
        action="throttle",
    ),
    "aws_monthly": Budget(
        limit=5000.00,
        period="monthly",
        alert_threshold=0.85,
        action="alert",
    ),
}

tracker.set_budgets(budgets)

# Check budgets
status = await tracker.check_budgets()
# Returns: {budget_name: {used, limit, percent, status}}
```

---

### 3. Cost Anomaly Detection

```python
# Anomaly detection config
anomaly_config = AnomalyConfig(
    method="statistical",  # or "ml", "threshold"
    sensitivity=3.0,       # Standard deviations
    min_samples=30,        # Minimum data points
    lookback_days=30,
)

detector = AnomalyDetector(anomaly_config)

# Detect anomalies
anomalies = await detector.detect(cost_data)
# Returns: list of Anomaly(timestamp, expected, actual, severity, description)
```

---

### 4. Cost Forecasting

```python
# Forecast next month's costs
forecast = await forecaster.forecast(
    horizon_days=30,
    method="prophet",  # or "arima", "linear"
    confidence_interval=0.95,
)

# Returns:
# {
#     "predicted_total": 8500.00,
#     "confidence_interval": [8000, 9000],
#     "daily_breakdown": [...],
#     "trend": "increasing",
#     "drivers": ["LLM usage +15%", "DB storage +5%"]
# }
```

---

### 5. Cost Allocation & Tagging

```python
# Tag all resources
tagging_rules = {
    "aws": {
        "required_tags": ["Environment", "Team", "Project", "CostCenter"],
        "enforce": True,
    },
    "gcp": {
        "required_labels": ["env", "team", "project"],
    },
}

# Auto-tag resources
await tagger.auto_tag_resources()

# Cost by tag
cost_by_team = await tracker.get_cost_by_tag("Team", period="monthly")
# Returns: {"platform": 5000, "backend": 3000, "frontend": 2000}
```

---

## Common Operations

### 1. Setting Up Budgets

```python
# Define budgets in config
budgets_config = {
    "global": {
        "monthly_limit": 20000,
        "alert_thresholds": [0.5, 0.75, 0.9, 1.0],
        "actions": ["alert", "alert", "throttle", "block"],
    },
    "by_team": {
        "platform": {"monthly": 8000, "alert_at": 0.8},
        "backend": {"monthly": 6000, "alert_at": 0.8},
        "frontend": {"monthly": 4000, "alert_at": 0.9},
        "ml": {"monthly": 5000, "alert_at": 0.85},
    },
    "by_service": {
        "llm": {"daily": 200, "action": "throttle"},
        "database": {"monthly": 2000, "action": "alert"},
        "storage": {"monthly": 500, "action": "alert"},
    },
}

tracker.configure_budgets(budgets_config)
```

---

### 2. Cost Anomaly Investigation

```python
# When anomaly detected
async def investigate_anomaly(anomaly: CostAnomaly):
    # 1. Identify affected resources
    resources = await tracker.get_resources_in_period(
        anomaly.start_time,
        anomaly.end_time,
    )
    
    # 2. Break down by service
    breakdown = await tracker.get_cost_breakdown(
        start=anomaly.start_time,
        end=anomaly.end_time,
        group_by="service",
    )
    
    # 4. Check for new deployments
    deployments = await get_deployments_in_window(
        anomaly.start_time,
        anomaly.end_time,
    )
    
    # 5. Generate report
    return AnomalyReport(
        anomaly=anomaly,
        affected_resources=resources,
        cost_breakdown=breakdown,
        recent_deployments=deployments,
        recommendation=generate_recommendation(anomaly, breakdown),
    )
```

---

### 3. Cost Optimization Recommendations

```python
async def generate_optimization_recommendations():
    recommendations = []
    
    # 1. Idle resources
    idle = await find_idle_resources()
    if idle:
        recommendations.append(OptimizationRecommendation(
            type="idle_resource",
            savings=sum(r.monthly_cost for r in idle),
            action=f"Terminate {len(idle)} idle resources",
            resources=[r.id for r in idle],
        ))
    
    # 2. Right-sizing
    oversized = await find_oversized_instances()
    if oversized:
        recommendations.append(OptimizationRecommendation(
            type="rightsize",
            savings=sum(r.potential_savings for r in oversized),
            action=f"Downsize {len(oversized)} instances",
        ))
    
    # 3. Storage optimization
    old_snapshots = await find_old_snapshots(older_than_days=90)
    if old_snapshots:
        recommendations.append(OptimizationRecommendation(
            type="storage_cleanup",
            savings=sum(s.size_gb * 0.10 for s in old_snapshots),  # $0.10/GB
            action=f"Delete {len(old_snapshots)} old snapshots",
        ))
    
    # 4. Reserved instances / Savings Plans
    ri_savings = await calculate_ri_savings()
    if ri_savings > 100:
        recommendations.append(OptimizationRecommendation(
            type="reserved_instances",
            savings=ri_savings,
            action="Purchase reserved instances for stable workloads",
        ))
    
    return recommendations
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Untagged resources** | Unallocated costs | Enforce tagging policy |
| **No budgets** | Surprise bills | Set budgets + alerts |
| **No anomaly detection** | Surprise spikes | Enable anomaly detection |
| **No forecasting** | Budget surprises | Enable forecasting |
| **Unused resources** | Wasted spend | Regular cleanup jobs |
| **Over-provisioned** | Overspending | Right-size + RI/SP |
| **No cost allocation** | Can't chargeback | Enforce tagging |
| **No anomaly detection** | Late detection | Enable statistical detection |

---

## Evolution Without Breaking Contracts

### Adding New Cost Source

```python
# Non-breaking: add new collector
tracker.register_collector("new_cloud", NewCloudCollector())
```

### Adding Budget Dimension

```python
# Non-breaking: add budget dimension
budgets["by_environment"] = {
    "production": {"monthly": 15000},
    "staging": {"monthly": 2000},
    "development": {"monthly": 500},
}
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Budget increase > 20% | **REVIEW** — Finance approval |
| New cost category | **REVIEW** — Accounting review |
| Anomaly > $500/day | **REVIEW** — Investigate |
| Forecast > budget | **REVIEW** — Plan adjustment |
| New cloud provider | **REVIEW** — Security + Finance |

---

## Health Checks & Monitoring

```python
@app.get("/health/cost")
async def cost_health():
    return {
        "status": "healthy",
        "checks": {
            "collectors": await check_collectors_health(),
            "budgets": await check_budget_status(),
            "anomalies": await check_anomaly_status(),
            "forecast": await check_forecast_accuracy(),
        }
    }

# Metrics:
# - cost.total.monthly
# - cost.by_service
# - cost.by_team
# - cost.anomaly.count
# - budget.utilization
# - forecast.accuracy
```

---

## Debugging Quick Reference

```bash
# View current costs
python -c "
from app.cost import CostTracker
t = CostTracker()
print(await t.get_current_spending())
"

# Check budgets
python -c "
from app.cost import CostTracker
t = CostTracker()
for name, b in (await t.check_budgets()).items():
    print(f'{name}: {b.used}/{b.limit} ({b.percent:.1%})')
"

# Check anomalies
python -c "
from app.cost import AnomalyDetector
d = AnomalyDetector()
print(await d.detect_last_7d())
"

# Forecast
python -c "
from app.cost import CostForecaster
f = CostForecaster()
print(await f.forecast(30))
"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Collection interval | `collection_interval` | 5-15 min |
| Aggregation window | `rollup_window` | 1 hour |
| Retention | `retention_days` | 90-365 days |
| Anomaly lookback | `lookback_days` | 30 days |
| Forecast horizon | `forecast_days` | 30-90 days |

---

## Security Checklist

- [ ] Cost data encrypted at rest
- [ ] API keys for collectors in vault
- [ ] Access control on cost data
- [ ] Audit log for budget changes
- [ ] No sensitive data in cost metadata
- [ ] Encrypted cost exports
- [ ] Access logging for cost API

---

*Cost Domain Maintenance Skill v1.0 | Maintained by FinOps Team | Next review: 2026-12-04*