# MODULES V2 AUDIT — Database, Background Jobs, WebSockets, Caching

**Scope**: 9 files across 4 modules in `modules/` (v2 predecessor)
**Auditor**: Claude Sonnet 4.6
**Date**: 2026-04-12
**Purpose**: Determine what is unique/valuable vs duplicated, and map to the 51 new specs.

---

## Summary Table

| File | Unique Logic? | Overlap with generators/? | Spec Mapping | Verdict |
|------|--------------|--------------------------|--------------|---------|
| `operate_db.py` | YES — live pg diagnostics | NONE (generators have no runtime ops) | TOOL-040, TOOL-028 | PRESERVAR |
| `verify_db.py` | YES — 8 AST checks (DB-01..08) | PARTIAL (engine.py generates correct code; no analyzer) | TOOL-028, TOOL-040 | PRESERVAR |
| `scaffold_db.py` | PARTIAL — alembic async env, multi-tenancy RLS | HIGH (engine.py, session.py, alembic.py, model.py cover 80%) | TOOL-008, TOOL-036, TOOL-043 | ARQUIVAR |
| `scaffold_jobs.py` | YES — DLQ + idempotency + XFetch pattern | NONE (generators have no ARQ) | TOOL-020, TOOL-046 | PRESERVAR |
| `verify_jobs.py` | YES — 8 AST checks (JOBS-01..08) | NONE | TOOL-020 | PRESERVAR |
| `scaffold_ws.py` | YES — Redis pub/sub, per-IP limits, rooms, schemas | PARTIAL (generators/tools/add_websocket.py is minimal) | (no exact spec, closest: TOOL-014) | PRESERVAR |
| `verify_ws.py` | YES — 8 AST checks (WS-01..08) | NONE | (no exact spec) | PRESERVAR |
| `scaffold_cache.py` | YES — XFetch algorithm, distributed lock Lua, TTL jitter | NONE (generators have no caching) | TOOL-021 | PRESERVAR |
| `operate_cache.py` | YES — live Redis health diagnostics | NONE | TOOL-021, TOOL-040 | PRESERVAR |

**Net: 7 PRESERVAR, 1 ARQUIVAR, 0 DESCARTAR.**

---

## File 1: `operate_db.py` (799 LOC)

### A. O que faz

Conecta a um PostgreSQL ao vivo via psycopg/psycopg2 e extrai inteligência operacional em 5 funções:

- `check_pool_health(db_url)` — consulta `pg_stat_activity`: contagens por estado (active, idle, idle-in-transaction), conexões esperando lock, queries rodando > 30s, utilização vs `max_connections`.
- `find_slow_queries(db_url, min_ms, limit)` — consulta `pg_stat_statements` com colunas compatíveis PG13+; detecta ausência da extensão e instrui como ativar.
- `analyze_query(db_url, sql)` — roda `EXPLAIN (ANALYZE, BUFFERS)` dentro de transaction + rollback; parser `_interpret_plan()` extrai: execution_time, seq_scans por tabela com rowcount, rows removed by filter, disk sort (external merge), nested loops count, buffer cache hit%; gera findings com severity HIGH/MEDIUM.
- `check_table_bloat(db_url, table, limit)` — lê `pg_stat_user_tables`: dead_pct, last vacuum/autovacuum, emite CRITICAL se dead_pct > 50%, WARNING se > 20% ou nunca autovacuumed em tabelas grandes.
- `suggest_indexes(db_url)` — analisa `pg_stat_user_tables` pelo seq_scan_pct e `pg_stat_user_indexes` para índices com 0 scans.

### B. Lógica única?

Alta. O `_interpret_plan()` é um parser de EXPLAIN ANALYZE com heurísticas calibradas (>10K rows = HIGH, >1K = MEDIUM, loops > 1000 = HIGH, external merge = MEDIUM). Os thresholds de pool health (idle-in-transaction > 3, utilization > 80%) são opiniões deliberadas. A lógica de normalização de URL (`+asyncpg` → `+psycopg`) é infra-glue necessária.

### C. Equivalente em generators/?

