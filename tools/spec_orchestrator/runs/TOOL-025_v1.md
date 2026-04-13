<!--
{
  "tool_num": "025",
  "tool_name": "add_factory",
  "model": "deepseek/deepseek-chat",
  "elapsed_seconds": 541.2880371569772,
  "prompt_tokens": 43350,
  "completion_tokens": 10119,
  "cost_usd": 0.060960600000000004,
  "calls": 6
}
-->

# TOOL-025: add_factory

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview

| Metric | Value |  
|--------|-------|  
| Tool name | `fastapi_add_factory` |  
| Category | EXTEND > Testing |  
| Complexity | Medium |  
| Dependencies | FastAPI, SQLAlchemy, pytest |  
| Signature | `add_factory(project_dir: str, models: list[str] | None = None, backend: Literal["factory_boy", "polyfactory"] = "polyfactory") -> dict` |  
| Parameters | `project_dir`: Absolute path to project root directory<br>`models`: List of SQLAlchemy model names to generate factories for (None = all models)<br>`backend`: Factory library to use — `polyfactory` (default) or `factory_boy` |  

## 2. Purpose  

The `fastapi_add_factory` tool generates test data factories for SQLAlchemy models in FastAPI projects. It creates parameterless callables (`ItemFactory.build()`) that produce valid model instances with realistic fake data using Faker. Without this tool, developers must manually write boilerplate code for test fixtures, leading to inconsistent test data and maintenance overhead. The tool integrates seamlessly into the testing workflow by generating a `tests/factories` module and adding fixtures to `conftest.py`. Key design decisions include using polyfactory as the default backend for modern Pydantic integration, supporting sub-factories for FK relationships, and ensuring idempotency for repeated tool execution.  

## 3. Performance SLOs  

| Metric | Target | Why |  
|--------|--------|-----|  
| Tool execution time | < 3s for up to 10 models | Ensures quick iteration during development |  
| Files modified | ≤ 2 (`conftest.py`, `tests/__init__.py`) | Minimizes impact on existing codebase |  
| Files created | ≥ 5 (factories module + one factory per model) | Provides comprehensive test coverage |  
| Factory build latency | < 1 ms per instance | Enables efficient test execution |  
| Batch generation latency | < 50 ms for 100 instances | Supports bulk data testing |  
| FK resolution | Sub-factories only (no DB calls in `build()`) | Maintains test isolation |  
| Migration runtime | 0s — no DB changes | Tests-only tool, no schema modifications |  
| Idempotency | Re-run skips existing factory files | Prevents redundant file generation |

---

## 4. Code Examples (Before / After)

### 4.1 Project Structure: BEFORE
```python
# Project directory structure before running add_factory
# tests/
# ├── conftest.py
# ├── __init__.py
# └── test_items.py
# app/
# ├── models/
# │   ├── item.py
# │   ├── user.py
# │   └── order.py
# └── schemas/
#     ├── item.py
#     └── user.py

# tests/conftest.py (before factories)
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from app.models.base import Base
import asyncio

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def db(engine) -> AsyncSession:
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
```

### 4.2 Project Structure: AFTER
```python
# Project directory structure after running add_factory
# tests/
# ├── conftest.py
# ├── __init__.py
# ├── factories/
# │   ├── __init__.py
# │   ├── item_factory.py
# │   ├── user_factory.py
# │   └── order_factory.py
# └── test_items.py
# app/ (unchanged)
# ├── models/
# │   ├── item.py
# │   ├── user.py
# │   └── order.py
# └── schemas/
#     ├── item.py
#     └── user.py

# tests/conftest.py (after factories - showing only added fixtures)
import pytest
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from tests.factories import ItemFactory, UserFactory, OrderFactory

# ... existing engine and db fixtures remain unchanged ...

@pytest.fixture
def item_factory() -> SQLAlchemyFactory:
    """Fixture providing ItemFactory instance."""
    return ItemFactory

@pytest.fixture
def user_factory() -> SQLAlchemyFactory:
    """Fixture providing UserFactory instance."""
    return UserFactory

@pytest.fixture
def order_factory() -> SQLAlchemyFactory:
    """Fixture providing OrderFactory instance."""
    return OrderFactory

@pytest.fixture
async def create_item(db, item_factory):
    """Helper fixture to create and persist an item."""
    async def _create(**kwargs):
        item = item_factory.build(**kwargs)
        db.add(item)
        await db.flush()
        await db.refresh(item)
        return item
    return _create

@pytest.fixture
async def create_user(db, user_factory):
    """Helper fixture to create and persist a user."""
    async def _create(**kwargs):
        user = user_factory.build(**kwargs)
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user
    return _create
```

### 4.3 Item Factory Module (NEW)
```python
# tests/factories/item_factory.py
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from polyfactory import Use, Ignore
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from polyfactory.faker import Faker
from app.models.item import Item
from tests.factories.user_factory import UserFactory
from tests.factories.tenant_factory import TenantFactory

faker = Faker()

class ItemFactory(SQLAlchemyFactory[Item]):
    __model__ = Item
    __faker__ = faker
    
    id = Use(lambda: uuid4())
    title = Use(lambda: faker.text(max_nb_chars=200))
    description = Use(lambda: faker.text(max_nb_chars=1000))
    price_cents = Use(lambda: faker.random_int(min=100, max=100000))
    status = Use(lambda: faker.random_element(["draft", "active", "archived"]))
    owner = Use(UserFactory.build)
    tenant = Use(TenantFactory.build)
    created_at = Use(lambda: datetime.utcnow() - timedelta(days=faker.random_int(min=0, max=365)))
    updated_at = Use(lambda: datetime.utcnow())
    
    # Traits for common variants
    @classmethod
    def draft(cls, **kwargs):
        """Build a draft item."""
        return cls.build(status="draft", **kwargs)
    
    @classmethod
    def active(cls, **kwargs):
        """Build an active item."""
        return cls.build(status="active", **kwargs)
    
    @classmethod
    def expensive(cls, **kwargs):
        """Build an expensive item (price > $500)."""
        return cls.build(price_cents=faker.random_int(min=50000, max=200000), **kwargs)
    
    @classmethod
    def cheap(cls, **kwargs):
        """Build a cheap item (price < $20)."""
        return cls.build(price_cents=faker.random_int(min=100, max=2000), **kwargs)
    
    class Config:
        faker_seed = 42
        allow_population_by_field_name = True
```

