# CLAUDE.md — HuGR Skills

> Configuração para Claude Code no repo HuGR_Skills.

## Projeto

```yaml
projeto: "HuGR Skills"
descricao: "Executable knowledge skills for LLM worker agents"
tipo: "MCP tools + code generators"
repo: "humangr-labs/HuGR_Skills"
visibilidade: "PRIVADO"
```

## Estrutura

```
HuGR_Skills/
├── CLAUDE.md              # Este arquivo
├── README.md              # Visão geral
├── QUICK_START.md         # Setup rápido
├── skills/
│   └── SKILL-001-fastapi-production/   # FastAPI production skill
│       ├── SKILL.md                    # Entry point da skill (Anthropic Agent Skills format)
│       ├── STATUS.md                   # Counts humanos + test matrix
│       ├── INVENTORY.md                # Machine-verified counts (fonte única)
│       ├── generators/                 # 56 code generators
│       ├── adapt/                      # 126 tools (100 extend + 26 outros)
│       │   ├── extend/                 # 100 feature tools (api_design, auth_access, crud_data, infrastructure, realtime, testing_tools)
│       │   ├── verify/                 # 6 validation tools
│       │   ├── operate/                # 8 operations tools
│       │   ├── evolve/                 # 8 evolution tools
│       │   ├── contracts/              # 4 contract tools
│       │   └── proactive/              # 1 proactive tool
│       ├── modules/                    # 28 feature packages prontos
│       ├── core/venous/                # 122 registered primitives + 16 FastAPI adapters + 181 staged em _extracted/ (+47 quarantined)
│       ├── mcp_tools/                  # Tier-1 meta + tree dispatchers + auto-discovery
│       │   ├── tier1.py + compose.py   # 7 meta tools (home/search/describe/scaffold/compose/audit/verify)
│       │   └── tree/                   # 9 domain dispatchers (auth, data, api, realtime, resiliency, obs, compliance, deployment, testing)
│       ├── engine/                     # audit, index, bench, docs, extraction, inventory, promotion
│       ├── specs/                      # 124 formal specifications
│       # examples/ vive em /examples/ no repo root — 20 apps completos
│       ├── tests/                      # Test infrastructure
│       │   ├── common/                 # Fixture factory
│       │   ├── contracts/              # Pydantic delivery contract + agent briefing
│       │   ├── test_boot.py            # 100-tool boot test
│       │   ├── test_boot_chains.py     # Forward + reverse chain tests
│       │   ├── test_stress.py          # 100-tool stress test
│       │   ├── property_tests.py       # 8 properties × 123 tools
│       │   ├── test_e2e_hardcore.py    # 12 E2E scenarios (SQLite)
│       │   ├── test_e2e_postgres.py    # 8 E2E scenarios (PostgreSQL)
│       │   ├── test_behavior_scenarios.py  # 12 domain archetypes
│       │   ├── test_cross_composition.py   # 200+ composition scenarios
│       │   ├── test_soak.py            # 5-min sustained load test
│       │   └── mutation_runner.py      # AST-based mutation tester
│       ├── mcp_tools/                  # MCP server + auto-discovery
│       ├── ci.sh                       # Local CI (10 suites)
│       └── benchmarks/                 # FinHealth benchmark
├── tools/                  # Shared tooling
├── examples/               # Usage examples
└── install.sh              # Installation script
```

## SKILL-001 — FastAPI Production

A skill principal. Convention over Configuration para FastAPI.

### Números atuais (machine-verified por `engine.inventory`)

> **Fonte única de verdade:** `skills/SKILL-001-fastapi-production/INVENTORY.md`.
> Regenerar com `PYTHONPATH=. .venv/bin/python -m engine.inventory`.
> Drift entre este bloco e INVENTORY.md = bug de audit.

```
257  arquivos com MCP_TOOL      (superfície Maestro)
201  tools indexados no catalog.json
122  primitivos registrados      (core/venous/<ns>/<Name>/)
181  primitivos staged           (PascalCase-filtered, +47 quarantined)
 16  FastAPI adapters            (production-wired)
127  adapt tools                 (100 extend + 8 operate + 8 evolve + 6 verify + 4 contracts + 1 proactive)
 22  extend add_* Rails-connected (§B1.3 floor = 22, non-regressive)
 56  generators
 28  modules/ packages           (auth, payments, caching, db, deployment, obs, security, background_jobs, websockets)
 20  examples/ apps completos    (5 baseline + 10 mid + 5 adversarial, repo-root /examples/)
 20  benchmark specs             (plan 100.00, code 100.00)
124  specs formais
 36  contract rules (36/36 green)
```

### Camadas do skill (arquitetura Rails-style)