Nenhum. `generators/database/engine.py` _gera_ código com `pool_pre_ping=True`; não há nenhum arquivo que _analise_ um banco ao vivo. O `benchmark/analyzer.py` analisa dados de benchmark locais, não PostgreSQL real.

### D. Mapeia para specs?

- **TOOL-040 `connection_pool_monitor`**: overlap direto com `check_pool_health()`. A spec TOOL-040 especifica Prometheus metrics; `operate_db.py` usa pg_stat_activity direto. São complementares — `operate_db` é o "diagnóstico imediato", TOOL-040 é "monitoramento contínuo".
- **TOOL-028 `detect_n_plus_one`**: `analyze_query()` detecta seq scans e nested loops que são sintomas de N+1. TOOL-028 usa instrumentação SQLAlchemy em runtime; `operate_db` analisa planos ao vivo. Complementares.
- **TOOL-036 `migration_diff`**: sem overlap (TOOL-036 analisa arquivos Alembic, não banco ao vivo).

### E. Recomendação

**PRESERVAR.** Portar as 5 funções integralmente para o novo TOOL-040 como o subsistema de diagnóstico imediato (modo "check now" vs modo "monitor continuous"). `_interpret_plan()` é a lógica mais valiosa — é um mini-interpretador de EXPLAIN ANALYZE com heurísticas específicas que não existem em nenhum lugar do generators/.

---

## File 2: `verify_db.py` (652 LOC)

### A. O que faz

Análise estática AST de projetos FastAPI/SQLAlchemy. 8 checks via `verify_db_config(project_path)`:

- **DB-01**: `create_async_engine` sem `pool_pre_ping=True`
- **DB-02**: `pool_size * workers > 80` (risco de exceder max_connections)
- **DB-03**: `async_sessionmaker` sem `expire_on_commit=False` (causa MissingGreenlet)
- **DB-04**: `relationship()` sem lazy= e sem estratégias de eager loading no arquivo
- **DB-05**: Engine sem `pool_recycle` (risco de timeout atrás de load balancers)
- **DB-06**: `create_engine` síncrono em codebase async (CRITICAL — bloqueia event loop)
- **DB-07**: SQL injection via f-string/`.format()`/`%`/concatenação em `text()`/`execute()`
- **DB-08**: `mapped_column(ForeignKey(...))` sem `index=True` (FK sem índice)

### B. Lógica única?

Alta. O helper `_resolve_call_name()` resolve dotted call names via AST walk (incluindo nested attributes `x.y.z()`). A heurística DB-02 cruza `pool_size` + `max_overflow` com contagem de workers via regex no source — análise cross-parameter. DB-07 usa 4 regex patterns distintos para cobrir todas as formas de interpolação SQL perigosa. DB-08 é específica do mapeamento SQLAlchemy 2.0 `mapped_column`.

### C. Equivalente em generators/?

Parcial. `generators/database/engine.py` _gera_ código com `pool_pre_ping=True`, `pool_recycle=1800`, e `generators/database/session.py` gera `expire_on_commit=False` — ou seja, o código _gerado_ está correto. Mas não há nenhum _verificador_ que detecte se um projeto existente tem esses problemas. O `benchmark/analyzer.py` não faz análise AST de database config.

### D. Mapeia para specs?

- **TOOL-028 `detect_n_plus_one`**: DB-04 (N+1 via relationship sem lazy strategy) é parte do escopo de TOOL-028. A spec TOOL-028 usa instrumentação de runtime; `verify_db` faz análise estática. Complementares — a versão estática detecta o padrão antes de rodar.
- **TOOL-040 `connection_pool_monitor`**: DB-01, DB-02, DB-05 são checks de pool configuration que o TOOL-040 deveria incluir como análise estática pré-deploy.
- **TOOL-029 `security_scan`**: DB-07 (SQL injection) deveria alimentar TOOL-029.

### E. Recomendação

**PRESERVAR.** Os 8 checks são lógica de auditoria não trivial que não existe em generators/. DB-06 (sync engine em async codebase = CRITICAL) e DB-03 (MissingGreenlet) são os mais valiosos — erros silenciosos que destroem performance sem stacktrace óbvio. Portar como base para a análise estática de TOOL-028 e TOOL-040.

---

## File 3: `scaffold_db.py` (641 LOC)

