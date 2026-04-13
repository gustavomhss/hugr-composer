# TOOL-018: add_graphql

> **Status**: SPEC v2 (rigorous)  
> **Last updated**: 2026-04-08  

---

## 1. Overview  

| Field | Value |
|---|---|
| **Tool name**     | `fastapi_add_graphql` |  
| **Category**       | EXTEND > API Design   |  
| **Complexity**     | High                 |  
| **Dependencies**   | FastAPI, SQLAlchemy, Strawberry GraphQL, aiodataloader |  
| **Signature**      | `add_graphql(project_dir: str, models: list[str] | None = None, mount_path: str = "/graphql", expose_mutations: bool = True, enable_subscriptions: bool = False, max_query_depth: int = 8, max_query_complexity: int = 1000) -> dict` |  
| **Parameters**     | `project_dir`: project root path (e.g., `/app`) <br> `models`: list of model names to expose via GraphQL (None = all SQLAlchemy models) <br> `mount_path`: where to mount the GraphQL endpoint (default `/graphql`) <br> `expose_mutations`: if True, generates Mutation type with create/update/delete (default True) <br> `enable_subscriptions`: if True, mounts WebSocket route for `subscription` (default False) <br> `max_query_depth`: hard cap on query nesting depth (default 8) <br> `max_query_complexity`: complexity score cap (default 1000) |  
| **Returns**        | `dict` with keys `status`, `files_created`, `files_modified`, `next_steps`, `warnings`, `notes`, `metrics` |
| **Side effects**   | Adds `/graphql` HTTP route, optional `/graphql/subscriptions` WebSocket route, Strawberry schema module, dataloader registry, GraphQL integration tests; no DB schema changes |
| **Idempotency**    | Re-running the tool against the same project produces byte-identical files and a `status: "no_op"` result once the GraphQL layer is installed |

## 2. Purpose  

The `fastapi_add_graphql` tool adds a GraphQL layer to an existing FastAPI REST application using **Strawberry GraphQL** as the schema-first library so frontend teams can adopt the query flexibility of GraphQL without abandoning the REST endpoints that other consumers already depend on. It generates GraphQL types from SQLAlchemy models, query/mutation resolvers that delegate to existing CRUD functions to avoid duplicating business logic, and an `aiodataloader`-based N+1 prevention layer that batches database queries within a single request so a GraphQL query hitting 100 related rows becomes 2 SQL queries instead of 101.

The GraphQL endpoint coexists with REST, sharing the same auth dependencies, the same SQLAlchemy models, and the same database connection pool — clients can use REST or GraphQL interchangeably for the same domain and the two APIs never drift because they are generated from the same source of truth. Subscriptions are optional and use Starlette WebSocket routes, enabling real-time updates for clients that need them without forcing every consumer to upgrade to a WebSocket transport. Key design decisions: schema-first via Strawberry (type-safe), resolver delegation to existing CRUD (zero duplication), aiodataloader for automatic N+1 prevention, shared auth dependencies so every GraphQL resolver goes through the same security checks as REST routes, and a GraphQL-aware extension of TOOL-033 api_spec_compliance so breaking changes to the GraphQL schema are also caught at PR time.  

## 3. Performance SLOs  

| **Metric**                     | **Target**                     | **Why**                                                                 |  
|--------------------------------|--------------------------------|-------------------------------------------------------------------------|  
| Tool execution time            | < 6s                          | Ensures rapid integration into existing projects                        |  
| Files modified                 | ≤ 5                           | Minimizes impact on existing codebase                                  |  
| Files created                  | ≥ 10                          | Includes schema, types, resolvers, dataloaders, and tests              |  
| Single-field query latency p99 | < 30 ms                       | Matches REST GET performance                                           |  
| N+1 query prevention           | 2 SQL queries for nested list | Ensures efficient batch loading via dataloader                         |  
| Depth limit enforcement        | > 8 → 400                     | Protects against malicious deep queries                                |  
| Complexity limit enforcement   | > 1000 → 400                  | Prevents overly complex queries                                        |  
| Migration runtime              | 0s                            | No database schema changes required                                    |  
| Memory overhead per request    | < 2 MB                        | Dataloader cache flushed at request end                                |  
| Schema introspection latency   | < 200 ms                      | Ensures introspection queries remain performant                        |

---

## 4. Code Examples (Before / After)

### 4.1 Main API file: BEFORE
```python
# app/api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routers import router as api_router
from app.core.config import settings
from app.core.db import lifespan

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
```

### 4.2 Main API file: AFTER
```python
# app/api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from app.api.routers import router as api_router
from app.core.config import settings
from app.core.db import lifespan
from app.graphql.schema import schema
from app.graphql.context import get_graphql_context
from app.graphql.extensions import DepthLimitExtension, ComplexityLimitExtension

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

graphql_extensions = [
    DepthLimitExtension(max_depth=settings.GRAPHQL_MAX_DEPTH),
    ComplexityLimitExtension(max_complexity=settings.GRAPHQL_MAX_COMPLEXITY),
]

graphql_app = GraphQLRouter(
    schema,
    context_getter=get_graphql_context,
    graphiql=settings.GRAPHQL_ENABLE_GRAPHIQL,
    extensions=graphql_extensions,
)
app.include_router(graphql_app, prefix="/graphql")
```

### 4.3 GraphQL context file (NEW)
```python
# app/graphql/context.py
from typing import Dict, Any
from fastapi import Request
from strawberry.fastapi import BaseContext
from app.core.auth import get_current_user
from app.graphql.dataloaders import DataLoaders

class GraphQLContext(BaseContext):
    def __init__(
        self,
        request: Request,
        user: Any = None,
        loaders: DataLoaders = None
    ):
        self.request = request
        self.user = user
        self.loaders = loaders or DataLoaders()
        super().__init__()

async def get_graphql_context(request: Request) -> GraphQLContext:
    """Build GraphQL context with authenticated user and dataloaders."""
    try:
        user = await get_current_user(request)
    except Exception:
        user = None
    
    return GraphQLContext(
        request=request,
        user=user,
        loaders=DataLoaders()
    )
```

### 4.4 GraphQL dataloaders file (NEW)
```python
# app/graphql/dataloaders.py
from typing import List, Dict
from aiodataloader import DataLoader
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.db import async_session_maker
from app.models.user import User
from app.models.post import Post

class UserLoader(DataLoader):
    async def batch_load_fn(self, user_ids: List[int]) -> List[User]:
        async with async_session_maker() as session:
            stmt = select(User).where(User.id.in_(user_ids))
            result = await session.execute(stmt)
            users = result.scalars().all()
            
            user_map = {user.id: user for user in users}
            return [user_map.get(uid) for uid in user_ids]

class PostLoader(DataLoader):
    async def batch_load_fn(self, post_ids: List[int]) -> List[Post]:
        async with async_session_maker() as session:
            stmt = select(Post).where(Post.id.in_(post_ids))
            result = await session.execute(stmt)
            posts = result.scalars().all()
            
            post_map = {post.id: post for post in posts}
            return [post_map.get(pid) for pid in post_ids]

class PostsByUserLoader(DataLoader):
    async def batch_load_fn(self, user_ids: List[int]) -> List[List[Post]]:
        async with async_session_maker() as session:
            stmt = (
                select(User)
                .where(User.id.in_(user_ids))
                .options(selectinload(User.posts))
            )
            result = await session.execute(stmt)
            users = result.scalars().all()
            
            user_posts_map = {user.id: user.posts for user in users}
            return [user_posts_map.get(uid, []) for uid in user_ids]

class DataLoaders:
    def __init__(self):
        self.user_loader = UserLoader()
        self.post_loader = PostLoader()
        self.posts_by_user_loader = PostsByUserLoader()
```

