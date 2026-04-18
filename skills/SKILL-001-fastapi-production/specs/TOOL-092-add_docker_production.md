# TOOL-092: `fastapi_add_docker_production`

**Skill:** SKILL-001-fastapi-production
**Category:** extend / infrastructure
**Source:** `adapt/extend/infrastructure/add_docker_production.py`
**Test file:** `adapt/extend/infrastructure/test_add_docker_production.py`
**MCP name:** `fastapi_add_docker_production`

---

## 1. Overview

`fastapi_add_docker_production` adds a complete, production-grade Docker
configuration to any FastAPI project that already has `app/core/config.py`
and `requirements.txt`. It generates four artifacts and patches one existing
file:

| Artifact | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build: `builder` installs deps into `/venv`; `runtime` copies the venv, runs as `USER 1000`, exposes a `HEALTHCHECK` |
| `.dockerignore` | Excludes `__pycache__`, `.venv`, `*.pyc`, `.git`, test dirs, CI dirs |
| `docker-compose.prod.yml` | Three-service stack: `app`, `db` (postgres:16-alpine), `cache` (redis:7-alpine) — all with `restart: unless-stopped` and `healthcheck` blocks |
| `scripts/docker-entrypoint.sh` | Socket-wait loop for DB readiness, `alembic upgrade head`, then `exec "$@"` |
| `app/core/config.py` *(patch)* | Inserts `DOCKER_WORKERS`, `DOCKER_PORT`, `DOCKER_HEALTH_PATH` inside `class Settings` |

The tool is **idempotent**: a second invocation on a project that already
contains `docker-compose.prod.yml` with a `restart` keyword returns
`status="no_op"` and writes nothing.

---

## 2. Purpose & Problem Solved

Shipping a FastAPI service to production requires a non-trivial container
configuration. Developers frequently make security mistakes (running as root),
operational mistakes (no health checks, no restart policies), and performance
mistakes (no pip build cache, single-process gunicorn). This tool encodes
SOTA production container practices in one idempotent command:

- **Security:** non-root `USER 1000`, `chown -R appuser:appgroup /app`,
  `.dockerignore` blocks secrets from entering the image.
- **Performance:** BuildKit `--mount=type=cache,target=/root/.cache/pip`
  keeps layer rebuild times low; gunicorn + `UvicornWorker` for
  multi-process async serving.
- **Observability:** `HEALTHCHECK` directive in both the `Dockerfile` and
  the compose service enables `docker ps` health status and compose
  `condition: service_healthy` dependency.
- **Reliability:** `restart: unless-stopped` for all services; `alembic
  upgrade head` in the entrypoint guarantees schema is always current on
  container start.

---

## 3. Performance SLOs

| Metric | Target |
|---|---|
| `execution_time_ms` | < 500 ms on cold filesystem |
| Files created | 3–4 (Dockerfile + .dockerignore + compose + entrypoint.sh) |
| Files modified | 1 (`app/core/config.py`) |
| Config fields injected | 3 (`DOCKER_WORKERS`, `DOCKER_PORT`, `DOCKER_HEALTH_PATH`) |
| Maximum function LOC (`app/`) | ≤ 50 |
| `no_op` detection cost | O(1) — single file existence + string check |

---

## 4. Code Examples

### 4.1 Before (minimal FastAPI project)

```
my_project/
├── app/
│   ├── main.py
│   └── core/
│       └── config.py          # class Settings: ... ; settings = Settings()
├── requirements.txt
└── (no Docker files)
```

`app/core/config.py` before:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/db"
    SECRET_KEY: str = "change-me"

settings = Settings()
```

### 4.2 After (tool applied)

```
my_project/
├── app/
│   └── core/
│       └── config.py          # DOCKER_WORKERS, DOCKER_PORT, DOCKER_HEALTH_PATH added
├── Dockerfile                 # multi-stage builder + runtime
├── .dockerignore
├── docker-compose.prod.yml
└── scripts/
    └── docker-entrypoint.sh  # +x chmod set
```

`app/core/config.py` after (injected block):

```python
    DOCKER_WORKERS: int = 2
    DOCKER_PORT: int = 8000
    DOCKER_HEALTH_PATH: str = "/healthz"

settings = Settings()
```

### 4.3 Dockerfile (key sections)

```dockerfile
# syntax=docker/dockerfile:1.7
# Stage 1 — builder
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /venv && \
    /venv/bin/pip install --upgrade pip && \
    /venv/bin/pip install -r requirements.txt

