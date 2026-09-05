# Auth Domain — Maintenance Skill

> **Crates**: 9 | **Status**: Production-ready | **Owner**: Auth Team | **Last Updated**: 2026-09-04

> **Purpose**: Authentication, authorization, and identity management. The gatekeeper of the system.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `AuthorizationCodeFlow` | OAuth2/OIDC Authorization Code flow with PKCE | High | Production |
| `CurrentPrincipal` | Current user extraction from request | Medium | Production |
| `FeatureFlagCache` | Distributed feature flag cache with TTL | Medium | Production |
| `RequestGuard` | Request-level authorization guard | High | Production |
| `SessionStore` | Distributed session storage (Redis-backed) | High | Production |
| `TokenIntrospector` | OAuth2 token introspection (RFC 7662) | Medium | Production |
| `TotpVerifier` | TOTP verification (RFC 6238) | Low | Production |
| `WebAuthnAuthenticator` | WebAuthn/FIDO2 authentication | High | Production |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTH DOMAIN ARCHITECTURE                 │
├─────────────────────────────────────────────────────────────┤
│  Request → RequestGuard → CurrentPrincipal → Your Handler  │
│       ↓              ↓                    ↓                 │
│  TokenIntrospector  SessionStore      FeatureFlagCache      │
│       ↓              ↓                    ↓                 │
│  AuthorizationCodeFlow ←→ TokenIntrospector ←→ SessionStore │
│       ↓                                                 │
│  TotpVerifier / WebAuthnAuthenticator                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### 1. Adding a New OAuth2 Provider

```python
# 1. Add provider config to settings
class Settings(BaseSettings):
    OAUTH_PROVIDERS: dict[str, OAuthProviderConfig] = {
        "github": OAuthProviderConfig(
            client_id="...",
            client_secret="...",
            authorization_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            scopes=["read:user", "user:email"],
        ),
    }

# 2. Add provider to AuthorizationCodeFlow
# generators/auth/authorization_code_flow.py
class AuthorizationCodeFlow:
    PROVIDERS = {
        "google": GoogleOAuthProvider,
        "github": GitHubOAuthProvider,  # ADD HERE
        # ...
    }
```

**Checklist**:
- [ ] Add provider config to Settings
- [ ] Add provider class in `AuthorizationCodeFlow`
- [ ] Add tests for OAuth flow
- [ ] Update `FeatureFlagCache` if new scopes needed
- [ ] Update documentation

---

### 2. Rotating JWT Signing Keys (ES256 / ECDSA P-256)

```bash
# 1. Generate new ECDSA P-256 key pair (recommended for ES256)
openssl ecparam -name prime256v1 -genkey -noout -out private_key.pem
openssl ec -in private_key.pem -pubout -out public_key.pem

# For RS256 (RSA), use:
# openssl genrsa -out private_key.pem 2048
# openssl rsa -in private_key.pem -pubout -out public_key.pem

# 2. Update secrets (zero-downtime rotation)
# 1. Add new public key to JWKS endpoint
# 2. Deploy new private key to all instances
# 3. Wait for token TTL to expire (max 30 min)
# 4. Remove old public key from JWKS
# 5. Revoke old private key

# 3. Verify
python -m pytest tests/auth/test_jwt_rotation.py -v
```

**Critical**: Never have a window where NO valid key exists. Use overlapping validity windows.

---

### 3. Rotating Session Encryption Keys

```bash
# Sessions use Fernet encryption (AES-256 + HMAC)
# Rotation procedure:
# 1. Generate new key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 2. Add new key to SESSION_KEYS list (comma-separated)
# 2. Deploy — new sessions encrypted with first key
# 3. Wait for all old sessions to expire (max TTL)
# 4. Remove old key from list
```

---

### 4. Enabling WebAuthn for a New Relying Party

```python
# 1. Configure relying party
rp_config = WebAuthnRelyingPartyConfig(
    rp_id="api.example.com",
    rp_name="Example API",
    origin="https://app.example.com",
)

# 2. Update WebAuthnAuthenticator config
# generators/auth/webauthn_authenticator.py
WebAuthnAuthenticator(
    rp_id=rp_config.rp_id,
    rp_name=rp_config.rp_name,
    origin=rp_config.origin,
)

# 3. Test with multiple authenticator types:
# - Platform authenticators (Touch ID, Windows Hello)
# - Cross-platform (YubiKey, Titan)
# 3. Test recovery flows
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **JWT algorithm confusion** | `alg: none` accepted | Explicitly allow only `RS256`/`ES256` in `TokenIntrospector` |
| **Session fixation** | Session ID not regenerated on login | Call `session_store.regenerate()` on auth |
| **Token replay** | Replay attacks on OAuth callbacks | Use `state` + `nonce` + PKCE; store `state` in secure cookie |
| **Token leakage in logs** | JWT in access logs | Use `StructuredLogger` with `SENSITIVE_FIELDS` filter |
| **Session fixation on privilege change** | Elevated privileges persist | Regenerate session on role change |
| **Clock skew** | Tokens rejected for valid users | Configure `leeway=60` in JWT validation |
| **Replay of WebAuthn challenges** | Challenge reuse attacks | Store challenge with TTL; single-use only |

---

## Evolution Without Breaking Contracts

### Adding a New Claim to JWT

```python
# 1. Add claim to token payload (non-breaking)
def create_access_token(self, subject: str, extra_claims: dict = None) -> str:
    claims = {
        "sub": subject,
        "iat": now(),
        "exp": now() + self.access_token_ttl,
        **(extra_claims or {}),  # <-- extensible
    }
    return self.encode(claims)

