# MODULES V2 AUDIT — Security & Auth

> Audit de 7 arquivos em `modules/security/` e `modules/auth/`.
> Objetivo: determinar o que é único/valioso vs. duplicata do que já existe em `generators/` e `benchmark/`.
>
> **Veredicto sumário**: 3 PRESERVAR (lógica única não coberta pelos generators), 2 ARQUIVAR (conteúdo duplica generators mas com variações úteis como referência), 2 DESCARTAR (duplicatas diretas ou subconjuntos do que já existe).

---

## 1. `modules/security/tools/pentest_api.py` (919 LOC)

### A. O que faz

Executa 6 testes de penetração ativos contra uma instância FastAPI em execução (live/runtime), usando `httpx` async:

1. **`test_security_headers`** — GET para um endpoint e verifica presença/valor correto dos 7 headers OWASP (X-Content-Type-Options, X-Frame-Options, HSTS, CSP, Referrer-Policy, Permissions-Policy, X-XSS-Protection). Score >= 85% para passar.
2. **`test_cors_bypass`** — Envia OPTIONS + GET de 3 origins maliciosas (`https://evil.example.com`, `https://attacker.com`, `null`) e detecta se o servidor reflete o origin ou habilita credentials com wildcard.
3. **`test_rate_limiting`** — Dispara 25 requests em burst e verifica se 429 aparece antes do fim. Também verifica presença de `Retry-After`.
4. **`test_body_size`** — Envia JSON com 5MB de payload e verifica resposta 413/400/422 (ou timeout/connection reset = aprovado).
5. **`test_sql_injection`** — Envia 7 payloads clássicos de SQLi (Classic OR, Comment bypass, Union select, Stacked query, Boolean blind, Time blind, Error based) e verifica se SQL error strings aparecem na resposta (lista de 13 padrões: "syntax error", "sqlite3.operationalerror", "sqlalchemy.exc.", "relation \"", etc.).
6. **`test_error_disclosure`** — 5 probes de erro (404 path, invalid content-type, malformed JSON, URL de 10K chars, path traversal `/../../../etc/passwd`) com 12 disclosure patterns (Traceback, "/site-packages/", "sqlalchemy.exc.", "pydantic_core._pydantic_core", "at 0x", etc.).

Função `run_all_tests()` orquestra todos sequencialmente.

### B. Lógica única vs. glue

**LÓGICA ÚNICA de alta densidade:**

- Lista `_SQLI_PAYLOADS` com 7 payloads e os 13 padrões de `sql_error_patterns` mapeados explicitamente.
- Lista `_EVIL_ORIGINS` e a lógica dupla (preflight OPTIONS + GET) para detectar `reflected=True AND credentials_allowed=True` vs. só reflected.
- A heurística do body size: timeout/connection reset = pass (não apenas 413), e o check `rejected or not accepted` (inclui 422 como proteção indireta via Pydantic).
- Os 12 disclosure patterns do `test_error_disclosure` + os 5 probes específicos (incluindo path traversal `/../../../etc/passwd` e URL 10K chars).
- Score 85% para headers (`all_present and score >= 0.85`): grade parcial aceitável.

### C. Equivalente em `generators/`?

Não existe em nenhum arquivo de `generators/`. O `benchmark/analyzer.py` faz análise **estática** (regex/AST sobre código fonte), não testes dinâmicos contra servidor em execução. São ferramentas complementares — este arquivo testa runtime, o analyzer testa código.

### D. Mapeia para spec novo?

**TOOL-029 `security_scan`** é o spec mais próximo, mas a abordagem é diferente:
- TOOL-029 usa bandit + semgrep + pip-audit (análise estática, SARIF output, CI-first).
- Este arquivo faz pentest dinâmico (requer servidor rodando, httpx async, testa runtime behavior).

Nenhum dos 51 specs define um "dynamic pentest runner" — há uma lacuna real aqui.

### E. Recomendação: **PRESERVAR**

A lógica de pentest dinâmico (CORS bypass com credenciais, timing com `null` origin, SQLi payload list + error patterns, disclosure probes) não existe em `generators/` e não é coberta pelo TOOL-029. Este arquivo é candidato direto a ser portado como a função de runtime de TOOL-029 ou como um tool separado `fastapi_pentest_live`.