### 4.5 GraphQL types file (NEW)
```python
# app/graphql/types.py
import strawberry
from datetime import datetime
from typing import List, Optional
from strawberry.scalars import JSON

@strawberry.type
class UserType:
    id: strawberry.ID
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    @strawberry.field
    async def posts(self, info) -> List["PostType"]:
        """Resolve user's posts using dataloader."""
        return await info.context.loaders.posts_by_user_loader.load(self.id)

@strawberry.type
class PostType:
    id: strawberry.ID
    title: str
    content: str
    published: bool
    metadata: JSON
    created_at: datetime
    updated_at: Optional[datetime]
    author_id: strawberry.ID
    
    @strawberry.field
    async def author(self, info) -> Optional[UserType]:
        """Resolve post author using dataloader."""
        return await info.context.loaders.user_loader.load(self.author_id)

@strawberry.input
class PostCreateInput:
    title: str
    content: str
    published: bool = False
    metadata: JSON = None

@strawberry.input
class PostUpdateInput:
    title: Optional[str] = None
    content: Optional[str] = None
    published: Optional[bool] = None
    metadata: Optional[JSON] = None
```

### 4.6 GraphQL queries file (NEW)
```python
# app/graphql/queries.py
import strawberry
from typing import List, Optional
from app.graphql.types import UserType, PostType
from app.crud.user import get_user, list_users
from app.crud.post import get_post, list_posts

@strawberry.type
class Query:
    @strawberry.field
    async def user(self, info, id: strawberry.ID) -> Optional[UserType]:
        """Get a single user by ID."""
        if not info.context.user:
            raise PermissionError("Authentication required")
        
        user = await get_user(int(id))
        if user and (info.context.user.is_admin or user.id == info.context.user.id):
            return UserType(
                id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at
            )
        return None

    @strawberry.field
    async def users(
        self,
        info,
        skip: int = 0,
        limit: int = 100
    ) -> List[UserType]:
        """List users with pagination."""
        if not info.context.user or not info.context.user.is_admin:
            raise PermissionError("Admin access required")
        
        users = await list_users(skip=skip, limit=limit)
        return [
            UserType(
                id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at
            )
            for user in users
        ]

    @strawberry.field
    async def post(self, info, id: strawberry.ID) -> Optional[PostType]:
        """Get a single post by ID."""
        if not info.context.user:
            raise PermissionError("Authentication required")
        
        post = await get_post(int(id))
        if post and (info.context.user.is_admin or post.author_id == info.context.user.id):
            return PostType(
                id=str(post.id),
                title=post.title,
                content=post.content,
                published=post.published,
                metadata=post.metadata,
                created_at=post.created_at,
                updated_at=post.updated_at,
                author_id=str(post.author_id)
            )
        return None

    @strawberry.field
    async def posts(
        self,
        info,
        published: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[PostType]:
        """List posts with optional published filter."""
        if not info.context.user:
            raise PermissionError("Authentication required")
        
        posts = await list_posts(
            published=published,
            skip=skip,
            limit=limit,
            user_id=info.context.user.id if not info.context.user.is_admin else None
        )
        return [
            PostType(
                id=str(post.id),
                title=post.title,
                content=post.content,
                published=post.published,
                metadata=post.metadata,
                created_at=post.created_at,
                updated_at=post.updated_at,
                author_id=str(post.author_id)
            )
            for post in posts
        ]
```

### 4.7 GraphQL mutations file (NEW)
```python
# app/graphql/mutations.py
import strawberry
from typing import Optional
from app.graphql.types import PostType, PostCreateInput, PostUpdateInput
from app.crud.post import create_post, update_post, delete_post
from app.schemas.post import PostCreate, PostUpdate

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_post(
        self,
        info,
        input: PostCreateInput
    ) -> PostType:
        """Create a new post."""
        if not info.context.user:
            raise PermissionError("Authentication required")
        
        post_in = PostCreate(
            title=input.title,
            content=input.content,
            published=input.published,
            metadata=input.metadata or {},
            author_id=info.context.user.id
        )
        
        post = await create_post(post_in=post_in)
        
        return PostType(
            id=str(post.id),
            title=post.title,
            content=post.content,
            published=post.published,
            metadata=post.metadata,
            created_at=post.created_at,
            updated_at=post.updated_at,
            author_id=str(post.author_id)
        )

    @strawberry.mutation
    async def update_post(
        self,
        info,
        id: strawberry.ID,
        input: PostUpdateInput
    ) -> Optional[PostType]:
        """Update an existing post."""
        if not info.context.user:
            raise PermissionError("Authentication required")
        
        post_update = PostUpdate(
            title=input.title,
            content=input.content,
            published=input.published,
            metadata=input.metadata
        )
        
        post = await update_post(
            post_id=int(id),
            post_in=post_update,
            user_id=info.context.user.id
        )
        
        if post:
            return PostType(
                id=str(post.id),
                title=post.title,
                content=post.content,
                published=post.published,
                metadata=post.metadata,
                created_at=post.created_at,
                updated_at=post.updated_at,
                author_id=str(post.author_id)
            )
        return None

    @strawberry.mutation
    async def delete_post(
        self,
        info,
        id: strawberry.ID
    ) -> bool:
        """Delete a post."""
        if not info.context.user:
            raise PermissionError("Authentication required")
        
        success = await delete_post(
            post_id=int(id),
            user_id=info.context.user.id
        )
        return success
```

### 4.8 GraphQL migration file (NEW)
```python
# alembic/versions/0010_add_graphql_indexes.py
"""add graphql indexes

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add composite index for common GraphQL query pattern: posts by author with pagination
    op.create_index(
        'ix_posts_author_created',
        'posts',
        ['author_id', 'created_at'],
        postgresql_where=sa.text("published = true")
    )
    
    # Add index for user email lookups (common in GraphQL queries)
    op.create_index(
        'ix_users_email_lower',
        'users',
        [sa.text('lower(email)')],
        unique=True
    )
    
    # Add partial index for active users only
    op.create_index(
        'ix_users_active',
        'users',
        ['is_active', 'created_at'],
        postgresql_where=sa.text("is_active = true")
    )

def downgrade() -> None:
    op.drop_index('ix_posts_author_created', table_name='posts')
    op.drop_index('ix_users_email_lower', table_name='users')
    op.drop_index('ix_users_active', table_name='users')
```

