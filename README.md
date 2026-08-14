# Skill-001 — FastAPI Production (+ Claude Code Gateway)

> Convention-over-Configuration FastAPI skill for LLM worker agents, with a
> multi-provider gateway for the Claude Code native model picker. Zero
> friction, zero overhead, zero unnecessary complexity.

- [PRODUCT.md](PRODUCT.md) — product brief
- [ROADMAP.md](ROADMAP.md) — roadmap
- [CONTRACT.md](CONTRACT.md) — binding contract + audit rules

## Current status

- Primitives: 124 (registered, framework-free)
- Staged: 174 (in `_staging/`, +41 quarantined)
- 18 FastAPI adapters (production-wired; +1 Redis, +1 Stripe)
- 135 adapt tools (105 extend + 30 other)
- 61 generators · 28 modules · 20 examples · 124 specs
- Contract: 46/47 (1 open violation — see docs/decisions/0005)

## Quick Start

```bash
./install.sh                                  # install deps + init skill tree
PYTHONPATH=. .venv/bin/python -m engine.inventory   # regenerate INVENTORY.md
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check --quiet   # contract gate
./ci.sh --no-pg                               # local CI without PostgreSQL
```

## Repository layout

```
skill root/             # SKILL-001 FastAPI production
├── generators/          # 61 macro scaffold helpers
├── adapt/               # 135 tools (105 extend + 30 other)
├── core/venous/         # 124 primitives + 18 FastAPI adapters (+ Redis/Stripe)
│   ├── _staging/        # 174 staged (+41 quarantined)
│   └── _adapters/fastapi/
├── modules/             # 28 feature packages
├── mcp_tools/           # tier-1 meta + tree dispatchers
├── engine/              # audit, inventory, promotion, verify
├── specs/               # 124 formal specs
└── benchmarks/          # FinHealth + blind A/B harness
```

> Note: this repo also carries the `gateway/` package (see below).

## Claude Code Gateway

Multi-provider gateway for Claude Code's `/model` picker and subagent
`model:` frontmatter. Providers: OpenRouter (pass-through), Groq, Google AI
Studio (Gemini), NVIDIA NIM, Mistral, opencode-bridge. Independent
quota/keys per provider; only `claude-*`/`anthropic` model IDs surface.

```bash
pip install -e ".[dev]"
cp .env.example .env     # add keys for the providers you use
uvicorn gateway.main:app --host 127.0.0.1 --port 8787
```

Point Claude Code at it: `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`,
`ANTHROPIC_AUTH_TOKEN=sk-or-<OPENROUTER_KEY>`,
`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`. See
`gateway_config.yaml` for fallback chains + model maps.

## Development

```bash
pytest -v                                   # unit + behavior suites
ruff check . && mypy gateway                # lint + types
PYTHONPATH=. .venv/bin/python -m engine.verify_registry   # T0/T1 gate (124)
```

## License

MIT