---

## 2. `modules/security/tools/verify_security.py` (908 LOC)

### A. O que faz

Análise estática via AST + regex de um projeto FastAPI inteiro. Detecta 10 anti-patterns:

- **SEC-01** (`_check_sec01_cors_wildcard`): Detecta `CORSMiddleware(allow_origins=["*"], allow_credentials=True)` via AST walk. Também detecta origin reflection dinâmica via regex no source.
- **SEC-02** (`_check_sec02_missing_headers`): Verifica presença dos 7 headers obrigatórios em arquivos de middleware (relevance filter por palavras-chave).
- **SEC-03** (`_check_sec03_no_rate_limiting`): Project-wide search por 9 indicators (`slowapi`, `SlowAPI`, `Limiter`, etc.).
- **SEC-04** (`_check_sec04_unbounded_strings`): AST walk sobre `ClassDef` que herda de `BaseModel` — detecta `str` fields sem `max_length` em `Field()`. Inclui `str | None` union type.
- **SEC-05** (`_check_sec05_raw_sql`): Detecta `ast.JoinedStr` (f-strings) com variáveis + 2+ SQL keywords, `.format()` em SQL strings, e concatenação `"SELECT..." + variable` via regex.
- **SEC-06** (`_check_sec06_secrets_in_code`): 7 regex patterns para API keys, secrets, Stripe keys, GitHub tokens, AWS keys, DB connection strings, hardcoded JWTs. Mascara valores no finding.
- **SEC-07** (`_check_sec07_no_body_limit`): Project-wide search por 7 indicators.
- **SEC-08** (`_check_sec08_debug_mode`): AST — `FastAPI(debug=True)` como constante. Também detecta `docs_url`/`redoc_url`/`openapi_url` sem guard de environment.
- **SEC-09** (`_check_sec09_no_https`): Project-wide search por HSTS e HTTPS redirect indicators.
- **SEC-10** (`_check_sec10_exception_exposure`): AST — `HTTPException(detail=str(exc))`, `detail=repr(exc)`, `detail=f"...{e}..."` onde `e` é nome de exceção.

Helpers críticos: `_resolve_call_name()` para dotted calls (`app.add_middleware`, `CORSMiddleware`), `_get_keyword_value()` para keyword args em AST.

### B. Lógica única vs. glue

**LÓGICA ÚNICA:**

- `_check_sec01_cors_wildcard`: Combinação AST (kwargs inspection) + regex (dynamic reflection pattern `headers[.*Access-Control-Allow-Origin.*] = .*request.`).
- `_check_sec04_unbounded_strings`: AST walk sobre `BaseModel` subclasses verificando `str | None` union types sem `max_length` — granularidade que `benchmark/analyzer.py` não tem.
- `_check_sec05_raw_sql`: Triple detection (JoinedStr AST + .format() AST + concatenation regex) com threshold de 2 SQL keywords para reduzir falsos positivos.
- `_check_sec08_debug_mode`: Detecta docs_url/redoc_url expostos sem environment guard, verificando contexto de 10 linhas ao redor.
- `_check_sec10_exception_exposure`: Analisa `HTTPException(detail=...)` com AST para identificar `str(e)`, `repr(exc)`, f-strings com variáveis de exceção.
- `_SECRET_PATTERNS`: 7 patterns compilados para diferentes tipos de secrets com mascaramento do valor.

### C. Equivalente em `generators/`?

`benchmark/analyzer.py` cobre algumas áreas similares (password hashing, JWT algorithm whitelist, DUMMY_HASH, CORS), mas com abordagem regex simples (`_has_pattern`). As diferenças específicas:

| Check | verify_security.py | benchmark/analyzer.py |
|-------|-------------------|-----------------------|
| CORS wildcard detection | AST walk + dynamic reflection regex | Regex simples `r"allow_origins.*\*"` |
| Pydantic str max_length | AST walk em ClassDef/AnnAssign com union type support | Não cobre |
| Raw SQL f-string | AST JoinedStr inspection | Não cobre |
| Exception detail exposure | AST HTTPException inspection | Não cobre |
| Secrets in code | 7 regex patterns com mascaramento | Não cobre |
| Debug mode | AST FastAPI(debug=True) + docs_url guard | Não cobre |