# Stage 2 — runtime: lean image, non-root user
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 appgroup \
    && useradd -u 1000 -g appgroup -m -s /bin/sh appuser
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
RUN chown -R appuser:appgroup /app
USER 1000
EXPOSE ${DOCKER_PORT:-8000}
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${DOCKER_PORT:-8000}${DOCKER_HEALTH_PATH:-/healthz}')"
ENTRYPOINT ["scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "${DOCKER_WORKERS:-2}", \
     "--bind", "0.0.0.0:${DOCKER_PORT:-8000}", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

### 4.4 docker-compose.prod.yml (key sections)

```yaml
services:
  app:
    build:
      context: .
      target: runtime
    env_file: .env.prod
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:${DOCKER_PORT:-8000}${DOCKER_HEALTH_PATH:-/healthz}')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

  db:
    image: postgres:16-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"]
      interval: 10s
      timeout: 5s
      retries: 5

  cache:
    image: redis:7-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### 4.5 docker-entrypoint.sh (key sections)

```sh
#!/bin/sh
set -e

DB_HOST="${POSTGRES_SERVER:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
MAX_TRIES=30

echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
tries=0
until python -c "
import socket, sys
s = socket.socket()
try:
    s.connect(('${DB_HOST}', ${DB_PORT}))
    s.close()
except OSError:
    sys.exit(1)
" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -ge "$MAX_TRIES" ]; then
        echo "Database not ready after ${MAX_TRIES} attempts. Aborting." >&2
        exit 1
    fi
    sleep 2
done

echo "Running alembic upgrade head..."
alembic upgrade head

echo "Starting application..."
exec "$@"
```

### 4.6 `_patch_config` implementation

```python
def _patch_config(config_file: Path) -> None:
    content = config_file.read_text()
    fields_needed = [
        "    DOCKER_WORKERS: int = 2",
        "    DOCKER_PORT: int = 8000",
        '    DOCKER_HEALTH_PATH: str = "/healthz"',
    ]
    new_lines = [line for line in fields_needed
                 if line.strip().split(":")[0] not in content]
    if not new_lines:
        return
    insertion = "\n".join(new_lines) + "\n"
    marker = "settings = Settings()"
    if marker in content:
        content = content.replace(marker, insertion + "\n" + marker, 1)
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + insertion
    config_file.write_text(content)
```

### 4.7 Idempotency guard

```python
compose_fingerprint = project / "docker-compose.prod.yml"
if compose_fingerprint.exists() and "restart" in compose_fingerprint.read_text():
    return ToolResult(
        status="no_op",
        notes=["docker-compose.prod.yml already present — skipped."],
        execution_time_ms=_elapsed_ms(start),
    )
```

### 4.8 MCP descriptor

```python
MCP_TOOL = {
    "name": "fastapi_add_docker_production",
    "description": (
        "Add a multi-stage production Dockerfile, .dockerignore, "
        "docker-compose.prod.yml, and docker-entrypoint.sh to a FastAPI project."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_docker_production",
}
```

---

## 5. Quality Standards

| Standard | Requirement |
|---|---|
| Function size | No function in generated `app/` code exceeds 50 LOC (AST-enforced) |
| Python validity | Every generated `.py` file passes `ast.parse()` before `status="success"` |
| Non-root container | `USER 1000` present in Dockerfile |
| Multi-stage build | Both `AS builder` and `AS runtime` stages present |
| Pip cache | `--mount=type=cache,target=/root/.cache/pip` in Dockerfile |
| Compose reliability | All services have `restart:` and `healthcheck:` keys |
| Migration safety | `alembic upgrade head` in entrypoint before `exec "$@"` |
| Config hygiene | Config fields are 4-space indented inside `class Settings` body |
| Zero new deps | No new packages added to `requirements.txt` |
| No model/route pollution | `app/models/__init__.py` and `app/routes/__init__.py` untouched |

---

## 6. Completeness Criteria

| CC | Criterion | Verification | Test |
|---|---|---|---|
| CC-01 | `status="success"` on fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"`, no files written | `r2.status == "no_op"` and `not r2.files_created` | `test_idempotent` |
| CC-03 | `dry_run=True` returns `status="success"` with zero writes | No files changed, `result.status == "success"` | `test_dry_run` |
| CC-04 | At least 3 files created (Dockerfile, compose, entrypoint) | `len(result.files_created) >= 3` | `test_files_created_count` |
| CC-05 | At least 1 file modified (`config.py`) | `len(result.files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | All generated `.py` files parse without `SyntaxError` | `ast.parse()` on every `.py` | `test_all_py_parse` |
| CC-07 | No function in `app/` exceeds 50 LOC | AST walk `end_lineno - lineno` | `test_no_function_over_50_loc` |
| CC-08 | `DOCKER_WORKERS`, `DOCKER_PORT`, `DOCKER_HEALTH_PATH` inside `class Settings` | 4-space indent check | `test_config_fields_patched` |
| CC-09 | `app/models/__init__.py` unchanged | `before == after` | `test_no_spurious_models_init_changes` |
| CC-10 | `app/routes/__init__.py` unchanged | `before == after` | `test_no_spurious_routes_init_changes` |
| CC-11 | `Dockerfile` exists with `HEALTHCHECK` and `gunicorn` | File content check | `test_dockerfile_created_with_healthcheck` |
| CC-12 | Dockerfile has `builder` and `runtime` stages | `"builder" in content and "runtime" in content` | `test_dockerfile_multistage` |
| CC-13 | Dockerfile runs as `USER 1000` or `USER appuser` | Content check | `test_dockerfile_nonroot_user` |
| CC-14 | `.dockerignore` excludes `__pycache__` and `.venv` | Content check | `test_dockerignore_created` |
| CC-15 | `docker-compose.prod.yml` has postgres and redis services | Content check | `test_compose_prod_created` |
| CC-16 | `scripts/docker-entrypoint.sh` contains `alembic upgrade` | Content check | `test_entrypoint_created` |
| CC-17 | Compose services have `restart:` keys | `"restart" in content` | `test_compose_has_restart_policies` |
| CC-18 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-19 | `next_steps` is non-empty and mentions `docker` | `"docker" in combined` | `test_next_steps_present` |
| CC-20 | Project still parses after two consecutive runs | `ast.parse()` on all `.py` files | `test_idempotent_project_still_parses` |
| CC-21 | Dockerfile uses `--mount=type=cache` for pip | Content check | `test_pip_cache_mount_in_dockerfile` |
| CC-22 | Dockerfile CMD uses `gunicorn` with `UvicornWorker` | Content check | `test_gunicorn_uvicorn_in_dockerfile` |
| CC-23 | Compose services have `healthcheck:` definitions | `"healthcheck" in content` | `test_compose_has_healthchecks` |

---

## 7. Definition of Done

- [ ] All 23 tests in `test_add_docker_production.py` pass
- [ ] `Dockerfile` has both `AS builder` and `AS runtime` stages
- [ ] `USER 1000` present in `Dockerfile`
- [ ] `HEALTHCHECK` directive present in `Dockerfile`
- [ ] `--mount=type=cache,target=/root/.cache/pip` present in `Dockerfile`
- [ ] `CMD ["gunicorn", ..., "--worker-class", "uvicorn.workers.UvicornWorker", ...]` present
- [ ] `.dockerignore` excludes `__pycache__`, `.venv`, `.env`, `.git/`
- [ ] `docker-compose.prod.yml` has `app`, `db`, `cache` services
- [ ] All compose services have `restart:` and `healthcheck:` keys
- [ ] `postgres:16-alpine` and `redis:7-alpine` images used
- [ ] `scripts/docker-entrypoint.sh` contains socket-wait loop and `alembic upgrade head`
- [ ] `chmod +x` applied to `docker-entrypoint.sh` via `stat.S_IXUSR | S_IXGRP | S_IXOTH`
- [ ] `config.py` receives `DOCKER_WORKERS`, `DOCKER_PORT`, `DOCKER_HEALTH_PATH` at 4-space indent
- [ ] Second invocation returns `no_op` without writing any file
- [ ] `dry_run=True` returns `success` without writing any file
- [ ] `execution_time_ms` is a positive integer on every return path
- [ ] `next_steps` mentions `docker` commands
- [ ] No function in generated Python code exceeds 50 LOC

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|---|---|---|---|
| INV-DOCK-01 | `USER 1000` is always set in the runtime stage | `_write_dockerfile` hardcodes it | `test_dockerfile_nonroot_user` |
| INV-DOCK-02 | Fingerprint check uses `docker-compose.prod.yml` presence + `"restart"` keyword | `_patch_config` never creates this file; only `_write_compose_prod` does | `test_idempotent` |
| INV-DOCK-03 | `_patch_config` only inserts missing fields; repeated calls are no-ops | `line.strip().split(":")[0] not in content` guard | `test_config_fields_patched` + `test_idempotent_project_still_parses` |
| INV-DOCK-04 | `dry_run=True` check is placed *after* the idempotency check and *before* all `Path.write_text()` calls | Code order in `add_docker_production` | `test_dry_run` |
| INV-DOCK-05 | `scripts/docker-entrypoint.sh` is always made executable via `stat.S_IXUSR | S_IXGRP | S_IXOTH` | `entrypoint.chmod(...)` in Step 4 | `test_entrypoint_created` |
| INV-DOCK-06 | `.dockerignore` is skipped (not overwritten) if it already exists | `if not dockerignore.exists():` guard | `test_files_created_count` |
| INV-DOCK-07 | `ast.parse()` validation loop runs only on `.py` files (YAML/sh skipped) | `if p.suffix == ".py"` in validation loop | `test_all_py_parse` |
| INV-DOCK-08 | `app/models/__init__.py` and `app/routes/__init__.py` are never written | No reference to those paths in source | `test_no_spurious_models_init_changes`, `test_no_spurious_routes_init_changes` |

---

## 9. User Stories

**US-1 — First containerisation (happy path)**
> As a developer who has never containerised their FastAPI service, I run
> `fastapi_add_docker_production` and immediately get a working multi-stage
> Docker build with health checks, restart policies, and automatic migrations
> on container start.

**US-2 — Re-running safely after partial setup**
> As a developer who ran the tool yesterday and then switched branches, I can
> safely run the tool again — it returns `no_op` without corrupting any
> existing files.

**US-3 — Dry-run before committing**
> As a developer in a code-review workflow, I run with `dry_run=True` to see
> exactly what would change before writing any files.

**US-4 — Production security posture**
> As a security engineer, I verify that the generated image never runs as root
> and that secrets are never baked in (`.env` and `.env.*` are in
> `.dockerignore`).

**US-5 — CI/CD integration**
> As a DevOps engineer, I use `docker compose -f docker-compose.prod.yml build`
> and `up -d` from the generated `next_steps` to wire the service into the
> deployment pipeline.

---

## 10. Edge Cases

| Edge Case | Expected Behaviour |
|---|---|
| `.dockerignore` already exists | Tool skips creation; does not overwrite; `.dockerignore` not added to `files_created` |
| `docker-compose.prod.yml` already has `restart` | `status="no_op"`, zero writes |
| `app/core/config.py` missing | Config patch skipped silently; other files still created |
| `scripts/` directory already exists | `mkdir(parents=True, exist_ok=True)` is a no-op |
| `DOCKER_WORKERS` already in `config.py` | `_patch_config` skip-guard prevents duplicate injection |
| `settings = Settings()` absent from `config.py` | Fields appended to end of file rather than inserted inline |
| Project name contains underscores | No effect on Docker files (app name only used in `next_steps`) |
| Very long `requirements.txt` | `--mount=type=cache` ensures Docker layer cache is used; no functional impact |

---

## 11. Dependencies

| Dependency | Type | Version / Notes |
|---|---|---|
| `adapt.contracts.ToolInput` | Internal | Required; provides `project_dir`, `dry_run` |
| `adapt.contracts.ToolResult` | Internal | Required; `status`, `files_created`, `files_modified`, `notes`, `next_steps`, `execution_time_ms` |
| `adapt.contracts.validate_project_dir` | Internal | Returns error string if path invalid |
| `adapt.contracts.prerequisites.ensure_prerequisites` | Internal | Checks `CONFIG_SETTINGS`, `REQUIREMENTS_TXT`; auto-scaffolds if missing |
| `adapt.contracts.prerequisites.Prereq` | Internal | Enum: `CONFIG_SETTINGS`, `REQUIREMENTS_TXT` |
| `ast` | stdlib | AST parse validation |
| `textwrap` | stdlib | `dedent` for multi-line file templates |
| `time` | stdlib | `time.monotonic()` for `execution_time_ms` |
| `stat` | stdlib | `S_IXUSR`, `S_IXGRP`, `S_IXOTH` for `chmod` on entrypoint |
| `pathlib.Path` | stdlib | All file I/O |
| **gunicorn + uvicorn** | Runtime (project) | Must be in `requirements.txt` at deploy time; not added by this tool |

---

## 12. File Map

```
{project_dir}/
├── Dockerfile                         # CREATED — multi-stage production build
├── .dockerignore                      # CREATED (if absent)
├── docker-compose.prod.yml            # CREATED
├── scripts/
│   └── docker-entrypoint.sh           # CREATED (+x)
└── app/
    └── core/
        └── config.py                  # MODIFIED — DOCKER_WORKERS, DOCKER_PORT, DOCKER_HEALTH_PATH
```

Source module: `adapt/extend/infrastructure/add_docker_production.py`
Test module: `adapt/extend/infrastructure/test_add_docker_production.py`

---

## 13. Rollback

This tool creates new files and appends to `config.py`. Rollback is:

```bash
# Remove created files
rm Dockerfile .dockerignore docker-compose.prod.yml scripts/docker-entrypoint.sh

# Undo config.py patch (remove the three DOCKER_* lines)
# The _patch_config function inserts a contiguous block; a single-hunk git diff
# is sufficient to revert.
git checkout app/core/config.py
```

The `.dockerignore` is only created if it did not exist, so rollback of a
pre-existing `.dockerignore` is never required.

No database migrations or destructive filesystem operations are performed.

---

## 14. Security Considerations

| Concern | Mitigation |
|---|---|
| Container runs as root | `USER 1000` in runtime stage; `chown` before the USER instruction |
| Secrets baked into image | `.dockerignore` excludes `.env`, `.env.*`; compose reads `env_file: .env.prod` at runtime |
| `POSTGRES_PASSWORD` required | Compose uses `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}` — build fails fast if unset |
| pip cache poisoning | BuildKit cache mounts are per-machine and scoped to the pip cache directory; not shared across images |
| DB not ready at startup | Entrypoint socket-wait loop with `MAX_TRIES=30` prevents Alembic from running against an unreachable DB |
| gunicorn worker crash | `HEALTHCHECK` in Dockerfile and compose will restart unhealthy containers |

---

## 15. Observability

| Signal | Where |
|---|---|
| `execution_time_ms` | `ToolResult.execution_time_ms` — wall-clock ms via `time.monotonic()` |
| `files_created` | `ToolResult.files_created` — absolute paths of all new files |
| `files_modified` | `ToolResult.files_modified` — absolute path of patched `config.py` |
| `notes` | Human-readable summary: "Production Docker setup added: …" |
| `next_steps` | Ordered shell commands: `docker compose -f docker-compose.prod.yml build`, `up -d`, `logs -f app`, health curl |
| Container health | `HEALTHCHECK` directive in Dockerfile; `healthcheck:` block in all compose services |
| App logs | `--access-logfile -` and `--error-logfile -` in gunicorn CMD — logs go to stdout/stderr |

---

## 16. Test Coverage Map

| Test function | CC | What it proves |
|---|---|---|
| `test_success_status` | CC-01 | Happy path returns `status="success"` |
| `test_idempotent` | CC-02 | Second run returns `no_op` without writing files |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 3 files created and all exist on disk |
| `test_files_modified_count` | CC-05 | `config.py` is reported as modified |
| `test_all_py_parse` | CC-06 | All generated `.py` files parse cleanly |
| `test_no_function_over_50_loc` | CC-07 | 50-LOC function limit enforced |
| `test_config_fields_patched` | CC-08 | Three `DOCKER_*` fields inside `class Settings` at 4-space indent |
| `test_no_spurious_models_init_changes` | CC-09 | `models/__init__.py` untouched |
| `test_no_spurious_routes_init_changes` | CC-10 | `routes/__init__.py` untouched |
| `test_dockerfile_created_with_healthcheck` | CC-11 | `Dockerfile` has `HEALTHCHECK` and `gunicorn` |
| `test_dockerfile_multistage` | CC-12 | `builder` and `runtime` stages both present |
| `test_dockerfile_nonroot_user` | CC-13 | `USER 1000` or `USER appuser` in Dockerfile |
| `test_dockerignore_created` | CC-14 | `.dockerignore` excludes `__pycache__` and `.venv` |
| `test_compose_prod_created` | CC-15 | Compose file has postgres and redis |
| `test_entrypoint_created` | CC-16 | Entrypoint references `alembic upgrade` |
| `test_compose_has_restart_policies` | CC-17 | `restart:` in compose |
| `test_execution_time_recorded` | CC-18 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-19 | `next_steps` non-empty and mentions `docker` |
| `test_idempotent_project_still_parses` | CC-20 | Two runs leave all `.py` files parseable |
| `test_pip_cache_mount_in_dockerfile` | CC-21 | `--mount=type=cache` in Dockerfile |
| `test_gunicorn_uvicorn_in_dockerfile` | CC-22 | `gunicorn` + `UvicornWorker` in Dockerfile CMD |
| `test_compose_has_healthchecks` | CC-23 | `healthcheck:` in compose services |
