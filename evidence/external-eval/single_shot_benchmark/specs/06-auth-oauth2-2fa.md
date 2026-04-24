# auth-oauth2-2fa

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: OAuth2 password grant + TOTP 2FA challenge for sensitive
endpoints. Tokens expire in 1h; refresh token in 7d. 2FA challenge
required for any DELETE on user records.]

## Acceptance criteria

- POST `/oauth/token` with valid creds returns access + refresh.
- DELETE `/users/me` without 2FA returns 403 with `WWW-Authenticate: TOTP`.
- DELETE `/users/me` with valid 6-digit TOTP returns 204.
- An expired refresh token returns 401 (not 200 with new token).

## Non-requirements

- No SSO / OIDC at v1.
- No backup codes.
