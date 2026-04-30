# Quick Start — HuGR Smith

Install and use SKILL-001 (FastAPI Production) in under 2 minutes.

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR-Smith/main/install.sh | bash
```

This clones the repo to `~/.hugr-skills`, creates a Python venv, installs
`fastmcp` + skill dependencies, and prints the exact `.mcp.json` stanza
you need to paste into your IDE.

**Requirements:** Python 3.12+, git, 200MB free disk.

## 2. Wire it into your IDE

### Claude Code

Paste the stanza the installer printed into `~/.claude/mcp.json` (global)
or `./.mcp.json` (per project). See [`examples/claude_code.mcp.json`](examples/claude_code.mcp.json)
for the format. Restart Claude Code.

### Cursor / Windsurf

Same `.mcp.json` format — add the stanza to your IDE's MCP settings,
point it at `~/.hugr-skills/skills/SKILL-001-fastapi-production/mcp_server.py`
via the venv's Python interpreter, set `PYTHONPATH` to the skill directory.

## 3. Use it

In Claude Code, just ask:

> Generate a production FastAPI project with Product, Order, and Customer
> models. Add JWT auth, soft delete, audit logging, RBAC, and multi-tenancy.

Claude will call these MCP tools in order:

```
fastapi_generate_project(...)      → 53 files scaffolded
fastapi_add_soft_delete(...)       → is_deleted + restore endpoint
fastapi_add_audit_log(...)         → tamper-evident audit trail
fastapi_add_rbac(...)              → permissions/roles tables
fastapi_add_multi_tenancy(...)     → tenant isolation middleware
```

Result: ~150 files of production-grade code, zero decisions about infra,
100% cross-database, 100/100 on the FinHealth security benchmark.

## 4. What's included

| Skill | Tools | Tests | Benchmark |
|-------|-------|-------|-----------|
| SKILL-001 FastAPI Production | 100 MCP tools (49 generators + 51 adapt) | 1,280 unit + 18 audit suites + 20 E2E (real HTTP + PostgreSQL) | 100/100 — Grade S |

Full catalog: see [`skills/SKILL-001-fastapi-production/SKILL.md`](skills/SKILL-001-fastapi-production/SKILL.md)

## 5. Upgrade

```bash
curl -fsSL https://raw.githubusercontent.com/humangr-labs/HuGR-Smith/main/install.sh | bash
```

Re-running the installer pulls the latest commits, keeps your venv,
reinstalls dependencies (idempotent).

## 6. Uninstall

```bash
rm -rf ~/.hugr-skills
```

Then remove the `fastapi-production` entry from your `.mcp.json`.
