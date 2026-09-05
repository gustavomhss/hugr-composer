# Data Domain — Maintenance Skill

> **Crates**: 19 | **Status**: Production-ready | **Owner**: Data Team | **Last Updated**: 2026-09-04

> **Purpose**: Domain-driven data layer — aggregates, repositories, CQRS, event sourcing, and data integrity patterns.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `Aggregate` | DDD Aggregate root base with event sourcing | High | Production |
| `AntiCorruptionLayer` | ACL pattern for external system integration | High | Production |
| `BoundedContext` | DDD bounded context boundary enforcement | High | Production |
| `ChangeDataCapture` | CDC pattern for event-driven architectures | High | Production |
| `ConfigBinding` | Configuration binding with validation | Low | Production |
| `DataMapper` | ORM-agnostic data mapping | Medium | Production |
| `DiContainer` | Dependency injection container | Medium | Production |
| `IdentityMap` | Identity map pattern for entity tracking | Medium | Production |
| `LegalHold` | Legal hold / data retention enforcement | High | Production |
| `LifetimeScope` | Scoped lifetime management | Medium | Production |
| `MaterializedView` | CQRS read model projections | High | Production |
| `OptimisticConcurrency` | Optimistic locking for concurrent updates | High | Production |
| `PiiClassification` | PII detection and classification | High | Production |
| `Repository` | Repository pattern base | Medium | Production |
| `ShardedCounter` | High-throughput distributed counter | High | Production |
| `Specification` | Specification pattern for queries | Medium | Production |
| `TransactionalBatch` | Batched transactional operations | High | Production |
| `UnitOfWork` | Unit of Work pattern for transactions | High | Production |
| `ValueObject` | Value object base with equality | Low | Production |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA LAYER                           │
├─────────────────────────────────────────────────────────────┤
│  Commands → Aggregate → Events → Event Store                │
│       ↓                                                      │
│  UnitOfWork → Repository → ORM → Database                   │
│       ↓                                                      │
│  Events → Projections → MaterializedView → Read Models      │
│       ↓                                                      │
│  CDC → ChangeDataCapture → External Systems                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Patterns Implemented

### 1. Aggregate Root (DDD)

```python
# core/venous/data/Aggregate/
class AggregateRoot:
    def __init__(self):
        self._events: list[DomainEvent] = []
        self._version = 0
    
    def _add_event(self, event: DomainEvent):
        self._events.append(event)
    
    def collect_events(self) -> list[DomainEvent]:
        events = self._events
        self._events = []
        return events
    
    @property
    def version(self) -> int:
        return self._version

# Usage in your aggregate:
class Order(AggregateRoot):
    def __init__(self, order_id: str, customer_id: str):
        super().__init__()
        self.id = order_id
        self.customer_id = customer_id
        self.status = OrderStatus.PENDING
        self.items: list[OrderItem] = []
    
    def add_item(self, product_id: str, quantity: int, price: Decimal):
        if self.status != OrderStatus.PENDING:
            raise InvalidOperation("Cannot modify confirmed order")
        item = OrderItem(product_id, quantity, price)
        self.items.append(item)
        self._add_event(OrderItemAdded(self.id, item))
```

---

## Common Patterns

### 1. Repository Pattern

```python
# Base repository with common operations
class Repository(Generic[T, ID]):
    async def get(self, id: ID) -> T | None
    async def add(self, entity: T) -> None
    async def remove(self, entity: T) -> None
    async def find(self, spec: Specification[T]) -> list[T]
    async def count(self, spec: Specification[T]) -> int

# Usage:
class OrderRepository(Repository[Order, OrderId]):
    async def find_by_customer(self, customer_id: CustomerId) -> list[Order]:
        return await self.find(OrderSpecification.by_customer(customer_id))
```

---

### 2. Unit of Work

```python
# Manages transaction boundaries
class UnitOfWork:
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._repositories: dict[type, Repository] = {}
    
    async def __aenter__(self):
        self._session = self._session_factory()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
        await self._session.close()
    
    def repo(self, entity_type: type[T]) -> Repository[T, Any]:
        if entity_type not in self._repositories:
            self._repositories[entity_type] = self._create_repo(entity_type)
        return self._repositories[entity_type]
    
    async def commit(self):
        await self._session.commit()
    
    async def rollback(self):
        await self._session.rollback()

# Usage:
async with UnitOfWork(session_factory) as uow:
    order = await uow.repo(Order).get(order_id)
    order.ship()
    # Auto-commits on success, rolls back on exception
```

