# Module: Security — Production API Security for FastAPI

> O LLM gera: CORSMiddleware com allow_origins=["*"] + nenhum security header + zero rate limiting.
> O staff engineer sabe: OWASP API Top 10, 3-layer rate limiting, sliding window com Redis, CSP para APIs, request body limits, API key hashing, dependency scanning, error sanitization.

---

## 1. Security Headers — Complete Set (Nao apenas X-Frame-Options)

### WHY
O LLM adiciona X-Frame-Options e para por ai. Uma API de producao precisa de 7+ headers: cada um bloqueia uma classe inteira de ataque. OWASP Secure Headers Project (2025) e o scan anual de 1M websites mostram que menos de 25% deployam CSP e 40% ainda nao tem X-Content-Type-Options. Cada header ausente e uma superficie de ataque aberta.

### HOW
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Previne MIME sniffing — browser nao reinterpreta Content-Type
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Clickjacking — impede embedding em iframe de outro dominio
        response.headers["X-Frame-Options"] = "DENY"

        # HSTS — forca HTTPS por 1 ano + inclui subdomains
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # CSP para APIs — default-src 'none' bloqueia tudo (API nao serve HTML)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )

        # Referrer — nao vaza URL completa em requests cross-origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy — desliga features de browser irrelevantes pra API
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )

        # X-XSS-Protection — legacy mas ainda util pra browsers antigos
        # Nota: CSP substitui isso em browsers modernos
        response.headers["X-XSS-Protection"] = "1; mode=block"

        return response
```

### GOTCHA
- `X-Content-Type-Options: nosniff` so tem um valor valido. Se esquecer, browsers podem interpretar JSON como HTML e executar scripts embutidos (MIME confusion attack).
- `HSTS preload` e IRREVERSIVEL — uma vez na preload list do Chrome, seu dominio NUNCA mais funciona sem HTTPS. So adicione `preload` quando tiver certeza que HTTPS esta 100% configurado em todos os subdomains.
- `Content-Security-Policy: default-src 'none'` e o mais restritivo possivel. Para APIs REST que nao servem HTML, e o correto. Se sua API serve paginas (docs Swagger), use `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'` para /docs e /redoc.
- `Permissions-Policy` substituiu `Feature-Policy` em 2021. Se voce ainda usa Feature-Policy, browsers modernos ignoram.

---

## 2. CORS Hardening — Quando allow_credentials + Wildcard Falha

### WHY
Em 2025, uma analise de 100.000+ aplicacoes web encontrou que 35% tinham pelo menos uma misconfiguracao CORS exploravel. O ataque classico: servidor reflete o Origin do request no `Access-Control-Allow-Origin` com `Access-Control-Allow-Credentials: true`. Isso e funcionalmente equivalente a wildcard com credentials — qualquer site malicioso rouba cookies e tokens.

### HOW
```python
from fastapi.middleware.cors import CORSMiddleware

# CORRETO: lista explicita de origens permitidas
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://myapp.com",
        "https://staging.myapp.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
    max_age=600,  # Cache preflight por 10min (reduz latencia)
)

# ERRADO — NUNCA faca isso:
# allow_origins=["*"], allow_credentials=True
# O browser bloqueia, mas o servidor pode ter logic bugs que bypassam.

# ERRADO — Dynamic origin reflection:
# origin = request.headers.get("origin")
# response.headers["Access-Control-Allow-Origin"] = origin  # REFLECTION ATTACK
```

### GOTCHA
- `allow_origins=["*"]` com `allow_credentials=True` faz o browser REJEITAR o response. Mas muitos devs "consertam" isso refletindo o Origin — o que e PIOR porque agora funciona E e inseguro.
- `expose_headers` controla quais headers o JS do browser pode LER da response. Sem isso, so headers CORS-safelisted sao visiveis. Se sua API retorna `X-Request-ID` para troubleshooting, precisa listar aqui.
- `max_age=600` reduz preflight requests (OPTIONS) fazendo cache por 10 minutos. Chrome limita a 2 horas; Firefox a 24 horas. Nao coloque `max_age=86400` pensando que vai funcionar — o browser ignora valores acima do limite.
- Em desenvolvimento local, use `allow_origins=["http://localhost:3000"]` — NUNCA `*`. Isso evita que o padrao de dev vaze para producao via copy-paste.
- `allow_methods` deve listar APENAS os metodos que sua API usa. Se nao tem DELETE, nao liste DELETE.

