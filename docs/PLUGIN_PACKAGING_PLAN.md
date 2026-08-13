# HuGR Arsenal — SOTA Plugin Packaging Plan

## Overview
Transform the skill into a production-grade, auto-discoverable plugin with three artifacts:
1. **`hugr-fastapi`** (PyPI wheel) — runtime primitives for generated apps
2. **`hugr-arsenal`** (MCP server + opencode plugin) — agent toolbelt
3. **`claude-gateway`** (container) — multi-provider LLM gateway

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        hugr-arsenal (MCP)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  202 tools   │  │  9 trees     │  │  8 meta (tier1)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────┬───────────────────────────────────────┘
                          │ discovers / generates
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    hugr-fastapi (PyPI)                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │resiliency│ │auth     │ │data     │ │obs      │ │events   │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘   │
│  + extras: redis, stripe (optional deps)                        │
└─────────────────────────┬───────────────────────────────────────┘
                          │ imported by generated apps
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   claude-gateway (Docker)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ OpenAI   │ │ Anthropic│ │ Groq     │ │ Mistral  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Artifact 1: hugr-fastapi (PyPI Wheel)

### Source Structure (current)
```
core/venous/
├── resiliency/
│   ├── CircuitBreaker/
│   │   ├── CircuitBreaker.py          ← impl
│   │   ├── CircuitBreaker.protocol.py ← interface
│   │   ├── CircuitBreaker.contract.json
│   │   ├── CircuitBreaker.tla
│   │   └── tests/
│   └── RateLimiter/
│       └── ...
├── auth/
│   └── ...
```

### Target Wheel Structure
```
hugr_fastapi/
├── __init__.py              # exports all namespaces
├── resiliency/
│   ├── __init__.py
│   ├── CircuitBreaker.py
│   ├── RateLimiter.py
│   └── ...
├── auth/
│   ├── __init__.py
│   └── ...
├── data/
├── events/
├── obs/
├── _adapters/
│   ├── fastapi/
│   ├── redis/
│   └── stripe/
├── _protocols/
│   ├── resiliency/
│   └── ...
└── py.typed
```

### Build Pipeline (promotion integration)
```python
# engine/promotion/promote.py additions
def emit_wheel_source(primitive_name: str, target_dir: Path):
    """Harvest impl + protocol from staged/registered → flattened wheel source."""
    # 1. Copy <Name>.py → hugr_fastapi/<ns>/<Name>.py
    # 2. Copy <Name>.protocol.py → hugr_fastapi/_protocols/<ns>/<Name>.py
    # 3. Generate hugr_fastapi/<ns>/__init__.py with exports
    # 4. Drop test/chaos/metamorphic/corpus files
    # 5. Run ruff + mypy on emitted source
```

### pyproject.toml (wheel)
```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "hugr-fastapi"
version = "0.1.0"
dependencies = []  # zero required deps (framework-free)

[project.optional-dependencies]
fastapi = ["fastapi>=0.115", "sqlalchemy[asyncio]>=2.0"]
redis = ["redis>=5.0"]
stripe = ["stripe>=11.0"]

[tool.hatch.build.targets.wheel]
packages = ["hugr_fastapi"]
```

---

## Artifact 2: hugr-arsenal (MCP Server + Plugin)

### Entry Points
```toml
# pyproject.toml
[project.scripts]
hugr-arsenal = "hugr_arsenal.mcp_server:main"
hugr-arsenal-index = "hugr_arsenal.index:main"
```

### opencode.json (Plugin Manifest)
```json
{
  "name": "hugr-arsenal",
  "version": "1.0.0",
  "description": "FastAPI production skill for opencode",
  "entry": "hugr_arsenal.mcp_server:main",
  "tools": ["adapt/**", "generators/**"],
  "config": {
    "skill_path": "{config_dir}/skills/SKILL-001-fastapi-production",
    "catalog_path": "{config_dir}/catalog.json"
  },
  "permissions": ["read", "write", "exec", "net"],
  "mcp": {
    "server": true,
    "resources": ["skill://catalog", "skill://primitives", "skill://tools"]
  }
}
```

