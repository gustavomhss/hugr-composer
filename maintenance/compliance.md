# Compliance Domain — Maintenance Skill

> **Crates**: 1 | **Status**: Production-ready | **Owner**: Compliance Team | **Last Updated**: 2026-09-04

> **Purpose**: Regulatory compliance primitives — audit logging, data retention, breach notification, and privacy controls.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `ComplianceEngine` | Compliance rule engine | High | Production |

---

## Crate: `ComplianceEngine`

**Purpose**: Centralized compliance rule engine for GDPR, LGPD, CCPA, HIPAA, SOC2, PCI-DSS compliance.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    COMPLIANCE ENGINE                        │
├─────────────────────────────────────────────────────────────┤
│  Request → RuleEngine → PolicyEvaluation → AuditLog        │
│       ↓                                                      │
│  DataSubjectRights → ConsentManagement → Retention         │
│       ↓                                                      │
│  BreachDetector → Notification → RegulatoryReporting       │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 1. Data Subject Rights (GDPR Art. 15-22)

```python
from generators.compliance.engine import ComplianceEngine

engine = ComplianceEngine()

# Right of Access (Art. 15)
async def handle_access_request(user_id: str) -> DataSubjectResponse:
    return await engine.process_access_request(
        data_subject_id=user_id,
        regulation="GDPR",
    )

# Right to Rectification (Art. 16)
async def handle_rectification_request(user_id: str, corrections: dict) -> RectificationResult:
    return await engine.process_rectification(
        data_subject_id=user_id,
        corrections=corrections,
    )

# Right to Erasure (Art. 17)
async def handle_erasure_request(user_id: str, reason: str) -> ErasureResult:
    return await engine.process_erasure(
        data_subject_id=user_id,
        reason=reason,
    )

# Right to Restriction (Art. 18)
async def handle_restriction_request(user_id: str) -> RestrictionResult:
    return await engine.process_restriction(
        data_subject_id=user_id,
    )

# Right to Data Portability (Art. 20)
async def handle_portability_request(user_id: str) -> PortabilityPackage:
    return await engine.generate_portability_package(
        data_subject_id=user_id,
        format="json",
    )

# Right to Object (Art. 21)
async def handle_objection_request(user_id: str, processing_purpose: str) -> ObjectionResult:
    return await engine.process_objection(
        data_subject_id=user_id,
        purpose=processing_purpose,
    )

# Automated Decision Making (Art. 22)
async def handle_automated_decision_request(user_id: str, decision_id: str) -> ExplanationResult:
    return await engine.explain_automated_decision(
        data_subject_id=user_id,
        decision_id=decision_id,
    )
```

---

### 2. Consent Management

```python
# Consent tracking
class ConsentRecord:
    data_subject_id: str
    purpose: str
    lawful_basis: LawfulBasis  # consent, contract, legal_obligation, vital_interests, public_task, legitimate_interests
    granted_at: datetime
    withdrawn_at: datetime | None
    version: str
    ip_address: str
    user_agent: str

# Consent operations
await engine.record_consent(
    data_subject_id="user-123",
    purpose="marketing_email",
    lawful_basis=LawfulBasis.CONSENT,
    version="1.2",
)

await engine.withdraw_consent(
    data_subject_id="user-123",
    purpose="marketing_email",
)

# Check consent
if await engine.has_valid_consent(user_id, "marketing_email"):
    await send_marketing_email(user_id)
```

---

### 3. Data Retention & Deletion

```python
# Retention policies
RETENTION_POLICIES = {
    "user_account": timedelta(days=2555),      # 7 years
    "transaction_log": timedelta(days=2555),   # 7 years
    "audit_log": timedelta(days=2555),         # 7 years
    "session_data": timedelta(days=30),        # 30 days
    "cache_data": timedelta(days=7),           # 7 days
    "analytics_events": timedelta(days=730),   # 2 years
    "marketing_consent": timedelta(days=2555), # 7 years
    "deleted_user_data": timedelta(days=30),   # 30 days grace period
}

# Automated deletion job
async def run_retention_cleanup():
    for data_type, retention in RETENTION_POLICIES.items():
        cutoff = datetime.utcnow() - retention
        deleted = await db.execute(
            f"DELETE FROM {data_type} WHERE created_at < ? AND deleted_at IS NULL",
            cutoff,
        )
        await audit_log.log(
            action="retention_deletion",
            resource_type=data_type,
            count=deleted.rowcount,
        )
```