---

## 3. Rate Limiting — 3 Camadas com Sliding Window (Redis)

### WHY
OWASP API Security Top 10 2023: #4 "Unrestricted Resource Consumption" — APIs sem rate limiting sao vulneraveis a brute force, credential stuffing, e DDoS de camada 7. Rate limiting precisa de 3 camadas: global (protege o servidor), per-IP (bloqueia atacantes individuais), per-user (previne abuso de contas comprometidas). Sliding window e o melhor algoritmo para APIs: mais preciso que fixed window (sem burst na fronteira), mais eficiente que token bucket para a maioria dos casos.

### HOW
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

# Camada 1: Global rate limiter com Redis backend
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],  # Global: 200 req/min por IP
    storage_uri="redis://localhost:6379/0",
    strategy="moving-window",  # Sliding window — sem burst na fronteira
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Handler customizado para 429
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": str(exc.detail)},  # Informa quando pode tentar
    )

# Camada 2: Per-endpoint com limites especificos
@app.post("/auth/login")
@limiter.limit("5/minute")  # Login: 5/min por IP (brute force)
async def login(request: Request, body: LoginRequest):
    ...

@app.post("/auth/register")
@limiter.limit("3/minute")  # Register: 3/min por IP
async def register(request: Request, body: RegisterRequest):
    ...

@app.get("/api/search")
@limiter.limit("30/minute")  # Search: 30/min por IP (caro)
async def search(request: Request, q: str):
    ...

# Camada 3: Per-user (apos autenticacao)
def get_user_key(request: Request) -> str:
    """Extrai user ID do token para rate limit per-user."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = verify_access_token(auth[7:])
            return f"user:{payload['sub']}"
        except Exception:
            pass
    return get_remote_address(request)

user_limiter = Limiter(
    key_func=get_user_key,
    storage_uri="redis://localhost:6379/0",
    strategy="moving-window",
)
```

### GOTCHA
- `strategy="moving-window"` usa sorted sets no Redis (ZRANGEBYSCORE) — mais preciso que fixed window mas consome um pouco mais de memoria. Para APIs com milhoes de requests, considere `fixed-window-elastic-expiry` como compromisso.
- Rate limiting por IP NAO funciona atras de proxy/load balancer. Todos os requests vem do IP do proxy. Configure `X-Forwarded-For` trust: `limiter = Limiter(key_func=get_remote_address)` le `X-Forwarded-For` por padrao no SlowAPI, MAS voce precisa garantir que o proxy/LB e confiavel (senao atacante forja o header).
- SEMPRE retorne `Retry-After` no 429. Sem ele, clientes bem-comportados nao sabem quando podem tentar de novo e ficam fazendo polling agressivo — piorando o problema.
- Rate limiting em memoria (sem Redis) NAO funciona com multiplas instancias (Kubernetes, Gunicorn workers). Cada worker tem seu proprio contador. Use Redis SEMPRE em producao.

---

## 4. Input Validation — max_length em TODOS os Campos String

### WHY
O LLM gera `name: str` sem restricao. Um atacante envia um campo `name` com 10MB de dados. Resultado: memoria esgotada, logs gigantes, DB storage abuse, e possivelmente DoS. Pydantic v2 com `strict=True` rejeita type coercion (ex: int "123" vira string). Cada campo string DEVE ter max_length.

### HOW
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

class CreateItemRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=5000)
    email: str = Field(min_length=5, max_length=254)  # RFC 5321
    slug: str = Field(max_length=100, pattern=r"^[a-z0-9-]+$")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            if len(tag) > 50:
                raise ValueError(f"Tag too long: {len(tag)} chars (max 50)")
            if not re.match(r"^[a-z0-9_-]+$", tag):
                raise ValueError(f"Tag contains invalid characters: {tag}")
        return v

class SearchQuery(BaseModel):
    model_config = ConfigDict(strict=True)

    q: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1, le=10000)
    per_page: int = Field(default=20, ge=1, le=100)

class PaginationParams(BaseModel):
    model_config = ConfigDict(strict=True)

    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=20, ge=1, le=100)
```

### GOTCHA
- `max_length` em listas (`list[str]`) limita o NUMERO de elementos, nao o tamanho de cada string. Voce precisa de `field_validator` para limitar o tamanho de cada item.
- `strict=True` no ConfigDict impede type coercion: `{"age": "25"}` causa erro ao inves de converter "25" para 25. Isso previne bugs sutis E ataques de type confusion.
- `pattern` no Field usa regex no Python (nao JS regex). Anchore com `^...$` ou Pydantic so verifica se o pattern aparece EM ALGUM LUGAR da string.
- NUNCA use `str` sem `max_length` em qualquer campo que aceita input do usuario. A unica excecao e campos computados internamente.
- `per_page: int = Field(default=20, ge=1, le=100)` — sem `le=100`, um atacante pede `per_page=999999` e causa OOM no SELECT.

---

## 5. SQL Injection Prevention — Parametrized Queries SEMPRE

### WHY
Em 2026, benchmarks mostram que queries parametrizadas via SQLAlchemy mitigam 99.9% dos payloads SQLi (testado com SQLMap 2.0). O ORM previne por padrao, mas o momento que voce usa `text()` ou f-strings com SQL, a protecao desaparece. Um unico endpoint vulneravel = acesso total ao database.

### HOW
```python
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

# CORRETO — ORM (protegido automaticamente)
async def get_user(session: AsyncSession, email: str):
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

# CORRETO — text() com bind parameters
async def search_items(session: AsyncSession, query: str, limit: int):
    stmt = text("""
        SELECT id, name, description
        FROM items
        WHERE name ILIKE :pattern
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    result = await session.execute(
        stmt,
        {"pattern": f"%{query}%", "limit": limit},
    )
    return result.mappings().all()

