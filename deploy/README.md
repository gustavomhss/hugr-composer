# HuGR Arsenal — gate deployment

Production stack that enforces the HuGR subscription gate:

| service | image | role |
|---------|-------|------|
| `db`    | `postgres:16-alpine`     | shared revocation authority (cancelled seats / revoked keys) |
| `auth`  | `hugr-auth` (built here)  | holds the signing secret; mints keys + answers `/introspect` |
| `mcp`   | `hugr-skill-fastapi` (built from the skill dir) | serves the ~146 tools, gated by a HuGR token |

**Gate guarantee.** `mcp` runs with `HUGR_GATE=1` and `HUGR_AUTH_URL=http://auth:8079`.
Every MCP request must carry a HuGR license key as a bearer token. The
`HugrTokenVerifier` forwards it to `auth /introspect`; only the auth service
holds the signing secret. **No valid, active subscription token ⇒ FastMCP
authenticates nobody ⇒ the server exposes ZERO tools.** The tool *code* lives
only on this host, so there is nothing to copy and no local check to delete.

Fail-closed posture:
- Missing/short signing secret → `/introspect` always returns `active:false`,
  `/admin/issue` returns `503`.
- Admin token `< 16` chars or mismatched → all `/admin/*` return `403`.
- `HUGR_STORE_DSN` set but the SQL store can't be built → the API raises on
  startup (no silent fall-back to a store that would lose revocations).
- Auth API unreachable from the gate → introspection denies (gate serves nothing).

---

## Files

```
deploy/
  docker-compose.yml      # db + auth + mcp, healthchecks, volume, network
  auth.Dockerfile         # multi-stage, non-root, py3.12-slim image for the auth API
  requirements-auth.txt   # pinned runtime deps for the auth API ONLY
  .env.example            # documented env template (copy to deploy/.env)
  README.md               # this file
.dockerignore             # trims the auth build context (repo root) to hugr_auth/
```
The MCP image reuses the skill's existing production Dockerfile
(`skills/SKILL-001-fastapi-production/infra/docker/Dockerfile`) — not duplicated here.

---

## 1. Configure

```bash
cp deploy/.env.example deploy/.env
# then edit deploy/.env and set REAL values:
python -c "import secrets;print('HUGR_LICENSE_SIGNING_SECRET=',secrets.token_hex(32))"
python -c "import secrets;print('HUGR_ADMIN_TOKEN=',secrets.token_urlsafe(24))"
python -c "import secrets;print('POSTGRES_PASSWORD=',secrets.token_urlsafe(24))"
```

Mandatory in `deploy/.env`: `HUGR_LICENSE_SIGNING_SECRET` (>=64 hex chars),
`HUGR_ADMIN_TOKEN` (>=16 chars), `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`. Compose refuses to start if any are missing.

## 2. Validate (no build, cheap)

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env config
```
Parses + interpolates the compose file. Run this first; it catches missing env
vars and YAML errors without pulling or building anything.

## 3. First real build + bring up  (HEAVY — needs ~free machine)

> Requires `feat/auth-db-store` merged (or cherry-picked) so `hugr_auth/store_sql.py`
> exists — the auth image needs it for `HUGR_STORE_DSN`. See "Branch note" below.

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
docker compose -f deploy/docker-compose.yml ps      # all healthy?
```

## 4. Smoke test

Set the admin token you put in `.env`:
```bash
ADMIN=$(grep '^HUGR_ADMIN_TOKEN=' deploy/.env | cut -d= -f2-)
```

**a. Auth liveness**
```bash
curl -fsS http://127.0.0.1:8079/healthz        # → {"status":"ok"}
```

**b. Mint a license** (via the admin HTTP endpoint — the billing path):
```bash
KEY=$(curl -fsS -X POST http://127.0.0.1:8079/admin/issue \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d '{"seat":"smoke","plan":"pro","ttl_days":7}' | python -c 'import sys,json;print(json.load(sys.stdin)["key"])')
echo "$KEY"
```
Alternatively mint via the in-container CLI (writes to the same Postgres store):
```bash
docker compose -f deploy/docker-compose.yml exec auth \
  python -m hugr_auth.cli issue --seat smoke --plan pro --ttl-days 7
```

**c. Introspect — valid vs garbage**
```bash
curl -fsS -X POST http://127.0.0.1:8079/introspect \
  -H 'Content-Type: application/json' -d "{\"key\":\"$KEY\"}"      # → active:true + claims
curl -fsS -X POST http://127.0.0.1:8079/introspect \
  -H 'Content-Type: application/json' -d '{"key":"not-a-real-key"}' # → {"active":false}
```

**d. Gate proof — MCP with vs without a valid token.** Point any MCP HTTP client
at `http://127.0.0.1:8080` (FastMCP streamable-http).

- WITHOUT a token (or a bad one): the server authenticates nobody → tool list is
  empty / connection unauthorized.
- WITH `Authorization: Bearer $KEY`: tools are listed and callable.

Quick unauthenticated check (expect a 4xx / no tools, NOT a tool list):
```bash
curl -i http://127.0.0.1:8080/mcp        # unauthorized — gate serving nothing
```

**e. Revocation cuts access immediately**
```bash
JTI=$(curl -fsS -X POST http://127.0.0.1:8079/introspect \
  -H 'Content-Type: application/json' -d "{\"key\":\"$KEY\"}" \
  | python -c 'import sys,json;print(json.load(sys.stdin)["claims"]["jti"])')
curl -fsS -X POST http://127.0.0.1:8079/admin/revoke_key \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' \
  -d "{\"jti\":\"$JTI\"}"
curl -fsS -X POST http://127.0.0.1:8079/introspect \
  -H 'Content-Type: application/json' -d "{\"key\":\"$KEY\"}"      # → now active:false
```
Cancel a whole seat the same way via `/admin/cancel_seat {"seat":"smoke"}`.

## 5. Tear down
```bash
docker compose -f deploy/docker-compose.yml down            # keep the volume
docker compose -f deploy/docker-compose.yml down -v         # also drop pgdata
```

---

## Branch note (store_sql)

`hugr_auth/store_sql.py` (the `SqlSubscriptionStore` used by `HUGR_STORE_DSN`)
currently lives on branch `feat/auth-db-store`, not on `main`. The deploy is
designed *for* the SQL store: `auth.Dockerfile` copies the whole `hugr_auth/`
package, so once that module is on the build branch the image just works.
Until then, the auth image will fail to start with a DSN set (lazy import of
`store_sql` raises) — which is the intended fail-closed behaviour, not a silent
in-memory fall-back. To run before the merge, either cherry-pick
`hugr_auth/store_sql.py` onto this branch or unset `HUGR_STORE_DSN` and use a
`HUGR_STORE_PATH` JSON file on a mounted volume (single-instance only).

## Scaling

`auth` is stateless apart from the signing secret in env; scale it horizontally
(`docker compose up -d --scale auth=N` behind a load balancer) — all replicas
share revocation state through Postgres. Never publish `5432` to the host in
production; keep `db` internal to `hugr_net`.