### A. O que faz

Gera um módulo `database/` completo com:

- `engine.py` — `create_async_engine` com pool_size/max_overflow/recycle/pre_ping comentados
- `models/base.py` — `TimestampMixin`, `SoftDeleteMixin`, `Base(DeclarativeBase)`
- `alembic/env.py` — ambiente async com `run_async_migrations()` via `asyncio.run()`
- `alembic/alembic.ini`, `script.py.mako`
- `database/tenancy.py` — middleware RLS com `SET LOCAL app.current_tenant` + `TenantMixin`

### B. Lógica única?

Baixa a média. A estrutura básica (engine + session factory + dependency) está duplicada com `generators/database/engine.py` + `session.py`. O valor incremental está em:
1. `TenantMixin` + `get_tenant_session()` com `SET LOCAL` (RLS) — não existe em generators/database/.
2. `_alembic_env_py()` com `run_async_migrations` assíncrono — `generators/database/alembic.py` tem versão mais simples.
3. `SoftDeleteMixin` com `soft_delete()` / `restore()` — existe em generators/ via TOOL-001 (add_soft_delete), não no scaffold base.

### C. Equivalente em generators/?

**Alto overlap**. `generators/database/engine.py` gera `create_async_engine` com os mesmos parâmetros. `generators/database/session.py` gera `async_sessionmaker(expire_on_commit=False)`. `generators/database/alembic.py` + `alembic_migration.py` cobrem o Alembic async. `generators/database/model.py` gera modelos com TimestampMixin. O único delta real é o multi-tenancy RLS (`tenancy.py`) que TOOL-008 (`add_multi_tenancy`) cobre como spec dedicada.

### D. Mapeia para specs?

- **TOOL-008 `add_multi_tenancy`**: A parte de `tenancy.py` + `TenantMixin` + RLS é exatamente o escopo de TOOL-008.
- **TOOL-036 `migration_diff`**: O `alembic/env.py` async é infraestrutura para TOOL-036.
- **TOOL-043 `add_migration_data`**: O `script.py.mako` é necessário para data migrations.

### E. Recomendação

**ARQUIVAR.** O core (engine + session + base model) é 80% duplicata de generators/database/. Portar apenas o componente de multi-tenancy RLS (`tenancy.py` + `get_tenant_session()`) para TOOL-008, que é o spec dedicado para isso. O `_alembic_env_py()` async pode ser referenciado pelo TOOL-036 e TOOL-043. O resto é superseded pelos generators.

---

## File 4: `scaffold_jobs.py` (528 LOC)

### A. O que faz

Gera um módulo `jobs/` completo com ARQ (async task queue):

- `jobs/tasks.py` — 3 tasks de exemplo com padrões de produção:
  - `process_order`: idempotência via Redis SET NX (`idem_key`), distributed lock com TTL
  - `call_external_api`: exponential backoff `2^attempt * 5s + jitter`, fallback para DLQ após max_retries
- `jobs/dlq.py` — Dead Letter Queue via Redis Streams (XADD com maxlen=10000): `send_to_dlq()`, `inspect_dlq()`, `replay_dlq_entry()` com audit trail em `dlq:replayed`
- `jobs/worker.py` — `WorkerSettings` com `func()` per-task timeout, `cron()` jobs, `on_startup/on_shutdown` hooks
- `jobs/health.py` — `get_queue_metrics()` via `zcard("arq:queue")`, `zcard("arq:in-progress")`, `xlen("dlq:tasks")`
- `jobs/dependencies.py` — `init_arq_pool()` / `close_arq_pool()` / `get_arq_redis()` para injeção no FastAPI lifespan

### B. Lógica única?

Alta. O DLQ via Redis Streams com replay + audit trail é padrão não trivial. A combinação `idem_key` (idempotency) + `lock:order:{id}` (distributed mutex) no mesmo task é o padrão correto para finanças/pagamentos. O backoff `2^n * base + uniform(0, base * 0.3)` (jitter proporcional) é melhor que jitter fixo. O `replay_dlq_entry()` re-enqueue com fresh retry budget sem deletar a entrada original é design deliberado para audit trail.

### C. Equivalente em generators/?