# ERRADO — f-string com SQL (VULNERAVEL)
# stmt = text(f"SELECT * FROM users WHERE email = '{email}'")

# ERRADO — concatenacao de string
# query = "SELECT * FROM items WHERE name LIKE '%" + search + "%'"

# ERRADO — format()
# stmt = text("SELECT * FROM users WHERE id = {}".format(user_id))
```

### GOTCHA
- `text()` SEM parametros e seguro sintaticamente mas PERIGOSO semanticamente. Se voce escreve `text("SELECT 1")` e OK, mas `text(f"SELECT * FROM {table}")` e catastrofico porque `table` pode ser `users; DROP TABLE users;--`.
- Mesmo com ORM, cuidado com `column()` e `literal_column()` — eles inserem valores RAW no SQL. Use so com constantes, NUNCA com input do usuario.
- `ILIKE :pattern` e seguro, mas ILIKE com wildcards excessivos (`%a%b%c%d%e%`) pode causar DoS por regex backtracking no Postgres. Limite o numero de wildcards no input validation.
- Stored procedures NAO protegem contra SQLi se usam SQL dinamico internamente. A protecao vem dos bind parameters, nao do mecanismo de execucao.

---

## 6. Request Body Size Limiting — Prevenindo Memory Exhaustion

### WHY
FastAPI le o body inteiro em memoria por padrao. Sem limite, um atacante envia 1GB de JSON e causa OOM crash. O default do ASGI e ~2MB, mas isso depende do servidor (Uvicorn nao tem limite embutido). Voce DEVE adicionar um middleware explicito.

### HOW
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejeita requests com body maior que max_bytes."""

    def __init__(self, app, max_bytes: int = 1_048_576):  # 1MB default
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Max: {self.max_bytes} bytes."},
            )
        return await call_next(request)

# Adicionar ANTES de outros middlewares
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=1_048_576)  # 1MB

# Para endpoints de upload, use limite especifico:
from fastapi import UploadFile, File

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if file.size and file.size > 10_485_760:  # 10MB
        raise HTTPException(413, "File too large. Max 10MB.")
    contents = await file.read()
    ...
```