| Camada | Onde | Qtd | O que é |
|---|---|---:|---|
| Primitivos registrados | `core/venous/<ns>/<Name>/` | 122 | Peças framework-free |
| Primitivos staged (PascalCase) | `core/venous/_extracted/` | 181 | HuGR-shelled mas com REPLACE_ME, +47 quarantined |
| Adapters FastAPI | `core/venous/_adapters/fastapi/` | 16 | Wiring production-grade |
| EXTEND tools | `adapt/extend/` | 100 | Slice generators (add_*) |
| Outros adapt | `adapt/{verify,operate,evolve,contracts,proactive}/` | 27 | Validação, ops, evolução |
| Generators | `generators/` | 56 | Scaffolders de subsistemas (per `engine.inventory`; 60 .py files on disk incl. 3 top-level helpers + conftest) |
| Modules | `modules/` | 28 | Feature packages prontos |
| Tier-1 meta | `mcp_tools/tier1.py` + `compose.py` | 7 | home/search/describe/scaffold/compose/audit/verify |
| Tree dispatchers | `mcp_tools/tree/` | 9 | auth, data, api, realtime, resiliency, obs, compliance, deployment, testing |
| Examples | `examples/` | 5 | Apps completos de referência |

### Comandos

```bash
cd skills/SKILL-001-fastapi-production

# Rodar todos os testes
PYTHONPATH=. .venv/bin/python -m pytest adapt/ -q

# Boot test (100 tools)
PYTHONPATH=. .venv/bin/python tests/test_boot.py

# Property tests (8 properties × 123 tools)
PYTHONPATH=. .venv/bin/python tests/property_tests.py

# E2E hardcore (12 cenários, SQLite)
PYTHONPATH=. .venv/bin/python tests/test_e2e_hardcore.py

# Behavior scenarios (12 domínios, requer PostgreSQL)
PYTHONPATH=. .venv/bin/python tests/test_behavior_scenarios.py

# Cross-composition (200+ cenários)
PYTHONPATH=. .venv/bin/python tests/test_cross_composition.py

# Soak test (5 min, 10 concurrent)
PYTHONPATH=. .venv/bin/python tests/test_soak.py --duration 300

# CI completo (10 suites)
./ci.sh              # com PostgreSQL (Docker)
./ci.sh --no-pg      # sem PostgreSQL
```

### Padrões obrigatórios para novas tools

Toda nova tool DEVE seguir:
- `tests/contracts/AGENT_BRIEFING_TEMPLATE.md` — 9 anti-patterns, 18 CCs, 12 QS, DoD granular, 10 INVs
- `tests/contracts/delivery_contract.py` — Pydantic contract inviolável

### Promotion pipeline (Track B, 2026-04-21)

`engine/promotion/` handles the staged→registered path without silently
amending §A12. Core modules:

- `classify.py` — emits `ledger.json` with per-primitive verdict
  (promote_full / promote_lite / keep_staged / delete / needs_review).
- `promote.py` — atomic executor, automatic rollback on failure,
  refuses non-ready entries. Lite tier gated on `§B1.7 ratified` token
  in CONTRACT.md §E.
- `ledger.py` — renders `LEDGER.md` for approve/reject review.
- `HANDOFF.md` — overnight triage summary.

Run:

```bash
cd skills/SKILL-001-fastapi-production
PYTHONPATH=. .venv/bin/python -m engine.promotion.classify    # regenerate ledger
PYTHONPATH=. .venv/bin/python -m engine.promotion.ledger       # render Markdown
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --from-ledger NAME
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --delete NAME
```

Tier-lite proposal: `docs/decisions/0004-tier-lite.md`.

### Agent orchestration

Para construir novas tools em paralelo:
1. Spawn Sonnet agents com o briefing template
2. Cada agent entrega: tool .py + test .py + behavior test .py
3. Opus audita (patterns + quality do código gerado + domain correctness)
4. Wire into test infrastructure (boot, stress, property, cross-comp)
5. CI green → commit + push

## Convencoes

```yaml
nomenclatura:
  tools: "add_{feature_name}.py"
  tests: "test_add_{feature_name}.py"
  behavior: "test_add_{feature_name}_behavior.py"
  specs: "TOOL-{NNN}-add_{feature_name}.md"

patterns:
  mcp_tool: "MCP_TOOL dict at module level"
  prerequisites: "ensure_prerequisites() call"
  idempotency: "fingerprint check → no_op"
  dry_run: "returns before any write"
  elapsed_ms: "on EVERY return ToolResult path"
  ast_parse: "validation loop before success return"
  lazy_imports: "optional SDKs inside function bodies"
```

## Credenciais

NUNCA commitar `.env`, chaves de API, ou secrets no código.
Tools que integram com SDKs externos (Stripe, boto3, celery, etc.)
DEVEM usar lazy imports — app boota sem o SDK instalado.
