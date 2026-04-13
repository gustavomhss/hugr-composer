# Module: Auth — Production Authentication for FastAPI

> O LLM gera: OAuth2PasswordBearer + JWT com secret hardcoded + bcrypt + token sem refresh.
> O staff engineer sabe: timing attacks, refresh rotation, argon2id, PKCE, token revocation.

---

## 1. Password Hashing — Argon2id (não bcrypt)

### WHY
bcrypt tem limite de 72 bytes no input (trunca senhas longas silenciosamente). Argon2id é o vencedor do Password Hashing Competition, recomendado pelo OWASP desde 2023, e resistente a GPU/ASIC attacks. FastAPI oficial agora recomenda `pwdlib[argon2]` ao invés de `passlib[bcrypt]`.

### HOW
```python
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()

# Hash na criação do user
hashed = password_hash.hash("user_password")

# Verificação no login
is_valid = password_hash.verify("user_password", hashed)

# DUMMY_HASH para timing attack prevention (ver técnica 3)
DUMMY_HASH = password_hash.hash("dummy-password-for-timing")
```

### GOTCHA
`PasswordHash.recommended()` usa argon2id com parâmetros OWASP (m=65536, t=3, p=4). Se precisar customizar: `PasswordHash((Argon2Hasher(memory_cost=65536, time_cost=3, parallelism=4),))`. Não reduza esses valores — são o mínimo seguro.

---

## 2. JWT Token Lifecycle

### WHY
O LLM gera access token com 24h de validade e nenhum refresh token. Em produção: access token curto (15-30min) + refresh token com rotation. Se um access token vaza, o atacante tem no máximo 30min de janela. Refresh rotation garante que um refresh token roubado é detectado no próximo uso legítimo.

### HOW
```python
from datetime import datetime, timedelta, timezone
import jwt

SECRET_KEY = settings.jwt_secret  # NUNCA hardcoded
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = timedelta(minutes=15)
REFRESH_TOKEN_EXPIRE = timedelta(days=7)

def create_token_pair(user_id: str) -> dict:
    """Cria par access + refresh. Sempre retorna ambos."""
    now = datetime.now(timezone.utc)
    
    access = jwt.encode(
        {"sub": user_id, "type": "access", "exp": now + ACCESS_TOKEN_EXPIRE},
        SECRET_KEY, algorithm=ALGORITHM,
    )
    refresh = jwt.encode(
        {"sub": user_id, "type": "refresh", "exp": now + REFRESH_TOKEN_EXPIRE,
         "jti": str(uuid.uuid4())},  # ID único pra revogação
        SECRET_KEY, algorithm=ALGORITHM,
    )
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}

def verify_access_token(token: str) -> dict:
    """Verifica access token. Rejeita refresh tokens usados como access."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload

def verify_refresh_token(token: str) -> dict:
    """Verifica refresh token. Checa se não foi revogado."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Not a refresh token")
    # TODO: checar jti contra blocklist (Redis/DB)
    return payload
```

### GOTCHA
SEMPRE use `datetime.now(timezone.utc)` — nunca `datetime.utcnow()` (deprecated no Python 3.12). E separe access/refresh com campo `type` no payload pra evitar que refresh token seja usado como access.

---

## 3. Timing Attack Prevention no Login

### WHY
Se o login retorna rápido quando o email não existe e lento quando a senha é errada, um atacante descobre quais emails estão cadastrados. Solução: SEMPRE rodar a verificação de hash, mesmo quando o user não existe.

### HOW
```python
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("dummy-timing-prevention")

async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if user is None:
        # User não existe — roda hash contra dummy pra manter timing constante
        password_hash.verify(password, DUMMY_HASH)
        return None
    
    if not password_hash.verify(password, user.password_hash):
        return None
    
    return user
```

### GOTCHA
O DUMMY_HASH precisa ser gerado com o MESMO algoritmo usado pros users reais. Se trocar de bcrypt pra argon2id, o dummy precisa ser argon2id também, senão o timing muda.

---

## 4. Refresh Token Rotation

### WHY
Se um refresh token é roubado e usado pelo atacante, o dono legítimo vai tentar usar o mesmo refresh token — que já foi rotacionado. Essa colisão detecta o roubo e revoga toda a família de tokens.

### HOW
```python
import uuid

async def refresh_tokens(session: AsyncSession, refresh_token: str) -> dict:
    """Roda refresh com rotation. Detecta roubo por token family."""
    payload = verify_refresh_token(refresh_token)
    jti = payload["jti"]
    user_id = payload["sub"]
    
    # Checar se jti já foi usado (detecta roubo)
    if await is_token_revoked(session, jti):
        # Token já usado! Possível roubo. Revogar TODA a família.
        await revoke_all_user_tokens(session, user_id)
        raise HTTPException(status_code=401, detail="Token reuse detected — all sessions revoked")
    
    # Revogar o refresh token atual
    await revoke_token(session, jti)
    
    # Gerar novo par
    return create_token_pair(user_id)

async def is_token_revoked(session: AsyncSession, jti: str) -> bool:
    """Checa blocklist. Use Redis pra performance."""
    # Redis: EXISTS revoked:{jti}
    # DB: SELECT 1 FROM revoked_tokens WHERE jti = :jti
    ...

async def revoke_token(session: AsyncSession, jti: str) -> None:
    """Adiciona token à blocklist com TTL = refresh expiry."""
    # Redis: SET revoked:{jti} 1 EX 604800  (7 dias = refresh TTL)
    ...
```

