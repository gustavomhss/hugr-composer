# Security Domain — Maintenance Skill

> **Crates**: 7 | **Status**: Production-ready | **Owner**: Security Team | **Last Updated**: 2026-09-04

> **Purpose**: Security primitives — authentication, authorization, encryption, validation, and threat protection.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `ContentSecurityPolicy` | CSP header generation and management | Medium | Production |
| `CryptoEnvelope` | Authenticated encryption envelopes | High | Production |
| `CsrfGuard` | CSRF protection with double-submit cookie | Medium | Production |
| `InputValidator` | Input validation and sanitization | Medium | Production |
| `OutputEncoder` | Context-aware output encoding | Medium | Production |
| `PasswordHasher` | Argon2id password hashing | Medium | Production |
| `SecretsVault` | Secret management and rotation | High | Production |
| `SignatureVerifier` | Cryptographic signature verification | High | Production |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SECURITY LAYER                         │
├─────────────────────────────────────────────────────────────┤
│  Request → InputValidator → OutputEncoder → Your Handler   │
│       ↓                                                      │
│  CsrfGuard → CsrfCheck                                        │
│       ↓                                                      │
│  ContentSecurityPolicy → CSP Header                          │
│       ↓                                                      │
│  CryptoEnvelope → Encrypt/Decrypt                            │
│       ↓                                                      │
│  PasswordHasher → Hash/Verify                                │
│       ↓                                                      │
│  SecretsVault → Secret Access                                │
│       ↓                                                      │
│  SignatureVerifier → Verify Signatures                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Crate Details

### 1. `ContentSecurityPolicy`

**Purpose**: CSP header generation with nonce/hash support for inline scripts/styles.

**Key Features**:
- Nonce generation for inline scripts/styles
- Hash-based allowlisting for inline content
- Report-only mode for testing
- CSP violation reporting endpoint

**Usage**:
```python
from generators.middleware.security_headers import generate_security_headers

csp = ContentSecurityPolicy(
    default_src=["'self'"],
    script_src=["'self'", "'nonce-{nonce}'"],
    style_src=["'self'", "'nonce-{nonce}'"],
    img_src=["'self'", "data:", "https:"],
    connect_src=["'self'", "https://api.example.com"],
    font_src=["'self'", "https://fonts.gstatic.com"],
    frame_ancestors=["'none'"],
    form_action=["'self'"],
    base_uri=["'self'"],
    report_uri="/csp-report",
)

headers = csp.generate_headers(nonce="random-nonce-here")
```

---

### 2. `CryptoEnvelope`

**Purpose**: Authenticated encryption envelopes for sensitive data at rest and in transit.

**Key Features**:
- AES-256-GCM authenticated encryption
- Key rotation support
- Associated data (AAD) binding
- Streaming encryption for large payloads
- Key derivation from master key

**Usage**:
```python
from generators.security.crypto_envelope import CryptoEnvelope

envelope = CryptoEnvelope(master_key=settings.MASTER_KEY)

# Encrypt
encrypted = envelope.encrypt(
    plaintext=b"sensitive data",
    associated_data=b"user:123",  # AAD - bound to context
)

# Decrypt (verifies integrity + authenticity)
plaintext = envelope.decrypt(
    ciphertext=encrypted.ciphertext,
    nonce=encrypted.nonce,
    tag=encrypted.tag,
    associated_data=b"user:123",
)
```

---

### 3. `CsrfGuard`

**Purpose**: CSRF protection using double-submit cookie pattern with SameSite fallback.

**Key Features**:
- Double-submit cookie pattern
- SameSite=Lax fallback
- Per-request token generation
- AJAX-friendly header-based validation
- Subdomain-aware cookie settings

**Usage**:
```python
from generators.middleware.csrf_guard import CsrfGuard

csrf = CsrfGuard(
    secret_key=settings.CSRF_SECRET,
    cookie_name="csrf_token",
    header_name="X-CSRF-Token",
    cookie_secure=True,
    cookie_samesite="lax",
    excluded_paths=["/health", "/metrics"],
)

# In middleware
app.add_middleware(CsrfMiddleware, csrf_guard=csrf)

# In templates/forms
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

# For AJAX
fetch("/api/action", {
    method: "POST",
    headers: {
        "X-CSRF-Token": document.querySelector('[name=csrf_token]').value,
    },
})
```

---

### 3. `InputValidator`

**Purpose**: Input validation and sanitization with deny-list and allow-list approaches.

**Key Features**:
- Allow-list validation (preferred)
- Deny-list for known bad patterns
- SQL injection prevention
- XSS prevention
- Path traversal prevention
- Command injection prevention