### 4.4 User Factory Module (NEW)
```python
# tests/factories/user_factory.py
from uuid import UUID, uuid4
from polyfactory import Use, PostGenerated
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from polyfactory.faker import Faker
from app.models.user import User
from tests.factories.tenant_factory import TenantFactory

faker = Faker()

class UserFactory(SQLAlchemyFactory[User]):
    __model__ = User
    __faker__ = faker
    
    id = Use(lambda: uuid4())
    email = Use(lambda: faker.unique.email())
    username = Use(lambda: faker.unique.user_name())
    full_name = Use(lambda: faker.name())
    hashed_password = Use(lambda: "$2b$12$" + faker.pystr(min_chars=53, max_chars=53))
    is_active = Use(lambda: faker.boolean(chance_of_getting_true=90))
    is_superuser = Use(lambda: faker.boolean(chance_of_getting_true=5))
    tenant = Use(TenantFactory.build)
    created_at = Use(lambda: faker.date_time_between(start_date="-1y", end_date="now"))
    
    # Post-generation to ensure email and username uniqueness across batch
    @PostGenerated
    @classmethod
    def ensure_unique_email(cls, email: str, values: dict) -> str:
        """Ensure email uniqueness within factory instance."""
        return faker.unique.email()
    
    @PostGenerated
    @classmethod
    def ensure_unique_username(cls, username: str, values: dict) -> str:
        """Ensure username uniqueness within factory instance."""
        return faker.unique.user_name()
    
    # Traits
    @classmethod
    def admin(cls, **kwargs):
        """Build an admin user."""
        return cls.build(is_superuser=True, **kwargs)
    
    @classmethod
    def inactive(cls, **kwargs):
        """Build an inactive user."""
        return cls.build(is_active=False, **kwargs)
    
    @classmethod
    def with_specific_email(cls, email: str, **kwargs):
        """Build a user with specific email."""
        return cls.build(email=email, **kwargs)
    
    class Config:
        faker_seed = 42
        use_defaults = True
```

### 4.5 Factories Package Init (NEW)
```python
# tests/factories/__init__.py
from .item_factory import ItemFactory
from .user_factory import UserFactory
from .order_factory import OrderFactory
from .tenant_factory import TenantFactory
from .product_factory import ProductFactory
from .category_factory import CategoryFactory

__all__ = [
    "ItemFactory",
    "UserFactory",
    "OrderFactory",
    "TenantFactory",
    "ProductFactory",
    "CategoryFactory",
]

# Factory registry for dynamic access
FACTORY_REGISTRY = {
    "Item": ItemFactory,
    "User": UserFactory,
    "Order": OrderFactory,
    "Tenant": TenantFactory,
    "Product": ProductFactory,
    "Category": CategoryFactory,
}

def get_factory(model_name: str):
    """Get factory class by model name."""
    factory = FACTORY_REGISTRY.get(model_name)
    if not factory:
        raise ValueError(f"No factory registered for model: {model_name}")
    return factory

def create_batch(session, model_name: str, size: int = 5, **kwargs):
    """Create and persist a batch of model instances."""
    factory = get_factory(model_name)
    instances = factory.build_batch(size, **kwargs)
    session.add_all(instances)
    return instances
```

### 4.6 Factory Configuration Module (NEW)
```python
# tests/factories/config.py
from typing import Dict, Any, Type
from polyfactory import Factory
from polyfactory.faker import Faker
from polyfactory.field_meta import FieldMeta
from sqlalchemy import Column, String, Integer, DateTime, Boolean, UUID
from sqlalchemy.orm import DeclarativeBase
import uuid
from datetime import datetime

class FactoryConfig:
    """Central configuration for all factories."""
    
    # Default Faker locale
    FAKER_LOCALE = "en_US"
    
    # Type mappings: SQLAlchemy type -> Faker method
    TYPE_MAPPINGS: Dict[Type, str] = {
        String: "text",
        Integer: "random_int",
        DateTime: "date_time",
        Boolean: "boolean",
        UUID: "uuid4",
    }
    
    # Field-specific overrides
    FIELD_OVERRIDES: Dict[str, Dict[str, Any]] = {
        "email": {"generator": "email", "unique": True},
        "username": {"generator": "user_name", "unique": True},
        "password": {"generator": "password", "length": 12},
        "name": {"generator": "name"},
        "title": {"generator": "sentence", "nb_words": 3},
        "description": {"generator": "text", "max_nb_chars": 500},
        "created_at": {"generator": "date_time_between", "start_date": "-1y"},
        "updated_at": {"generator": "date_time_between", "start_date": "-30d"},
    }
    
    @classmethod
    def configure_factory(cls, factory_class: Type[Factory]) -> None:
        """Apply configuration to a factory class."""
        factory_class.__faker__ = Faker(locale=cls.FAKER_LOCALE)
        
    @classmethod
    def get_field_value(cls, field_meta: FieldMeta, model_class: Type[DeclarativeBase]) -> Any:
        """Get appropriate fake value for a field based on configuration."""
        field_name = field_meta.name
        
        # Check for field-specific override
        if field_name in cls.FIELD_OVERRIDES:
            override = cls.FIELD_OVERRIDES[field_name]
            generator = override["generator"]
            faker = Faker(locale=cls.FAKER_LOCALE)
            
            if generator == "email" and override.get("unique"):
                return faker.unique.email()
            elif generator == "user_name" and override.get("unique"):
                return faker.unique.user_name()
            elif hasattr(faker, generator):
                method = getattr(faker, generator)
                kwargs = {k: v for k, v in override.items() if k != "generator" and k != "unique"}
                return method(**kwargs)
        
        # Fall back to type-based mapping
        column_type = getattr(model_class, field_name).property.columns[0].type
        for sql_type, faker_method in cls.TYPE_MAPPINGS.items():
            if isinstance(column_type, sql_type):
                faker = Faker(locale=cls.FAKER_LOCALE)
                if hasattr(faker, faker_method):
                    return getattr(faker, faker_method)()
        
        # Default fallback
        return None
```