### GOTCHA
- `Content-Length` pode ser omitido (chunked transfer encoding). O middleware acima so checa se o header existe. Para protecao completa, leia o body em chunks e aborte se exceder o limite.
- Uvicorn tem `--limit-max-header-size` (default 8KB) mas NAO tem limite de body. Nginx na frente com `client_max_body_size 1m;` e a protecao mais robusta.
- `UploadFile.size` pode ser `None` em requests chunked. Sempre leia em chunks de 64KB e conte os bytes manualmente para protecao real.
- Se usar streaming (`request.stream()`), voce precisa contar bytes no loop. O middleware de body size nao se aplica a streaming requests.

---

## 7. File Upload Security — Content-Type + Size + Virus Scanning

### WHY
Upload sem validacao e vetor para: web shells (upload de .php/.py), XXE (SVG/XML malicioso), zip bombs (1KB -> 1TB descomprimido), e malware. Validar Content-Type pelo header e INSUFICIENTE — o atacante controla o header. Validar pelo magic bytes (file signature).

### HOW
```python
import magic  # python-magic

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
}
MAX_FILE_SIZE = 10_485_760  # 10MB

async def validate_upload(file: UploadFile) -> bytes:
    """Valida tipo real do arquivo e tamanho."""
    # 1. Ler primeiros bytes para magic number detection
    header = await file.read(2048)
    await file.seek(0)

    mime = magic.from_buffer(header, mime=True)
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            400,
            f"File type '{mime}' not allowed. Accepted: {', '.join(ALLOWED_MIME_TYPES)}",
        )

    # 2. Ler arquivo completo contando bytes
    chunks = [header]
    total = len(header)
    while chunk := await file.read(65536):
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise HTTPException(413, f"File too large. Max {MAX_FILE_SIZE} bytes.")
        chunks.append(chunk)

    return b"".join(chunks)

# 3. Opcional: scan com ClamAV via clamd
# import clamd
# cd = clamd.ClamdUnixSocket()
# result = cd.instream(io.BytesIO(content))
# if result["stream"][0] == "FOUND":
#     raise HTTPException(400, f"Malware detected: {result['stream'][1]}")
```

### GOTCHA
- O header `Content-Type` do upload e controlado pelo cliente. NUNCA confie nele para decisoes de seguranca. Use `python-magic` (libmagic) para detectar o tipo real.
- Zip bombs: um arquivo de 42KB pode expandir para 4.5 PB. Se voce descomprime uploads, limite o tamanho DESCOMPRIMIDO, nao so o comprimido.
- SVG e XML — ambos podem conter `<script>` e XXE. Se aceita SVG, sanitize com bibliotecas como `defusedxml`. Melhor ainda: converta SVG para PNG no servidor.
- Salve arquivos FORA do diretorio web (nunca em `static/`). Use UUIDs como nomes para prevenir path traversal: `f"uploads/{uuid4()}.{ext}"`.

---

## 8. API Key Management — Hash + Scope + Rotation

### WHY
API keys armazenadas em plaintext no banco sao roubadas em qualquer SQL injection ou backup vazado. Em 2025, organizacoes lideres adotam: hash com SHA-256 (como passwords), prefixo para identificacao rapida (ex: `sk_live_`), scoping por permissao, e rotacao automatica a cada 90 dias. A key completa so e mostrada UMA VEZ na criacao.

### HOW
```python
import hashlib
import secrets

PREFIX = "sk_live_"
KEY_LENGTH = 48  # 384 bits de entropia

def generate_api_key() -> tuple[str, str]:
    """Gera API key. Retorna (key_plaintext, key_hash).

    A key plaintext e mostrada ao usuario UMA VEZ.
    Apenas o hash e armazenado no banco.
    """
    raw = secrets.token_urlsafe(KEY_LENGTH)
    key = f"{PREFIX}{raw}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key, key_hash

def verify_api_key(provided_key: str, stored_hash: str) -> bool:
    """Verifica API key contra hash armazenado."""
    computed_hash = hashlib.sha256(provided_key.encode()).hexdigest()
    return secrets.compare_digest(computed_hash, stored_hash)

# Schema do banco
# CREATE TABLE api_keys (
#     id UUID PRIMARY KEY,
#     user_id UUID REFERENCES users(id),
#     key_hash VARCHAR(64) UNIQUE NOT NULL,
#     key_prefix VARCHAR(12) NOT NULL,      -- "sk_live_abc..." pra identificacao
#     name VARCHAR(100) NOT NULL,           -- "Production API Key"
#     scopes TEXT[] NOT NULL DEFAULT '{}',  -- ["read:items", "write:items"]
#     expires_at TIMESTAMPTZ,
#     last_used_at TIMESTAMPTZ,
#     created_at TIMESTAMPTZ DEFAULT now(),
#     revoked_at TIMESTAMPTZ               -- soft delete
# );

# Dependency para rotas
from fastapi import Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key_dep(
    key: str = Security(api_key_header),
    session: AsyncSession = Depends(get_session),
) -> dict:
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    result = await session.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.revoked_at.is_(None),
            (APIKey.expires_at.is_(None) | (APIKey.expires_at > func.now())),
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(401, "Invalid or expired API key")
    return {"user_id": api_key.user_id, "scopes": api_key.scopes}
```

