# PLAN — Lint + Gate debt (2026-08-13)

> **Âncora do plano.** Este arquivo é o checkpoint durável. Cada bloco termina
> atualizando este doc (estado → `done`/`blocked` + contagem real de erros).
> Se o contexto explodir, retomar lendo APENAS este arquivo + os comandos de
> verificação do bloco corrente.

## Objetivo

Endereçar TODOS os três frentes levantados na triagem:

1. **Bug do gate** — `engine/llm/__init__.py:3` re-exporta `LLMCallFailed`
   (não existe; a classe é `LLMCallFailedError`). Quebra o import do gate
   inteiro (`engine.check_primitive` → `engine.gates` → `engine.llm`).
   Meta `fastapi_meta_verify` quebrada há ~10 meses.
2. **Primitives que reprovam o gate** — após destravar, rodar o gate completo
   (124 registrados) e corrigir todas as falhas. Conhecidos: `ValueObject`,
   `ShardedCounter` (invariante de fan-out falha: hash mapeia threads p/ 1 shard).
3. **Dívida ruff repo-wide** — 12.965 erros, 2.021 arquivos.

## Baseline medido (2026-08-13)

```
12.965  erros ruff (2.021 arquivos)
 4.729  auto-fixáveis seguros (--fix)
 2.143  auto-fixáveis unsafe (--unsafe-fixes)

core/venous              6.505 erros / 1.150 arq    (registered=~2.001, staging=4.369, adapters=135)
core/venous/_staging     4.369 erros / 345 arq      (maioria F821 em _quarantine — REPLACE_ME, by-design)
adapt                    1.709 erros / 344 arq
tests                    1.303 erros / 128 arq
engine                     946 erros / 125 arq
generators                 514 erros /  53 arq
modules                    477 erros /  28 arq
benchmarks                 243 erros / 102 arq   (benchmarks = 20.169 arquivos .py? — verificar; só 102 com erro)
mcp_tools                  205 erros /  17 arq
core/venous/_adapters      135 erros /  32 arq
```

### Regras top (repo-wide)

| Regra | N | Tipo | Estratégia |
|---|---:|---|---|
| Q000 bad-quotes | 2.542 | fixável seguro | `--fix` |
| F821 undefined-name | 2.272 | 96% `_staging/_quarantine` (by-design) | per-file-ignore em `_staging/*` |
| E501 line-too-long | 2.243 | strings em templates emitidos | per-file-ignore em `*/templates/*` + `generators/*` |
| T201 print | 1.462 | CLI/testes (by-design) | per-file-ignore `T201` (CLI) |
| I001 unsorted-imports | 864 | fixável seguro | `--fix` |
| F401 unused-import | 455 | fixável unsafe | `--unsafe-fixes` + revisão |
| PT018/PT011/PT017/PT012 | ~510 | testes (by-design) | per-file-ignore em `tests/*` |
| SLF001 private-access | 301 | testes (by-design) | já ignorado em `tests/*` |
| E402 import-not-top | 278 | lazy imports (convenção OBRIGATÓRIA) | per-file-ignore |
| RUF100 unused-noqa | 277 | fixável seguro | `--fix` |

## Princípio de bloco

- Cada bloco ≈ **100–150k tokens** (~7–12k linhas de Python a carregar).
- Sequência recomendada (respeitar ordem):
  - Bloco 0 destrava o gate (pré-requisito de tudo).
  - Blocos ruff: `--fix` mecânico → `--unsafe-fixes` → manuais, agrupados por camada.
- **Não** rodar `ruff --fix` repo-wide de uma vez (histórico: 856 arquivos de diff
  incontrolável). Por bloco, com revisão de diff + teste da camada.

---

## Blocos

### B0 — Destravar o gate (tiny) ✅ PRÉ-REQUISITO

- **Arquivo:** `engine/llm/__init__.py` (5 linhas)
- **Fix:** `LLMCallFailed` → `LLMCallFailedError` no import e `__all__`.
- **Gate:** `python -m engine.check_primitive --name ValueObject` importa.
- **Teste de regressão:** smoke test de import (`from engine.llm import LLMCallFailedError`).
- **Tamanho:** < 5k tokens.