### 4.7 Test Using Factories (NEW)
```python
# tests/test_item_factories.py
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.item import Item
from app.models.user import User
from tests.factories import ItemFactory, UserFactory

@pytest.mark.asyncio
async def test_item_factory_builds_valid_instance(db: AsyncSession):
    """Test that ItemFactory.build() creates a valid Item instance."""
    item = ItemFactory.build()
    
    assert isinstance(item, Item)
    assert item.id is not None
    assert isinstance(item.title, str) and len(item.title) > 0
    assert isinstance(item.price_cents, int) and item.price_cents >= 100
    assert item.status in ["draft", "active", "archived"]
    assert item.owner is not None and isinstance(item.owner, User)
    assert item.created_at is not None
    assert item.updated_at is not None

@pytest.mark.asyncio
async def test_item_factory_create_persists_to_db(db: AsyncSession):
    """Test that ItemFactory.create() persists to database."""
    item = await ItemFactory.create(session=db)
    
    # Verify item was persisted
    stmt = select(Item).where(Item.id == item.id)
    result = await db.execute(stmt)
    fetched_item = result.scalar_one()
    
    assert fetched_item.id == item.id
    assert fetched_item.title == item.title
    assert fetched_item.owner_id == item.owner_id

@pytest.mark.asyncio
async def test_item_factory_build_batch(db: AsyncSession):
    """Test batch creation with unique instances."""
    items = ItemFactory.build_batch(5)
    
    assert len(items) == 5
    assert len({item.id for item in items}) == 5  # All IDs unique
    assert len({item.title for item in items}) == 5  # All titles unique
    
    # Verify all instances are valid
    for item in items:
        assert isinstance(item, Item)
        assert item.price_cents >= 100

@pytest.mark.asyncio
async def test_item_factory_traits(db: AsyncSession):
    """Test factory traits produce specific variants."""
    draft_item = ItemFactory.draft()
    active_item = ItemFactory.active()
    expensive_item = ItemFactory.expensive()
    cheap_item = ItemFactory.cheap()
    
    assert draft_item.status == "draft"
    assert active_item.status == "active"
    assert expensive_item.price_cents >= 50000
    assert cheap_item.price_cents <= 2000

@pytest.mark.asyncio
async def test_item_factory_with_relationships(db: AsyncSession):
    """Test factory resolves foreign key relationships."""
    # Create a user first
    user = await UserFactory.create(session=db)
    
    # Build item with specific owner
    item = ItemFactory.build(owner=user)
    
    assert item.owner_id == user.id
    assert item.owner.id == user.id
    assert item.owner.email == user.email
    
    # Persist the item
    db.add(item)
    await db.flush()
    
    # Verify relationship
    stmt = select(Item).where(Item.owner_id == user.id)
    result = await db.execute(stmt)
    fetched_items = result.scalars().all()
    
    assert len(fetched_items) >= 1
    assert any(fetched_item.id == item.id for fetched_item in fetched_items)
```

### 4.8 Factory Utility Module (NEW)
```python
# tests/factories/utils.py
from typing import Type, Any, Dict, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from polyfactory.faker import Faker
import inspect

def get_model_fields(model_class: Type[DeclarativeBase]) -> List[str]:
    """Get all column names from a SQLAlchemy model."""
    return [column.key for column in model_class.__table__.columns]

def generate_fake_for_type(python_type: Type, faker: Faker) -> Any:
    """Generate fake data for a Python type."""
    type_map = {
        str: lambda: faker.text(max_nb_chars=255),
        int: lambda: faker.random_int(min=1, max=10000),
        bool: lambda: faker.boolean(),
        UUID: lambda: faker.uuid4(),
        float: lambda: faker.pyfloat(positive=True, min_value=0, max_value=1000),
        dict: lambda: {"key": faker.word()},
        list: lambda: [faker.word() for _ in range(3)],
    }
    
    for supported_type, generator in type_map.items():
        if python_type == supported_type:
            return generator()
    
    # Check for Optional types
    if hasattr(python_type, "__origin__") and python_type.__origin__ == type(None).__class__:
        inner_type = python_type.__args__[0]
        return generate_fake_for_type(inner_type, faker)
    
    return None

def create_factory_class(
    model_class: Type[DeclarativeBase],
    factory_name: str,
    faker_locale: str = "en_US"
) -> Type[SQLAlchemyFactory]:
    """Dynamically create a factory class for a model."""
    
    class DynamicFactory(SQLAlchemyFactory[model_class]):
        __model__ = model_class
        __faker__ = Faker(locale=faker_locale)
        
        class Config:
            faker_seed = 42
    
    # Set the class name
    DynamicFactory.__name__ = factory_name
    
    return DynamicFactory

def validate_factory_output(factory_class: Type[SQLAlchemyFactory], count: int = 10) -> bool:
    """Validate that factory produces valid instances."""
    try:
        instances = factory_class.build_batch(count)
        
        # Check all instances are of correct type
        if not all(isinstance(inst, factory_class.__model__) for inst in instances):
            return False
        
        # Check for unique IDs in batch
        id_field = getattr(factory_class.__model__, "id", None)
        if id_field:
            ids = [inst.id for inst in instances if hasattr(inst, "id")]
            if len(set(ids)) != len(ids):
                return False
        
        return True
    except Exception:
        return False

async def create_with_relationships(
    session: AsyncSession,
    factory_class: Type[SQLAlchemyFactory],
    relationship_overrides: Dict[str, Any],
    **kwargs
) -> Any:
    """Create instance with pre-existing relationship objects."""
    # Build the instance
    instance = factory_class.build(**kwargs)
    
    # Apply relationship overrides
    for rel_name, rel_value in relationship_overrides.items():
        if hasattr(instance, rel_name):
            setattr(instance, rel_name, rel_value)
    
    # Persist
    session.add(instance)
    await session.flush()
    await session.refresh(instance)
    
    return instance
```

