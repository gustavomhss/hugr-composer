# SKILL-001 v3 — FastAPI Production Knowledge

> This knowledge file teaches you (the LLM agent) how to USE this skill's
> generators effectively. The generators handle infra. You handle business logic.

---

## Principle: Convention over Configuration

The generators produce SOTA code with calibrated defaults. Your job:
1. Call generators to build the foundation
2. Add business logic (domain services, integrations, custom queries)
3. Run the analyzer to verify you didn't break anything
4. DO NOT modify generated infra unless you have a specific reason

---

## Workflow: How to Build a Project

### Step 1: Generate the foundation

```python
# ONE call produces the entire project skeleton
fastapi_generate_project(
    output_dir="/path/to/project",
    name="my-api",
    models={
        "Product": {"name": "str", "price": "Decimal", "stock": "int"},
        "Order": {"status": "str", "total": "Decimal"},
    },
    owner_models={"Order": "user"},  # Order.owner_id -> users.id
    with_auth=True,         # argon2id + PyJWT + OAuth2 chain
    with_redis=False,       # set True if caching needed
    cors_origins=["https://myapp.com"],
)
```

### Step 2: Add business logic

The generators produce CRUD and auth. You add what's domain-specific:
- Custom business rules (e.g., stock validation before order)
- External integrations (payment gateways, email services, webhooks)
- Domain services (pricing calculations, inventory management)
- Custom queries beyond basic CRUD

### Step 3: Verify

```python
# Run the 35-check production audit
fastapi_analyze("/path/to/project")
# Should return 35/35 after generation
# If you modified code and score dropped, the analyzer tells you what broke
```

---

## What You MUST NOT Modify

These are calibrated by the generators. Changing them breaks production safety:

| Component | Why it's locked |
|-----------|----------------|
| `core/security.py` | argon2id + DUMMY_HASH = timing-safe auth. Changing hasher or removing DUMMY_HASH leaks user existence. |
| `core/jwt.py` algorithm whitelist | `algorithms=[ALGORITHM]` prevents algorithm confusion attacks. Never use `algorithms=None`. |
| `middleware/__init__.py` order | Starlette executes middleware LIFO. Correlation must be outermost, CORS before headers. Wrong order = broken tracing or CORS failures. |
| Pool config in `core/db.py` | `pool_pre_ping=True` detects stale connections. `pool_recycle=1800` prevents firewall kills. Removing these causes intermittent 500s at 3 AM. |
| `Dockerfile` structure | Multi-stage keeps image small. Non-root is required by most K8s policies. HEALTHCHECK enables Docker-native monitoring. |
| Health check paths | K8s expects `/healthz`, `/readyz`, `/startupz`. Renaming breaks probe config. |
| Error handler structure | Consistent error format across all endpoints. Changing one breaks client error parsing. |

---

## What You SHOULD Customize

### Models: Add domain-specific columns

```python
# The generator creates models/{name}.py with UUID PK + timestamps
# ADD your domain columns to the generated file:
class Product(Base):
    __tablename__ = "products"
    # Generated (don't touch):
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(...)

    # YOUR additions:
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
```

### Schemas: Add domain validators

```python
# The generator creates schemas/{name}.py with strict=True + max_length
# ADD custom validators for business rules:
from pydantic import field_validator

class ProductCreate(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = Field(max_length=255)
    price: Decimal = Field(ge=0, le=999999.99)  # generated
    sku: str = Field(max_length=50)              # your addition

    @field_validator("sku")
    @classmethod
    def validate_sku_format(cls, v: str) -> str:
        if not v.replace("-", "").isalnum():
            raise ValueError("SKU must be alphanumeric (hyphens allowed)")
        return v.upper()
```

### CRUD: Add domain queries

```python
# The generator creates crud/{name}.py with create/get/get_multi/update/delete
# ADD domain-specific queries:

async def get_available(session: AsyncSession, *, skip: int = 0, limit: int = 20) -> dict:
    """Fetch only available products."""
    stmt = select(Product).where(Product.is_available == True)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Product.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return {"data": list(result.scalars().all()), "count": total}

async def search_by_sku(session: AsyncSession, sku: str) -> Product | None:
    """Exact SKU lookup."""
    stmt = select(Product).where(Product.sku == sku.upper())
    return (await session.execute(stmt)).scalar_one_or_none()
```

### Routes: Add business endpoints

```python
# The generator creates CRUD routes. ADD business-specific endpoints:

@router.post("/{id}/reserve", response_model=ProductPublic)
async def reserve_product(
    id: uuid.UUID,
    quantity: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Product:
    product = await crud_get(session, id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.stock < quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")
    product.stock -= quantity
    await session.flush()
    return product
```

### Config: Add domain settings