### GOTCHA
- Use `SHA-256` para API keys, NAO bcrypt/argon2. API keys sao de alta entropia (384+ bits), entao brute force e inviavel. Bcrypt adiciona latencia desnecessaria (300ms por verificacao em vez de <1ms).
- `secrets.compare_digest()` previne timing attacks na comparacao de hashes. Sem isso, um atacante pode deduzir o hash byte a byte medindo tempo de resposta.
- `key_prefix` armazenado em plaintext permite que o usuario identifique qual key e qual no dashboard, sem expor a key completa.
- Grace period na rotacao: ao rotacionar, mantenha a key antiga ativa por 24-48h para permitir que sistemas dependentes atualizem. Implemente isso com `expires_at` no banco.

---

## 9. Dependency Vulnerability Scanning — pip-audit + Safety

### WHY
Dependencias desatualizadas sao o vetor #1 de ataques em supply chain (OWASP #6 2023: Vulnerable and Outdated Components). `pip-audit` (mantido pelo PyPA) checa contra o Advisory Database do Python. `safety` (Safety CLI) checa contra banco de dados comercial. Ambos devem rodar no CI/CD.

### HOW
```bash
# pip-audit — oficial do PyPA, checa contra OSV
pip install pip-audit
pip-audit --strict --desc on

# safety — banco de dados comercial (requer API key gratis)
pip install safety
safety check --full-report

# No CI (GitHub Actions)
# .github/workflows/security.yml
# - name: Audit dependencies
#   run: |
#     pip install pip-audit
#     pip-audit --strict --desc on
#   continue-on-error: false  # Falha o pipeline se tiver CVE

# Snyk (alternativa SaaS com mais features)
# snyk test --file=requirements.txt
```

```python
# Verificacao programatica
import subprocess
import json

def audit_dependencies() -> dict:
    """Roda pip-audit e retorna resultados estruturados."""
    result = subprocess.run(
        ["pip-audit", "--format", "json", "--desc", "on"],
        capture_output=True, text=True,
    )
    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError:
        findings = {"error": result.stderr}
    return {
        "exit_code": result.returncode,
        "vulnerable_packages": findings,
        "passed": result.returncode == 0,
    }
```

### GOTCHA
- `pip-audit` pode dar falso negativo se seu `requirements.txt` usa ranges (`>=1.0`). Sempre rode contra o ambiente instalado (`pip-audit` sem `--requirement`), nao contra o arquivo.
- `safety` free tier tem delay de 30 dias nos advisories. Para seguranca real-time, use a versao paga ou combine com `pip-audit`.
- Dependencias transitivas (deps das deps) tambem tem CVEs. `pip-audit` checa TODAS as instaladas, nao so as diretas.
- Pin suas versoes com `pip freeze > requirements.lock` e rode audit contra o lockfile. Sem pinning, `pip install` pode trazer versao nova com CVE.

---

## 10. Secret Management — Nunca no Codigo, Nunca em .env Commitado

### WHY
Secrets em codigo fonte sao o erro #1 de seguranca. GitHub escaneia repositorios publicos e encontra milhares de API keys por dia. `.env` no `.gitignore` e o minimo, mas nao e suficiente — qualquer dev com acesso ao servidor ve o arquivo. Producao precisa de vault (HashiCorp Vault, AWS Secrets Manager, ou 1Password CLI).