Nenhum. Generators/ não tem nenhuma referência a ARQ, task queues, DLQ, ou background jobs. É território exclusivo dos modules/.

### D. Mapeia para specs?

- **TOOL-020 `add_long_running_task`**: Overlap direto. TOOL-020 é o spec "adicionar task queue ARQ a um projeto existente" com POST /tasks 202 + polling. `scaffold_jobs.py` gera a infraestrutura de fundo (workers, DLQ, idempotência). São complementares: scaffold_jobs gera o worker side; TOOL-020 spec gera a API side.
- **TOOL-046 `add_event_driven`**: A spec menciona explicitamente ARQ como opção de worker para o outbox pattern. `scaffold_jobs.py` é a infraestrutura ARQ que TOOL-046 precisaria como dependência.
- **TOOL-023 `add_outbox_pattern`**: O DLQ é um componente do outbox pattern (failed events precisam de DLQ).

### E. Recomendação

**PRESERVAR.** A lógica de DLQ via Redis Streams, idempotência com distributed lock, e exponential backoff com jitter proporcional são únicas e diretamente portáveis para TOOL-020 e TOOL-046. Especialmente `dlq.py` e o padrão de `process_order` (lock + idempotency) devem ser preservados integralmente.

---

## File 5: `verify_jobs.py` (466 LOC)

### A. O que faz

Análise estática de projetos FastAPI para anti-padrões em background jobs. 8 checks via `verify_job_config(project_path)`:

- **JOBS-01**: Tasks sem `max_tries` ou `Retry` (retry não configurado)
- **JOBS-02**: Nenhum DLQ no projeto (project-wide check)
- **JOBS-03**: Task de pagamento/ordem sem idempotência (keywords: payment/order/charge/invoice/refund/transfer)
- **JOBS-04**: `WorkerSettings` sem `job_timeout`
- **JOBS-05**: Chamadas blocking (`time.sleep`, `requests.get`, `open`, etc.) dentro de `async def task(ctx, ...)`
- **JOBS-06**: Sem endpoint de health monitoring para a queue
- **JOBS-07**: Task functions sem `try/except`
- **JOBS-08**: `keep_result_forever=True` em WorkerSettings

### B. Lógica única?

Alta. JOBS-05 usa AST walk para identificar async functions com parâmetro `ctx` e procura blocking calls dentro delas — heurística precisa para o padrão ARQ. JOBS-03 combina keyword detection (domínio financeiro) com ausência de idempotency — é um check contextual, não genérico. JOBS-08 detecta um footgun específico do ARQ (resultados em Redis para sempre).

### C. Equivalente em generators/?

Nenhum. Não há nenhum verificador de jobs em generators/.

### D. Mapeia para specs?

- **TOOL-020 `add_long_running_task`**: JOBS-01/04/07 são os checks mais relevantes — retry, timeout, error handling. TOOL-020 deveria incluir um passo de verificação usando esses checks.
- **TOOL-051 `fastapi_doctor`**: Este "doctor" tool seria o lugar natural para todos os `verify_*.py` checks, incluindo JOBS-01..08.

### E. Recomendação

**PRESERVAR.** JOBS-05 (blocking call detection via AST walk dentro de async tasks) é o check mais sofisticado e único. JOBS-03 (idempotência em tasks financeiras) tem valor de segurança direto. Portar todos os 8 checks para TOOL-051 (`fastapi_doctor`) como a categoria "background_jobs" do health scanner.

---

## File 6: `scaffold_ws.py` (670 LOC)

### A. O que faz

Gera um módulo `ws/` completo com 6 arquivos:

- `ws/schemas.py` — `WSAction` (Enum), `WSIncoming` (Pydantic com `room` validado por pattern `^[a-zA-Z0-9_-]+$`), `WSOutgoing`
- `ws/auth.py` — autenticação JWT por query param com `configure_ws_auth(secret)` para injeção no lifespan; instrução de WS tickets de curta duração
- `ws/manager.py` — `ConnectionManager` com: `MAX_PER_USER=5`, `MAX_PER_IP=20`, `_ip_counts` via X-Forwarded-For, `can_connect()`, rooms dict, `broadcast_to_room()`, `close_all()` com `asyncio.gather` + `_safe_close` timeout 5s
- `ws/endpoint.py` — `@router.websocket("/ws")` com: auth antes de accept, heartbeat `asyncio.create_task(_heartbeat_loop)` a cada 30s com timeout 10s, match/case para actions, `finally` com `heartbeat_task.cancel()` + disconnect
- `ws/redis_pubsub.py` — bridge multi-worker: `psubscribe("ws:room:*")`, `broadcast_via_redis()` faz local + Redis publish, `_listen_loop()` decodifica channel para extrair room name

