# Example 06 — Authentication-only SaaS

**Tier:** baseline · **Benchmark spec:** `baseline/02_auth_only_saas.md`

Signup / login / logout / password-reset with brute-force defence and
constant-time responses. Demonstrates the **`PasswordHasher` +
`SessionStore` + `RateLimiter`** recipe.

## What this example shows

- Argon2-style hash with constant-time verify (no plaintext leak).
- Refresh token revoked the moment `/logout` is called (no grace).
- Single-use password-reset tokens — second use returns 400.
- `/login` is rate-limited per-email AND per-source-IP (credential-stuffing).
- Unknown-email and wrong-password paths take the SAME time
  (dummy-verify on unknown-email).

## How to run

```bash
cd examples/06-auth-saas
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                | Role                                           |
| ----------------------------------- | ---------------------------------------------- |
| `fastapi_add_auth_jwt`              | Access + refresh tokens via `SessionStore`.    |
| `fastapi_add_password_hasher`       | Argon2id wiring + dummy-verify for unknown users. |
| `fastapi_add_password_reset`        | Single-use time-limited reset tokens.          |
| `fastapi_add_login_rate_limit`      | Per-email + per-IP token bucket.               |

## Primitives imported

| Primitive         | Role                                                |
| ----------------- | --------------------------------------------------- |
| `PasswordHasher`  | Argon2id-style hashing with constant-time verify.   |
| `SessionStore`    | Refresh-token storage + revocation (immediate).    |
| `RateLimiter`     | Token bucket per `(login, email)` + `(login, ip)`. |
| `CurrentPrincipal`| Resolved identity per request.                     |
| `Redactor`        | Strips PII from login-failure logs.                |
