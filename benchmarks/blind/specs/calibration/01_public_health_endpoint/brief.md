# Public health + version endpoint

## Background

A small service needs a standard SRE-facing status surface so load
balancers and deploy scripts can tell it apart from a sibling service.

## Requirements

1. Expose `GET /health` that returns HTTP 200 with JSON
   `{"ok": true}`. The response MUST be a JSON object and MUST include
   the `ok` key set to the literal boolean `true`.
2. Expose `GET /version` that returns HTTP 200 with JSON
   `{"service": "<string>", "version": "<string>"}`. Both fields MUST
   be non-empty strings.
3. Expose `GET /ready` that returns HTTP 200 with JSON containing
   `{"ready": true}` once the process has finished booting. For the
   purposes of this brief "booting" is instantaneous — the key MUST
   always be present and set to boolean `true`.
4. Requests to an unknown path MUST return HTTP 404 with a JSON body.
   No HTML error pages, no tracebacks.
5. All responses MUST set `content-type: application/json` (case-
   insensitive).

## Acceptance criteria

- `GET /health` → 200, body `{"ok": true}` (strict: value is a bool).
- `GET /version` → 200, body has non-empty string `service` + `version`.
- `GET /ready` → 200, body has `ready` set to boolean `true`.
- `GET /not-a-real-path` → 404, body parses as JSON.
- Every declared endpoint responds within 2 s cold.

## Non-requirements

- No authentication.
- No persistence.
- No rate limiting.
- No metrics endpoint.
- No admin UI.