### B. Lógica única?

Alta a muito alta. Comparando com `generators/tools/add_websocket.py`:

| Feature | modules/scaffold_ws.py | generators/add_websocket.py |
|---------|----------------------|---------------------------|
| Per-IP limits | Sim (`MAX_PER_IP=20`, X-Forwarded-For) | Não |
| Per-user limits | Sim (`MAX_PER_USER=5`) | Não |
| Rooms | Sim (multi-room, subscribe/unsubscribe) | Não (single user-scoped) |
| Message validation (Pydantic) | Sim (WSIncoming, ValidationError handling) | Não |
| Redis pub/sub bridge | Sim (`redis_pubsub.py`) | TODO comment apenas |
| Graceful close_all() | Sim (com asyncio.gather, 5s timeout) | Não |
| Heartbeat architecture | Sim (asyncio.create_task, cancel no finally) | Sim (básico) |

O `generators/add_websocket.py` é uma versão simplificada sem rooms, sem limits, sem validação, e com pub/sub apenas comentado como TODO.

### C. Equivalente em generators/?

Parcial. `generators/tools/add_websocket.py` é um precursor com ~40% das features. Os módulos de `scaffold_ws.py` (redis_pubsub, per-IP limits, rooms, Pydantic schemas) são únicos.

### D. Mapeia para specs?

- **TOOL-014 `add_sse`**: SSE não é WebSocket, mas o padrão de pub/sub com Redis para multi-worker é o mesmo. `redis_pubsub.py` pode ser base para TOOL-014.
- Não há spec direto para WebSocket nos 51 novos tools. O mais próximo é TOOL-020 (long running tasks têm SSE/WS como delivery mechanism mencionado).

### E. Recomendação

**PRESERVAR.** O `scaffold_ws.py` é significativamente mais completo que o equivalente em generators/. As features únicas (per-IP limits, rooms com Pydantic validation, Redis pub/sub multi-worker bridge, graceful close_all com timeout) devem ser preservadas integralmente. Considerar como base para um eventual TOOL-WebSocket que não existe nos 51 specs atuais.

---

## File 7: `verify_ws.py` (466 LOC)

### A. O que faz

Análise estática de projetos para anti-padrões em WebSockets. 8 checks via `verify_websocket_config(project_path)`:

- **WS-01**: WebSocket sem autenticação (CRITICAL)
- **WS-02**: Sem heartbeat/ping-pong
- **WS-03**: Sem limites de conexão por user/IP
- **WS-04**: Sem `WebSocketDisconnect` handler ou sem `finally`
- **WS-05**: Mensagens recebidas sem validação Pydantic
- **WS-06**: Sem graceful shutdown
- **WS-07**: Uvicorn ws-max-size não configurado
- **WS-08**: `send_json/send_text` sem proteção contra conexões fechadas

### B. Lógica única?

Alta. WS-01 detecta ausência de auth com múltiplos heurísticos (authenticate, jwt, token, WS_1008, POLICY_VIOLATION) — robusto a diferentes implementações. WS-04 distingue entre "sem WebSocketDisconnect handler" (HIGH) e "sem finally" (MEDIUM) — gradações corretas. WS-08 detecta sends sem try/except — common footgun em broadcast loops onde um send falho interrompe a iteração.

### C. Equivalente em generators/?

Nenhum. Não há verificador de WebSocket em generators/.

### D. Mapeia para specs?

- **TOOL-051 `fastapi_doctor`**: Os 8 checks WS-01..08 são a categoria "websockets" do health scanner.
- **TOOL-029 `security_scan`**: WS-01 (autenticação) é um check de segurança que deveria ser parte de TOOL-029.