```python
# The generator creates core/config.py with BaseSettings
# ADD domain-specific settings to the Settings class:

class Settings(BaseSettings):
    # Generated (don't touch):
    SECRET_KEY: str
    DATABASE_URL: PostgresDsn
    # ...

    # YOUR additions:
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    MAX_ITEMS_PER_ORDER: int = 50
    TAX_RATE: Decimal = Decimal("0.10")
```

---

## Granular Generators: When to Use Each

If you need a specific component instead of a full project:

| Situation | Tool to call |
|-----------|-------------|
| Adding a new model to existing project | `fastapi_generate_model` + `fastapi_generate_crud` + `fastapi_generate_schemas` |
| Adding auth to existing project | `fastapi_generate_auth` |
| Adding K8s deployment | `fastapi_generate_k8s` |
| Adding monitoring | `fastapi_generate_otel` + `fastapi_generate_prometheus` |
| Adding load tests | `fastapi_generate_loadtest` |
| Adding CRUD endpoints for new model | `fastapi_generate_crud_routes` |
| Auditing existing project | `fastapi_analyze` |
| Checking running instance | `fastapi_check_health` + `fastapi_check_headers` |

---

## Common Patterns

### Adding a new domain model to an existing project

```python
# 1. Generate model
fastapi_generate_model(output_dir=".", name="Review",
    fields={"rating": "int", "comment": "text"},
    owner_field="user")

# 2. Generate CRUD
fastapi_generate_crud(output_dir=".", model_name="Review",
    with_owner_filter=True)

# 3. Generate schemas
fastapi_generate_schemas(output_dir=".", name="Review",
    fields={"rating": "int", "comment": "text"})

# 4. Generate routes
fastapi_generate_crud_routes(output_dir=".", model_name="Review",
    fields={"rating": "int", "comment": "text"},
    auth="required", owner_field="user")

# 5. Register route in routes/__init__.py
# 6. Run alembic revision --autogenerate
# 7. Verify: fastapi_analyze(".")
```

### Adding middleware (without regenerating stack)

If you need custom middleware, add it BEFORE GZip (innermost) in `middleware/__init__.py`:

```python
def register_middleware(app: FastAPI, settings: Settings) -> None:
    # Outermost (first to execute) ↓
    app.add_middleware(CorrelationMiddleware)
    configure_cors(app, settings)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(YourCustomMiddleware)  # ← ADD HERE
    app.add_middleware(RequestLoggingMiddleware)
    # Innermost (last to execute) ↑
```

### Email integration (password recovery)

The generator creates the recovery endpoint with a TODO for email sending.
Wire it to your email service:

```python
# In api/routes/login.py, replace the TODO:
if user:
    token = create_password_reset_token(email=email)
    await send_email(
        to=email,
        subject="Password Reset",
        body=f"Reset link: https://myapp.com/reset?token={token}",
    )
```

---

## SOTA Decisions Reference

Every generator default has a reason. If someone asks "why?":

| Default | Why | Source |
|---------|-----|--------|
| argon2id | Memory-hard, GPU-resistant. OWASP 2024 recommendation. | OWASP Password Storage Cheat Sheet |
| pwdlib | passlib unmaintained since 2020. pwdlib is the successor. | PyPI release history |
| PyJWT | python-jose has CVE-2024-33663 (ECDSA bypass). Unmaintained. | NVD CVE-2024-33663 |
| Algorithm whitelist | Prevents algorithm confusion attacks. | RFC 7515 §10.7 |
| DUMMY_HASH | Constant-time response prevents user enumeration via timing. | CWE-208, OWASP Auth Cheat Sheet |
| async engine | Non-blocking I/O for ASGI. Sync engine blocks the event loop. | SQLAlchemy 2.0 docs |
| pool_pre_ping | Detects dead connections before query. Prevents random 500s. | SQLAlchemy Pool docs |
| pool_recycle=1800 | Prevents firewall/proxy from killing idle connections. | SQLAlchemy Pool docs |
| structlog | JSON logs for machine parsing. stdlib logging is unstructured. | structlog docs |
| Correlation ID | Trace requests across services. W3C Trace Context standard. | W3C Trace Context |
| 3-level health | K8s probes: liveness (restart), readiness (traffic), startup (slow init). | Kubernetes docs |
| Multi-stage Docker | Separate build/runtime. Final image has no compiler, pip, or build deps. | Docker best practices |
| Non-root | CIS Docker Benchmark 4.1. Many K8s policies require it. | CIS Benchmark |
| HEALTHCHECK | Docker-native health monitoring. Required for orchestrator integration. | Docker docs |
| max_length | Prevents DoS via unbounded string input. | CWE-400 |
| datetime.now(tz=UTC) | utcnow() deprecated in Python 3.12. Returns naive datetime. | Python 3.12 changelog |

---

## Adapting Existing Projects

The adapt tools let you add capabilities to a project that already exists -- whether it was
generated by this skill or built manually. All adapt tools are idempotent: calling them
twice with the same arguments produces the same result.