### HOW
```python
# 1. Desenvolvimento — .env com pydantic-settings
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    redis_url: str = "redis://localhost:6379/0"
    api_key_salt: str

settings = Settings()  # Le de .env ou environment variables

# 2. Producao — nunca .env no filesystem
# Use environment variables injetadas pelo orchestrador:
# - Kubernetes: Secrets + envFrom
# - Docker: --env-file (nao commitado) ou secrets
# - AWS: Secrets Manager + SDK
# - Fly.io: fly secrets set JWT_SECRET=xxx

# 3. Validacao no startup — falhar RAPIDO se secret falta
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validar TODOS os secrets obrigatorios no boot
    required = ["database_url", "jwt_secret"]
    missing = [s for s in required if not getattr(settings, s, None)]
    if missing:
        raise RuntimeError(f"Missing required secrets: {missing}")
    yield
```

### GOTCHA
- `.env` no `.gitignore` nao apaga o historico do git. Se `.env` ja foi commitado uma vez, as secrets estao no historico PARA SEMPRE. Use `git filter-branch` ou `BFG Repo-Cleaner` para limpar, E rotacione TODAS as keys.
- `pydantic-settings` le environment variables COM PRIORIDADE sobre `.env`. Isso e intencional — permite override em producao sem modificar arquivos.
- Nunca use `os.getenv("SECRET", "default_secret")` — o default e um vetor de ataque. Se o secret nao esta setado, o app DEVE falhar no boot.
- Logs automaticos (FastAPI, SQLAlchemy) podem vazar secrets em connection strings. Configure `echo=False` no SQLAlchemy engine e filtre `DATABASE_URL` dos logs.

---

## 11. TLS/HTTPS Enforcement — HSTS Preload + HTTP Redirect

### WHY
Sem HTTPS enforcement, ataques de SSL stripping interceptam o primeiro request HTTP e fazem downgrade. HSTS resolve isso: depois do primeiro acesso HTTPS, o browser RECUSA conexoes HTTP por 1 ano. HSTS Preload vai alem: o browser ja sabe que seu dominio e HTTPS-only ANTES do primeiro acesso (hardcoded na lista do Chrome/Firefox/Safari).

### HOW
```python
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

# 1. Redirect HTTP -> HTTPS (em producao)
if settings.environment == "production":
    app.add_middleware(HTTPSRedirectMiddleware)

# 2. HSTS header (ja incluido no SecurityHeadersMiddleware)
# Strict-Transport-Security: max-age=31536000; includeSubDomains; preload

# 3. Submeter para HSTS Preload List:
# https://hstspreload.org
# Requisitos:
# - max-age >= 31536000 (1 ano)
# - includeSubDomains presente
# - preload presente
# - Servir HSTS em TODOS os subdomains
# - Redirect HTTP -> HTTPS no dominio raiz

# 4. Uvicorn com SSL direto (dev/staging)
# uvicorn main:app --ssl-keyfile=key.pem --ssl-certfile=cert.pem

# 5. Producao: terminar TLS no reverse proxy (Nginx, Caddy, CloudFlare)
# Nginx:
# server {
#     listen 443 ssl http2;
#     ssl_certificate /etc/ssl/certs/myapp.pem;
#     ssl_certificate_key /etc/ssl/private/myapp.key;
#     ssl_protocols TLSv1.3 TLSv1.2;
#     ssl_prefer_server_ciphers on;
# }
```

### GOTCHA
- `HTTPSRedirectMiddleware` em desenvolvimento vai quebrar tudo (voce nao tem certificado). Use `if settings.environment == "production"`.
- HSTS `preload` e IRREVERSIVEL por meses. Se voce adicionar e depois precisar servir HTTP (por qualquer motivo), seu site fica inacessivel ate ser removido da lista — processo que leva semanas.
- Em Kubernetes com ingress, o TLS termina no ingress controller, nao no pod. O pod ve HTTP. Nao adicione `HTTPSRedirectMiddleware` nesse caso — o ingress ja faz o redirect.
- `TLSv1.0` e `TLSv1.1` foram oficialmente deprecados em 2021 (RFC 8996). Configure `TLSv1.2` como minimo. `TLSv1.3` e preferivel (mais rapido e seguro).

---