### E. Recomendação

**PRESERVAR.** WS-01 (unauthenticated WebSocket = CRITICAL) é o check de segurança mais importante. WS-04 e WS-08 detectam bugs de produção frequentes (resource leaks e broadcast loop crashes). Portar todos os 8 para TOOL-051 como categoria "websockets".

---

## File 8: `scaffold_cache.py` (594 LOC)

### A. O que faz

Gera um módulo `cache/` completo com 7 arquivos:

- `cache/keys.py` — `CacheTTL` enum (REALTIME=10 até STATIC=604800), `ttl_with_jitter(base, pct=10%)`, `CacheKeys` com métodos tipados por entidade
- `cache/aside.py` — `CacheAside.get_or_set()`: check → miss → fetch (async ou sync) → set com jitter; `invalidate_pattern()` usa `scan_iter` (não KEYS, evita blocking)
- `cache/stampede.py` — algoritmo **XFetch**: probabilistic early recomputation. Armazena `{value, delta (tempo de computação), expiry}` serializado. Fórmula: `ttl_remaining + delta * beta * log(random) > 0`. Se negativo = proactive refresh. Beta tuning: 1.0 = optimal, >1.0 = more conservative.
- `cache/lock.py` — `RedisLock` com: `SET NX EX` para acquire, **Lua script atômico** para release (`if get(key) == token then del(key)`), `extend()` para long operations, context manager `__aenter__/__aexit__`
- `cache/warming.py` — `warm_cache()` com exemplos de pipeline bulk insert e comentários instrucionais
- `cache/client.py` — `redis.from_url` com `max_connections=20`, `decode_responses=False`

### B. Lógica única?

Muito alta. O algoritmo XFetch (referência: Vattani, Chierichetti & Lowenstein 2015) é correto e não trivial: armazenar `delta` (tempo real de computação) junto ao valor é necessário para calibrar o threshold probabilístico. O Lua script de release é o padrão correto (evita que worker A libere lock de worker B). `ttl_with_jitter` é simples mas crítico para evitar thundering herd na expiração simultânea. `invalidate_pattern()` usando `scan_iter` (não `KEYS *`) é conhecimento operacional importante.

### C. Equivalente em generators/?

Nenhum. Generators/ não tem absolutamente nenhum módulo de caching.

### D. Mapeia para specs?

- **TOOL-021 `add_cache_layer`**: Overlap quase total. TOOL-021 especifica estratégia cache-aside, TTL, invalidação event-driven + hybrid. `scaffold_cache.py` implementa cache-aside + TTL jitter + XFetch + distributed lock. A spec TOOL-021 adiciona: msgpack serialization, tenant-isolated namespaces, `@cached()` decorator, `/cache/stats` endpoint, SQLAlchemy event listeners para invalidação. O `scaffold_cache.py` é a base sobre a qual TOOL-021 deve construir.
- **TOOL-022 `add_circuit_breaker`**: `RedisLock` pode ser usado como building block para circuit breaker state.

### E. Recomendação

**PRESERVAR.** O algoritmo XFetch, o Lua script de release, e `ttl_with_jitter` são os 3 componentes mais valiosos. Portar integralmente para TOOL-021. O `CacheKeys` com hierarquia de TTLs é também diretamente utilizável. A spec TOOL-021 é mais completa (msgpack, tenant namespaces, `@cached()` decorator) — o módulo é a base sólida que a spec deve estender, não substituir do zero.

---

## File 9: `operate_cache.py` (302 LOC)

### A. O que faz

Conecta a um Redis ao vivo (sync client) e coleta diagnósticos operacionais via `check_cache_health(redis_url)`:

- **Latency**: ping round-trip, alerta se > 5ms
- **Memory**: `used_memory`, `maxmemory`, `usage_pct`, `eviction_policy`, `evicted_keys`. Alerta se > 85% ou maxmemory não configurado.
- **Performance**: `keyspace_hits/misses`, `hit_rate` calculado, `ops_per_sec`. Alerta se hit_rate < 80% após 100+ operações.
- **Clients**: `connected_clients` vs `maxclients`, `blocked_clients`. Alerta se > 80% de maxclients.
- **Key distribution**: `scan_iter` com cap 500 para namespace sampling (prefix antes de `:`)
- **Status**: "healthy" / "degraded" / "unhealthy" baseado em severity dos findings