### D. Mapeia para spec novo?

**TOOL-029 `security_scan`** mapeia diretamente. O spec usa bandit + semgrep + pip-audit em vez de AST próprio, mas as categorias de problemas detectados (SEC-01..10) são exatamente o que o spec descreve como "FastAPI-specific risks". As regras custom semgrep de TOOL-029 (`"SQL injection via unparameterized raw queries, CORS wildcards, unauthenticated admin routes, JWT signed with none algorithm"`) são o equivalente das checks SEC-01/SEC-05 aqui.

### E. Recomendação: **PRESERVAR**

Os 10 checks SEC-01..10 com AST puro (sem dependências externas como bandit/semgrep) representam conhecimento de "o que checar" que deve ser portado para o custom semgrep ruleset de TOOL-029. Em particular: SEC-04 (Pydantic max_length), SEC-05 (raw SQL triple detection), SEC-08 (docs_url env guard), SEC-10 (exception exposure). São patterns que bandit e semgrep padrão não cobrem para FastAPI. Portar como as regras semgrep custom de TOOL-029.

---

## 3. `modules/security/tools/scaffold_security.py` (469 LOC)

### A. O que faz

Gera um stack completo de middleware de segurança em `security/`: 4-5 arquivos via templates string:

- `security/middleware.py`: `SecurityHeadersMiddleware` (7 headers + Cache-Control/Pragma) + `RequestSizeLimitMiddleware` (verifica Content-Length, retorna 413).
- `security/cors.py`: `configure_cors()` com `ALLOWED_ORIGINS` explícito, configuração completa de CORSMiddleware.
- `security/rate_limit.py`: `Limiter` com `strategy="moving-window"`, `default_limits=["200/minute"]`, Redis backend opcional, `_rate_limit_exceeded_handler` com `Retry-After`.
- `security/exceptions.py`: 3 handlers (`Exception`, `IntegrityError`, `RequestValidationError`) com `error_id = uuid.uuid4().hex[:8]` para correlação, sem vazar detalhes.
- `security/__init__.py`: Package marker.

Parâmetros: `with_rate_limit`, `with_csp`, `with_redis`, `cors_origins`, `max_body_bytes`.

Retorna `integration_hint` com a ordem correta de middleware: size limit → headers → CORS → rate limiting.

### B. Lógica única vs. glue

Maioria é templates de código. Elementos únicos:

- A order hint explícita: "RequestSizeLimitMiddleware first, then SecurityHeadersMiddleware, then CORS" — esta ordem importa e não está documentada nos generators.
- `security/exceptions.py` template com 3 handlers distintos (incluindo `IntegrityError → 409`, `RequestValidationError → 422` clean format).
- `_rate_limit_exceeded_handler` com `Retry-After` header explícito.
- `strategy="moving-window"` especificado explicitamente no limiter.

### C. Equivalente em `generators/`?

Sim, com sobreposição substancial:

| Componente | scaffold_security.py | generators/middleware/ |
|------------|---------------------|----------------------|
| SecurityHeadersMiddleware | `security/middleware.py` | `middleware/security_headers.py` |
| CORSMiddleware config | `security/cors.py` | `middleware/cors.py` → `middleware/cors_config.py` |
| Rate limiting | `security/rate_limit.py` | `generators/auth/rate_limit.py` |
| Exception handlers | `security/exceptions.py` | Não encontrado diretamente |

`generators/middleware/security_headers.py` expõe `generate_security_headers()` que gera `SecurityHeadersMiddleware` com os mesmos 7 headers. `generators/middleware/cors.py` expõe `generate_cors()`. Os generators geram individualmente; este arquivo gera o stack completo como unidade.

O `security/exceptions.py` template (3 handlers com error_id) não tem equivalente claro em `generators/`.

### D. Mapeia para spec novo?

Não mapeia para nenhum dos 51 specs de customização (TOOL-010..060). Os specs assumem que o projeto base já tem middleware de segurança (gerado pelos generators). Este arquivo é ferramenta do tier de geração base, não de customização.

### E. Recomendação: **ARQUIVAR**