---

### 4. Breach Detection & Notification

```python
# Breach detection rules
BREACH_RULES = [
    {
        "name": "unauthorized_access",
        "condition": "failed_login_attempts > 5 in 5min",
        "severity": "high",
        "notification": ["security_team", "dpo"],
    },
    {
        "name": "data_exfiltration",
        "condition": "data_export > 100MB in 1hr",
        "severity": "critical",
        "notification": ["security_team", "dpo", "legal", "ceo"],
    },
    {
        "name": "unauthorized_data_access",
        "condition": "access_to_pii_without_legitimate_interest",
        "severity": "high",
        "notification": ["security_team", "dpo"],
    },
]

async def check_breach_rules():
    for rule in BREACH_RULES:
        if await evaluate_condition(rule["condition"]):
            await notify_breach(rule)
```

---

### 5. Data Processing Register (Art. 30)

```python
# Automated ROPA generation
async def generate_ropa() -> ProcessingRegister:
    activities = await db.fetch_all("""
        SELECT 
            processing_activity,
            purpose,
            lawful_basis,
            data_categories,
            data_subjects,
            recipients,
            transfers,
            retention_period,
            security_measures
        FROM processing_activities
    """)
    
    return ProcessingRegister(
        controller="Company Name",
        dpo_contact="dpo@example.com",
        activities=activities,
        generated_at=datetime.utcnow(),
    )
```

---

## Common Operations

### 1. Handling Data Subject Requests

```python
# Unified request handler
@app.post("/privacy/request")
async def handle_dsr(request: DSRRequest):
    handlers = {
        "access": engine.process_access_request,
        "rectification": engine.process_rectification,
        "erasure": engine.process_erasure,
        "restriction": engine.process_restriction,
        "portability": engine.generate_portability_package,
        "objection": engine.process_objection,
        "automated_decision": engine.explain_automated_decision,
    }
    
    handler = handlers.get(request.type)
    if not handler:
        raise HTTPException(400, "Invalid request type")
    
    result = await handler(
        data_subject_id=request.data_subject_id,
        **request.parameters,
    )
    
    # Log for audit
    await audit_log.log(
        action=f"dsr_{request.type}",
        data_subject_id=request.data_subject_id,
        result=result.status,
    )
    
    return result
```

---

### 2. Consent Withdrawal Flow

```python
@app.post("/privacy/consent/withdraw")
async def withdraw_consent(request: ConsentWithdrawalRequest):
    # 1. Verify identity
    user = await verify_identity(request.user_id, request.auth_token)
    
    # 2. Check if consent exists
    consent = await engine.get_consent(user.id, request.purpose)
    if not consent:
        raise HTTPException(404, "Consent not found")
    
    # 3. Check if withdrawal allowed
    if consent.lawful_basis != LawfulBasis.CONSENT:
        raise HTTPException(400, "Cannot withdraw: not consent-based")
    
    # 4. Withdraw
    await engine.withdraw_consent(user.id, request.purpose)
    
    # 3. Stop processing immediately
    await stop_processing_for_purpose(user.id, request.purpose)
    
    # 4. Notify downstream systems
    await notify_downstream_consent_withdrawn(user.id, request.purpose)
    
    return {"status": "withdrawn", "effective_immediately": True}
```

---

### 3. Automated Deletion Scheduler