### claude-plugin.json
```json
{
  "name": "hugr-arsenal",
  "version": "1.0.0",
  "mcpServers": {
    "hugr-arsenal": {
      "command": "hugr-arsenal",
      "args": ["--stdio"],
      "env": {
        "HUGR_SKILL_PATH": "${workspaceFolder}/.hugr/skills/SKILL-001-fastapi-production"
      }
    }
  }
}
```

---

## Artifact 3: claude-gateway (Container)

### Dockerfile
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen
COPY gateway/ ./gateway/
COPY gateway_config.yaml ./
EXPOSE 8080
HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1
CMD ["python", "-m", "gateway.main"]
```

### k8s/helm
```yaml
# helm/claude-gateway/values.yaml
replicaCount: 2
image:
  repository: humangr-labs/claude-gateway
  tag: latest
resources:
  limits:
    cpu: 500m
    memory: 512Mi
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
```

---

## CI/CD Pipeline

### GitHub Actions
```yaml
# .github/workflows/release.yml
on:
  push:
    tags: ['v*']

jobs:
  hugr-fastapi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build --wheel packaging/hugr-fastapi
      - uses: pypa/gh-action-pypi-publish@release/v1

  hugr-arsenal:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build --wheel
      - uses: actions/upload-artifact@v4
        with:
          name: hugr-arsenal-wheel
          path: dist/*.whl

  claude-gateway:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: gateway/Dockerfile
          push: true
          tags: ghcr.io/humangr-labs/claude-gateway:${{ github.ref_name }}
```

---

## Review Rounds

### Round 1: Architecture & Dependencies
- [ ] Dependency graph: zero required deps for hugr-fastapi core
- [ ] Optional deps correctly scoped (fastapi, redis, stripe)
- [ ] No circular imports between namespaces
- [ ] Protocol/interface separation clean
- [ ] Lazy imports for all optional SDKs

### Round 2: Build Pipeline & CI/CD
- [ ] Promotion pipeline emits valid wheel source
- [ ] Hatch build produces installable wheel
- [ ] PyPI publish on tag works
- [ ] MCP server entrypoint works (`python -m hugr_arsenal.mcp_server`)
- [ ] opencode plugin loads correctly
- [ ] Gateway Docker builds and health checks pass

### Round 3: Distribution & DX
- [ ] opencode.json auto-discovered
- [ ] claude-plugin.json works with Claude Code
- [ ] Semantic versioning across 3 artifacts
- [ ] Changelog generated from conventional commits
- [ ] Documentation: README, PACKAGING.md, CHANGELOG.md
- [ ] Examples work with published wheel

---

## Agent Parallelization

### Agent A: Primitive Library Build (hugr-fastapi)
**Scope:** `engine/promotion/`, `packaging/hugr-fastapi/`, `core/venous/` harvest
**Deliverables:**
- `emit_wheel_source()` in promote.py
- Flattened `hugr_fastapi/` source tree
- Hatch build working
- PyPI publish workflow

### Agent B: MCP Server & Plugin Manifest
**Scope:** `mcp_tools/`, `install.sh`, plugin manifests
**Deliverables:**
- `hugr_arsenal.mcp_server:main` entrypoint
- `opencode.json` + `claude-plugin.json`
- `install.sh` generates `.mcp.json` + `.opencode.json`
- Tool discovery/resources working

### Agent C: Gateway Deployment & Release Automation
**Scope:** `gateway/`, `helm/`, `.github/workflows/`
**Deliverables:**
- Dockerfile + health check
- Helm chart with autoscaling
- GitHub Actions release pipeline (3 jobs)
- Semantic versioning coordination

---

## Dependencies Between Agents

```
Agent A (hugr-fastapi) ──► Agent B (MCP uses catalog)
       │
       └──► Agent C (Gateway uses primitives)
```

**Sync points:**
1. After Agent A emits wheel source → Agent B updates catalog discovery
2. After Agent B MCP server works → Agent C integrates gateway health
3. All three coordinate version tag (`vX.Y.Z`)

---

## Timeline Estimate

| Phase | Duration |
|-------|----------|
| Round 1 Review | 30 min |
| Round 2 Review | 30 min |
| Round 3 Review | 30 min |
| Agent A | 2-3 hrs |
| Agent B | 1.5-2 hrs |
| Agent C | 1.5-2 hrs |
| Integration test | 30 min |
| **Total** | **~6-7 hrs** |

---

## Open Questions

1. **Version coordination:** Single tag for all 3 artifacts, or independent?
2. **Private PyPI:** hugr-fastapi is proprietary — use GH Packages or internal index?
3. **Gateway auth:** Built-in API key, or delegate to upstream?
4. **Plugin auto-update:** opencode supports self-update?
---

## Review Findings (2026-08-12)

### Round 1: Architecture & Dependencies
| Check | Status | Details |
|-------|--------|---------|
| hugr-fastapi required deps | ✅ | `[]` (zero required deps) |
| hugr-fastapi optional deps | ✅ | `fastapi`, `redis`, `stripe` |
| Protocol/interface separation | ✅ | 291 protocol files, 783 impl files |
| Lazy SDK imports | ✅ | Inside functions (`# noqa: PLC0415`) |
| Cross-namespace imports | ⚠️ | 196 (mostly `__init__.py` re-exports + tests) |
| TYPE_CHECKING blocks | ⚠️ | None used (lazy imports done inline) |

### Round 2: Build Pipeline & CI/CD
| Check | Status | Details |
|-------|--------|---------|
| Promotion pipeline | ✅ | `promote/classify/ledger` exist |
| Hatch build config | ✅ | `packages=["hugr_fastapi"]` |
| GitHub Actions | ✅ | 4 workflows |
| PyPI publish workflow | ❌ | **MISSING** |
| install.sh .mcp.json | ⚠️ | Points to **external** `hugr-composer` |
| requirements-mcp.txt | ✅ | Comprehensive |

### Round 3: Distribution & DX
| Check | Status | Details |
|-------|--------|---------|
| opencode.json | ❌ | **MISSING** |
| .claude-plugin/plugin.json | ✅ | Exists |
| .mcp.json | ❌ | Points to **external** `hugr-composer` |
| mcp_server.py | ✅ | Imports OK, fastmcp available |
| Gateway Dockerfile | ❌ | **MISSING** |
| Helm chart | ❌ | **MISSING** |
| opencode.json | ❌ | **MISSING** |
| Version sync | ⚠️ | root=0.1.0, wheel=0.1.0, plugin=1.0.0 |

---

## Critical Gaps (Must Fix)

1. **`.mcp.json` points to EXTERNAL package** — must point to local `mcp_server.py`
2. **`opencode.json` MISSING** — required for opencode auto-discovery
3. **NO PyPI publish workflow** — for `hugr-fastapi` wheel
4. **Gateway Dockerfile/Helm chart MISSING** — deployment blockers
4. **hugr-fastapi build pipeline NOT integrated** with promotion
4. **Version mismatch** — root=0.1.0, plugin=1.0.0

---

## Agent Work Plans (Parallel Execution)

### Agent A: Primitive Library Build (hugr-fastapi)
**Owner:** A | **Duration:** ~2-3 hrs | **Deps:** None

| Task | Description | Done |
|------|-------------|------|
| A1 | Add `emit_wheel_source()` to `engine/promotion/promote.py` | ☐ |
| A2 | Harvest impl + protocol from `core/venous/<ns>/<Name>/` → `hugr_fastapi/<ns>/` | ☐ |
| A3 | Add hatch build step in `engine/promotion/promote.py` (post-promote) | ☐ |
| A4 | Create `.github/workflows/publish-wheel.yml` (PyPI/GH Packages) | ☐ |
| A5 | Test `uv build --wheel packaging/hugr-fastapi` locally | ☐ |
| A6 | Verify wheel installs: `pip install dist/hugr_fastapi-*.whl` | ☐ |

**Deliverable:** Installable `hugr-fastapi` wheel published to PyPI/GH Packages on tag.

---

### Agent B: MCP Server & Plugin Manifest
**Owner:** B | **Duration:** ~1.5-2 hrs | **Deps:** None

| Task | Description | Done |
|------|-------------|------|
| B1 | Fix `.mcp.json` → point to local `mcp_server.py` (not `hugr-composer`) | ☐ |
| B2 | Create `opencode.json` with tool discovery + MCP config | ☐ |
| B3 | Update `.claude-plugin/plugin.json` → use local `.mcp.json` | ☐ |
| B4 | Add `opencode.json` with tool catalog + MCP config | ☐ |
| B5 | Update `install.sh` → generate correct local `.mcp.json` | ☐ |
| B6 | Add `pyproject.toml` script: `hugr-arsenal = hugr_arsenal.mcp_server:main` | ☐ |
| B7 | Test `hugr-arsenal --stdio` and `fastmcp run mcp_server.py:mcp` | ☐ |

**Deliverable:** Local MCP server runnable, opencode/Claude auto-discovery works.

---

### Agent C: Gateway Deployment & Release Automation
**Owner:** C | **Duration:** ~1.5-2 hrs | **Deps:** A, B

| Task | Description | Done |
|------|-------------|------|
| C1 | Create `gateway/Dockerfile` with health check + non-root user | ☐ |
| C2 | Create `helm/claude-gateway/` chart with HPA + resources | ☐ |
| C3 | Create `.github/workflows/release.yml` (3 jobs) | ☐ |
| C4 | Semantic versioning: single tag `vX.Y.Z` for all 3 artifacts | ☐ |
| C4a | Job 1: `hugr-fastapi` wheel → PyPI/GH Packages | ☐ |
| C4b | Job 2: `hugr-arsenal` wheel → GitHub Release assets | ☐ |
| C4c | Job 3: `claude-gateway` Docker → GHCR | ☐ |
| C5 | Gateway health/observability: Prometheus `/metrics` + Grafana dashboard | ☐ |
| C6 | Test: `docker build -t claude-gateway . && docker run -p 8080:8080` | ☐ |

**Deliverable:** Full release pipeline on tag push; gateway deployable to k8s.

---

## Parallel Execution Order

```
┌─────────────────────────────────────────────────────────────┐
│  START (all agents can begin immediately)                   │
├─────────────────────────────────────────────────────────────┤
│  Agent A (hugr-fastapi)          Agent B (MCP/Plugin)       │
│  ─────────────────────           ─────────────────────      │
│  A1 → A2 → A3 → A4 → A5 → A6     B1 → B2 → B3 → B4 → B5 → B6│
│       │                              │        │              │
│       ▼                              ▼        ▼              │
│  (wheel published)            (MCP server + plugin ready)    │
│       │                              │        │              │
│       └──────────────┬───────────────┘        │              │
│                      ▼                       ▼              │
│              Agent C (Gateway + Release)                    │
│              ─────────────────────────                      │
│              C1 → C2 → C3 → C4 → C5 → C6                    │
│                      │                                      │
│                      ▼                                      │
│              RELEASE TAG vX.Y.Z                             │
└─────────────────────────────────────────────────────────────┘
```

## Sync Points

1. **After A4/A5**: Wheel build tested → C4a ready
2. **After B6/B7**: MCP server + plugin ready → C4b ready  
3. **After A6 + B7 + C1-C5**: All artifacts ready → C6 (release tag)

## Quality Gates (Each Agent)

| Agent | Gate | Command |
|-------|------|---------|
| A | Wheel builds + installs | `uv build --wheel && pip install dist/*.whl` |
| B | MCP stdio works | `hugr-arsenal --stdio` |
| B | opencode discovers | `opencode plugin list` |
| C | Docker builds | `docker build -t claude-gateway gateway/` |
| C | Helm lints | `helm lint helm/claude-gateway/` |
| All | Release tag | `git tag vX.Y.Z && git push origin vX.Y.Z` |

---

## Next Steps

1. **Assign owners** for Agent A, B, C
2. **Create branches** for each agent
3. **Execute in parallel** with daily sync
4. **Integration test** after all three done
5. **Tag release** `v0.1.0` (or `v1.0.0` per plugin manifest)

