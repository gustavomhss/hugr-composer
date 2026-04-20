# Session refresh with rotation + replay detection

## Background

An internal tool needs server-side sessions with short-lived access
tokens and longer-lived refresh tokens. The product team cares about
**stolen-refresh-token** detection: if an old refresh token is ever
used again after having been rotated, the session family is
invalidated.

## Requirements

1. `POST /login` — body `{"username": "<string>"}`. Returns HTTP 200
   with `{"access_token": "<string>", "refresh_token": "<string>",
   "session_id": "<string>"}`. Any username is accepted (no password
   for this exercise).
2. `POST /refresh` — body `{"refresh_token": "<string>"}`. Issues a
   NEW access token AND a NEW refresh token. The old refresh token is
   **rotated** (one-time use); presenting it again MUST invalidate the
   whole session family.
3. `GET /whoami` — requires `Authorization: Bearer <access_token>`.
   Returns `{"username": "<string>", "session_id": "<string>"}`. On
   invalid / expired / revoked token returns HTTP 401.
4. `POST /logout` — body `{"refresh_token": "<string>"}`. Revokes the
   whole session family (all outstanding access + refresh tokens).
5. **Replay detection**: if a refresh token that has ALREADY been used
   for a rotation is presented again, the server MUST:
   (a) reject with HTTP 401, AND
   (b) mark the entire session family as compromised so every
       outstanding access token from that family returns 401 on
       `/whoami`.
6. Access tokens MUST be opaque random strings (NOT the refresh
   token, NOT the username).
7. `GET /health` → 200 `{"ok": true}`.

## Acceptance criteria

- Login → refresh → whoami works end-to-end; the new access token from
  refresh is accepted by /whoami.
- Using an OLD refresh token (already rotated) twice → 401 AND every
  access token from that family fails with 401 afterwards.
- Concurrent refreshes with the same refresh token (race) MUST result
  in AT MOST one success; all other concurrent calls with the same
  token either succeed-once or 401, never double-issue.
- Logout revokes all tokens in the family.
- An attacker trying random bytes as a bearer token gets 401, not 500.

## Non-requirements

- No password hashing / multi-factor.
- No persistence across restart.
- No token encryption (plain opaque strings are fine).
- No refresh rate-limiting (separate concern).