### B1 — Baseline completo do gate

- Rodar `python -m engine.check_primitive` (124 registrados).
- Capturar lista completa de primitives reprovando (B0 destrava; pode revelar mais
  além de ValueObject/ShardedCounter).
- **NÃO** corrigir aqui — só medir e ancorar a lista neste doc.

**Resultado (2026-08-13, `engine.verify_registry --json`):**

```
124  primitives registrados
 36  falhando (34×T0 + 3×T1)   — linha de base real
  1  já corrigido: ValueObject  (T1 super().__post_init__ slots bug — célula __class__ descartada)
  1  já corrigido: ShardedCounter (teste INV_05 sem concorrência real; barrier fix)
```

**T0 fail (34):** `api/` BatchCore(mypy), DataLoader(RUF006), DeprecationEntry(RUF023),
DeprecationRegistry(bare type:ignore), IdempotencyStore(RUF023), MiddlewarePipeline(RUF100),
PersistedQueryRegistry(A002), QueryBus(RUF022); `auth/` CurrentPrincipal(mypy),
FeatureFlagCache(mypy), RequestGuard(UP042), TokenIntrospector(SIM110);
`billing/Billing`(RUF022); `cache/SessionCache`(RUF100); `data/` LifetimeScope(UP042),
PiiClassification(UP042); `events/` DomainEvent(FURB162), EventEnvelope(FURB162),
PubSub(N818), TransactionalOutbox(RUF100); `extras/SchemaComparator`(?);
`obs/` CorrelationContext(SIM108), HealthProbe(UP042), LifecycleHook(?), TelemetryExporter(UP042);
`resiliency/` CostTracker(mypy), ExcelExporter(mypy), GracefulShutdown(mypy),
HeterogeneousWorkerPool(mypy), ModelRegistry(Q000), RetryBudget(mypy), RetryPolicy(C901),
TracingBuffer(Q000); `security/OutputEncoder`(UP042).

**T1 fail (3):** `compliance/DataSubjectRequest`, `data/LegalHold` (override blocked),
`flags/FeatureToggle` (deprecation flow).

> Observação: muitas falhas T0 são do gate "curated ALL" — mais agressivo que o
> pyproject.toml (mypy --strict + ruff ALL). Regras predominantes: UP042
> (str+Enum), mypy missing type args, RUF023/RUF022/RUF100, Q000. São fixes
> mecânicos em ~90% dos casos.

### B2 — Corrigir primitives reprovados (re-dimensionado: 36, não 2)

Fatiado por tipo de falha (blocos de contexto independentes):

- **B2a — T0 ruff mecânico (~26 primitives):** `--fix`/`--unsafe-fixes` + revisão.
  Agrupado por namespace (api → auth → data → events → obs → resiliency → resto).
- **B2b — T0 mypy --strict (8 primitives):** BatchCore, CurrentPrincipal,
  FeatureFlagCache, CostTracker, ExcelExporter, GracefulShutdown,
  HeterogeneousWorkerPool, RetryBudget. Anotações de tipo.
- **B2c — T1 comportamento (3 primitives):** DataSubjectRequest, LegalHold,
  FeatureToggle. Bugs reais de lógica de negócio.

Gate de saída: `engine.verify_registry` → 124/124 green.
- **Tamanho:** 3 × ~60-90k tokens.

### B3 — Política ruff (per-file-ignores) — o "cheap win"

- Editar `pyproject.toml` `[tool.ruff.lint] per-file-ignores`:
  - `core/venous/_staging/*` → `F821` (quarentena REPLACE_ME)
  - `*/templates/*`, `generators/*`, `benchmarks/*` → `E501`
  - CLI entrypoints (`*_cli*.py`, `engine/*/cli*`) → `T201`
  - `tests/*` → `PT018, PT011, PT017, PT012`
  - `*/_adapters/*` → `E402` (lazy imports), etc.
- Meta: remover ~5.5–6k erros "by-design" do radar, restando ~7k reais.
- **Tamanho:** ~5k tokens.

### B4 — mcp_tools (17 arq, 205 errs, ~4k linhas)