### 4.9 Depth + complexity validators (NEW)
```python
# app/graphql/extensions.py
from strawberry.extensions import SchemaExtension
from graphql import GraphQLError, FieldNode, OperationDefinitionNode

from app.core.config import settings


class DepthLimiter(SchemaExtension):
    """Reject queries deeper than settings.GRAPHQL_MAX_QUERY_DEPTH."""

    def on_validate(self) -> None:
        document = self.execution_context.graphql_document
        if document is None:
            return
        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                depth = self._depth(definition.selection_set, 1)
                if depth > settings.GRAPHQL_MAX_QUERY_DEPTH:
                    raise GraphQLError(
                        f"Query depth {depth} exceeds maximum {settings.GRAPHQL_MAX_QUERY_DEPTH}",
                        extensions={"code": "DEPTH_LIMIT_EXCEEDED"},
                    )

    def _depth(self, selection_set, current: int) -> int:
        if selection_set is None:
            return current
        max_depth = current
        for selection in selection_set.selections:
            if isinstance(selection, FieldNode) and selection.selection_set:
                max_depth = max(max_depth, self._depth(selection.selection_set, current + 1))
        return max_depth


class ComplexityLimiter(SchemaExtension):
    """Score query complexity and reject if over budget."""

    def on_validate(self) -> None:
        document = self.execution_context.graphql_document
        if document is None:
            return
        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                score = self._score(definition.selection_set)
                if score > settings.GRAPHQL_MAX_QUERY_COMPLEXITY:
                    raise GraphQLError(
                        f"Query complexity {score} exceeds {settings.GRAPHQL_MAX_QUERY_COMPLEXITY}",
                        extensions={"code": "COMPLEXITY_LIMIT_EXCEEDED"},
                    )

    def _score(self, selection_set) -> int:
        if selection_set is None:
            return 0
        total = 0
        for selection in selection_set.selections:
            if not isinstance(selection, FieldNode):
                continue
            field_score = 1
            for arg in (selection.arguments or []):
                if arg.name.value in ("first", "limit"):
                    try:
                        field_score *= int(arg.value.value)
                    except (AttributeError, ValueError):
                        field_score *= 10
            total += field_score + self._score(selection.selection_set)
        return total
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | GraphQL queries/mutations use the same `CurrentUser` dependency as REST | `get_context()` in `app/graphql/context.py` loads `request.state.user` via `CurrentUser.from_request()` and validates auth tokens identically to REST |
| QS-2 | N+1 queries are prevented for all nested relationships | `DataLoaders` class in `app/graphql/dataloaders.py` batches child queries using `aiodataloader.DataLoader` with per-request cache isolation |
| QS-3 | Query depth > `max_query_depth` is rejected before any resolver runs | `DepthLimiter` extension in `app/graphql/extensions.py` validates depth via AST traversal and raises `GraphQLError` with 400 status |
| QS-4 | Query complexity > `max_query_complexity` is rejected before resolvers run | `ComplexityLimiter` extension in `app/graphql/extensions.py` scores complexity using field weights and raises `GraphQLError` with 400 status |
| QS-5 | Mutations are only exposed when `expose_mutations=True` | `Mutation` type generation skipped in `app/graphql/schema.py` when `settings.EXPOSE_MUTATIONS=False` and schema introspection verifies absence |
| QS-6 | Business logic is never duplicated between REST and GraphQL | Resolvers in `app/graphql/queries.py` delegate to `app/crud/*.py` functions via explicit imports and verified by code coverage |
| QS-7 | Schema introspection is restricted to authenticated users in production | `GraphQLRouter` in `app/api/main.py` checks `settings.INTROSPECTION_AUTH_REQUIRED` before introspection and rejects with 401 if unauthorized |
| QS-8 | Errors never leak stack traces to clients | `GraphQLRouter` wraps exceptions in `GraphQLError` with typed extensions via `extensions` dict and strips internal details in production |
| QS-9 | Subscriptions require Redis configuration when enabled | `Subscription` class in `app/graphql/schema.py` validates Redis connection via `redis.ping()` and raises `RuntimeError` if unavailable |
| QS-10 | GraphQL types match SQLAlchemy model definitions | `@strawberry.type` generation in `app/graphql/types.py` inspects `__mapper__.attrs` for field types and validates via `ast.parse` |
| QS-11 | Pagination follows Relay-style cursor-based pattern | `Connection` types in `app/graphql/types.py` implement `edges`, `pageInfo`, `cursor` via `strawberry.relay` and verified by schema introspection |
| QS-12 | GraphQL context is per-request, never global | `GraphQLContext` in `app/graphql/context.py` uses FastAPI `Request` lifecycle and isolates dataloaders per request |
| QS-13 | Dataloader cache is flushed at request end | `DataLoaders` in `app/graphql/dataloaders.py` clears cache in `__del__` and verified by memory profiling |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `GraphQLRouter` mounted at `/graphql` in `app/api/main.py` | grep `app.include_router(graphql_app, prefix="/graphql")` |
| CC-02 | `schema.py` exists with `Query`, `Mutation`, `Subscription` types | File exists, exports verified via `ast.parse` |
| CC-03 | `types.py` contains `@strawberry.type` for each SQLAlchemy model | grep `@strawberry.type` for each model and validate field mappings |
| CC-04 | `queries.py` delegates to CRUD functions | grep `await crud.*` in resolver functions and verify code coverage |
| CC-05 | `mutations.py` exists when `expose_mutations=True` | File exists conditionally and verified by schema introspection |
| CC-06 | `dataloaders.py` contains `DataLoader` for each relationship | grep `DataLoader` for each FK and validate batch methods |
| CC-07 | `extensions.py` contains `DepthLimiter` and `ComplexityLimiter` | File exists, exports verified via `ast.parse` |
| CC-08 | `context.py` builds `GraphQLContext` with user + dataloaders | grep `class GraphQLContext` and validate `request.state.user` |
| CC-09 | `CurrentUser` dependency reused from REST | grep `request.state.user` in `get_context()` and verify auth flow |
| CC-10 | `GraphQLRouter` configured with `graphiql=True` | grep `graphiql=True` in `main.py` and verify UI access |
| CC-11 | `INTROSPECTION_AUTH_REQUIRED` setting exists | grep `INTROSPECTION_AUTH_REQUIRED` in `config.py` and validate enforcement |
| CC-12 | `max_query_depth` enforced by `DepthLimiter` | Inspect `DepthLimiter` implementation and verify AST traversal |
| CC-13 | `max_query_complexity` enforced by `ComplexityLimiter` | Inspect `ComplexityLimiter` implementation and verify scoring logic |
| CC-14 | `Subscription` class exists when `enable_subscriptions=True` | File exists conditionally and verify Redis integration |
| CC-15 | Redis connection validated for subscriptions | grep `redis.pubsub` in `schema.py` and verify `redis.ping()` |
| CC-16 | `Connection` types implement Relay-style pagination | Inspect `types.py` for `edges`, `pageInfo` and verify schema |
| CC-17 | `GraphQLError` wraps exceptions with typed extensions | grep `GraphQLError` in `main.py` and validate error handling |
| CC-18 | `@strawberry.type` fields match SQLAlchemy model columns | Inspect `types.py` field mappings and validate via `__mapper__.attrs` |
| CC-19 | `DataLoaders` batches queries for nested relationships | Inspect `dataloaders.py` batch methods and verify SQL logs |
| CC-20 | `GraphQLRouter` shares FastAPI lifespan | grep `lifespan` in `main.py` and validate startup/shutdown |
| CC-21 | `pyproject.toml` includes `strawberry-graphql` and `aiodataloader` | grep dependencies and verify installation |
| CC-22 | `tests/test_graphql.py` contains 30 tests | File exists, test count verified via pytest |
| CC-23 | `GraphQLRouter` mounts WebSocket route for subscriptions | grep `WebSocketRoute` in `main.py` and verify connection |
| CC-24 | `GraphQLContext` includes `request` and `user` | Inspect `context.py` and validate context builder |
| CC-25 | `Mutation` inputs match model fields | Inspect `mutations.py` input types and validate schema |
| CC-26 | `Query` type exposes all model queries | Inspect `queries.py` and verify resolver coverage |
| CC-27 | `GraphQLRouter` rejects invalid syntax with 400 | grep `400` in `main.py` and validate parser errors |
| CC-28 | `GraphQLRouter` rejects unauthorized introspection | grep `401` in `main.py` and validate auth flow |
| CC-29 | `GraphQLRouter` rejects depth > `max_query_depth` with 400 | grep `400` in `main.py` and validate depth enforcement |
| CC-30 | `GraphQLRouter` rejects complexity > `max_query_complexity` with 400 | grep `400` in `main.py` and validate complexity enforcement |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] `GraphQLRouter` mounted at `/graphql` in `app/api/main.py`
- [ ] `schema.py` contains `Query`, `Mutation`, `Subscription` types
- [ ] `types.py` contains `@strawberry.type` for each SQLAlchemy model
- [ ] `queries.py` delegates to CRUD functions
- [ ] `mutations.py` exists when `expose_mutations=True`
- [ ] `dataloaders.py` contains `DataLoader` for each relationship
- [ ] `extensions.py` contains `DepthLimiter` and `ComplexityLimiter`
- [ ] `context.py` builds `GraphQLContext` with user + dataloaders
- [ ] `CurrentUser` dependency reused from REST
- [ ] `GraphQLRouter` configured with `graphiql=True`
- [ ] `INTROSPECTION_AUTH_REQUIRED` setting exists
- [ ] `tests/test_graphql.py` contains 30 tests
- [ ] `pyproject.toml` includes `strawberry-graphql` and `aiodataloader`

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-GQL-01 | Every GraphQL query/mutation runs through the SAME `CurrentUser` dependency as REST | `get_context()` loads `request.state.user` via `CurrentUser.from_request()` and validates auth tokens identically to REST | T-13, T-14 |
| INV-GQL-02 | N+1 queries are NEVER issued — nested fetches always go through dataloader batch loading | `DataLoaders` batches child queries using `aiodataloader.DataLoader` with per-request cache isolation | T-07, T-08 |
| INV-GQL-03 | Query depth > `max_query_depth` is ALWAYS rejected with 400 BEFORE any resolver runs | `DepthLimiter` validates depth via AST traversal and raises `GraphQLError` with 400 status | T-19, T-20 |
| INV-GQL-04 | Query complexity > `max_query_complexity` is ALWAYS rejected with 400 before resolvers run | `ComplexityLimiter` scores complexity using field weights and raises `GraphQLError` with 400 status | T-21, T-22 |
| INV-GQL-05 | Mutations CANNOT be invoked when `expose_mutations=False` | `Mutation` type not generated when `settings.EXPOSE_MUTATIONS=False` and schema introspection verifies absence | T-25 |
| INV-GQL-06 | The same business logic in CRUD is invoked from REST and GraphQL — no duplication | Resolvers delegate to CRUD via explicit imports and verified by code coverage | T-26 |
| INV-GQL-07 | Schema introspection is restricted to authenticated users in production | `GraphQLRouter` checks `settings.INTROSPECTION_AUTH_REQUIRED` before introspection and rejects with 401 if unauthorized | T-18 |
| INV-GQL-08 | Errors NEVER leak stack traces; only typed error extensions reach the client | `GraphQLRouter` wraps exceptions in `GraphQLError` with `extensions` dict and strips internal details in production | T-27 |

---

## 9. User Stories

### 9.1 Schema Generation (US-01 .. US-05)

**US-01: Generate GraphQL types from SQLAlchemy models**  
- **As a** backend developer  
- **I want** GraphQL types automatically generated from my SQLAlchemy models  
- **So that** I don't have to manually define GraphQL schemas  
- **Given:** SQLAlchemy models `User` and `Post` with columns `id`, `name`, `email`, `title`, `content`  
- **When:** I call `add_graphql(project_dir="/app", models=["User", "Post"])`  
- **Then:**  
  - `app/graphql/types.py` contains `UserType` and `PostType` (INV-GQL-08)  
  - Each field matches the SQLAlchemy column types (CC-03)  
  - Relationships like `User.posts` are exposed as GraphQL connections  

**US-02: Expose queries for all models**  
- **As a** frontend developer  
- **I want** to query all models via GraphQL  
- **So that** I can fetch data without writing REST endpoints  
- **Given:** `User` and `Post` models  
- **When:** I query `{ users { id name } posts { title content } }`  
- **Then:**  
  - Response contains all users and posts (CC-26)  
  - Queries delegate to existing CRUD functions (INV-GQL-06)  
  - N+1 queries are prevented via dataloaders (INV-GQL-02)  

**US-03: Generate mutations when enabled**  
- **As a** full-stack developer  
- **I want** to create/update/delete models via GraphQL  
- **So that** I can perform mutations without REST endpoints  
- **Given:** `expose_mutations=True` and `Post` model  
- **When:** I call `mutation { createPost(input: {title: "New", content: "..."}) { id } }`  
- **Then:**  
  - `Post` is created in the database (CC-05)  
  - `createPost`, `updatePost`, `deletePost` mutations exist (INV-GQL-05)  
  - Input types match model fields (CC-25)  

**US-04: Handle custom scalar types**  
- **As a** backend developer  
- **I want** custom scalar types like `UUID` and `DateTime` to work  
- **So that** I can use complex fields in GraphQL  
- **Given:** `User` model with `uuid` (UUID) and `created_at` (DateTime) columns  
- **When:** I query `{ users { uuid created_at } }`  
- **Then:**  
  - `uuid` is returned as a string (CC-03)  
  - `created_at` is returned as an ISO8601 string (CC-03)  
  - Scalar types are validated on input  

**US-05: Expose Relay-style pagination**  
- **As a** frontend developer  
- **I want** paginated results via GraphQL connections  
- **So that** I can fetch large datasets efficiently  
- **Given:** `User` model with 1000 records  
- **When:** I query `{ users(first: 10) { edges { node { id name } } pageInfo { hasNextPage } } }`  
- **Then:**  
  - Response contains first 10 users (CC-16)  
  - `pageInfo.hasNextPage` is `true` (CC-16)  
  - Cursor-based pagination works with `after` parameter  

### 9.2 Auth & Access (US-06 .. US-10)

**US-06: Reuse REST authentication**  
- **As a** security engineer  
- **I want** GraphQL to reuse REST authentication  
- **So that** I don't have to maintain separate auth flows  
- **Given:** REST API with JWT auth  
- **When:** I query `{ me { id name } }` with a valid JWT  
- **Then:**  
  - `request.state.user` is available in resolvers (INV-GQL-01)  
  - Response contains the authenticated user's data (CC-09)  
  - Invalid tokens return `401 Unauthorized`  

**US-07: Restrict introspection in production**  
- **As a** security engineer  
- **I want** introspection queries to require auth in production  
- **So that** attackers can't explore my schema  
- **Given:** `INTROSPECTION_AUTH_REQUIRED=True` in production  
- **When:** I query `__schema { types { name } }` without auth  
- **Then:**  
  - Response is `401 Unauthorized` (INV-GQL-07)  
  - Introspection is blocked (CC-11)  
  - Authenticated introspection works  

**US-08: Enforce ownership in mutations**  
- **As a** backend developer  
- **I want** mutations to enforce ownership  
- **So that** users can't modify others' data  
- **Given:** `Post` model with `owner_id` and authenticated user `user1`  
- **When:** `user1` calls `mutation { updatePost(id: "post2", input: {...}) }` where `post2` is owned by `user2`  
- **Then:**  
  - Mutation fails with `403 Forbidden` (INV-GQL-01)  
  - Ownership is checked via `owner_id`  
  - Only the owner can modify the post  

**US-09: Reject anonymous queries**  
- **As a** security engineer  
- **I want** anonymous queries to be rejected  
- **So that** only authenticated users can access data  
- **Given:** `auth_required=True` in config  
- **When:** An unauthenticated client queries `{ users { id } }`  
- **Then:**  
  - Response is `401 Unauthorized` (INV-GQL-07)  
  - Query is rejected before resolvers run  
  - Authenticated queries work  

**US-10: Expose role-based fields**  
- **As a** backend developer  
- **I want** certain fields to be role-restricted  
- **So that** sensitive data is protected  
- **Given:** `User` model with `email` and `role="admin"` fields  
- **When:** A non-admin queries `{ users { email } }`  
- **Then:**  
  - `email` is excluded from the response (INV-GQL-01)  
  - Admins can see all fields  
  - Field-level permissions are enforced  

### 9.3 N+1 Prevention (US-11 .. US-15)

**US-11: Batch load nested relationships**  
- **As a** backend developer  
- **I want** nested relationships to be batched  
- **So that** I avoid N+1 queries  
- **Given:** `User` has many `Post` and 100 users  
- **When:** I query `{ users { id posts { title } } }`  
- **Then:**  
  - Exactly 2 SQL queries are executed (INV-GQL-02)  
  - Posts are loaded in a single batch (CC-06)  
  - Dataloader caches results  

**US-12: Cache dataloader results per request**  
- **As a** backend developer  
- **I want** dataloader results to be cached per request  
- **So that** repeated fields are efficient  
- **Given:** `User` model and query `{ user(id: "1") { name posts { title } } }`  
- **When:** `posts` is accessed multiple times  
- **Then:**  
  - Dataloader hits the cache (INV-GQL-02)  
  - No additional SQL queries are executed  
  - Cache is cleared at request end  

**US-13: Detect missing dataloaders**  
- **As a** backend developer  
- **I want** missing dataloaders to be detected  
- **So that** I don't accidentally introduce N+1 queries  
- **Given:** `User` model with `comments` relationship  
- **When:** I query `{ users { id comments { text } } }` without a dataloader  
- **Then:**  
  - Tool warns about missing dataloader (CC-06)  
  - N+1 queries are logged  
  - Dataloader is added for `comments`  

**US-14: Handle circular relationships**  
- **As a** backend developer  
- **I want** circular relationships to work  
- **So that** I can model complex domains  
- **Given:** `User` has many `Post` and `Post` belongs to `User`  
- **When:** I query `{ users { id posts { user { id } } } }`  
- **Then:**  
  - Circular relationship is resolved (CC-03)  
  - No infinite loops occur  
  - Dataloaders handle the nesting  

**US-15: Batch load across multiple levels**  
- **As a** backend developer  
- **I want** multi-level nesting to be batched  
- **So that** deep queries are efficient  
- **Given:** `User` has many `Post` and `Post` has many `Comment`  
- **When:** I query `{ users { id posts { id comments { text } } } }`  
- **Then:**  
  - Comments are loaded in a single batch (INV-GQL-02)  
  - No N+1 queries occur  
  - Dataloaders handle multiple levels  

### 9.4 Limits & DoS Protection (US-16 .. US-20)

**US-16: Enforce query depth limit**  
- **As a** security engineer  
- **I want** deep queries to be rejected  
- **So that** attackers can't overwhelm the server  
- **Given:** `max_query_depth=8`  
- **When:** I query `{ users { posts { comments { ... } } } }` with depth 9  
- **Then:**  
  - Query is rejected with `400 Bad Request` (INV-GQL-03)  
  - Error message indicates depth limit (CC-12)  
  - Depth = 8 works  

**US-17: Enforce query complexity limit**  
- **As a** security engineer  
- **I want** complex queries to be rejected  
- **So that** attackers can't overload the server  
- **Given:** `max_query_complexity=1000`  
- **When:** I query `{ users { id posts(first: 100) { id comments(first: 10) { id } } } }` with complexity 1001  
- **Then:**  
  - Query is rejected with `400 Bad Request` (INV-GQL-04)  
  - Error message indicates complexity limit (CC-13)  
  - Complexity = 1000 works  

**US-18: Timeout long-running queries**  
- **As a** backend developer  
- **I want** queries to timeout  
- **So that** the server stays responsive  
- **Given:** `query_timeout=5000` (5 seconds)  
- **When:** I run a query that takes > 5 seconds  
- **Then:**  
  - Query is aborted with `408 Request Timeout`  
  - Error message indicates timeout  
  - Shorter queries work  

**US-19: Limit introspection query size**  
- **As a** security engineer  
- **I want** introspection queries to be bounded  
- **So that** attackers can't overwhelm the server  
- **Given:** `introspection_limit=1000` fields  
- **When:** I query `__schema { types { fields { ... } } }` with > 1000 fields  
- **Then:**  
  - Query is rejected with `400 Bad Request` (INV-GQL-07)  
  - Error message indicates field limit  
  - Smaller introspection works  

**US-20: Reject invalid syntax**  
- **As a** backend developer  
- **I want** invalid queries to be rejected  
- **So that** malformed requests don't reach resolvers  
- **Given:** Query with syntax error `{ users { id name }`  
- **When:** I execute the query  
- **Then:**  
  - Query is rejected with `400 Bad Request`  
  - Error message indicates syntax error  
  - Valid queries work  

### 9.5 Integration & Performance (US-21 .. US-25)

**US-21: Coexist with REST API**  
- **As a** full-stack developer  
- **I want** GraphQL to coexist with REST  
- **So that** I can use both interchangeably  
- **Given:** Existing REST API at `/api/v1`  
- **When:** I mount GraphQL at `/graphql`  
- **Then:**  
  - Both REST and GraphQL endpoints work (CC-01)  
  - They share the same auth and models (INV-GQL-01)  
  - Clients can choose either  

**US-22: Match REST performance**  
- **As a** backend developer  
- **I want** GraphQL to match REST performance  
- **So that** clients aren't penalized for using GraphQL  
- **Given:** REST `GET /users/{id}` takes 20ms  
- **When:** I query `{ user(id: "1") { id name } }`  
- **Then:**  
  - GraphQL query takes < 30ms (INV-GQL-02)  
  - Performance matches REST  
  - Dataloaders prevent N+1  

**US-23: Support subscriptions**  
- **As a** frontend developer  
- **I want** real-time updates via subscriptions  
- **So that** I can build reactive UIs  
- **Given:** `enable_subscriptions=True` and Redis configured  
- **When:** I subscribe to `subscription { postCreated { id title } }`  
- **Then:**  
  - WebSocket connection is established (CC-23)  
  - New posts are pushed in real-time  
  - Subscription uses Redis pub/sub  

**US-24: Handle mutation errors gracefully**  
- **As a** backend developer  
- **I want** mutation errors to be typed  
- **So that** clients can handle them properly  
- **Given:** `Post` model with `title` required  
- **When:** I call `mutation { createPost(input: {}) { id } }`  
- **Then:**  
  - Mutation fails with `400 Bad Request` (INV-GQL-08)  
  - Error contains `title` validation message  
  - Stack trace is never exposed  

**US-25: Monitor GraphQL performance**  
- **As a** DevOps engineer  
- **I want** to monitor GraphQL performance  
- **So that** I can detect issues early  
- **Given:** Prometheus metrics endpoint  
- **When:** I query `{ users { id } }`  
- **Then:**  
  - Query latency is recorded  
  - Error rates are tracked  
  - Metrics are exposed via `/metrics`

---

## 10. Test Plan

### 10.1 Schema Generation

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Query type exists | `User` model defined | Query `{ __type(name: "Query") { name } }` | `{"name": "Query"}` |
| T-02 | Mutation type exists when enabled | `expose_mutations=True`, `Post` model | Query `{ __type(name: "Mutation") { name } }` | `{"name": "Mutation"}` |
| T-03 | Fields match model columns | `User` model with `id`, `name`, `email` | Query `{ __type(name: "User") { fields { name } } }` | Fields include `id`, `name`, `email` |
| T-04 | Scalar types work | `User` model with `uuid` (UUID) and `created_at` (DateTime) | Query `{ users { uuid created_at } }` | `uuid` as string, `created_at` as ISO8601 |
| T-05 | Pagination fields exist | `User` model with 100 records | Query `{ users(first: 10) { edges { node { id } } pageInfo { hasNextPage } } }` | `edges` with 10 nodes, `hasNextPage` true |
| T-06 | Mutations excluded when disabled | `expose_mutations=False` | Query `{ __type(name: "Mutation") { name } }` | `null` |

### 10.2 Resolution & N+1 Prevention

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Single field query | `User` model with `id`, `name` | Query `{ user(id: "1") { name } }` | Returns user name |
| T-08 | Nested list batched | `User` has many `Post`, 100 users | Query `{ users { id posts { title } } }` | Exactly 2 SQL queries |
| T-09 | Dataloader cache hit | `User` model, repeated `posts` access | Query `{ user(id: "1") { name posts { title } posts { title } } }` | Posts loaded once |
| T-10 | Missing dataloader detected | `User` model with `comments` relationship | Query `{ users { id comments { text } } }` | Warning logged, N+1 queries |
| T-11 | Circular relationship resolved | `User` has many `Post`, `Post` belongs to `User` | Query `{ users { id posts { user { id } } } }` | No infinite loops |
| T-12 | Multi-level nesting batched | `User` has many `Post`, `Post` has many `Comment` | Query `{ users { id posts { id comments { text } } } }` | Comments loaded in batch |

### 10.3 Auth & Access

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Authenticated query | Valid JWT token | Query `{ me { id name } }` | Returns user data |
| T-14 | Anonymous query rejected | No auth token | Query `{ users { id } }` | `401 Unauthorized` |
| T-15 | Cross-user data access | `Post` owned by `user1`, `user2` authenticated | Query `{ post(id: "post1") { id } }` | `404 Not Found` |
| T-16 | Introspection auth required | `INTROSPECTION_AUTH_REQUIRED=True` | Query `__schema { types { name } }` without auth | `401 Unauthorized` |
| T-17 | Role-based field access | `User` model with `email` field, non-admin authenticated | Query `{ users { email } }` | `email` excluded |
| T-18 | Ownership enforced in mutation | `Post` owned by `user1`, `user2` authenticated | Mutation `{ updatePost(id: "post1", input: {title: "New"}) }` | `403 Forbidden` |

### 10.4 Limits & DoS Protection

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Depth limit enforced | `max_query_depth=8` | Query `{ users { posts { comments { ... } } } }` with depth 9 | `400 Bad Request` |
| T-20 | Complexity limit enforced | `max_query_complexity=1000` | Query `{ users { id posts(first: 100) { id comments(first: 10) { id } } } }` with complexity 1001 | `400 Bad Request` |
| T-21 | Query timeout | `query_timeout=5000` | Query that takes > 5 seconds | `408 Request Timeout` |
| T-22 | Introspection bounded | `introspection_limit=1000` | Query `__schema { types { fields { ... } } }` with > 1000 fields | `400 Bad Request` |
| T-23 | Invalid syntax rejected | Query with syntax error `{ users { id name }` | Execute query | `400 Bad Request` |
| T-24 | Depth boundary case | `max_query_depth=8` | Query `{ users { posts { comments { ... } } } }` with depth 8 | `200 OK` |

### 10.5 Mutations & Integration

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Create mutation works | `expose_mutations=True`, `Post` model | Mutation `{ createPost(input: {title: "New", content: "..."}) { id } }` | `Post` created |
| T-26 | Update mutation propagates | `Post` model | Mutation `{ updatePost(id: "post1", input: {title: "Updated"}) { title } }` | `title` updated |
| T-27 | Delete mutation soft-deletes | `Post` model | Mutation `{ deletePost(id: "post1") { id } }` | `Post` soft-deleted |
| T-28 | REST/GQL coexistence | Existing REST API at `/api/v1` | Query `{ users { id } }` and `GET /api/v1/users/` | Both return same data |
| T-29 | Performance matches REST | REST `GET /users/{id}` takes 20ms | Query `{ user(id: "1") { id name } }` | Latency < 30ms |
| T-30 | Subscriptions work | `enable_subscriptions=True`, Redis configured | Subscribe `subscription { postCreated { id title } }` | New posts pushed in real-time |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| `add_soft_delete` | Yes | GraphQL queries automatically filter out deleted records | Soft-delete status appears in GraphQL types as `deleted_at: DateTime` field |
| `add_cursor_pagination` | Yes | GraphQL uses Relay-style pagination instead of offset pagination | Must disable REST-style pagination in GraphQL resolvers |
| `add_search` | No | GraphQL queries can use search filters via `search: String` argument | Search resolvers integrate with GraphQL query arguments |
| `add_audit_log` | No | GraphQL mutations trigger audit log entries | Audit logs capture GraphQL operation ID and query hash |
| `add_data_export` | Yes | GraphQL queries can trigger CSV/JSON exports | Export format includes GraphQL query context in metadata |
| `add_bulk_operations` | Yes | GraphQL mutations use single-operation pattern | Bulk mutations disabled by default in GraphQL schema |
| `add_multi_tenancy` | Yes | GraphQL queries filter by `tenant_id` automatically | Tenant middleware must run before GraphQL context setup |
| `add_feature_flags` | No | GraphQL endpoints respect feature flag `graphql_enabled` | Feature flags can disable specific GraphQL fields |
| `add_api_key_auth` | Yes | GraphQL accepts `X-API-KEY` header | API key validation occurs in shared auth middleware |
| `add_oauth2_provider` | Yes | GraphQL accepts OAuth2 Bearer tokens | OAuth2 scopes map to GraphQL field permissions |
| `add_rbac` | Yes | GraphQL field-level permissions enforced via RBAC | RBAC checks run during resolver execution |
| `add_mfa` | No | Sensitive GraphQL mutations require MFA verification | Existing MFA flow works for GraphQL mutations |
| `add_cache_layer` | No | GraphQL query responses cached by query hash | Cache keys incorporate GraphQL query text and variables |
| `add_circuit_breaker` | No | Circuit breaker protects GraphQL resolvers | Trips on repeated GraphQL resolver errors |
| `add_outbox_pattern` | No | GraphQL mutation side-effects go through outbox | Ensures reliable delivery of GraphQL-triggered events |
| `add_long_running_task` | No | GraphQL mutations can trigger background tasks | Task status queryable via GraphQL `task(id: ID!)` field |
| `add_sse` | No | SSE provides alternative to GraphQL subscriptions | SSE endpoint `/events` shares auth with GraphQL |
| `add_webhook_sender` | No | GraphQL mutations trigger webhooks | Webhook payloads include GraphQL operation context |
| `add_webhook_receiver` | No | Webhooks can trigger GraphQL mutations | Webhook handlers can execute GraphQL mutations via internal client |

**Conflicts:**
- `add_cursor_pagination`: Must choose between Relay-style (GraphQL) and offset pagination (REST)
- `add_bulk_operations`: GraphQL mutations should use single-operation pattern, not bulk endpoints

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
# Restore modified files
git restore app/api/main.py
git restore pyproject.toml
git restore app/core/config.py

# Remove created GraphQL directory
rm -rf app/graphql/

# Remove GraphQL migration if created
find alembic/versions -name "*_add_graphql_indexes.py" -delete

# Remove GraphQL tests
rm -f tests/test_graphql.py
```

### Database rollback (after deploy)
```sql
-- Drop GraphQL-specific indexes
DROP INDEX IF EXISTS ix_posts_author_created;
DROP INDEX IF EXISTS ix_users_email_lower;
DROP INDEX IF EXISTS ix_users_active;
```

### Data preservation rollback

**N/A — `add_graphql` does not migrate or persist any business data.** GraphQL is
a read/write transport layer over the existing CRUD; the underlying tables are
unchanged. There is nothing to archive before downgrade and nothing to restore
after upgrade. Subscriptions (when enabled) use ephemeral Redis pub/sub channels
that contain no durable state. If your application has accumulated GraphQL query
analytics in a custom log table, snapshot it explicitly:

```sql
-- Optional: archive query analytics if you instrumented the GraphQL endpoint
CREATE TABLE _graphql_query_log_archive AS SELECT * FROM graphql_query_log;
```

### Failure mode: tool partially modified files
```bash
# Restore all tracked files modified by tool
git restore $(git status --porcelain | grep -E "^( M|MM)" | cut -c4-)

# Remove any untracked files in app/graphql/
if [ -d "app/graphql" ]; then
    rm -rf app/graphql/
fi

# Remove untracked test file
if [ -f "tests/test_graphql.py" ]; then
    rm tests/test_graphql.py
fi
```

### Emergency: GraphQL CPU overload
```bash
# Disable GraphQL endpoint via admin API
curl -X POST http://localhost:8000/admin/emergency \
  -H "Authorization: Bearer $SUPERUSER_TOKEN" \
  -d '{"action":"disable_graphql","duration":"15m","reason":"cpu_overload"}'

# Alternative: block GraphQL route at load balancer
# nginx: location /graphql { return 503; }
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no SQLAlchemy models | Tool errors: "No SQLAlchemy models found. Create models in app/models/ first." |
| EC-2 | Strawberry GraphQL not installed | Tool errors: "Missing dependency: strawberry-graphql. Install with pip install strawberry-graphql" |
| EC-3 | Model has circular foreign key relationship | Tool generates dataloaders for both directions and handles circular imports via forward references |
| EC-4 | Two models share same name in different modules | Tool errors: "Ambiguous model name 'Item'. Use fully qualified name: app.models.store.Item or app.models.inventory.Item" |
| EC-5 | Model field is JSON column with no schema | Tool types field as `strawberry.scalars.JSON` scalar with `Any` type annotation |
| EC-6 | Model has private field `_internal_id` | Tool excludes private fields (starting with underscore) from GraphQL type generation |
| EC-7 | Mutation input references enum not in DB | Tool errors: "Enum 'Status' not found in SQLAlchemy model. Define enum in model first." |
| EC-8 | Query depth equals `max_query_depth` exactly | Query executes successfully (boundary case, depth=8 when max=8 returns 200) |
| EC-9 | Query complexity equals `max_query_complexity` exactly | Query executes successfully (boundary case, complexity=1000 when max=1000 returns 200) |
| EC-10 | Subscriptions enabled but Redis not configured | Tool errors: "Redis required for subscriptions. Set REDIS_URL in config or disable subscriptions." |
| EC-11 | Two clients subscribe to same WebSocket channel | Both clients receive published events via Redis pub/sub fanout |
| EC-12 | Introspection disabled in production | Query `{ __schema { types { name } } }` returns 400 with "Introspection disabled" error |
| EC-13 | Query has invalid GraphQL syntax | Request returns 400 with parse error: "Syntax Error: Expected Name, found '}'" |
| EC-14 | Mutation violates database unique constraint | Mutation fails with 400 and error extension: `{"code": "CONSTRAINT_VIOLATION", "field": "email"}` |
| EC-15 | GraphQL behind reverse proxy stripping WebSocket headers | Tool documents requirement: proxy must pass `Upgrade: websocket` and `Connection: Upgrade` headers |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified via automated checks in `tools/verify_graphql.py`  
✅ 2. GraphiQL interface accessible at `/graphql` with proper CORS headers configured  
✅ 3. Depth limiter rejects queries beyond `max_query_depth` with 400 status and clear error message  
✅ 4. Dataloaders reduce N+1 queries to exactly 2 SQL queries for nested relationships (verified via SQL log)  
✅ 5. GraphQL mutations enforce same business rules as REST endpoints (verified via integration tests)  
✅ 6. Subscription endpoints return 101 Switching Protocols when `enable_subscriptions=True`  
✅ 7. All generated files pass `ast.parse` validation and import without errors  
✅ 8. Test suite `pytest tests/test_graphql.py` covers all 30 test cases with 100% pass rate  
✅ 9. Performance benchmarks show <30ms p99 latency for `{ user(id: "1") { id name } }` query  
✅ 10. Developer successfully executes end-to-end flow: create post via mutation → query post → subscribe to post updates (if enabled)  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight validation
- [ ] Verify `project_dir` contains `app/` directory with FastAPI structure
- [ ] Confirm SQLAlchemy models exist in `app/models/*.py` via AST parsing
- [ ] Check for existing GraphQL installation (`app/graphql/` directory)
- [ ] Validate Python version >=3.8 using `sys.version_info`
- [ ] Verify `strawberry-graphql` not already in `pyproject.toml` dependencies
- [ ] Check for model naming conflicts across modules via `inspect.getmembers`

### 15.2 Dependency installation
- [ ] Add `strawberry-graphql = "^0.215.0"` to `pyproject.toml` `[tool.poetry.dependencies]`
- [ ] Add `aiodataloader = "^0.3.0"` to `pyproject.toml` dependencies
- [ ] Add `redis = "^5.0.0"` to `pyproject.toml` when `enable_subscriptions=True`
- [ ] Add `python-multipart = "^0.0.6"` for file upload support
- [ ] Update `requirements.txt` if exists with same dependencies
- [ ] Verify dependency resolution with `poetry lock --no-update`

### 15.3 Configuration setup
- [ ] Add `GRAPHQL_MAX_DEPTH = 8` to `app/core/config.py`
- [ ] Add `GRAPHQL_MAX_COMPLEXITY = 1000` to `app/core/config.py`
- [ ] Add `GRAPHQL_ENABLE_GRAPHIQL = True` to `app/core/config.py`
- [ ] Add `GRAPHQL_ENABLE_INTROSPECTION = True` to `app/core/config.py`
- [ ] Add `INTROSPECTION_AUTH_REQUIRED = False` to `app/core/config.py`
- [ ] Add `REDIS_URL = "redis://localhost:6379"` when `enable_subscriptions=True`

### 15.4 GraphQL directory structure
- [ ] Create `app/graphql/__init__.py` with package marker
- [ ] Create `app/graphql/schema.py` with `Query`, `Mutation`, `Subscription` types
- [ ] Create `app/graphql/types.py` with `@strawberry.type` for each model
- [ ] Create `app/graphql/queries.py` with query resolvers delegating to CRUD
- [ ] Create `app/graphql/mutations.py` when `expose_mutations=True`
- [ ] Create `app/graphql/dataloaders.py` with `DataLoader` classes per relationship

### 15.5 Type generation from models
- [ ] Parse each SQLAlchemy model's `__table__.columns` for field definitions
- [ ] Map SQLAlchemy `Integer` → `strawberry.ID` for primary keys
- [ ] Map SQLAlchemy `DateTime` → `datetime.datetime` with auto string conversion
- [ ] Map SQLAlchemy `UUID` → `strawberry.ID` with string representation
- [ ] Map SQLAlchemy `Enum` → GraphQL Enum type with same values
- [ ] Map SQLAlchemy `JSON` → `strawberry.scalars.JSON` scalar

### 15.6 Query resolver implementation
- [ ] Generate `user(id: ID!)` resolver calling `app.crud.user.get_user`
- [ ] Generate `users(skip: Int = 0, limit: Int = 100)` resolver calling `app.crud.user.list_users`
- [ ] Generate model-specific queries for each exposed model
- [ ] Implement Relay-style pagination with `Connection`, `Edge`, `PageInfo` types
- [ ] Add authentication check via `info.context.user` in each resolver
- [ ] Add authorization checks matching REST endpoint permissions

### 15.7 Mutation implementation
- [ ] Generate `create_<model>(input: <Model>Input!)` mutation for each model
- [ ] Generate `update_<model>(id: ID!, input: <Model>UpdateInput!)` mutation
- [ ] Generate `delete_<model>(id: ID!)` mutation returning `Boolean`
- [ ] Create input types matching model fields in `app/graphql/types.py`
- [ ] Add validation matching Pydantic schemas in `app/schemas/`
- [ ] Enforce ownership checks matching REST endpoint logic

### 15.8 Dataloader implementation
- [ ] Create `UserLoader` batch loading users by ID list
- [ ] Create `PostsByUserLoader` batch loading posts by user ID list
- [ ] Create dataloader for each foreign key relationship in models
- [ ] Implement `batch_load_fn` using `SELECT ... WHERE id IN (:ids)` queries
- [ ] Configure cache clearing at end of request in `DataLoaders.__del__`
- [ ] Add `selectinload()` for eager loading of nested relationships

### 15.9 Security extensions
- [ ] Create `app/graphql/extensions.py` with `DepthLimitExtension` class
- [ ] Implement depth calculation via GraphQL AST traversal
- [ ] Create `ComplexityLimitExtension` with field weights (scalar=1, list=10)
- [ ] Add query timeout extension using `asyncio.timeout`
- [ ] Implement introspection auth check when `INTROSPECTION_AUTH_REQUIRED=True`
- [ ] Add CSRF protection for GraphQL POST requests

### 15.10 Context and middleware
- [ ] Create `app/graphql/context.py` with `GraphQLContext` class
- [ ] Implement `get_graphql_context` loading `request.state.user` from JWT
- [ ] Inject `DataLoaders` instance into context for request lifetime
- [ ] Mount `GraphQLRouter` at `/graphql` in `app/api/main.py`
- [ ] Configure CORS for GraphQL endpoint matching REST settings
- [ ] Add WebSocket route for subscriptions when `enable_subscriptions=True`

### 15.11 Subscription setup
- [ ] Create `app/graphql/subscriptions.py` with `Subscription` class
- [ ] Implement Redis pub/sub for `post_created`, `post_updated` events
- [ ] Add `async_iterator` pattern using `strawberry.subscription`
- [ ] Handle WebSocket connection lifecycle and clean disconnect
- [ ] Implement keepalive ping every 30 seconds for WebSocket connections
- [ ] Validate Redis connection with `await redis.ping()` on startup

### 15.12 Test generation
- [ ] Create `tests/test_graphql.py` with 30 test cases (T-01 to T-30)
- [ ] Test schema generation with `__type` introspection queries
- [ ] Test query execution with authentication fixtures
- [ ] Test N+1 prevention by counting SQL queries via event listener
- [ ] Test depth and complexity limit enforcement
- [ ] Test subscription WebSocket connection and message flow

### 15.13 Documentation and verification
- [ ] Append GraphQL section to `core/KNOWLEDGE.md` with usage examples
- [ ] Add tool entry to `manifest.yaml` with parameters and dependencies
- [ ] Update `SKILL.md` tools table with `fastapi_add_graphql` entry
- [ ] Run `ast.parse` on every modified and created file
- [ ] Execute `pytest tests/` to verify no regressions
- [ ] Measure tool execution time and verify <6s SLO
- [ ] Open `/graphql` in browser, run sample query against a real model, verify N+1 prevention via SQL log
- [ ] Curl introspection query with and without auth token to confirm protection respects `INTROSPECTION_AUTH_REQUIRED`

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/graphql/__init__.py",
    "app/graphql/schema.py",
    "app/graphql/types.py",
    "app/graphql/queries.py",
    "app/graphql/mutations.py",
    "app/graphql/dataloaders.py",
    "app/graphql/extensions.py",
    "app/graphql/context.py",
    "app/graphql/subscriptions.py",
    "tests/test_graphql.py",
    "alembic/versions/0010_add_graphql_indexes.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "pyproject.toml",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 5432,
    "files_changed": 14,
    "lines_added": 876,
    "lines_removed": 22,
    "models_exposed": 5,
    "max_query_depth": 8,
    "subscriptions_enabled": false
  },
  "next_steps": [
    "Run: pytest tests/test_graphql.py -xvs",
    "Test: curl -X POST http://localhost:8000/graphql -H 'Content-Type: application/json' -d '{\"query\":\"{users{id email}}\"}'",
    "Explore: Open http://localhost:8000/graphql in browser for GraphiQL interface",
    "Monitor: Check SQL logs for N+1 queries during development with DEBUG=True",
    "Optimize: Review query complexity limits in production based on actual usage"
  ],
  "warnings": [
    "Introspection disabled in production by default. Set INTROSPECTION_AUTH_REQUIRED=False to allow unauthenticated introspection.",
    "Subscriptions require Redis. Configure REDIS_URL in .env before enabling subscriptions."
  ],
  "notes": [
    "GraphQL endpoint mounted at /graphql with GraphiQL enabled",
    "5 models exposed: User, Post, Comment, Tag, Category",
    "Mutations enabled for all models (create/update/delete)",
    "Depth limiting set to 8 levels maximum via DepthLimitExtension",
    "Dataloaders implemented for 7 relationships to prevent N+1 queries"
  ]
}
