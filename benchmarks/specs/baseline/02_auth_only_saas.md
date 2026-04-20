# Authentication-only SaaS

## Requirements

- Email + password signup with strong password hashing (brute-force resistant).
- Login issues an access token with a short expiry and a refresh token.
- A logout endpoint revokes the refresh token immediately.
- Password reset flow via single-use time-limited tokens.
- Rate-limit login attempts per email and per source IP to resist credential stuffing.

## Acceptance criteria

- Hash output is not plaintext-recoverable (verifier accepts the correct password, rejects wrong).
- `POST /login` with 6 wrong passwords in 60s returns 429.
- A refresh token returned by `/login`, then used after `/logout`, returns 401.
- A password-reset token used twice returns 400 on the second use.
- No timing-based distinction between "unknown email" and "wrong password" in `/login` responses.

## Non-requirements

- No SSO, OAuth providers, or magic-link login.
- No MFA.
- No device management UI.
- No user-facing web pages — API only.