### GOTCHA
A blocklist de tokens revogados DEVE ter TTL igual ao tempo de expiração do refresh token. Senão a blocklist cresce infinitamente. Redis com `EX` é a melhor opção.

---

## 5. FastAPI Auth Dependency Chain

### WHY
O LLM coloca tudo numa função `get_current_user` de 30 linhas. O staff engineer separa em camadas composáveis: token extraction → token validation → user lookup → permission check. Cada camada é substituível em testes.

### HOW
```python
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_token_payload(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> dict:
    """Layer 1: Extract and validate JWT. No DB access."""
    try:
        return verify_access_token(token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(
    payload: Annotated[dict, Depends(get_token_payload)],
    session: SessionDep,
) -> User:
    """Layer 2: Load user from DB. Raises 401 if not found."""
    result = await session.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")
    return user

async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Layer 3: Permission check. Raises 403 if not admin."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return user

# Type aliases pra rotas
TokenPayload = Annotated[dict, Depends(get_token_payload)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]

# Uso nas rotas
@app.get("/users/me")
async def get_me(user: CurrentUser):
    return user

@app.delete("/users/{id}")
async def delete_user(user_id: int, admin: AdminUser):
    ...
```

### GOTCHA
`OAuth2PasswordBearer(tokenUrl=...)` não valida nada — só extrai o token do header. Toda validação é responsabilidade sua no dependency chain. E o `tokenUrl` é usado só pra docs (Swagger UI), não pra routing.

---

## 6. Rate Limiting em Auth Endpoints

### WHY
Login é o endpoint mais atacado. Sem rate limiting, um bot testa 10.000 senhas por minuto. Rate limit por IP + por email + global. Usar `429 Too Many Requests` com `Retry-After` header.

### HOW
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/auth/login")
@limiter.limit("5/minute")  # 5 tentativas por IP por minuto
async def login(request: Request, body: LoginRequest, session: SessionDep):
    user = await authenticate_user(session, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return create_token_pair(str(user.id))

@app.post("/auth/register")
@limiter.limit("3/minute")  # 3 registros por IP por minuto
async def register(request: Request, body: RegisterRequest, session: SessionDep):
    ...
```

### GOTCHA
Rate limiting por IP não funciona atrás de proxy/load balancer (todos os requests vêm do mesmo IP). Configure `X-Forwarded-For` trust ou use `X-Real-IP`. Em FastAPI: `app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])` e configure o limiter pra ler o header correto.

---

## 7. Logout e Token Revocation

### WHY
O LLM gera login mas não gera logout. JWT é stateless — não dá pra "invalidar" um token. Solução: blocklist de tokens revogados (por `jti`) com TTL.

### HOW
```python
@app.post("/auth/logout")
async def logout(payload: TokenPayload):
    """Revoga o access token atual."""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti:
        ttl = max(0, exp - int(datetime.now(timezone.utc).timestamp()))
        await revoke_token(jti, ttl=ttl)
    return {"detail": "Logged out"}

@app.post("/auth/logout-all")
async def logout_all(user: CurrentUser, session: SessionDep):
    """Revoga TODOS os tokens do user (all devices)."""
    await revoke_all_user_tokens(session, str(user.id))
    return {"detail": "All sessions revoked"}
```

### GOTCHA
Access tokens geralmente NÃO têm `jti` (são curtos, não vale o overhead). Nesse caso, logout só revoga o refresh token — o access token expira naturalmente em 15min. Se precisa de revogação imediata, adicione `jti` ao access token E cheque a blocklist em CADA request (overhead de Redis).

---

## 8. JWT Library — PyJWT (NÃO python-jose)

### WHY
`python-jose` tem CVE-2024-33663 ativo (algorithm confusion com ECDSA keys, permite bypass de autenticação). Último release em 2021 — abandonado. FastAPI migrou oficialmente pra `PyJWT` (PR #11589). `passlib` também morreu — quebra no Python 3.13+ (`crypt` module removido).

### HOW
```python
# ❌ NUNCA (CVE ativo, abandonado):
from jose import jwt  # python-jose

# ❌ NUNCA (quebra Python 3.13+):
from passlib.context import CryptContext  # passlib