### Adding a model (the easy way)

Instead of calling 4 generators + manually wiring the router, use `fastapi_add_model`:

```python
# ONE call: creates model, CRUD, schemas, routes, wires router + models/__init__
fastapi_add_model(
    project_dir="/path/to/project",
    name="Review",
    fields={"rating": "int", "comment": "text", "product_id": "uuid"},
    owner_field="user",
)
# Done. Router registered, model importable, CRUD + routes ready.
```

### Adding a custom endpoint

When you need an endpoint that is not standard CRUD:

```python
fastapi_add_endpoint(
    project_dir="/path/to/project",
    route_file="api/routes/products.py",   # existing or new file
    method="POST",
    path="/{id}/reserve",
    name="reserve_product",
    auth="required",
    request_body={"quantity": "int"},       # generates inline Pydantic model
    response_model="ProductPublic",
    description="Reserve stock for a product",
)
```

### Adding middleware

Middleware position matters (Starlette LIFO). The tool handles correct placement:

```python
fastapi_add_middleware(
    project_dir="/path/to/project",
    name="RateLimiter",
    code="...",                    # middleware class code
    position="after_cors",        # outermost | after_cors | before_logging | innermost
)
# Writes middleware/rate_limiter.py + updates register_middleware() at correct position
```

### Adding background jobs

ARQ-based async job processing with optional cron scheduling:

```python
# First call creates worker.py + core/arq.py infrastructure
# Every call creates jobs/{name}.py
fastapi_add_background_job(
    project_dir="/path/to/project",
    name="send_welcome_email",
    queue="default",
    retry_max=3,
    cron=None,                   # or "0 9 * * *" for daily at 9 AM
)
```

### Adding WebSocket support

Full WebSocket with connection management, rooms, and auth:

```python
fastapi_add_websocket(
    project_dir="/path/to/project",
    name="chat",
    path="/ws/chat",
    auth=True,                   # JWT from query param ?token=...
)
# Creates ConnectionManager with rooms, broadcast, heartbeat ping/30s
```

### Adding external service integrations

Use `fastapi_add_integration` for common services instead of writing boilerplate:

```python
# Stripe: checkout session + webhook handler
fastapi_add_integration(
    project_dir="/path/to/project",
    service="stripe",
    config={"webhook_path": "/webhooks/stripe"},
)

# S3: upload, presigned URLs, delete
fastapi_add_integration(
    project_dir="/path/to/project",
    service="s3",
    config={"bucket": "my-uploads"},
)

# SendGrid: templated email sending
fastapi_add_integration(
    project_dir="/path/to/project",
    service="sendgrid",
    config={},
)

# Redis: cache layer + @cached decorator
fastapi_add_integration(
    project_dir="/path/to/project",
    service="redis",
    config={},
)
```

**When to use `add_integration` vs manual:** Use the tool for stripe/s3/sendgrid/redis --
it handles config entries, requirements, and boilerplate. For services not in the list,
add them manually following the patterns in `core/config.py`.

### Database migrations

After adding or modifying models:

```python
fastapi_migrate_db(
    project_dir="/path/to/project",
    message="add review table",
)
# Creates migration helper script + returns exact alembic commands to run
```

---

## Fixing Production Readiness

`fastapi_fix_findings` is the power tool for taking any FastAPI project to production
grade. It reads the analyzer output and auto-fixes every failing check.

### The workflow

```python
# 1. Analyze the project (see what fails)
fastapi_analyze("/path/to/project")
# Example output: 21/35 passing

# 2. Auto-fix all findings
fastapi_fix_findings(project_dir="/path/to/project")

# 3. Re-analyze (should be 35/35)
fastapi_analyze("/path/to/project")
# Output: 35/35 passing
```

### What it fixes (proven on real Sonnet naked project: 21/35 → 35/35)

| Finding | Fix applied |
|---------|------------|
| bcrypt / passlib | Replaces with argon2id via pwdlib + DUMMY_HASH |
| python-jose | Replaces with PyJWT + algorithm whitelist |
| Missing security headers | Adds 7-header middleware (HSTS, CSP, X-Frame, etc.) |
| Unstructured logging | Adds structlog + correlation ID middleware |
| No health checks | Adds /healthz, /readyz, /startupz |
| Basic Dockerfile | Rewrites as multi-stage, non-root, HEALTHCHECK |
| Sync engine | Converts to async engine with pool config |
| No pool config | Adds pool_size, pool_pre_ping, pool_recycle |
| on_event decorator | Converts to asynccontextmanager lifespan |

### When to use fix_findings

- **Existing project not generated by this skill:** Run analyze → fix_findings → analyze
- **Project generated by Sonnet/Haiku without skill:** Same workflow, proven 21→35
- **After manual modifications broke checks:** fix_findings restores production compliance
- **CI/CD gate:** Run analyze in CI, fix_findings locally to fix regressions
