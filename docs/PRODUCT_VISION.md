# HuGR Smith — Product Vision

> Biblioteca proprietária de componentes de código battle-tested que servem
> como peças de LEGO para o HuGR Maestro (coding agent powered by Claude).

## O Produto

**HuGR Smith** é uma biblioteca de componentes de código (peças de LEGO)
que o HuGR Maestro usa para montar projetos completos. O LLM não gera código
do zero — seleciona, compõe e adapta peças prontas e testadas.

## O Moat

Não é o LLM (todo mundo tem). Não é o agent (Cursor/Devin fazem).
É a BIBLIOTECA de peças testadas com composição verificada.

```
Outros agents:  LLM → gera do zero → lento, caro, errático
HuGR Maestro:   LLM → monta peças testadas → rápido, barato, preciso
```

| Métrica | Cursor/Devin | HuGR Maestro |
|---------|-------------|--------------|
| Custo por projeto | $0.50-2.00 | $0.02-0.10 |
| Tempo | 60-180s | 8-20s |
| LLM calls | 10-50 | 1-2 |
| Qualidade | Variável | Consistente (peças testadas) |
| Testes inclusos | Não | Sim (por peça) |
| Segurança auditada | Não | Sim (20 checks por peça) |

## Arquitetura

```
Layer 0: CONVENTION ($0, 50ms)     → Tudo que todo projeto precisa
Layer 1: RULES ($0, 10ms)          → Keyword matching seleciona peças
Layer 2: LLM ($0.02-0.05, 3-5s)   → Domain models, nomes, relações (UMA call)
Layer 3: TEMPLATES ($0, 500ms)     → Peças da biblioteca, parametrizadas
Layer 4: VALIDATION ($0-0.05, 5s)  → ruff + mypy + pytest
```

## Estado Atual

### SKILL-001: FastAPI Production (DONE)
- 100 EXTEND tools (peças)
- 124 formal specs
- 3000+ testes
- 38 behavior scenarios (464 assertions)
- META-003 audit tool (20 checks automáticos)
- 100/100 audit PASS
- Convention over Configuration completo

### Próximos Skills (planejados)
- SKILL-002: Rust/Axum (maior delta de valor — LLM naked é péssimo com Rust)
- SKILL-003: NestJS/TypeScript
- SKILL-004: Go/Gin
- SKILL-005: Terraform/IaC
- SKILL-006: React/Next.js

### Infra necessária
- SkillEngine: orquestrador inteligente (Layer 0-4)
- Pattern specs: 100+ patterns language-agnostic
- Maestro: coding agent que consome o SkillKit

## Flywheel

```
Mais peças → Maestro resolve mais → Mais usuários → Mais feedback → Mais peças
```

## Defensabilidade

1. Tempo: meses pra replicar qualidade + testes + composição
2. Exclusividade: só Maestro acessa (não é open source)
3. Calibração: Haiku + SkillKit > Opus naked (provado)
4. Composição: peças compõem entre si (200+ cenários testados)
5. Crescimento: cada peça nova torna o sistema mais valioso

## Findings da Pesquisa (2026-04-18)

### Convention over Configuration
- Rails: templates + conventions + composition (20 anos de sucesso)
- Spring Boot: classpath detection + conditional auto-config (melhor pattern)
- Next.js: file-system conventions (routing by naming)
- Padrão universal: defaults sem config + escape hatches

### LLM-augmented Code Gen
- Template + LLM hybrid é 10-25x mais barato que LLM puro
- Uma LLM call batched > muitas calls pequenas
- Constrained output space = melhor qualidade (v0 prova isso)
- Feedback loop (generate→run→fix) é essencial
- Fault localization > code generation (SWE-bench finding)

### Architectural Recommendation
- Convention over Configuration para infra (Layer 0)
- Rule-based selection para componentes (Layer 1)  
- LLM ONLY para domain modeling (Layer 2)
- Templates parametrizados para código (Layer 3)
- Deterministic validation para qualidade (Layer 4)