# ✅ CORRETO:
import jwt  # PyJWT — pip install PyJWT[crypto]
from pwdlib import PasswordHash  # pwdlib — pip install pwdlib[argon2]
```

### GOTCHA
`pip install PyJWT` (maiúsculas importam). O import é `import jwt`, não `import PyJWT`. A extra `[crypto]` é necessária pra RS256/ES256.

---

## 9. Token Storage — HttpOnly Cookie (não localStorage)

### WHY
localStorage é acessível por JavaScript. Qualquer XSS = roubo de token. OWASP: "Do not store session identifiers in local storage." O pattern correto: access token em memória (variável JS), refresh token em HttpOnly cookie.

### HOW
```python
from fastapi import Response
from fastapi.responses import JSONResponse

@app.post("/auth/login")
async def login(body: LoginRequest, response: Response, session: SessionDep):
    user = await authenticate_user(session, body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    tokens = create_token_pair(str(user.id))
    
    # Refresh token vai em HttpOnly cookie — JS NÃO consegue ler
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,       # JavaScript NÃO pode acessar
        secure=True,         # Só HTTPS
        samesite="lax",      # Proteção básica contra CSRF
        max_age=7 * 86400,   # 7 dias
        path="/auth/refresh", # Só enviado pro endpoint de refresh
    )
    
    # Access token vai no body — frontend guarda em memória (não localStorage)
    return {"access_token": tokens["access_token"], "token_type": "bearer"}
```

### GOTCHA
`path="/auth/refresh"` é CRÍTICO — restringe o cookie a SÓ ser enviado pro endpoint de refresh. Sem isso, o refresh token é enviado em TODA request (desnecessário e perigoso).

---

## 10. CSRF Protection com Cookie Auth

### WHY
Se o refresh token tá num cookie, sites maliciosos podem forjar requests que incluem o cookie automaticamente (CSRF). Solução: double-submit cookie pattern — um token CSRF legível pelo JS + header obrigatório.

### HOW
```python
import secrets

@app.post("/auth/login")
async def login(body: LoginRequest, response: Response, session: SessionDep):
    # ... autenticação ...
    
    csrf_token = secrets.token_urlsafe(32)
    
    # CSRF token em cookie legível pelo JS (httponly=False)
    response.set_cookie("csrf_token", csrf_token,
                        httponly=False, secure=True, samesite="lax")
    
    # Refresh token em cookie NÃO legível pelo JS
    response.set_cookie("refresh_token", refresh,
                        httponly=True, secure=True, samesite="lax",
                        path="/auth/refresh")
    
    return {"access_token": access, "token_type": "bearer"}

@app.post("/auth/refresh")
async def refresh(request: Request):
    csrf_cookie = request.cookies.get("csrf_token")
    csrf_header = request.headers.get("X-CSRF-Token")
    
    # Double-submit: cookie e header DEVEM coincidir
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(403, "CSRF validation failed")
    
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(401, "No refresh token")
    
    # ... verificar e rotacionar refresh token ...
```

### GOTCHA
`SameSite=Lax` protege contra CSRF em POST cross-origin (browser não envia cookie). Mas navegadores antigos não suportam. O double-submit pattern é defesa em profundidade.

---

## 11. Signing Algorithm — ES256 com JWKS

### WHY
HS256 (HMAC) usa secret simétrico — quem verifica pode forjar. Em microserviços, isso significa que qualquer serviço que valida tokens pode criar tokens falsos. ES256 (ECDSA P-256) usa par assimétrico — só o auth service tem a private key, todos os outros verificam com a public key via JWKS.

### HOW
```python
# Auth service — assina com private key
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private_key = ec.generate_private_key(ec.SECP256R1())

access_token = jwt.encode(
    {"sub": user_id, "exp": exp, "kid": "key-2026-04"},
    private_key,
    algorithm="ES256",
    headers={"kid": "key-2026-04"},
)

# Qualquer serviço — verifica com public key via JWKS
from jwt import PyJWKClient

jwks_client = PyJWKClient("https://auth.myapp.com/.well-known/jwks.json")

def verify_token(token: str) -> dict:
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token, signing_key.key,
        algorithms=["ES256"],  # SEMPRE whitelist explícita
        audience="my-api",
    )
```

### GOTCHA
SEMPRE passe `algorithms=["ES256"]` explicitamente no decode. Sem isso, um atacante pode enviar um token com `alg=none` e bypassing a verificação (ataque clássico). E rotacione keys a cada 90 dias (NIST) — o `kid` header seleciona a key correta.

---

## 12. Password Validation Rules

### WHY
O LLM aceita qualquer string como senha. OWASP 2024 recomenda: mínimo 8 chars, máximo 128 (evita DoS com hash de senha gigante), checar contra Have I Been Pwned API ou lista de senhas comuns.

### HOW
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator

COMMON_PASSWORDS = {"password", "12345678", "qwerty123", "admin123"}  # Expandir com lista real

class RegisterRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    email: str = Field(min_length=5)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if v.lower() in COMMON_PASSWORDS:
            raise ValueError("Password is too common")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v
```

### GOTCHA
`max_length=128` é crítico. Sem isso, alguém envia uma senha de 1MB e o argon2id passa minutos hasheando — DoS efetivo. OWASP 2024 diz 128 é suficiente.