---

### 3. Specification Pattern

```python
# Composable query specifications
class Specification(Generic[T]):
    def is_satisfied_by(self, candidate: T) -> bool: ...
    def and_(self, other: Specification[T]) -> Specification[T]: ...
    def or_(self, other: Specification[T]) -> Specification[T]: ...
    def not_(self) -> Specification[T]: ...

# Pre-built specifications
class OrderSpecification:
    @staticmethod
    def by_customer(customer_id: CustomerId) -> Specification[Order]:
        return Specification(lambda o: o.customer_id == customer_id)
    
    @staticmethod
    def pending() -> Specification[Order]:
        return Specification(lambda o: o.status == OrderStatus.PENDING)
    
    @staticmethod
    def placed_between(start: datetime, end: datetime) -> Specification[Order]:
        return Specification(lambda o: start <= o.created_at <= end)

# Composable!
spec = OrderSpecification.by_customer(cust_id).and_(OrderSpecification.pending())
orders = await order_repo.find(spec)
```

---

### 4. Optimistic Concurrency

```python
# Automatic optimistic locking via version column
class Order(Base):
    __tablename__ = "orders"
    version = Column(Integer, default=0, nullable=False)
    
    @validates('version')
    def _check_version(self, key, value):
        if value <= self.__dict__.get('version', 0):
            raise OptimisticLockError("Stale version")
        return value

# Usage:
async with uow:
    order = await uow.repo(Order).get(order_id)
    order.ship()  # Increments version implicitly
    # On commit: if version changed by another transaction → OptimisticLockError
```

---

## Common Operations

### 1. Repository Operations

```python
# Basic CRUD
await repo.add(entity)
entity = await repo.get(id)
await repo.remove(entity)

# Query with specifications
results = await repo.find(spec)
count = await repo.count(spec)
```

### 2. Unit of Work

```python
async with UnitOfWork(session_factory) as uow:
    entity = await uow.repo(Entity).get(id)
    entity.modify()
    # Auto-commits on success, rolls back on exception
```

### 3. Specification Composition

```python
# Compose complex queries
spec = UserSpecification.by_email(email).and_(UserSpecification.active())
users = await repo.find(spec)

# Reusable specifications
class UserSpecification:
    @staticmethod
    def by_email(email: str) -> Specification[User]:
        return Specification(lambda u: u.email == email)
    
    @staticmethod
    def active() -> Specification[User]:
        return Specification(lambda u: u.is_active)
    
    @staticmethod
    def by_department(dept: str) -> Specification[User]:
        return Specification(lambda u: u.department == dept)
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Anemic domain model** | Logic in services, not aggregates | Move logic to aggregate roots |
| **Leaky abstractions** | ORM leaks into domain | Use DataMapper; keep domain pure |
| **N+1 queries** | N+1 SELECTs for collections | Use `selectinload` / `joinedload` |
| **Stale reads** | Stale data in read models | Use MaterializedView with CDC |
| **Optimistic lock failures** | High contention on hot aggregates | Reduce aggregate size; use saga |
| **Transaction too large** | Lock contention, timeouts | Keep transactions small; use saga |
| **Eventual consistency confusion** | Stale read models | Document consistency boundaries |
| **Aggregate too large** | Performance, contention | Split into smaller aggregates |

---

## Evolution Without Breaking Contracts

### Adding a Field to an Aggregate

```python
# Non-breaking: add optional field with default
class Order(AggregateRoot):
    def __init__(self, ...):
        ...
        self.notes: str | None = None  # NEW FIELD
```

### Adding a New Event

```python
# 1. Define new event (non-breaking)
class OrderNotesAdded(DomainEvent):
    order_id: OrderId
    notes: str

# 2. Add to aggregate (non-breaking)
class Order(AggregateRoot):
    def add_notes(self, notes: str):
        self._add_event(OrderNotesAdded(self.id, notes))

# 3. Projections handle new event (eventual consistency)
# No breaking changes for existing consumers
```

---












*Data Domain Maintenance Skill v1.0 | Maintained by Data Team | Next review: 2026-12-04*