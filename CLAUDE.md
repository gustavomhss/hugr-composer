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
│       ├── SKILL.md                    # Entry point da skill
│       ├── EXPANSION_ROADMAP.md        # Roadmap de expansão
│       ├── generators/                 # 34 code generators
│       ├── adapt/                      # 49 EXTEND + 24 other adapt tools
│       │   ├── extend/                 # Feature tools (crud, auth, infra, realtime, api, testing)
│       │   ├── verify/                 # Validation tools
│       │   ├── operate/                # Operations tools
│       │   ├── evolve/                 # Evolution tools
│       │   └── proactive/              # Proactive tools
│       ├── specs/                      # 64 formal specifications (16 sections each)
│       ├── tests/                      # Test infrastructure
│       │   ├── common/                 # Fixture factory
│       │   ├── contracts/              # Pydantic delivery contract + agent briefing
│       │   ├── test_boot.py            # 49-tool boot test
│       │   ├── test_boot_chains.py     # Forward + reverse chain tests
│       │   ├── test_stress.py          # 49-tool stress test
│       │   ├── property_tests.py       # 8 properties × 72 tools
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

### Números atuais

```
49 EXTEND tools
72 adapt tools total (49 extend + 6 verify + 8 operate + 8 evolve + 1 proactive)
52 generators
124 MCP tools total
64 formal specs (16 sections each)
~2100+ tests (unit + behavior + E2E)
576 property checks (72 × 8 properties)
22 behavior scenarios (12 original + 10 new tools)
```

### Comandos

```bash
cd skills/SKILL-001-fastapi-production

# Rodar todos os testes
PYTHONPATH=. .venv/bin/python -m pytest adapt/ -q

# Boot test (49 tools)
PYTHONPATH=. .venv/bin/python tests/test_boot.py

# Property tests (8 properties × 72 tools)
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