### 4.9 Migration for Test Models (NEW)
```python
# alembic/versions/0010_add_test_models_for_factories.py
"""Add test models for factory generation demonstration

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"

def upgrade() -> None:
    # Create tenants table (if not exists) for multi-tenancy
    op.create_table(
        "tenants",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(63), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'suspended', 'archived')", name="ck_tenants_status"),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'", name="ck_tenants_slug_format"),
    )
    
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("username", sa.String(63), nullable=False, unique=True, index=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.Index("ix_users_tenant_email", "tenant_id", "email", unique=True),
    )
    
    # Create items table
    op.create_table(
        "items",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("owner_id", UUID(), nullable=False),
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint("price_cents >= 0", name="ck_items_price_non_negative"),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_items_status"),
        sa.Index("ix_items_tenant_status", "tenant_id", "status"),
        sa.Index("ix_items_owner_created", "owner_id", "created_at"),
    )
    
    # Insert default tenant for testing
    op.execute("""
        INSERT INTO tenants (id, slug, name) 
        VALUES ('11111111-1111-1111-1111-111111111111', 'default', 'Default Tenant')
        ON CONFLICT (slug) DO NOTHING
    """)

def downgrade() -> None:
    op.drop_table("items")
    op.drop_table("users")
    op.drop_table("tenants")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Every factory produces instances that pass all DB constraints** | `SQLAlchemyFactory` validates field types against model columns via `__model__` introspection in `polyfactory/factories/sqlalchemy_factory.py` |
| QS-2 | **FK relationships are always resolved via sub-factories** | Factory fields with FK constraints use `Use(RelatedFactory.build)` pattern verified by AST parsing in `tests/factories/*_factory.py` |
| QS-3 | **Factories never hit the database during `build()`** | `SQLAlchemyFactory.build()` contains no `session.add()` calls; verified via `grep -r "session\.add" tests/factories/` |
| QS-4 | **Batch generation produces unique instances** | `Faker.unique` decorator applied to all unique fields via `@post_generated` hooks in factory class definitions |
| QS-5 | **Field values match SQLAlchemy column types exactly** | Type mapping enforced by `polyfactory.field_meta.FieldMeta.from_type()` with overrides for UUID/JSONB in `tests/factories/type_handlers.py` |
| QS-6 | **Tool never modifies application source code** | File operations restricted to `tests/` directory via `pathlib.Path(project_dir)/"tests"` validation |
| QS-7 | **Factories handle all nullable/required constraints** | Nullable fields checked via `Column.nullable` flag with `Optional[]` type hints in factory field definitions |
| QS-8 | **Circular FK dependencies are detected and broken** | AST visitor in `tool/validators.py` checks for import cycles and inserts `Use(lambda: None)` |
| QS-9 | **Unique constraints are respected via Faker.unique** | `@pytest.mark.parametrize` runs 100 iterations of unique field generation in `tests/test_uniqueness.py` |
| QS-10 | **Factory output is deterministic with fixed seed** | `Config.faker_seed = 42` set in every factory class via template in `tool/templates/factory.py.j2` |
| QS-11 | **Sub-factories inherit parent factory configuration** | Child factories receive context via `SQLAlchemyFactory.get_provider_map()` override in `tests/factories/__init__.py` |
| QS-12 | **Tool is idempotent across multiple runs** | File existence checks in `tool/generator.py` skip writing if factory file checksum matches |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `tests/factories/__init__.py` exists with correct exports | File exists, contains `__all__` list matching factory classes |
| CC-02 | One factory file per model exists at `tests/factories/<model>_factory.py` | Count files matching `*_factory.py` equals model count |
| CC-03 | Each factory class inherits from `SQLAlchemyFactory[Model]` | grep `class .*\(SQLAlchemyFactory` in factory files |
| CC-04 | Every factory has `__model__` class attribute set | grep `__model__ = ` in factory files |
| CC-05 | All non-nullable fields have factory defaults | Cross-check model `nullable=False` with factory field definitions |
| CC-06 | FK fields use `Use(RelatedFactory.build)` pattern | grep `Use\(.*Factory\.build` in factory files |
| CC-07 | Unique fields use `Faker.unique` decorator | grep `@Faker.unique` in factory files |
| CC-08 | `conftest.py` contains fixtures for all factories | grep `@pytest.fixture.*factory` matches factory count |
| CC-09 | Factory `build()` creates valid instances without DB | `pytest tests/test_factory_build.py` (T-01..T-06) |
| CC-10 | Factory `create()` persists to test database | `pytest tests/test_factory_create.py` (T-07..T-12) |
| CC-11 | Batch operations generate correct instance count | `pytest tests/test_batch_operations.py` (T-19..T-21) |
| CC-12 | Traits generate variant instances correctly | `pytest tests/test_traits.py` (T-22..T-24) |
| CC-13 | Nullable FK fields can be explicitly set to None | `pytest tests/test_nullable_fk.py` (T-13..T-15) |
| CC-14 | Circular FK dependencies are handled safely | Inspect factory files for models with circular references |
| CC-15 | Custom type handlers exist for UUID/JSONB | Check `tests/factories/type_handlers.py` for registration |
| CC-16 | Factory field types match model column types | Cross-check SQLAlchemy types with Faker providers in factory |
| CC-17 | `Config.faker_seed` is set in all factories | grep `class Config:` in factory files |
| CC-18 | String fields respect max_length constraints | Check `Faker.text(max_nb_chars=COLUMN_LENGTH)` usage |
| CC-19 | Enum fields use valid enum values | grep `random.choice\(.*\.__members__\.values\(\)\)` |
| CC-20 | DateTime fields use realistic timestamps | Check `Use(datetime.utcnow)` in factory files |
| CC-21 | Self-referential FKs are optional by default | grep `Optional\[.*\]` for self-referential fields |
| CC-22 | Composite PKs have separate factory fields | Inspect factories for models with composite primary keys |
| CC-23 | Tool skips existing files on re-run | Modify factory file, re-run tool, verify no changes |
| CC-24 | New models get factories on subsequent runs | Add model, re-run tool, check new factory file |
| CC-25 | FactoryBoy backend generates valid factories | Run with `--backend=factory_boy`, verify output |
| CC-26 | Polyfactory backend generates valid factories | Default run, verify Pydantic schema integration |
| CC-27 | All generated code passes `flake8` | Run `flake8 tests/factories/` |
| CC-28 | All generated code passes `mypy` | Run `mypy tests/factories/` |
| CC-29 | Factory execution time < 1ms per instance | Benchmark `build()` in `tests/benchmark_factories.py` |
| CC-30 | Batch of 100 instances completes in <50ms | Benchmark `build_batch(100)` in `tests/benchmark_factories.py` |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified via checks in section 6
- [ ] All 12 Quality Standards enforced per section 5
- [ ] All 8 Invariants tested per section 8
- [ ] Test suite passes with 30 tests covering T-01 through T-30
- [ ] Factory execution meets performance SLOs (<1ms per instance)
- [ ] Batch generation meets performance SLOs (<50ms for 100)
- [ ] No flake8/mypy errors in generated factory code
- [ ] All model fields have appropriate fake data generators
- [ ] FK relationships resolve correctly via sub-factories
- [ ] Unique constraints respected via Faker.unique
- [ ] Tool handles circular FK dependencies safely
- [ ] Idempotency verified via multiple tool runs
- [ ] Both backends (polyfactory/factory_boy) supported

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-FAC-01 | Factory `build()` **always** produces instances that pass DB constraints | `SQLAlchemyFactory` validates field types against model columns via `__table__` introspection in `polyfactory/factories/sqlalchemy_factory.py` | T-01, T-02 |
| INV-FAC-02 | FK relationships are **never** unresolved in built instances | AST visitor in `tool/validators.py` enforces `Use(RelatedFactory.build)` pattern for all FK fields | T-13, T-14 |
| INV-FAC-03 | Factories **never** hit the database during `build()` | `grep -r "session\.add\|session\.commit" tests/factories/` returns no matches | T-07, T-08 |
| INV-FAC-04 | Unique field values are **always** unique within test scope | `@Faker.unique` decorator applied with per-test reset in `conftest.py` fixture | T-19, T-20 |
| INV-FAC-05 | Factory output is **always** deterministic with fixed seed | `Config.faker_seed = 42` enforced via template in `tool/templates/factory.py.j2` | T-25, T-26 |
| INV-FAC-06 | The tool **never** modifies application source code | File operations restricted to `tests/` via `pathlib.Path(project_dir)/"tests"` validation | T-27, T-28 |
| INV-FAC-07 | Batch generation **always** produces the exact requested count | `SQLAlchemyFactory.build_batch()` implementation uses list comprehension with no filtering | T-21, T-22 |
| INV-FAC-08 | Nullable fields are **always** explicitly optional in factories | AST parser in `tool/validators.py` checks for `Optional[]` type hints on nullable columns | T-15, T-16 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Generate factories for all models**
- **As a** developer writing integration tests
- **I want** factories for every SQLAlchemy model in my project
- **So that** I can quickly create test data without manual boilerplate
- **Given:** project with `Item`, `User`, `Order` models
- **When:** I call `add_factory(project_dir="/app")`
- **Then:**
  - `tests/factories/item_factory.py` created with `ItemFactory` class (CC-02)
  - `tests/factories/__init__.py` exports all factories (CC-01)
  - `conftest.py` contains `item_factory` fixture (CC-08)

**US-02: Build valid model instances**
- **As a** test engineer
- **I want** factories that produce instances passing all DB constraints
- **So that** my tests don't fail due to invalid data
- **Given:** `ItemFactory` with `title` (NOT NULL) and `price` (CHECK > 0)
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `item.title` contains non-empty string (INV-FAC-01)
  - `item.price` is positive float (T-01)

**US-03: Resolve FK relationships**
- **As a** developer testing related models
- **I want** FK fields to reference valid instances
- **So that** I can test relationships without manual setup
- **Given:** `Item.owner_id` FK to `User`
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `item.owner` is valid `User` instance (INV-FAC-02)
  - `UserFactory.build()` called internally (T-13)

**US-04: Generate batch data**
- **As a** QA engineer testing bulk operations
- **I want** to create multiple instances in one call
- **So that** I can test performance with realistic data volumes
- **Given:** `ItemFactory` with all required fields
- **When:** I call `items = ItemFactory.build_batch(100)`
- **Then:**
  - Returns list of 100 unique `Item` instances (INV-FAC-07)
  - Completes in <50ms (CC-30)

**US-05: Support traits for common variants**
- **As a** developer testing edge cases
- **I want** factory traits for common scenarios
- **So that** I can test variants without custom setup
- **Given:** `UserFactory` with `admin` trait
- **When:** I call `user = UserFactory.build(admin=True)`
- **Then:**
  - `user.is_admin` is True
  - Other fields still populated with valid data (T-22)

### 9.2 Integration & configuration (US-06 .. US-10)

**US-06: Integrate with conftest**
- **As a** pytest user
- **I want** factories available as fixtures
- **So that** I can use them in test functions
- **Given:** `tests/conftest.py` exists
- **When:** I run `add_factory(project_dir="/app")`
- **Then:**
  - `conftest.py` contains `@pytest.fixture def item_factory()` (CC-08)
  - Fixture returns `ItemFactory` class (T-25)

**US-07: Configure Faker locale**
- **As a** developer testing localized apps
- **I want** factories to use specific locales
- **So that** test data matches production language
- **Given:** project with `User.name` field
- **When:** I set `Faker.locale = "ja_JP"` in factory config
- **Then:**
  - `UserFactory.build().name` contains Japanese characters (CC-16)
  - Falls back to `en_US` if locale unavailable (T-11)

**US-08: Handle custom types**
- **As a** developer using UUID primary keys
- **I want** factories to generate valid UUIDs
- **So that** I can test models with custom types
- **Given:** `Item.id` column with UUID type
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `item.id` is valid UUID instance (CC-15)
  - Type matches SQLAlchemy column exactly (INV-FAC-01)

**US-09: Support nullable fields**
- **As a** developer testing optional relationships
- **I want** nullable FK fields to be optional
- **So that** I can test partial data scenarios
- **Given:** `Item.parent_id` FK (nullable=True)
- **When:** I call `item = ItemFactory.build(parent_id=None)`
- **Then:**
  - `item.parent_id` is None (INV-FAC-08)
  - Instance still passes all constraints (T-15)

**US-10: Generate deterministic data**
- **As a** developer debugging test failures
- **I want** factories to produce consistent data
- **So that** I can reproduce test failures
- **Given:** `UserFactory` with seeded Faker
- **When:** I call `UserFactory.build()` twice with same seed
- **Then:**
  - Both instances have identical field values (INV-FAC-05)
  - Verified by T-25, T-26

### 9.3 Edge cases & error handling (US-11 .. US-15)

**US-11: Handle circular FK dependencies**
- **As a** developer testing self-referential models
- **I want** circular FKs to resolve safely
- **So that** I can test recursive relationships
- **Given:** `Item.parent_id` FK to `Item`
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `item.parent` defaults to None (CC-14)
  - No infinite recursion during build (T-18)

**US-12: Respect unique constraints**
- **As a** developer testing validation logic
- **I want** unique fields to generate unique values
- **So that** I can test constraint violations
- **Given:** `User.email` column with unique=True
- **When:** I call `UserFactory.build_batch(100)`
- **Then:**
  - All 100 emails are unique (INV-FAC-04)
  - Verified by T-19, T-20

**US-13: Handle composite primary keys**
- **As a** developer testing legacy schemas
- **I want** factories to support composite PKs
- **So that** I can test models with complex keys
- **Given:** `Order` with composite PK (`user_id`, `order_id`)
- **When:** I call `order = OrderFactory.build()`
- **Then:**
  - Both PK fields populated with valid values (CC-22)
  - Instance passes all constraints (T-01)

**US-14: Skip existing factory files**
- **As a** developer re-running the tool
- **I want** existing factories to be preserved
- **So that** I don't lose customizations
- **Given:** `tests/factories/item_factory.py` exists
- **When:** I run `add_factory(project_dir="/app")`
- **Then:**
  - Existing file remains unchanged (INV-FAC-06)
  - Tool notes "skipped existing factory" (CC-23)

**US-15: Handle model name collisions**
- **As a** developer testing edge cases
- **I want** factories to handle Python keywords
- **So that** I can test models with reserved names
- **Given:** model named `Class`
- **When:** I run `add_factory(models=["Class"])`
- **Then:**
  - Creates `tests/factories/class_factory.py` with valid Python identifier (CC-10)
  - Factory class named `ClassFactory` (T-28)

### 9.4 Performance & observability (US-16 .. US-20)

**US-16: Meet build latency SLO**
- **As a** developer running thousands of tests
- **I want** factories to build instances quickly
- **So that** my test suite runs efficiently
- **Given:** `UserFactory` with 10 fields
- **When:** I call `UserFactory.build()`
- **Then:**
  - Completes in <1ms (CC-29)
  - Verified by benchmark in `tests/benchmark_factories.py` (T-29)

**US-17: Handle large batch sizes**
- **As a** QA engineer testing scalability
- **I want** factories to generate large batches efficiently
- **So that** I can test with production-like volumes
- **Given:** `ItemFactory` with all required fields
- **When:** I call `ItemFactory.build_batch(1000)`
- **Then:**
  - Completes in <500ms
  - All instances pass constraints (T-21)

**US-18: Validate field lengths**
- **As a** developer testing edge cases
- **I want** string fields to respect max_length
- **So that** I can test validation logic
- **Given:** `Item.title` with max_length=200
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `len(item.title)` <= 200 (CC-18)
  - Verified by T-03

**US-19: Handle enum fields**
- **As a** developer testing restricted choices
- **I want** factories to generate valid enum values
- **So that** I can test enum validation
- **Given:** `User.status` with `active`, `inactive` values
- **When:** I call `user = UserFactory.build()`
- **Then:**
  - `user.status` is either `active` or `inactive` (CC-19)
  - Verified by T-04

**US-20: Generate realistic timestamps**
- **As a** developer testing time-based logic
- **I want** factories to generate valid timestamps
- **So that** I can test time-sensitive features
- **Given:** `Item.created_at` DateTime field
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `item.created_at` is valid UTC timestamp (CC-20)
  - Verified by T-05

### 9.5 Tool integration & idempotency (US-21 .. US-25)

**US-21: Add factories for new models**
- **As a** developer extending my project
- **I want** to generate factories for new models
- **So that** I can test new features quickly
- **Given:** existing project with `Invoice` model added
- **When:** I run `add_factory(models=["Invoice"])`
- **Then:**
  - Creates `tests/factories/invoice_factory.py` (CC-24)
  - Existing factories remain unchanged (CC-23)

**US-22: Support both factory backends**
- **As a** developer migrating from factory_boy
- **I want** to choose between polyfactory and factory_boy
- **So that** I can maintain compatibility
- **Given:** project using factory_boy
- **When:** I run `add_factory(backend="factory_boy")`
- **Then:**
  - Generates factory_boy-compatible factories (CC-25)
  - Verified by T-30

**US-23: Handle JSONB fields**
- **As a** developer testing unstructured data
- **I want** factories to generate valid JSONB values
- **So that** I can test JSONB operations
- **Given:** `Item.metadata` JSONB field
- **When:** I call `item = ItemFactory.build()`
- **Then:**
  - `item.metadata` is valid JSON-compatible dict (CC-15)
  - Verified by T-06

**US-24: Generate factories for subset of models**
- **As a** developer testing specific features
- **I want** to generate factories for selected models
- **So that** I can focus on relevant tests
- **Given:** project with `Item`, `User`, `Order` models
- **When:** I run `add_factory(models=["Item"])`
- **Then:**
  - Creates only `tests/factories/item_factory.py` (CC-02)
  - Other models remain unchanged (CC-23)

**US-25: Validate generated code quality**
- **As a** developer maintaining clean code
- **I want** factory code to pass linting
- **So that** I can maintain high standards
- **Given:** newly generated `ItemFactory`
- **When:** I run `flake8 tests/factories/`
- **Then:**
  - No linting errors (CC-27)
  - Verified by T-28

---

## 10. Test Plan

### 10.1 Factory Build Validation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Build produces valid instance | Item model with NOT NULL title | `item = ItemFactory.build()` | `item.title` is non-empty string (INV-FAC-01) |
| T-02 | Numeric constraints respected | Item with price CHECK > 0 | `item = ItemFactory.build()` | `item.price` is positive float (INV-FAC-01) |
| T-03 | String length respected | User.name max_length=100 | `user = UserFactory.build()` | `len(user.name) <= 100` (CC-18) |
| T-04 | Enum values valid | User.status enum('active','inactive') | `user = UserFactory.build()` | `user.status in ['active', 'inactive']` (CC-19) |
| T-05 | Timestamps realistic | Item.created_at DateTime | `item = ItemFactory.build()` | `item.created_at` is recent UTC timestamp (CC-20) |
| T-06 | JSONB field valid | Item.metadata JSONB | `item = ItemFactory.build()` | `isinstance(item.metadata, dict)` (CC-15) |

### 10.2 Relationship Handling

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | FK resolved via sub-factory | Item.owner_id → User | `item = ItemFactory.build()` | `isinstance(item.owner, User)` (INV-FAC-02) |
| T-08 | Nullable FK can be None | Item.parent_id nullable=True | `item = ItemFactory.build(parent_id=None)` | `item.parent_id is None` (INV-FAC-08) |
| T-09 | Circular FK handled | Item.parent_id → Item | `item = ItemFactory.build()` | `item.parent is None` (CC-14) |
| T-10 | Many-to-many resolved | User.roles association | `user = UserFactory.build()` | `isinstance(user.roles, list)` |
| T-11 | Composite PK supported | Order(user_id, order_id) PK | `order = OrderFactory.build()` | Both PK fields populated (CC-22) |
| T-12 | Self-referential optional | Comment.parent_id → Comment | `comment = CommentFactory.build()` | `comment.parent is None` (CC-21) |

### 10.3 Batch & Uniqueness

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Batch produces exact count | UserFactory | `users = UserFactory.build_batch(100)` | `len(users) == 100` (INV-FAC-07) |
| T-14 | Unique fields respected | User.email unique=True | `users = UserFactory.build_batch(100)` | All emails unique (INV-FAC-04) |
| T-15 | Deterministic with seed | UserFactory with seed=42 | `u1 = UserFactory.build()`<br>`u2 = UserFactory.build()` | `u1.email == u2.email` (INV-FAC-05) |
| T-16 | Traits override defaults | UserFactory(admin=True) | `user = UserFactory.build(admin=True)` | `user.is_admin is True` |
| T-17 | Batch with traits | UserFactory(active=False) | `users = UserFactory.build_batch(5, active=False)` | All have `active=False` |
| T-18 | Large batch performance | ItemFactory | Time `ItemFactory.build_batch(1000)` | Completes in <500ms (CC-30) |

### 10.4 Database Integration

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Create persists to DB | ItemFactory, db session | `item = ItemFactory.create(session=db)` | `db.query(Item).count() == 1` |
| T-20 | No DB in build | ItemFactory | `item = ItemFactory.build()` | No SQL queries emitted (INV-FAC-03) |
| T-21 | Batch create persists | UserFactory, db session | `UserFactory.create_batch(10, session=db)` | `db.query(User).count() == 10` |
| T-22 | Create with relationships | Order with Item FK | `order = OrderFactory.create(session=db)` | `order.items` exists in DB |
| T-23 | Rollback on failure | Invalid data in trait | `OrderFactory.create(session=db, invalid=True)` | DB count unchanged |
| T-24 | Async session support | AsyncSession | `await ItemFactory.create_async(session=db)` | Item exists in DB |

### 10.5 Tool Operation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Idempotent re-run | Existing factories | Run tool twice | Second run skips files (INV-FAC-06) |
| T-26 | Partial model list | models=["Item"] | Run tool | Only item_factory.py created |
| T-27 | FactoryBoy backend | backend="factory_boy" | Run tool | factory_boy imports present |
| T-28 | No app code modified | Existing project | Run tool | No changes outside tests/ (INV-FAC-06) |
| T-29 | Performance SLO | 10 models | Time tool execution | <3s (CC-29) |
| T-30 | Linting passes | Generated factories | Run flake8 | No violations (CC-27) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Factories generate soft-deleted instances via traits |
| add_cursor_pagination | No | ✅ Compatible | Factories support pagination testing with realistic data |
| add_search | No | ✅ Compatible | Factories generate searchable text fields with Faker |
| add_audit_log | No | ✅ Compatible | Factories generate audit log entries with realistic timestamps |
| add_data_export | No | ✅ Compatible | Factories support testing export functionality with batch data |
| add_bulk_operations | No | ✅ Compatible | Factories enable testing bulk operations with build_batch |
| add_multi_tenancy | Yes | ⚠️ Caveat | Must run after add_multi_tenancy to include tenant_id in factories |
| add_feature_flags | No | ✅ Compatible | Factories support testing feature flag scenarios via traits |
| add_api_key_auth | No | ✅ Compatible | Factories generate valid API keys for testing |
| add_oauth2_provider | No | ✅ Compatible | Factories generate OAuth2 tokens and client credentials |
| add_rbac | No | ✅ Compatible | Factories support testing role-based access control |
| add_mfa | No | ✅ Compatible | Factories generate MFA tokens and recovery codes |
| add_cache_layer | No | ✅ Compatible | Factories support testing cache invalidation scenarios |
| add_outbox_pattern | No | ✅ Compatible | Factories generate outbox messages with realistic payloads |
| add_sse | No | ✅ Compatible | Factories support testing server-sent events with realistic data |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout tests/factories/
git checkout tests/conftest.py
rm -rf tests/factories/item_factory.py
rm -rf tests/factories/user_factory.py
rm -rf tests/factories/order_factory.py
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout tests/factories/
git checkout tests/conftest.py
rm -rf tests/factories/item_factory.py
rm -rf tests/factories/user_factory.py
rm -rf tests/factories/order_factory.py
```

### Emergency: Factory generation fails mid-execution
1. Check which files were created: `ls tests/factories/`
2. Remove partially generated files: `rm tests/factories/*_factory.py`
3. Restore original state: `git checkout tests/conftest.py`

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Model has no Pydantic schema | Tool uses SQLAlchemy column types directly for factory generation |
| EC-2 | Model with circular FK relationships | Tool detects cycle and breaks it via Use(lambda: None) |
| EC-3 | Column with CHECK constraint | Tool generates values that satisfy the constraint |
| EC-4 | Unique email field | Tool uses Faker.unique.email() to ensure uniqueness |
| EC-5 | Column with custom type (UUID, JSONB) | Tool provides default generator for custom types |
| EC-6 | Self-referential FK (e.g. parent_id) | Field defaults to None to prevent infinite recursion |
| EC-7 | Composite primary key | Tool creates separate factory fields for each PK component |
| EC-8 | Column with default value | Factory respects default value unless explicitly overridden |
| EC-9 | Model with no nullable fields | Factory generates values for all required fields |
| EC-10 | Model name collides with Python keyword | Tool sanitizes factory class name to valid Python identifier |
| EC-11 | Faker locale missing for a provider | Tool falls back to en_US locale for missing providers |
| EC-12 | Tool re-run with existing factories | Tool skips existing factory files to maintain idempotency |
| EC-13 | New model added after initial tool run | Re-running tool creates new factory for added model |
| EC-14 | Generated fields exceed column length | Tool uses Faker.text(max_nb_chars=column_length) |
| EC-15 | JSONB field with schema | Tool generates random dict that matches JSONB schema |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via checks in section 6  
✅ 2. All 12 Quality Standards enforced per section 5  
✅ 3. All 8 Invariants tested per section 8  
✅ 4. Test suite passes with 30 tests covering T-01 through T-30  
✅ 5. Factory execution meets performance SLOs (<1ms per instance)  
✅ 6. Batch generation meets performance SLOs (<50ms for 100)  
✅ 7. No flake8/mypy errors in generated factory code  
✅ 8. All model fields have appropriate fake data generators  
✅ 9. FK relationships resolve correctly via sub-factories  
✅ 10. Developer successfully uses ItemFactory.build() in integration test  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists and contains FastAPI project
- [ ] Verify SQLAlchemy models exist in app/models/
- [ ] Check for existing factories directory
- [ ] Detect existing factory files for idempotency
- [ ] Validate backend parameter (polyfactory or factory_boy)
- [ ] Parse target model files with AST
- [ ] Verify pytest is installed in project

### 15.2 Factory module generation
- [ ] Create tests/factories/ directory if missing
- [ ] Generate __init__.py with factory exports
- [ ] Create one factory file per model
- [ ] Ensure each factory inherits from SQLAlchemyFactory
- [ ] Set __model__ attribute for each factory
- [ ] Generate realistic field values using Faker
- [ ] Handle FK relationships with sub-factories

### 15.3 Field generation
- [ ] Map SQLAlchemy column types to Faker providers
- [ ] Handle nullable fields appropriately
- [ ] Generate unique values for unique constraints
- [ ] Respect max_length for string fields
- [ ] Generate valid enum values for enum fields
- [ ] Create realistic timestamps for DateTime fields
- [ ] Handle custom types (UUID, JSONB)

### 15.4 Relationship handling
- [ ] Detect FK relationships in models
- [ ] Generate sub-factory references for FK fields
- [ ] Handle circular FK dependencies safely
- [ ] Support many-to-many relationships
- [ ] Make self-referential FK fields optional
- [ ] Handle composite primary keys
- [ ] Support nullable FK fields

### 15.5 Conftest integration
- [ ] Add factory fixtures to conftest.py
- [ ] Ensure fixtures return factory classes
- [ ] Add pytest markers for factory tests
- [ ] Configure Faker locale in conftest
- [ ] Add cleanup hooks for unique fields
- [ ] Add session management for create()
- [ ] Add async session support

### 15.6 Test generation
- [ ] Create test_factories.py module
- [ ] Add tests for factory.build()
- [ ] Add tests for factory.create()
- [ ] Verify FK relationship resolution
- [ ] Test batch operations
- [ ] Verify unique constraints
- [ ] Test traits functionality

### 15.7 Performance optimization
- [ ] Benchmark factory.build() latency
- [ ] Optimize batch generation performance
- [ ] Cache Faker instances
- [ ] Use efficient data generation patterns
- [ ] Profile memory usage during batch ops
- [ ] Optimize FK resolution
- [ ] Minimize imports in factory files

### 15.8 Error handling
- [ ] Handle missing models gracefully
- [ ] Validate model fields before generation
- [ ] Detect invalid FK relationships
- [ ] Handle circular imports safely
- [ ] Validate factory output against model
- [ ] Provide clear error messages
- [ ] Rollback partial changes on failure

### 15.9 Documentation
- [ ] Add factory usage examples to KNOWLEDGE.md
- [ ] Document factory traits system
- [ ] Add troubleshooting guide
- [ ] Document performance characteristics
- [ ] Add API reference for factory methods
- [ ] Document FK relationship handling
- [ ] Add migration guide for factory_boy users

### 15.10 Verification
- [ ] Run ast.parse on all generated files
- [ ] Verify no flake8 errors
- [ ] Verify no mypy errors
- [ ] Run pytest test suite
- [ ] Verify performance SLOs
- [ ] Check idempotency on re-run
- [ ] Verify FK relationship resolution

### 15.11 Atomicity
- [ ] Use temp-file + rename pattern for writes
- [ ] Track touched files for rollback
- [ ] Verify file checksums before overwrite
- [ ] Maintain backup of modified files
- [ ] Implement transactional file operations
- [ ] Rollback on validation failure
- [ ] Preserve existing factory customizations

### 15.12 Localization
- [ ] Support Faker locale configuration
- [ ] Handle missing locale providers
- [ ] Generate locale-specific test data
- [ ] Support multiple locales in same project
- [ ] Document locale configuration
- [ ] Add locale validation
- [ ] Fallback to en_US for unsupported locales

### 15.13 Tool integration
- [ ] Add tool entry to manifest.yaml
- [ ] Add tool to SKILL.md tools table
- [ ] Update mcp_server.py with new decorator
- [ ] Add CLI interface for tool
- [ ] Support CI/CD integration
- [ ] Add version compatibility checks
- [ ] Document tool dependencies

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "tests/factories/__init__.py",
    "tests/factories/item_factory.py",
    "tests/factories/user_factory.py",
    "tests/factories/order_factory.py",
    "tests/conftest.py",
    "tests/test_factories.py",
    "tests/benchmark_factories.py",
    "tests/factories/type_handlers.py"
  ],
  "files_modified": [
    "tests/__init__.py",
    "tests/conftest.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 1234,
    "files_changed": 10,
    "lines_added": 456,
    "lines_removed": 12,
    "factories_generated": 3,
    "fk_relationships_resolved": 5
  },
  "next_steps": [
    "Run: pytest tests/test_factories.py -v",
    "Use ItemFactory.build() in your tests",
    "Generate batch data: ItemFactory.build_batch(100)",
    "Test FK relationships: item = ItemFactory.build()",
    "Verify performance: pytest tests/benchmark_factories.py"
  ],
  "warnings": [
    "Existing factory files were skipped to maintain idempotency",
    "Circular FK relationships were broken via Use(lambda: None)"
  ],
  "notes": [
    "3 factories generated: Item, User, Order",
    "5 FK relationships resolved via sub-factories",
    "Factories configured with Faker seed=42 for deterministic output",
    "Performance meets SLOs: <1ms per instance, <50ms for batch of 100"
  ]
}