```python
# Celery task for automated deletion
@celery.task
async def scheduled_deletion():
    for data_type, retention in RETENTION_POLICIES.items():
        cutoff = datetime.utcnow() - retention
        try:
            # Soft delete first (soft_delete = true)
            deleted = await db.execute(
                f"UPDATE {data_type} SET deleted_at = NOW() WHERE created_at < ? AND deleted_at IS NULL",
                datetime.utcnow() - retention,
            )
            
            # Log for audit
            await audit_log.log(
                action="retention_deletion",
                resource_type=data_type,
                count=deleted.rowcount,
                cutoff_date=cutoff.isoformat(),
            )
            
            # Hard delete after grace period
            grace_cutoff = datetime.utcnow() - retention - timedelta(days=30)
            await db.execute(
                f"DELETE FROM {data_type} WHERE deleted_at < ?",
                grace_cutoff,
            )
        except Exception as e:
            logger.error(f"Retention cleanup failed for {data_type}: {e}")
            await alert_oncall(f"Retention cleanup failed: {e}")
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Incomplete erasure** | Data remains in backups | Include backups in erasure |
| **Consent withdrawal not immediate** | Processing continues | Stop processing immediately |
| **Portability format unusable** | User can't use data | Provide standard formats (JSON, CSV) |
| **Retention policy not enforced** | Data kept too long | Automated deletion + audit |
| **Breach notification delayed** | Regulatory fines | Automated detection + 72h notification |
| **Consent withdrawal not immediate** | Processing continues | Stop processing immediately |
| **Portability format unusable** | User can't import | Provide standard formats |
| **No breach detection** | Late detection | Automated monitoring + alerts |

---

## Evolution Without Breaking Contracts

### Adding a New Data Subject Right

```python
# Non-breaking: add new DSR type to handler
handlers = {
    "access": engine.process_access_request,
    "rectification": engine.process_rectification,
    "erasure": engine.process_erasure,
    "restriction": engine.process_restriction,
    "portability": engine.generate_portability_package,
    "objection": engine.process_objection,
    "automated_decision": engine.explain_automated_decision,
    "new_right": engine.process_new_right,  # ADD HERE
}
```

### Adding a New Lawful Basis

```rego
# Non-breaking: add new lawful basis
lawful_basis["legitimate_interests"] := true
```

### Adding a New Retention Category

```python
RETENTION_POLICIES = {
    "user_account": timedelta(days=2555),
    "new_data_type": timedelta(days=365),  # ADD HERE
}
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| New data processing activity | **REVIEW** — DPIA required |
| New international transfer | **STOP** — SCC/adequacy check |
| New lawful basis | **REVIEW** — Legal review |
| New data category | **REVIEW** — DPIA if high risk |
| Change in retention period | **REVIEW** — Legal compliance |
| New third-party processor | **REVIEW** — DPA required |

---

## Health Checks & Monitoring

```python
@app.get("/health/compliance")
async def compliance_health():
    return {
        "status": "healthy",
        "checks": {
            "dsr_sla": await check_dsr_sla(),
            "consent_validity": await check_consent_validity(),
            "retention_compliance": await check_retention(),
            "breach_detection": await check_breach_detection(),
            "consent_validity": await check_consent_freshness(),
        }
    }

# Metrics:
# - dsr.requests.total
# - dsr.sla.met
# - consent.withdrawal.rate
# - retention.deletions.count
# - breach.detected.count
# - breach.notification.time
```

---

## Debugging Quick Reference

```bash
# Check pending DSRs
sql "SELECT * FROM dsr_requests WHERE status = 'pending'"

# Check consent status
sql "SELECT * FROM consent_records WHERE data_subject_id = 'user-123'"

# Check retention compliance
sql "SELECT * FROM retention_audit WHERE status != 'compliant'"

# Check breach alerts
sql "SELECT * FROM breach_alerts WHERE acknowledged = false"

# Test erasure
python -c "
from app.compliance import ComplianceEngine
e = ComplianceEngine()
result = await e.process_erasure('user-123', 'user_request')
print(result)
"

# Check consent status
python -c "
from app.compliance import ComplianceEngine
e = ComplianceEngine()
c = await e.get_consent('user-123', 'marketing')
print(c)
"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| DSR processing | async_workers | 4-8 |
| Consent check | cache_ttl | 5 min |
| Retention job | batch_size | 1000 |
| Breach detection | check_interval | 60s |
| Audit log | batch_size | 100 |

---

## Security Checklist

- [ ] All DSRs processed within legal timeframes (30 days GDPR)
- [ ] Consent withdrawal immediate
- [ ] Erasure includes backups
- [ ] Portability in standard formats
- [ ] Breach notification within 72h
- [ ] DPO notified on all breaches
- [ ] Records of processing activities current
- [ ] DPIA for high-risk processing
- [ ] Data processing agreements with all processors
- [ ] International transfer safeguards
- [ ] Data retention policies enforced
- [ ] Audit logs immutable
- [ ] Consent granular and specific
- [ ] Right to object honored
- [ ] Automated decision explanations available

---

*Compliance Domain Maintenance Skill v1.0 | Maintained by Compliance Team | Next review: 2026-12-04*