**Usage**:
```python
from generators.security.input_validator import InputValidator

validator = InputValidator(
    allow_patterns=[r"^[a-zA-Z0-9_-]+$"],  # Allow-list
    deny_patterns=[r"<script", r"javascript:", r"on\w+\s*="],  # Deny-list
    max_length=10000,
)

# In your API
@app.post("/api/comment")
async def create_comment(comment: CommentInput):
    validated = validator.validate(comment.text)
    if not validated.valid:
        raise ValidationError(validated.errors)
    
    # Sanitized output
    clean = validator.sanitize_html(comment.text)
    ...
```

---

### 4. `OutputEncoder`

**Purpose**: Context-aware output encoding for XSS prevention.

**Key Features**:
- HTML entity encoding
- JavaScript string encoding
- CSS encoding
- URL encoding
- SQL string encoding (for legacy)

**Usage**:
```python
from generators.security.output_encoder import OutputEncoder

encoder = OutputEncoder()

# In templates
{{ output_encoder.html(user_content) }}
{{ output_encoder.js(user_input) }}
{{ output_encoder.url(user_input) }}
{{ output_encoder.css(user_input) }}

# In JSON APIs
return JSONResponse(
    content={"message": encoder.js(user_message)},
    media_type="application/javascript",
)
```

---

### 5. `PasswordHasher`

**Purpose**: Argon2id password hashing via `pwdlib`.

**Key Features**:
- Argon2id (OWASP recommended)
- Automatic salt generation
- Timing-safe verification
- Configurable cost parameters
- Dummy hash for timing-attack prevention

**Usage**:
```python
from generators.auth.hasher import PasswordHasher

hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
)

# Hash
hash = hasher.hash(password)

# Verify (timing-safe)
if hasher.verify(password, stored_hash):
    # Valid
    ...

# Dummy hash for timing-attack prevention
dummy_hash = hasher.dummy_hash()
```

---

### 5. `SecretsVault`

**Purpose**: Secret management with rotation, auditing, and access control.

**Key Features**:
- Encrypted storage (AES-256-GCM)
- Automatic rotation schedules
- Access logging and alerting
- Versioning and rollback
- Kubernetes secrets sync
- AWS Secrets Manager / Vault integration

**Usage**:
```python
from generators.security.secrets_vault import SecretsVault

vault = SecretsVault(
    master_key=settings.VAULT_MASTER_KEY,
    rotation_interval=timedelta(days=90),
    audit_log=audit_logger,
)

# Store
await vault.set("stripe/api_key", "sk_live_...", ttl=timedelta(days=90))

# Get (with automatic rotation check)
api_key = await vault.get("stripe/api_key")

# Rotate
await vault.rotate("stripe/api_key", new_value="sk_live_new...")
```

---

### 6. `SignatureVerifier`

**Purpose**: Cryptographic signature verification for webhooks and API integrity.

**Key Features**:
- Ed25519 / RSA-PSS verification
- Webhook signature verification (Stripe, GitHub, etc.)
- JWS/JWT verification
- Certificate chain validation
- Timestamp validation

**Usage**:
```python
from generators.security.signature_verifier import SignatureVerifier

verifier = SignatureVerifier()

# Stripe webhook
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header()):
    payload = await request.body()
    
    if not verifier.verify_stripe_signature(
        payload=await request.body(),
        signature=stripe_signature,
        secret=settings.STRIPE_WEBHOOK_SECRET,
    ):
        raise HTTPException(400, "Invalid signature")
    
    # Process event
    ...

# Generic JWS
payload = verifier.verify_jws(
    token=token,
    public_key=public_key,
    algorithms=["RS256", "ES256"],
)
```

---

## Common Patterns

### 1. Defense in Depth

```python
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # 1. CSP
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = csp_header
    
    # 2. CSRF
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        await csrf_guard.validate(request)
    
    # 3. Input validation
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        validator.validate(body)
    
    # 4. Output encoding
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    return response
```

---

### 2. Secure Password Reset Flow