A geração de middleware individual já está em `generators/middleware/`. O valor residual são: (1) o template `security/exceptions.py` com 3 handlers e `error_id` que não existe nos generators — esse trecho específico deve ser absorvido pelo `generators/middleware/stack.py`; (2) a `integration_hint` com a ordem correta de middleware. Arquivar como referência, extraindo os dois trechos únicos antes.

---

## 4. `modules/security/models.py` (73 LOC)

### A. O que faz

Define 4 Pydantic models especializados para resultados de análise de segurança:

- `SecurityHeader(BaseModel)`: `name`, `expected_value`, `actual_value`, `present: bool`, `correct: bool`, `description`.
- `SecurityHeadersReport(BaseModel)`: `url`, `headers: list[SecurityHeader]`, `headers_present: int`, `headers_total: int`, `score: float = Field(ge=0.0, le=1.0)`.
- `CORSTestResult(BaseModel)`: `origin_tested`, `allowed: bool`, `credentials_allowed: bool`, `reflected: bool`, `headers_returned: dict[str, str]`.
- `RateLimitTestResult(BaseModel)`: `endpoint`, `total_requests: int`, `rate_limited_at: int | None`, `status_code_distribution: dict[int, int]`, `has_retry_after: bool`.
- `PentestResult(BaseModel)`: `test_name`, `passed: bool`, `details: dict[str, Any]`, `recommendation: str | None`.

### B. Lógica única vs. glue

Sem lógica — apenas schema definitions. Os models são bem projetados (`score: float = Field(ge=0.0, le=1.0)`, campos opcionais corretos), mas não implementam nada computacional.

### C. Equivalente em `generators/`?

Não existe equivalente. O `core/models.py` (ao qual os outros arquivos importam) define `Finding` e `Severity`, mas não os models de resultado de pentest. Estes models não são usados internamente por `pentest_api.py` — aquele arquivo retorna `dict` diretamente, não instâncias desses models.

### D. Mapeia para spec novo?

Não mapeia diretamente para nenhum spec. Seriam úteis como tipos de retorno de TOOL-029.

### E. Recomendação: **DESCARTAR**

Os models não são usados pelos tools do mesmo módulo (pentest_api.py retorna dicts, não instâncias). São schemas "aspiracionais" da v2 que nunca foram integrados. Se TOOL-029 for implementado com output estruturado, novos schemas serão definidos com base na assinatura do spec (SARIF 2.1.0 output, não estes models). Descartar.

---

## 5. `modules/auth/tools/pentest_auth.py` (469 LOC)

### A. O que faz

Executa 4 testes de penetração ativos específicos para auth:

1. **`test_brute_force`**: 20 requests POST para `/auth/login` com credenciais inválidas, verifica se 429 aparece.
2. **`test_timing_attack`**: 10 amostras para dois emails ("admin@example.com" vs. "xyzzy-no-such-user-99@nonexistent.invalid"), compara mediana dos tempos de resposta. Threshold: 50ms. Usa `time.perf_counter()`, warm-up request, e `asyncio.sleep(0.1)` entre amostras para não acionar rate limiting.
3. **`test_token_reuse`**: Registra usuário de teste com timestamp no email, pega refresh_token, usa uma vez (deve suceder), usa segunda vez (deve retornar 401). Testa refresh token rotation real.
4. **`test_expired_token`**: Crafta JWT com `exp` 1 hora no passado usando `pyjwt` com dummy secret, envia para rota protegida. Verifica 401. Testa duas coisas: rejeição de exp E rejeição de signature inválida.

### B. Lógica única vs. glue

**LÓGICA ÚNICA de alta densidade:**

- `test_timing_attack`: A metodologia completa — warm-up para evitar cold start bias, 10 samples intercalados, `asyncio.sleep(0.1)` para não acionar rate limiting, uso de `statistics.median()` (não mean, mais robusto a outliers), threshold de 50ms com justificativa clara. Não é trivial.
- `test_token_reuse`: O fluxo multi-step (register → first refresh → second refresh) com email único por timestamp. Verifica rotation real, não apenas "refresh endpoint exists".
- `test_expired_token`: O insight de usar dummy secret — testa expiração E validação de signature simultaneamente (ambos devem retornar 401). Comentário documenta o raciocínio explicitamente.