### B. Lógica única?

Média a alta. Os thresholds (`_MAX_MEMORY_USAGE_PCT=85`, `_MIN_HIT_RATE=0.80`, `_MAX_LATENCY_MS=5.0`) são valores operacionais calibrados, não arbitrários. O namespace sampling com cap de 500 chaves via `scan_iter` (não `KEYS *`) é operacionalmente correto. O retorno de Finding objects com severity e fix_suggestion é uma interface limpa para integração com TOOL-051.

### C. Equivalente em generators/?

Nenhum. Sem nenhum diagnosticador de Redis ao vivo em generators/.

### D. Mapeia para specs?

- **TOOL-021 `add_cache_layer`**: O `/cache/stats` endpoint especificado em TOOL-021 poderia usar `check_cache_health()` como backend.
- **TOOL-040 `connection_pool_monitor`**: TOOL-040 monitora pool de DB; `operate_cache.py` monitora Redis. São o par de "operate" tools para os dois sistemas de estado.
- **TOOL-051 `fastapi_doctor`**: O `check_cache_health()` seria o check de cache do doctor.

### E. Recomendação

**PRESERVAR.** O retorno estruturado com `status`, `memory`, `performance`, `keys`, `clients`, `findings` é a interface certa para o TOOL-021 `/cache/stats` endpoint e para TOOL-051. Portar integralmente.

---

## Recomendações de Ação Prioritizadas

### P0 — Lógica mais valiosa, portar agora

1. **`operate_db._interpret_plan()`** → TOOL-040: parser de EXPLAIN ANALYZE com heurísticas calibradas (seq scan rowcount, nested loop count, external merge, buffer hit rate). Não existe em nenhum outro lugar.

2. **`scaffold_cache._stampede_py()` (XFetch algorithm)** → TOOL-021: implementação correta do algoritmo probabilístico com `delta` de computação real. Referência acadêmica sólida (Vattani 2015).

3. **`scaffold_cache._lock_py()` (Lua release script)** → TOOL-021: o padrão correto para distributed lock Redis. Sem o Lua atômico, o lock é vulnerável a race conditions.

4. **`scaffold_jobs._dlq_py()` (DLQ via Redis Streams)** → TOOL-020 / TOOL-046: `replay_dlq_entry()` com audit trail é a implementação mais completa encontrada.

5. **`verify_db._check_db07_sql_injection()`** → TOOL-029: 4 regex patterns para interpolação SQL são valiosos para o security scan.

### P1 — Portar como base de specs novas

6. **`scaffold_ws.py` inteiro** → novo tool WebSocket (não coberto pelos 51 specs): per-IP limits, rooms, Redis pub/sub bridge, graceful close_all.

7. **`verify_db.py` checks DB-01..08** → TOOL-040 (pool checks) + TOOL-028 (N+1) + TOOL-051 (doctor).

8. **`verify_jobs.py` checks JOBS-01..08** → TOOL-051 categoria "background_jobs".

9. **`verify_ws.py` checks WS-01..08** → TOOL-051 categoria "websockets".

10. **`operate_cache.check_cache_health()`** → TOOL-021 `/cache/stats` + TOOL-051.

### P2 — Arquivar como referência

11. **`scaffold_db.py` core** → supersedido por generators/database/. Manter apenas `tenancy.py` como referência para TOOL-008.

---

## Notas de Integração

- Todos os 9 arquivos usam `from core.models import Finding, Severity` — a interface de output é consistente e compatível com o padrão dos novos tools.
- Os `verify_*.py` files têm o mesmo padrão arquitetural: walk de arquivos Python, análise por-arquivo + project-wide, sort por severity. Este padrão deve ser preservado nos novos tools.
- Os `operate_*.py` files usam sync clients (psycopg, redis sync) propositalmente para não precisar de event loop — correto para MCP tools invocados via CLI.
- Nenhum dos 9 arquivos está referenciado pelo `mcp_server.py` atual, mas a lógica é portável diretamente.
