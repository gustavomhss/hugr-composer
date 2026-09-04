"""Generator for operational runbooks (5 standard scenarios)."""

from __future__ import annotations

import textwrap
from pathlib import Path

MCP_TOOL = {
    "name": "fastapi_runbook_generate",
    "description": "Generate 5 operational runbooks: migration_fail, secret_leak, deploy_break, db_slow, rollback.",
    "tags": ["generator", "runbook"],
    "entry": "generate_runbooks",
}


def generate_runbooks(
    output_dir: str,
    project_name: str = "app",
) -> dict:
    """Generate 5 standard operational runbooks.

    Args:
        output_dir: Directory where runbooks/ directory will be created.
        project_name: Name of the project for runbook metadata.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "runbooks"
    out.mkdir(parents=True, exist_ok=True)

    runbooks = [
        {
            "name": "migration_fail.md",
            "title": "Runbook: Migration Failure",
            "scenario": "Alembic migration fails during deployment or upgrade.",
            "symptoms": [
                "Deployment pipeline fails at migration step",
                "Alembic error in logs (e.g., constraint violation, deadlock, timeout)",
                "Application fails health checks after failed migration",
            ],
            "diagnosis": [
                "Check deployment logs for exact Alembic error message",
                "Identify failed revision: `alembic current` and `alembic history`",
                "Check database for partial migration state: `alembic current -v`",
                "Determine if migration is retryable (transient) or requires manual intervention",
            ],
            "resolution": [
                "For transient errors (deadlock, timeout): retry deployment",
                "For constraint violations:",
                "  1. Inspect failed migration SQL: `alembic show <revision>`",
                "  2. Fix data inconsistency manually or create fixup migration",
                "  3. Stamp to failed revision: `alembic stamp <failed_revision>`",
                "  4. Apply fixup migration, then continue",
                "For irreversible schema changes:",
                "  1. Restore database from pre-deployment backup",
                "  2. Create corrected migration",
                "  3. Re-deploy",
            ],
            "prevention": [
                "Always test migrations on staging with production-like data volume",
                "Run `alembic upgrade head --sql` to inspect SQL before applying",
                "Ensure migrations are idempotent where possible",
                "Maintain pre-deployment database backups with verified restore procedure",
            ],
        },
        {
            "name": "secret_leak.md",
            "title": "Runbook: Secret Leak",
            "scenario": "Accidental commit or exposure of secrets (API keys, DB passwords, JWT secrets).",
            "symptoms": [
                "Secret detected in Git history by secret scanner (GitHub, GitLeaks, TruffleHog)",
                "Alert from secret scanning service (GitGuardian, TruffleHog, GitHub Advanced Security)",
                "Suspicious activity on cloud resources (unexpected API calls, billing spikes)",
            ],
            "diagnosis": [
                "Identify leaked secret type (DB password, API key, JWT secret, cloud credentials)",
                "Determine exposure scope: when committed, who has access, where deployed",
                "Check if secret was used in production (check logs for auth failures)",
                "Assess blast radius: which systems/services used the leaked secret",
            ],
            "resolution": [
                "IMMEDIATE: Rotate the leaked secret everywhere it was used",
                "  1. Generate new secret: `openssl rand -hex 32`",
                "  2. Update in all environments: .env, Kubernetes Secrets, CI/CD variables, cloud provider",
                "  2. Deploy config changes (rolling restart if needed)",
                "  3. Verify new secret works: test auth, DB connections, API calls",
                "  4. Revoke old secret in source system (rotate API key, rotate DB password, rotate JWT secret)",
                "Purge from Git history:",
                "  1. `git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch PATH' --prune-empty --tag-name-filter cat -- --all`",
                "  2. Force push: `git push origin --force --all`",
                "  3. Contact GitHub/GitLab support to purge from cached views if needed",
                "Post-incident: audit access logs for unauthorized access during exposure window",
            ],
            "prevention": [
                "Enable secret scanning in CI (GitHub Secret Scanning, GitLeaks, TruffleHog)",
                "Use `.env` files (never commit) + `direnv` or `dotenv` for local dev",
                "Store secrets in vault (HashiCorp Vault, AWS Secrets Manager, 1Password)",
                "Enforce pre-commit hooks: `pre-commit install` with `detect-secrets`",
                "Rotate secrets on schedule (quarterly for JWT, monthly for DB passwords)",
            ],
        },
        {
            "name": "deploy_break.md",
            "title": "Runbook: Deployment Breakage",
            "scenario": "Deployment succeeds but application fails health checks or exhibits broken behavior.",
            "symptoms": [
                "Health check endpoint returns 5xx or times out",
                "Application logs show unhandled exceptions or import errors",
                "Features broken (API returns 500, UI shows errors, background jobs fail)",
                "Metrics show spike in 5xx errors or latency",
            ],
            "diagnosis": [
                "Check deployment logs for errors during build/startup",
                "Check application logs for tracebacks, import errors, config errors",
                "Check health check endpoint: `curl -v /health` or `/healthz`",
                "Compare deployed code vs previous version: `git diff HEAD~1..HEAD`",
                "Check if config/env vars changed: diff .env vs .env.example",
                "Check if dependencies changed: diff requirements.lock vs previous",
            ],
            "resolution": [
                "IMMEDIATE: Rollback to previous version",
                "  1. `kubectl rollout undo deployment/<app>` or `docker-compose down && docker-compose up -d` with previous image",
                "  2. Verify health checks pass",
                "Root cause analysis:",
                "  1. Compare git diff between broken and working commit",
                "  2. Check for missing migrations, config changes, env var changes",
                "  3. Test fix locally with same environment",
                "  4. Re-deploy with fix",
            ],
            "prevention": [
                "Enforce pre-deploy smoke tests (health check, critical API endpoints)",
                "Require PR reviews + CI green before merge to main",
                "Use canary deployments (10% traffic, then 100%)",
                "Automated rollback on health check failure (Argo Rollouts, Flagger)",
                "Maintain runbook for each service with rollback procedure",
            ],
        },
        {
            "name": "db_slow.md",
            "title": "Runbook: Database Performance Degradation",
            "scenario": "Database queries slow, high latency, connection pool exhaustion, or timeouts.",
            "symptoms": [
                "API latency spikes (p95 > 1s, p99 > 5s)",
                "Database CPU/memory near 100%",
                "Connection pool exhausted (pool timeout errors)",
                "Slow query logs show long-running queries",
                "Deadlocks or lock contention errors",
            ],
            "diagnosis": [
                "Check DB metrics: CPU, memory, connections, active queries",
                "Run `pg_stat_activity` (PostgreSQL) to find long-running queries",
                "Check slow query log for queries > 1s",
                "Check for missing indexes: `EXPLAIN ANALYZE` on slow queries",
                "Check for lock contention: `pg_locks` + `pg_stat_activity`",
                "Check connection pool settings vs max_connections",
            ],
            "resolution": [
                "IMMEDIATE: Kill longest-running queries if safe",
                "  1. `SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE state = 'active' AND now() - query_start > interval '5 minutes';`",
                "Add missing indexes (online if possible): `CREATE INDEX CONCURRENTLY ...`",
                "Adjust connection pool: increase pool size or add PgBouncer",
                "Enable query caching (Redis) for expensive read-heavy queries",
                "Scale read replicas for read-heavy workloads",
                "Archive/purge old data if table size is the issue",
            ],
            "prevention": [
                "Enable `pg_stat_statements` and monitor query performance",
                "Set up alerts: p95 latency > 500ms, CPU > 80%, connections > 80%",
                "Regular index maintenance: `REINDEX CONCURRENTLY` during low traffic",
                "Implement query timeout: `statement_timeout = 30s` in Postgres",
                "Use connection pooler (PgBouncer) in production",
            ],
        },
        {
            "name": "rollback.md",
            "title": "Runbook: Emergency Rollback",
            "scenario": "Critical production issue requires immediate rollback to previous version.",
            "symptoms": [
                "Critical bug causing data corruption or security breach",
                "Deployment breaks core functionality with no quick fix",
                "Performance regression causing SLA breach",
                "Security vulnerability in deployed version",
            ],
            "diagnosis": [
                "1. DECLARE INCIDENT: Alert on-call, create incident channel",
                "2. IDENTIFY TARGET: Determine exact previous version to roll back to",
                "  - Check git tags: `git tag --sort=-v:refname | head -5`",
                "  - Check deployment history: `kubectl rollout history deployment/app`",
                "3. EXECUTE ROLLBACK:",
                "  Kubernetes: `kubectl rollout undo deployment/app --to-revision=N`",
                "  Docker Compose: `docker-compose down && docker tag app:prev app:latest && docker-compose up -d`",
                "  Bare metal: `git checkout <prev-tag> && ./deploy.sh`",
                "4. VERIFY:",
                "  - Health checks pass",
                "  - Critical user flows work (login, core API, payments)",
                "  - Metrics return to baseline (latency, error rate, throughput)",
                "5. COMMUNICATE: Postmortem channel, stakeholder update, timeline",
                "6. ROOT CAUSE: Create postmortem within 24h",
            ],
            "resolution": [
                "Verify no data loss or inconsistency (run integrity checks)",
                "Monitor error rates and latency for 30 minutes",
                "Communicate to stakeholders: what happened, impact, resolution",
                "Schedule postmortem within 24 hours",
                "Create follow-up ticket for fix and re-deployment",
            ],
            "prevention": [
                "Automated rollback on health check failure (Argo Rollouts, Flagger)",
                "Canary deployments (10% -> 50% -> 100% with automated rollback)",
                "Pre-deployment smoke tests (health check + critical user flows)",
                "Immutable infrastructure: never modify running containers",
                "Database migrations: backward-compatible, reversible, tested on staging",
            ],
        },
    ]

    def _render_runbook(rb: dict) -> str:
        return textwrap.dedent(f"""\
            # {rb["title"]}

            ## Scenario
            {rb["scenario"]}

            ## Symptoms
            {chr(10).join(f"- {s}" for s in rb["symptoms"])}

            ## Diagnosis
            {chr(10).join(f"{i+1}. {s}" for i, s in enumerate(rb["diagnosis"]))}

            ## Resolution
            {chr(10).join(f"{i+1}. {s}" for i, s in enumerate(rb["resolution"]))}

            {"## Post-Rollback" if "post_rollback" in rb else "## Prevention"}
            {chr(10).join(f"{i+1}. {s}" for i, s in enumerate(rb.get("post_rollback", rb.get("prevention", []))))}
        """)

    out = Path(output_dir) / "runbooks"
    out.mkdir(parents=True, exist_ok=True)

    files_created = []
    for rb in runbooks:
        content = _render_runbook(rb)
        path = out / rb["name"]
        path.write_text(content)
        files_created.append(f"runbooks/{rb['name']}")

    return {
        "files_created": files_created,
        "notes": [
            f"Generated {len(runbooks)} runbooks in runbooks/ directory",
            "Covers: migration failure, secret leak, deployment breakage, DB slowdown, emergency rollback",
        ],
    }


MCP_TOOL = {
    "name": "fastapi_runbook_generate",
    "description": "Generate 5 operational runbooks: migration_fail, secret_leak, deploy_break, db_slow, rollback.",
    "tags": ["generator", "runbook"],
    "entry": "generate_runbooks",
}