## 12. Error Message Sanitization — Nunca Expor Stack Traces

### WHY
O LLM gera `except Exception as e: raise HTTPException(500, detail=str(e))`. Isso vaza: nomes de tabelas do banco, paths internos do servidor, versoes de bibliotecas, e stack traces completos. Um atacante usa essas informacoes para direcionar ataques (ex: saber que voce usa PostgreSQL 14.2 com CVE especifica).

### HOW
```python
import logging
import uuid

logger = logging.getLogger(__name__)

# 1. Exception handler global — NUNCA retorna detalhes internos
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = str(uuid.uuid4())[:8]
    logger.error(
        "Unhandled exception [%s]: %s",
        error_id, str(exc),
        exc_info=True,  # Stack trace vai pro LOG, nao pro cliente
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error_id": error_id,  # Pra correlacao em suporte
        },
    )

# 2. Erros de DB — NUNCA expor
from sqlalchemy.exc import IntegrityError, OperationalError

@app.exception_handler(IntegrityError)
async def db_integrity_handler(request: Request, exc: IntegrityError):
    error_id = str(uuid.uuid4())[:8]
    logger.error("DB integrity error [%s]: %s", error_id, str(exc))
    # Mensagem generica — nao revela nome da constraint ou tabela
    return JSONResponse(
        status_code=409,
        content={"detail": "Resource conflict", "error_id": error_id},
    )

# 3. Validation errors — Pydantic ja formata bem, mas filtrar paths
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    # Pydantic errors sao seguros para retornar (input do usuario)
    # Mas filtre qualquer path interno
    errors = []
    for err in exc.errors():
        clean = {
            "field": " -> ".join(str(l) for l in err.get("loc", [])),
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        }
        errors.append(clean)
    return JSONResponse(status_code=422, content={"detail": errors})

# ERRADO — NUNCA faca:
# raise HTTPException(500, detail=str(e))           # Vaza stack trace
# raise HTTPException(500, detail=repr(exc))         # Vaza class + args
# return {"error": traceback.format_exc()}           # Vaza TUDO
```

### GOTCHA
- `str(e)` em `IntegrityError` do SQLAlchemy inclui o SQL statement completo, com nomes de tabelas e colunas. NUNCA retorne isso ao cliente.
- Em desenvolvimento, voce QUER ver os erros. Use `if settings.debug: detail = str(exc)` para ter detalhes em dev sem vazar em producao.
- `error_id` com UUID curto (8 chars) e suficiente para correlacao. O usuario reporta "error abc12345", voce busca nos logs. Sem isso, o suporte e impossivel.
- FastAPI em modo debug (`debug=True`) retorna stack traces automaticamente. NUNCA use `debug=True` em producao.
- Validation errors do Pydantic sao SEGUROS para retornar (contem input do usuario, nao internals). Mas FILTRE o campo `ctx` que pode conter detalhes internos em validators customizados.

---

## 13. Debug Mode Detection — Nunca em Producao

### WHY
FastAPI com `debug=True` retorna stack traces completos ao cliente, exibe o debugger interativo, e pode executar codigo arbitrario via debugger. Uvicorn com `--reload` recarrega modulos a cada mudanca — overhead de performance e vetor de code injection se o atacante consegue escrever um .py no diretorio do projeto.

### HOW
```python
import os

# CORRETO — ler de environment
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

app = FastAPI(
    debug=DEBUG and ENVIRONMENT != "production",  # NUNCA debug em prod
    docs_url="/docs" if ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if ENVIRONMENT != "production" else None,
)

# Startup check
@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENVIRONMENT == "production":
        assert not app.debug, "FATAL: debug=True in production!"
        assert app.docs_url is None, "FATAL: docs exposed in production!"
    yield
```

### GOTCHA
- `docs_url=None` desabilita o Swagger UI em producao. Isso previne reconhecimento de API por atacantes. Se precisa de docs em producao, proteja com autenticacao.
- `--reload` do Uvicorn monitora o filesystem. Se um atacante consegue fazer upload de um `.py` no working directory, o Uvicorn carrega automaticamente. NUNCA use `--reload` em producao.
- Letta, Django, e Flask tambem tem modos de debug. Audite TODOS os frameworks no seu stack.