### C. Equivalente em `generators/`?

Não existe em `generators/auth/`. O `benchmark/analyzer.py` cobre timing attack prevention de forma estática (procura `DUMMY_HASH` no código), mas não testa runtime behavior. São complementares.

### D. Mapeia para spec novo?

Parcialmente TOOL-011 (`add_oauth2_provider`) e TOOL-013 (`add_mfa`) mencionam token security, mas não definem ferramentas de teste. O `test_timing_attack` e `test_token_reuse` são mais relevantes para TOOL-029 como testes de validação pós-instalação. Nenhum spec cobre explicitamente um runtime auth pentest.

### E. Recomendação: **PRESERVAR**

A metodologia de `test_timing_attack` (warm-up + median + sleep entre samples + threshold 50ms) e a lógica de `test_token_reuse` (registro de usuário efêmero + dois usos do mesmo refresh token) são implementações não-triviais de conceitos de segurança que não existem em nenhum outro lugar na skill. Portar como componente de validação pós-deploy de TOOL-010/011/013 ou como tool de CI separado.

---

## 6. `modules/auth/tools/verify_auth.py` (582 LOC)

### A. O que faz

Análise estática via AST + regex para 8 anti-patterns de auth:

- **AUTH-01** (`_check_auth01_hardcoded_secret`): AST walk em `jwt.encode()` verificando se o segundo arg é string literal. Também regex para `SECRET_KEY = "..."` com allowlist de placeholders (`CHANGE-ME-IN-PRODUCTION`) e skip para `getenv`/`settings.` no mesmo line.
- **AUTH-02** (`_check_auth02_token_expiry`): AST walk em `ast.Assign` procurando nomes com "ACCESS"/"TOKEN_EXPIRE" e `timedelta()` com `minutes > 30`, `hours >= 1`, ou `days >= 1`.
- **AUTH-03** (`_check_auth03_refresh_rotation`): Verifica presença de `jti` no source quando há lógica de refresh tokens.
- **AUTH-04** (`_check_auth04_timing_attack`): Verifica presença de `DUMMY_HASH`, `hmac.compare_digest`, `secrets.compare_digest`, ou pattern `user is None.*verify` em regex dotall.
- **AUTH-05** (`_check_auth05_password_hashing`): Detecta weak algorithms (`md5`, `sha1`, `sha256`, `sha512`, `hashlib.*`) em linhas que também contêm "password". Verifica presença de safe algorithms (`argon2`, `bcrypt`, `scrypt`, `pwdlib`, `passlib`).
- **AUTH-06** (`_check_auth06_rate_limiting`): Detecta `/auth/login` route sem decorador de rate limiting.
- **AUTH-07** (`_check_auth07_logout`): Project-wide — verifica ausência de `/auth/logout`, `/auth/revoke`, `/auth/sign-out` quando JWT/OAuth presente.
- **AUTH-08** (`_check_auth08_password_maxlength`): Detecta `password.*Field()` sem `max_length=` e flags `max_length > 128`.

### B. Lógica única vs. glue

**LÓGICA ÚNICA:**

- AUTH-01: Allowlist de placeholders legítimos (`CHANGE-ME-IN-PRODUCTION`) + skip para patterns de env vars na mesma linha. Reduz falsos positivos em arquivos de config template.
- AUTH-02: AST walk com detecção de timedelta por nome de variável — distingue access token de refresh token pelo nome (`ACCESS`, `TOKEN_EXPIRE`, `ACCESS_EXPIRE`).
- AUTH-04: O pattern regex dotall `user\s*(is\s*None|==\s*None|not\s)).*verify` para detectar timing protection alternativa além de DUMMY_HASH.
- AUTH-05: Contextualização de weak hashing — só flagra se a linha com MD5/SHA também contém "password" (não flagra checksums de arquivo).
- AUTH-08: Verifica max_length > 128 como anti-pattern separado de ausência de max_length.

### C. Equivalente em `generators/`?

`benchmark/analyzer.py` cobre uma sobreposição significativa mas com menor granularidade:

| Check | verify_auth.py | benchmark/analyzer.py |
|-------|---------------|----------------------|
| Argon2id hashing | AUTH-05 (contexto password) | `uses_argon2 = _has_pattern(py_code, r"argon2\|Argon2")` |
| PyJWT vs python-jose | Não cobre | Sim — CVE-2024-33663 check |
| JWT algorithm whitelist | Não cobre | Sim — `algorithms=[...]` check |
| Timing attack (DUMMY_HASH) | AUTH-04 (+ alternatives) | Regex simples para DUMMY_HASH |
| Password constraints | AUTH-08 (max_length>128) | `min=8 AND max=128` check |
| Hardcoded JWT secret | AUTH-01 (AST + allowlist) | Não cobre |
| Token expiry check | AUTH-02 (AST timedelta) | Não cobre |
| Refresh rotation (jti) | AUTH-03 | Não cobre |
| Rate limiting on login | AUTH-06 | Não cobre |
| Logout endpoint | AUTH-07 | Não cobre |

As checks AUTH-01, AUTH-02, AUTH-03, AUTH-06, AUTH-07 são únicas e não existem no benchmark analyzer.

### D. Mapeia para spec novo?

**TOOL-029 `security_scan`** é o mapeamento direto. As checks AUTH-01..08 são exatamente o tipo de "FastAPI-specific risks" que o spec descreve para o custom semgrep ruleset. Em particular: AUTH-01 (hardcoded JWT secret), AUTH-04 (timing attack prevention), AUTH-05 (weak password hashing) são candidatos a regras semgrep custom.

### E. Recomendação: **PRESERVAR**

As 8 checks AUTH-01..08 complementam as 10 checks SEC-01..10 de `verify_security.py` e cobrem casos não presentes no `benchmark/analyzer.py`. A lógica de AUTH-01 (AST + allowlist de placeholders), AUTH-02 (timedelta via AST), e AUTH-05 (contexto de password) representa know-how de "como checar sem falsos positivos" que deve ser portado como regras semgrep custom de TOOL-029. As checks AUTH-06 e AUTH-07 podem ser testes de integração de TOOL-013/TOOL-012.

---

## 7. `modules/auth/tools/scaffold_auth.py` (448 LOC)

### A. O que faz

Gera um módulo de auth completo em `auth/` com 4 arquivos via templates string:

- `auth/security.py`: `PasswordHash.recommended()` + `DUMMY_HASH` + `configure_jwt()` + `create_token_pair()` + `verify_access_token()` + `verify_refresh_token()`. Access token: 15min. Refresh token: 7 dias com `jti = str(uuid.uuid4())`.
- `auth/schemas.py`: `LoginRequest(strict=True)`, `RegisterRequest(strict=True)` com `@field_validator("password")` verificando `COMMON_PASSWORDS` set de 10 senhas + digit + uppercase check. `TokenResponse`, `RefreshRequest`.
- `auth/dependencies.py`: Layered chain: `get_token_payload()` → `get_current_user()` → `require_admin()`. Type aliases `TokenPayload`, `CurrentUser`, `AdminUser` via `Annotated`.
- `auth/router.py`: `/auth/register`, `/auth/login` (com DUMMY_HASH para timing), `/auth/logout`, `/auth/refresh` (condicional). TODO comments para Redis blocklist de jti.

Parâmetros: `with_refresh=True`, `with_oauth2=False`.

### B. Lógica única vs. glue

Maioria são templates. Elementos únicos em relação aos generators:

- `auth/schemas.py` template: `COMMON_PASSWORDS` set (10 senhas comuns) + `@field_validator` verificando digit + uppercase — não existe nos generators.
- `auth/router.py` template: Login endpoint com DUMMY_HASH inline, comentários explicativos na lógica de timing attack.
- `configure_jwt(secret)` função para injeção de secret no startup (pattern não presente nos generators).
- TODO comments no refresh endpoint documentando o padrão Redis blocklist (jti → TTL) — valor educativo.

### C. Equivalente em `generators/`?

Sim, com sobreposição substancial:

| Componente | scaffold_auth.py | generators/auth/ |
|------------|-----------------|-----------------|
| JWT helpers | `auth/security.py` | `jwt.py` → `generate_jwt()` (sem refresh token rotation) |
| Password hashing | `auth/security.py` | `hasher.py` → `generate_password_hasher()` (com DUMMY_HASH) |
| Auth routes | `auth/router.py` | `routes.py` → `generate_auth_routes()` |
| Schemas | `auth/schemas.py` | `schemas.py` → `generate_auth_schemas()` |
| Dependencies | `auth/dependencies.py` | `deps.py` → `generate_auth_deps()` |

Diferença crítica: `generators/auth/jwt.py` gera um access token sem refresh token rotation (`create_access_token()` apenas). Este arquivo gera `create_token_pair()` com jti no refresh token — é mais completo em termos de segurança.

`generators/auth/schemas.py` não tem o `@field_validator` com COMMON_PASSWORDS check — essa validação está apenas aqui.

### D. Mapeia para spec novo?

O `with_oauth2=True` path (com TODO stubs para authlib) seria o ponto de entrada para TOOL-011 (`add_oauth2_provider`). O `with_refresh=True` com jti é mais próximo do que os generators geram hoje.

### E. Recomendação: **ARQUIVAR**

A estrutura base já existe em `generators/auth/`. O valor residual são: (1) o `COMMON_PASSWORDS` validator em `_schemas_py()` — deve ser absorvido por `generators/auth/schemas.py`; (2) o `create_token_pair()` com `jti` no refresh token — deve ser integrado em `generators/auth/jwt.py` como opção `with_refresh_rotation=True`; (3) o `configure_jwt(secret)` pattern. Arquivar como referência, extraindo esses 3 elementos antes.

---

## Sumário Executivo

| Arquivo | LOC | Veredicto | Razão |
|---------|-----|-----------|-------|
| `security/tools/pentest_api.py` | 919 | **PRESERVAR** | Pentest dinâmico único — SQLI payloads, CORS evil origins, disclosure probes. Não coberto pelos generators nem pelo benchmark analyzer. |
| `security/tools/verify_security.py` | 908 | **PRESERVAR** | 10 AST checks (SEC-01..10) com lógica de contexto que bandit/semgrep padrão não cobre para FastAPI. Fonte das regras custom semgrep de TOOL-029. |
| `security/tools/scaffold_security.py` | 469 | **ARQUIVAR** | Duplica `generators/middleware/`. Extrair antes: `security/exceptions.py` template (3 handlers + error_id) e middleware ordering hint. |
| `security/models.py` | 73 | **DESCARTAR** | Schemas não usados pelos tools do mesmo módulo (pentest_api.py retorna dicts). Nunca integrados. |
| `auth/tools/pentest_auth.py` | 469 | **PRESERVAR** | Timing attack test com metodologia rigorosa (median + warm-up + sleep), token_reuse flow multi-step, expired token com dummy secret. Não existe nos generators. |
| `auth/tools/verify_auth.py` | 582 | **PRESERVAR** | 8 AST/regex checks (AUTH-01..08) complementares ao benchmark/analyzer.py. Checks de hardcoded secret, timedelta expiry, jti, logout endpoint são únicos. |
| `auth/tools/scaffold_auth.py` | 448 | **ARQUIVAR** | Duplica `generators/auth/`. Extrair antes: COMMON_PASSWORDS validator, `create_token_pair()` com jti, `configure_jwt()` pattern. |

### Ações imediatas recomendadas

1. **pentest_api.py + pentest_auth.py**: Portar como runtime validation layer de TOOL-029 ou como tool standalone `fastapi_pentest_live`. A combinação dos dois cobre 10 testes ativos.

2. **verify_security.py + verify_auth.py**: Os 18 checks (SEC-01..10 + AUTH-01..08) são o conteúdo exato das regras semgrep custom de TOOL-029. Portar como `.security/semgrep-rules.yaml` ou como AST analyzer nativo integrado ao tool.

3. **scaffold_security.py**: Extrair `_exceptions_py()` para `generators/middleware/exceptions.py`. Extrair `integration_hint` ordering para documentação de `generators/middleware/stack.py`.

4. **scaffold_auth.py**: Extrair `COMMON_PASSWORDS` validator para `generators/auth/schemas.py`. Adicionar `with_refresh_rotation=True` flag em `generators/auth/jwt.py` usando o padrão `create_token_pair()` + `jti`.