```python
@app.post("/auth/password/reset/request")
async def request_password_reset(email: str):
    # 1. Rate limit
    await rate_limiter.check(f"password_reset:{email}", limit=3, window=3600)
    
    # 2. Generate secure token
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=1)
    
    # 3. Store with hash (never store plain token)
    token_hash = password_hasher.hash(token)
    await db.execute(
        "INSERT INTO password_resets (email, token_hash, expires_at) VALUES (?, ?, ?)",
        email, password_hasher.hash(token), expires
    )
    
    # 3. Send email (token in link, not email body)
    await email_service.send(
        to=email,
        template="password_reset",
        context={"reset_link": f"https://app.example.com/reset?token={token}"}
    )

@app.post("/auth/password/reset/confirm")
async def confirm_password_reset(token: str, new_password: str):
    # 1. Verify token
    record = await db.fetchone(
        "SELECT * FROM password_resets WHERE token_hash = ? AND expires_at > NOW()",
        password_hasher.hash(token)  # Hash provided token to compare
    )
    if not record:
        raise HTTPException(400, "Invalid or expired token")
    
    # 2. Validate new password
    if len(new_password) < 12:
        raise ValidationError("Password too short")
    if password_hasher.is_weak(new_password):
        raise ValidationError("Password too weak")
    
    # 3. Update password
    new_hash = password_hasher.hash(new_password)
    await db.execute("UPDATE users SET password_hash = ? WHERE email = ?", new_hash, email)
    
    # 4. Invalidate token
    await db.execute("DELETE FROM password_resets WHERE email = ?", email)
    
    # 5. Invalidate all sessions
    await session_store.delete_user_sessions(user_id)
```

---

## Common Operations

### 1. Input Validation

```python
from generators.security.input_validator import InputValidator

validator = InputValidator(
    allow_patterns=[r"^[a-zA-Z0-9_-]+$"],
    deny_patterns=[r"<script", r"javascript:", r"on\w+\s*="],
    max_length=10000,
)

@app.post("/api/comment")
async def create_comment(comment: CommentInput):
    validated = validator.validate(comment.text)
    if not validated.valid:
        raise ValidationError(validated.errors)
    
    clean = validator.sanitize_html(comment.text)
    ...
```

### 2. Output Encoding

```python
from generators.security.output_encoder import OutputEncoder

encoder = OutputEncoder()

# In templates
{{ output_encoder.html(user_content) }}
{{ output_encoder.js(user_input) }}
{{ output_encoder.url(user_input) }}
{{ output_encoder.css(user_input) }}

# In JSON APIs
return JSONResponse(
    content={"message": encoder.js(user_message)},
    media_type="application/javascript",
)
```

### 3. CSRF Protection

```python
from generators.middleware.csrf_guard import CsrfGuard

csrf = CsrfGuard(
    secret_key=settings.CSRF_SECRET,
    cookie_name="csrf_token",
    header_name="X-CSRF-Token",
    cookie_secure=True,
    cookie_samesite="lax",
    excluded_paths=["/health", "/metrics"],
)

app.add_middleware(CsrfMiddleware, csrf_guard=csrf)

# In templates/forms
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

# For AJAX
fetch("/api/action", {
    method: "POST",
    headers: {
        "X-CSRF-Token": document.querySelector('[name=csrf_token]').value,
    },
})
```

### 4. CSP Header Generation

```python
from generators.middleware.security_headers import generate_security_headers

csp = ContentSecurityPolicy(
    default_src=["'self'"],
    script_src=["'self'", "'nonce-{nonce}'"],
    style_src=["'self'", "'nonce-{nonce}'"],
    img_src=["'self'", "data:", "https:"],
    connect_src=["'self'", "https://api.example.com"],
    font_src=["'self'", "https://fonts.gstatic.com"],
    frame_ancestors=["'none'"],
    form_action=["'self'"],
    base_uri=["'self'"],
    report_uri="/csp-report",
)

headers = csp.generate_headers(nonce="random-nonce-here")
```

### 5. Password Hashing

```python
from generators.auth.hasher import PasswordHasher

hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
)

# Hash
hash = hasher.hash(password)

# Verify (timing-safe)
if hasher.verify(password, stored_hash):
    ...

# Dummy hash for timing-attack prevention
dummy_hash = hasher.dummy_hash()
```

### 6. Secrets Management

```python
from generators.security.secrets_vault import SecretsVault

vault = SecretsVault(
    master_key=settings.VAULT_MASTER_KEY,
    rotation_interval=timedelta(days=90),
    audit_log=audit_logger,
)

# Store
await vault.set("stripe/api_key", "sk_live_...", ttl=timedelta(days=90))

# Get (with automatic rotation check)
api_key = await vault.get("stripe/api_key")

# Rotate
await vault.rotate("stripe/api_key", new_value="sk_live_new...")
```

### 7. Signature Verification