- `--fix` seguro + unsafe, revisão, `fastapi_meta_home` smoke.
- **Tamanho:** ~40k.

### B5 — engine (125 arq, 946 errs, ~42k linhas)

- Fatiar em 2 sub-blocos (~21k linhas cada): `engine/audit*` e restante.
- `--fix` + revisão por sub-bloco.
- **Tamanho:** 2 × ~100k.

### B6 — adapt/extend/infrastructure (195 arq, 58k linhas)

- O maior pedaço. Fatiar em 4 sub-blocos (~15k linhas cada).
- **Tamanho:** 4 × ~120k.

### B7 — adapt/extend restante

- `auth_access` (58 arq, 16k linhas) → 1 bloco.
- `crud_data` (42 arq, 13k linhas) + `testing_tools` (38 arq, 10k) → 1 bloco.
- `api_design` (29 arq, 7k) + `realtime` (17 arq, 7k) → 1 bloco.
- **Tamanho:** 3 × ~100k.

### B8 — adapt/outros (evolve/operate/verify/proactive/contracts/_base, ~18k linhas)

- **Tamanho:** 1–2 blocos ~100k.

### B9 — core/venous registered (113k linhas, ~2.001 errs)

- Fatiar por namespace (cada ≤ ~15k linhas):
  - `data` (21k) + `api` (9k) → 2 blocos
  - `events` (16k) + `auth` (11k) → 2 blocos
  - `obs` (13k) + `resiliency` (11k) → 2 blocos
  - `security` (10k) + `compliance` (5k) → 1 bloco
  - `cache/jobs/llm/policy/extras/flags/billing/_ports` (~19k) → 2 blocos
- **Tamanho:** 9 × ~100k.

### B10 — core/venous/_staging (345 arq, 21k linhas)

- Após B3 (F821 ignorado), restam ~1.3k errs mecânicos.
- 2 blocos (~10k linhas cada).
- **Tamanho:** 2 × ~80k.

### B11 — core/venous/_adapters (44 arq, ~4.8k linhas)

- **Tamanho:** ~50k.

### B12 — tests (128 arq, 1.303 errs, ~31k linhas)

- Após B3, PT*/SLF ignorados; restam mecânicos + F841/F811.
- 3 blocos (~10k cada).
- **Tamanho:** 3 × ~100k.

### B13 — benchmarks (102 arq, 243 errs)

- Verificar estrutura (20k arquivos?); maioria templates → E501 via B3.
- **Tamanho:** ~40k.

### B14 — generators (53 arq, 514 errs) + modules (28 arq, 477 errs)

- **Tamanho:** 2 × ~90k.

### B15 — Verificação final + docs

- `ruff check .` → alvo < 500 erros (só by-design restante documentado).
- `python -m engine.check_primitive` → 124/124 green.
- `pytest adapt/ -q` + suítes principais (test_boot, property, cross-comp).
- Atualizar `STATUS.md` + `INVENTORY.md` + este plano (estado final).
- **Tamanho:** ~20k.

---

## Estado

| Bloco | Status | Obs |
|---|---|---|
| B0 | done | import fix + verify_registry runner + mypy install |
| B1 | done | 124 baseline: 36 failing (34 T0 + 3 T1) |
| B2a | pending | T0 ruff mecânico (~26) |
| B2b | pending | T0 mypy strict (8) |
| B2c | pending | T1 comportamento (3) |
| B3 | pending | |
| B4 | pending | |
| B5 | pending | |
| B6 | pending | |
| B7 | pending | |
| B8 | pending | |
| B9 | pending | |
| B10 | pending | |
| B11 | pending | |
| B12 | pending | |
| B13 | pending | |
| B14 | pending | |
| B15 | pending | |

## Protocolo de retomada

Se o contexto for perdido no meio de um bloco:

1. Ler este arquivo (`docs/PLAN_LINT_GATE_2026-08-13.md`).
2. Encontrar o bloco com status `in_progress` (ou o último `done` + 1).
3. Rodar os comandos de verificação do bloco (cada bloco lista seus gates).
4. Continuar a partir daí. NUNCA começar um bloco novo sem o anterior `done`.