# 2. Consumers use .get("new_claim") — safe
# 3. No breaking change for existing consumers
```

### Adding a New OAuth Scope

```python
# 1. Add scope to provider config
SCOPES = ["read:user", "user:email", "read:org"]  # ADD HERE

# 2. Update token introspection response
# 3. Update FeatureFlagCache if scope-gated features
# 3. Update documentation
```

**Rule**: Adding scopes is non-breaking. Removing scopes IS breaking.

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing JWT algorithm | **STOP** — Security review required |
| Changing token TTL | **REVIEW** — Impact on session UX |
| Adding new OAuth provider | **REVIEW** — Security + UX review |
| Changing session storage backend | **REVIEW** — Migration plan needed |
| Changing password hash algorithm | **STOP** — Migration plan + security review |
| Adding new WebAuthn feature | **REVIEW** — FIDO2 compliance check |

---

## Health Checks & Monitoring

```python
# Every auth crate MUST expose:
@app.get("/health/auth")
async def auth_health():
    return {
        "status": "healthy",
        "checks": {
            "jwks_endpoint": await check_jwks_endpoint(),
            "session_store": await session_store.ping(),
            "token_introspector": await check_introspection_endpoint(),
            "oauth_providers": await check_oauth_providers(),
        }
    }

# Metrics to alert on:
# - auth.login.failure_rate > 5%
# - auth.token.introspection.latency.p99 > 500ms
# - auth.session.store.latency.p99 > 100ms
# - auth.webauthn.registration.failure_rate > 1%
```

---

## Debugging Quick Reference

```bash
# Decode JWT without verification (debug only)
python -c "import jwt; print(jwt.decode('TOKEN', options={'verify_signature': False}))"

# Inspect session
redis-cli GET "session:<session_id>"

# Test WebAuthn registration
python -m pytest tests/auth/test_webauthn.py::test_registration -v -s

# Debug OAuth flow
export OAUTH_DEBUG=1
python -m pytest tests/auth/test_oauth_flow.py -v -s

# Check JWKS endpoint
curl https://auth.example.com/.well-known/jwks.json | jq
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| `SessionStore` | Redis connection pool | `max_connections=50` |
| `TokenIntrospector` | HTTP client pool | `max_connections=20` |
| `SessionStore` | TTL | 24h (access) / 30d (refresh) |
| `TokenIntrospector` | Cache TTL | 300s (5 min) |
| `FeatureFlagCache` | TTL | 60s (configurable) |

---

## Security Checklist (Pre-Deploy)

- [ ] All passwords hashed with Argon2id (via `PasswordHasher`)
- [ ] JWT signed with RS256 (not HS256)
- [ ] JWKS endpoint serves correct keys
- [ ] OAuth `state` + `nonce` + PKCE enforced
- [ ] WebAuthn challenge TTL ≤ 5 min
- [ ] Rate limiting on auth endpoints (5/min login, 10/min register)
- [ ] Brute-force protection (account lockout after 5 failures)
- [ ] Secure cookies: `Secure; HttpOnly; SameSite=Lax`
- [ ] CSP headers include `frame-ancestors 'none'`
- [ ] HSTS header with `preload`
- [ ] Rate limit headers exposed (`X-RateLimit-*`)

---

## Version Upgrade Procedures

### Upgrading `pwdlib` / `argon2`

```bash
# 1. Check changelog for breaking changes
# 2. Test hash verification with existing hashes
python -c "
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
ph = PasswordHash([Argon2Hasher()])
h = ph.hash('test')
assert ph.verify('test', h)
print('OK')
"
# 3. Run full auth test suite
python -m pytest tests/auth/ -v
```

### Upgrading `slowapi` (rate limiting)

```bash
# 1. Check changelog for breaking changes
# 2. Test rate limiting behavior
python -m pytest tests/auth/test_rate_limit.py -v
# 3. Check Redis storage compatibility
```

---

## Testing Strategy

```python
# Unit tests (fast, isolated)
# - Token encoding/decoding
# - Password hash/verify
# - TOTP/WebAuthn verification logic
# - Scope validation

# Integration tests (with Redis/Postgres)
# - Full OAuth2 flow
# - Session create/read/delete
# - Token introspection
# - WebAuthn registration/authentication

# Contract tests (schema validation)
# - JWT payload schema
- OAuth token response schema
- WebAuthn challenge/response schema

# Load tests
# - 1000 req/s login
# - 5000 concurrent sessions
# - Token introspection under load
```

---

## Emergency Procedures

### JWT Key Compromise

```bash
# 1. Generate new key pair IMMEDIATELY
# 2. Deploy new public key to JWKS
# 3. Rotate private key on all instances
# 3. Force logout all users (invalidate all sessions)
# 4. Force re-auth for all users
# 4. Audit logs for suspicious activity
# 5. Post-incident review within 24h
```

### Session Store Outage

```bash
# 1. Failover to backup Redis (if configured)
# 2. If no backup: degrade gracefully
#    - Disable session creation
#    - Allow existing sessions (read-only)
#    - Show maintenance page for auth endpoints
# 3. Alert on-call
# 4. Post-incident: root cause analysis
```

---

*Auth Domain Maintenance Skill v1.0 | Maintained by Auth Team | Next review: 2026-12-04*