```python
from generators.security.signature_verifier import SignatureVerifier

verifier = SignatureVerifier()

# Stripe webhook
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header()):
    payload = await request.body()
    
    if not verifier.verify_stripe_signature(
        payload=await request.body(),
        signature=stripe_signature,
        secret=settings.STRIPE_WEBHOOK_SECRET,
    ):
        raise HTTPException(400, "Invalid signature")
    
    # Process event
    ...

# Generic JWS
payload = verifier.verify_jws(
    token=token,
    public_key=public_key,
    algorithms=["RS256", "ES256"],
)
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **SQL injection** | Data breach | Use parameterized queries; InputValidator |
| **XSS** | Account takeover | OutputEncoder + CSP |
| **CSRF** | Unauthorized actions | CsrfGuard + SameSite cookies |
| **Weak passwords** | Account takeover | PasswordHasher + strength check |
| **Hardcoded secrets** | Credential leak | SecretsVault |
| **Missing CSP** | XSS execution | ContentSecurityPolicy |
| **No CSRF** | Unauthorized actions | CsrfGuard |
| **Weak passwords** | Brute force | PasswordHasher + policy |
| **Secrets in code** | Credential leak | SecretsVault |
| **Unverified webhooks** | Spoofed events | SignatureVerifier |

---

## Evolution Without Breaking Contracts

### Adding a New Validation Rule

```python
# Non-breaking: add new validation rule
validator.add_rule(
    name="no_sql_injection",
    pattern=r"(union|select|insert|update|delete|drop|exec)",
    message="Potential SQL injection detected",
)
```

### Adding a New CSP Directive

```python
# Non-breaking: add directive
csp = ContentSecurityPolicy(
    default_src=["'self'"],
    script_src=["'self'", "'nonce-{nonce}'"],
    connect_src=["'self'", "https://api.example.com"],  # NEW
)
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing CSP policy | **REVIEW** — May break frontend |
| Changing password policy | **REVIEW** — UX impact |
| Adding new CSP directive | **REVIEW** — May break features |
| Changing password hash algorithm | **STOP** — Migration plan required |
| Adding new validation rule | **REVIEW** — False positive risk |
| Changing CSRF token handling | **REVIEW** — May break forms |

---

## Health Checks & Monitoring

```python
@app.get("/health/security")
async def security_health():
    return {
        "status": "healthy",
        "checks": {
            "csp_header": await check_csp_header(),
            "csrf_protection": await check_csrf(),
            "secrets_vault": await secrets_vault.health_check(),
            "certificate_expiry": await check_cert_expiry(),
        }
    }

# Metrics:
# - security.csp.violations
# - security.csrf.failures
# - security.validation.failures
# - security.vault.access.latency
```

---

## Debugging Quick Reference

```bash
# Test CSP
curl -I https://app.example.com | grep -i content-security-policy

# Test CSRF
curl -X POST https://app.example.com/api/action \
  -H "X-CSRF-Token: invalid" \
  -v

# Test CSP report endpoint
curl -X POST https://app.example.com/csp-report \
  -H "Content-Type: application/json" \
  -d '{"csp-report": {"document-uri": "https://example.com", "violated-directive": "script-src"}}'

# Check secrets vault
python -c "
from app.security.secrets_vault import SecretsVault
v = SecretsVault()
print(await v.get('stripe/api_key'))
"

# Check CSP violations
tail -f /var/log/nginx/csp-violations.log
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Password hashing | time_cost | 3 |
| Password hashing | memory_cost | 65536 (64 MB) |
| Password hashing | parallelism | 4 |
| CSRF token TTL | cookie max_age | 24h |
| CSP report endpoint | batch_size | 100 |
| Secrets vault | cache_ttl | 5 min |

---

## Security Checklist

- [ ] Argon2id for password hashing
- [ ] CSP header on all responses
- [ ] CSRF protection on all state-changing endpoints
- [ ] Input validation on all inputs
- [ ] Output encoding on all outputs
- [ ] Argon2id for passwords
- [ ] Secrets in vault (not code)
- [ ] Webhook signatures verified
- [ ] CSP in report-only mode first
- [ ] Security headers on all responses
- [ ] Rate limiting on auth endpoints
- [ ] Secure cookie flags (Secure, HttpOnly, SameSite)
- [ ] HSTS header
- [ ] Referrer-Policy header
- [ ] Permissions-Policy header
- [ ] X-Content-Type-Options: nosniff
- [ ] X-Frame-Options: DENY
- [ ] X-XSS-Protection: 1; mode=block
- [ ] Referrer-Policy: strict-origin-when-cross-origin

---

*Security Domain Maintenance Skill v1.0 | Maintained by Security Team | Next review: 2026-12-04*