# agent session — 06-auth-saas

Plan-level transcript for `baseline/02_auth_only_saas.md`.

## Requirement → kit mapping

1. **Strong password hashing, constant-time.**
   → `PasswordHasher` (Argon2id). `verify()` runs even on unknown emails
     (dummy hash) so `/login` can't distinguish via timing.
2. **Access + refresh tokens, revocation on /logout.**
   → `SessionStore` keyed by `(user_id, session_id)`. `/logout` deletes.
3. **Single-use password-reset tokens.**
   → One-time token stored with `used_at` flag; second use → 400.
4. **Rate-limit login: per-email + per-IP.**
   → Two `RateLimiter` instances (`login_by_email`, `login_by_ip`).
     Either trips → 429.
5. **No timing distinction unknown-email vs wrong-password.**
   → `PasswordHasher.verify()` always called (unknown user gets a
     precomputed dummy-hash verify).

## Tool call sequence

```
1. fastapi_generate_project(name="auth_svc")
2. fastapi_add_password_hasher(algorithm="argon2id",
                                dummy_verify_on_unknown_email=True)
3. fastapi_add_auth_jwt(access_ttl_s=900, refresh_ttl_s=2_592_000)
4. fastapi_add_password_reset(token_ttl_s=900, single_use=True)
5. fastapi_add_login_rate_limit(
     per_email={"burst":5,"window_s":60},
     per_ip={"burst":20,"window_s":60})
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
