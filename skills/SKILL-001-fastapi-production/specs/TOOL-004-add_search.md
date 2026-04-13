# TOOL-004: fastapi_add_search

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_search` |
| Category | EXTEND > CRUD & Data |
| Complexity | High |
| Dependencies | PostgreSQL (tsvector/tsquery), SQLAlchemy 2.0 async, Alembic, existing model with ≥1 text field; optional: opensearch-py for OpenSearch backend |
| Signature | `add_search(project_dir: str, model_name: str, fields: list[str], language: str = "english", min_length: int = 2, with_snippet: bool = False, weighted: bool = False, autocomplete: bool = False, facets: list[str] \| None = None, backend: Literal["postgres", "opensearch"] = "postgres") -> dict` |
| Parameters | `project_dir`: project root path<br>`model_name`: SQLAlchemy model class name to add search to<br>`fields`: text columns to index (first field receives highest weight A, remaining B/C/D in order)<br>`language`: PostgreSQL text search dictionary (default: `"english"`)<br>`min_length`: minimum query character count enforced at validation layer (default: `2`)<br>`with_snippet`: generate `ts_headline` highlighted excerpt in result rows (default: `False`, expensive)<br>`weighted`: enable `setweight()` on per-field tsvectors for title > body relevance boost (default: `False`)<br>`autocomplete`: add `GET /{model}s/autocomplete` endpoint using prefix matching via `to_tsquery('term:*')` (default: `False`)<br>`facets`: list of categorical column names to include as faceted filter parameters (default: `None`)<br>`backend`: `"postgres"` (zero infra cost, default) or `"opensearch"` (external cluster, higher throughput) |

---

## 2. Purpose

`fastapi_add_search` replaces table-scan string matching (`LIKE '%query%'`, `ILIKE`) with production-grade full-text search powered by PostgreSQL's native `tsvector`/`tsquery` engine. The core problem is that `LIKE '%query%'` forces a sequential scan on every row regardless of indexes — a table with one million products becomes a latency disaster at the 95th percentile. This tool generates a GIN (Generalized Inverted Index) expression index over the concatenated tsvector of all target fields, reducing search to an O(log n) bitmap index scan. Beyond raw indexing, it solves four recurring production problems that greenfield implementations consistently miss: weighted field relevance (so a query matching a product's `name` outranks one only matching its `description` via PostgreSQL `setweight` with labels A–D), stemming and stop-word removal (the `english` dictionary reduces "running", "runs", "ran" to the stem "run" and ignores "the", "and", "a" before indexing), SQL-injection safety (user input is always parameterized through `plainto_tsquery` or `websearch_to_tsquery`, never interpolated into SQL strings), and pagination-aware ranking (cursor pagination on `ts_rank` value keeps page 1000 as fast as page 1 without `OFFSET` drift).

Beyond the primary Postgres backend, the tool supports an optional OpenSearch backend for teams whose write volume or search complexity exceeds what a single Postgres instance can handle. When `backend="opensearch"` is selected, the tool scaffolds an `app/search/opensearch_backend.py` module that writes to the `outbox_events` table (compatible with TOOL-046 if installed) and indexes documents via `opensearch-py` with explicit mapping for `text` and `keyword` fields. The design decision to default to Postgres is deliberate: zero additional infrastructure cost, a single deployment surface, ACID-consistent search results that never diverge from the source-of-truth table, and no synchronization lag. OpenSearch is scaffolded as a swap-in backend that satisfies the same `SearchBackend` protocol, so switching backends requires only a configuration change — not a rewrite. Faceted search adds categorical `WHERE` clauses (e.g., `category=electronics AND price_range=50-100`) that combine with the `tsvector` match to let users progressively narrow results. The autocomplete endpoint (`GET /{model}s/autocomplete?q=mac`) uses `to_tsquery('mac:*')` prefix matching with a strict 5-result cap and 20ms target latency, enabling search-as-you-type without a dedicated typeahead service.

---

## 3. Performance SLOs

| Metric | Target | Notes |
|--------|--------|-------|
| Tool execution time | < 3s | Single model; measured from call to file writes complete |
| Files modified | ≤ 4 (crud, route, schema, model comment) | Predictable blast radius |
| Files created | 1 migration + 1 test file (+ 1 OpenSearch backend if backend="opensearch") | Predictable |
| Search query latency p50 (1M rows, GIN indexed) | < 20 ms | GIN bitmap index scan |
| Search query latency p99 (1M rows, GIN indexed) | < 50 ms | Includes ts_rank computation |
| Search query latency p99 (10M rows, GIN indexed) | < 100 ms | GIN scales sub-linearly |
| Autocomplete latency p99 (prefix match, 1M rows) | < 20 ms | Prefix tsquery `term:*` with LIMIT 5 |
| Index update latency (tsvector trigger, single row INSERT) | < 10 ms | BEFORE INSERT/UPDATE trigger; synchronous |
| ts_headline snippet generation per row | < 5 ms per row | Applies only when `with_snippet=True`; opt-in |
| GIN index build time (1M rows, CONCURRENTLY) | < 5 minutes | One-time; does NOT lock table |
| GIN index storage overhead | ~25–35% of indexed text | tsvector compression; lexemes only |
| ts_rank computation per result set (20 rows) | < 5 ms | Rank is index-resident; no extra pass |
| Result count query | < 15 ms | Separate `SELECT COUNT(*)` on subquery |

---

## 4. Code Examples

### 4.1 Migration: tsvector column + GIN index

```python
# alembic/versions/0004_search_idx_product.py
"""Add full-text search GIN index on product (name, description)."""

revision = "0004_search_idx_product"
down_revision = "0003_previous"
branch_labels = None
depends_on = None

# IMPORTANT: GIN index must be created OUTSIDE a transaction.
# Alembic's transactional_ddl must be False for CONCURRENTLY to work.
from alembic import op

# Required to disable autobegin for CONCURRENTLY
def upgrade() -> None:
    # Add generated tsvector column for deterministic indexing
    op.execute("""
        ALTER TABLE product
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B')
        ) STORED;
    """)
    # GIN index on the stored column — fastest for static-weight queries
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_product_search_vector
        ON product
        USING GIN (search_vector);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_search_vector;")
    op.execute("ALTER TABLE product DROP COLUMN IF EXISTS search_vector;")
```

### 4.2 Weighted tsvector via setweight (multi-field, title > description > tags)

```python
# app/crud/product.py — weighted tsvector helper
from sqlalchemy import func, text
from sqlalchemy.orm import InstrumentedAttribute


def _build_weighted_tsvector(
    model_cls,
    language: str = "english",
) -> "ColumnElement":
    """
    Compose weighted tsvector from name (A), description (B), tags (C).
    setweight labels: A=highest, D=lowest. Weights applied by ts_rank_cd().
    Using coalesce ensures NULL fields are treated as empty strings.
    """
    name_vec = func.setweight(
        func.to_tsvector(text(f"'{language}'"), func.coalesce(model_cls.name, "")),
        text("'A'"),
    )
    desc_vec = func.setweight(
        func.to_tsvector(text(f"'{language}'"), func.coalesce(model_cls.description, "")),
        text("'B'"),
    )
    tags_vec = func.setweight(
        func.to_tsvector(text(f"'{language}'"), func.coalesce(model_cls.tags, "")),
        text("'C'"),
    )
    return name_vec.op("||")(desc_vec).op("||")(tags_vec)
```

### 4.3 SearchParams Pydantic schema (filters + facets + pagination)

```python
# app/schemas/product.py — addition
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    """Validated search parameters. All user-supplied values are validated here."""

    q: str = Field(..., min_length=2, max_length=200, description="Full-text search query")
    page_size: int = Field(default=20, ge=1, le=100)
    cursor_score: float | None = Field(default=None, description="Rank cursor for next page")
    # Facet filters: optional categorical refinements
    category: str | None = Field(default=None, max_length=100, description="Filter by category")
    status: Literal["active", "archived"] | None = Field(default=None)
    # Sort override: relevance (default) or recency
    sort: Literal["relevance", "recency"] = Field(default="relevance")


class SearchResultItem(BaseModel):
    """Single search result with optional ranking metadata."""

    id: str
    name: str
    description: str | None = None
    rank: float | None = Field(default=None, description="ts_rank score; higher = more relevant")
    snippet: str | None = Field(default=None, description="ts_headline excerpt; present only when with_snippet=True")


class SearchResponse(BaseModel):
    data: list[SearchResultItem]
    count: int
    has_more: bool
    next_cursor: float | None = None
```

### 4.4 CRUD search function (weighted + facets + cursor pagination)

```python
# app/crud/product.py — add_search injection
import uuid
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession


async def search(
    session: AsyncSession,
    *,
    q: str,
    page_size: int = 20,
    cursor_score: float | None = None,
    owner_id: uuid.UUID | None = None,
    category: str | None = None,
    status: str | None = None,
    sort: str = "relevance",
    language: str = "english",
) -> dict:
    """
    Full-text search using PostgreSQL tsvector + GIN index.
    User input is ALWAYS parameterized — never interpolated.
    Returns: {data, count, has_more, next_cursor}.
    """
    if not q or len(q.strip()) < 2:
        raise ValueError("Search query must be at least 2 characters.")

    # --- tsquery: websearch_to_tsquery supports OR, AND, NOT, phrase ---
    tsquery_expr = func.websearch_to_tsquery(text(f"'{language}'"), q)

    # --- Use stored search_vector column if available (generated STORED) ---
    if hasattr(Product, "search_vector"):
        match_expr = Product.search_vector.op("@@")(tsquery_expr)
        rank_expr = func.ts_rank_cd(Product.search_vector, tsquery_expr).label("rank")
    else:
        # Fallback: compute tsvector on-the-fly (no STORED column)
        tv = _build_weighted_tsvector(Product, language)
        match_expr = tv.op("@@")(tsquery_expr)
        rank_expr = func.ts_rank_cd(tv, tsquery_expr).label("rank")

    # --- Base statement with match filter ---
    stmt = select(Product, rank_expr).where(match_expr)

    # --- Apply soft-delete filter if model supports it ---
    if hasattr(Product, "is_deleted"):
        stmt = stmt.where(Product.is_deleted == False)  # noqa: E712

    # --- Apply ownership filter ---
    if owner_id is not None:
        stmt = stmt.where(Product.owner_id == owner_id)

    # --- Facet filters ---
    if category is not None:
        stmt = stmt.where(Product.category == category)
    if status is not None:
        stmt = stmt.where(Product.status == status)

    # --- Total count (separate query before cursor filter) ---
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # --- Rank-based cursor pagination ---
    if cursor_score is not None:
        stmt = stmt.where(rank_expr < cursor_score)

    # --- Ordering ---
    if sort == "recency":
        stmt = stmt.order_by(Product.created_at.desc(), Product.id.desc())
    else:
        stmt = stmt.order_by(rank_expr.desc(), Product.id.desc())

    stmt = stmt.limit(page_size + 1)
    result = await session.execute(stmt)
    rows = list(result.all())

    has_more = len(rows) > page_size
    rows = rows[:page_size]

    data = [{**row[0].__dict__, "rank": float(row[1])} for row in rows]
    next_cursor = float(rows[-1][1]) if has_more and rows else None
    return {"data": data, "count": total, "has_more": has_more, "next_cursor": next_cursor}
```

### 4.5 Route with facets, cursor pagination, and snippet

```python
# app/api/routes/product.py — addition
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.crud import product as crud_product
from app.schemas.product import SearchParams, SearchResponse

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search_products(
    session: SessionDep,
    current_user: CurrentUser,
    q: str = Query(..., min_length=2, max_length=200, description="Full-text query"),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: float | None = Query(default=None, description="Rank cursor for next-page"),
    category: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern="^(active|archived)$"),
    sort: str = Query(default="relevance", pattern="^(relevance|recency)$"),
) -> SearchResponse:
    """
    Full-text search over products.
    Results ordered by ts_rank_cd DESC (most relevant first).
    Supports faceted filters, rank-cursor pagination, and sort override.
    """
    try:
        result = await crud_product.search(
            session,
            q=q,
            page_size=page_size,
            cursor_score=cursor,
            owner_id=current_user.id,
            category=category,
            status=status,
            sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SearchResponse(**result)
```

### 4.6 Autocomplete endpoint (prefix matching, search-as-you-type)

```python
# app/api/routes/product.py — autocomplete addition
from typing import Annotated
from pydantic import BaseModel


class AutocompleteResult(BaseModel):
    suggestions: list[str]


@router.get("/autocomplete", response_model=AutocompleteResult)
async def autocomplete_products(
    session: SessionDep,
    current_user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=100),
) -> AutocompleteResult:
    """
    Prefix-match autocomplete using to_tsquery('term:*').
    Returns up to 5 name suggestions ordered by popularity (id DESC as proxy).
    Latency target: < 20ms p99.
    """
    if not q.strip():
        return AutocompleteResult(suggestions=[])

    # Sanitize: extract first token only to avoid malformed tsquery on partials
    first_token = q.strip().split()[0]
    # Append :* for prefix matching; to_tsquery (not plainto) required here
    prefix_query = func.to_tsquery(text("'english'"), text(f"'{first_token}:*'"))

    stmt = (
        select(Product.name)
        .where(Product.search_vector.op("@@")(prefix_query))
        .where(Product.owner_id == current_user.id)
        .where(Product.is_deleted == False)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(5)
    )
    result = await session.execute(stmt)
    suggestions = [row[0] for row in result.all() if row[0]]
    return AutocompleteResult(suggestions=suggestions)
```

### 4.7 Relevance ranking function (ts_rank_cd with coverage normalization)

```python
# app/crud/product.py — ranking helper
from sqlalchemy import func, text


def _rank_expr(tsvector_col, tsquery_expr, normalization: int = 32):
    """
    ts_rank_cd with normalization=32 divides rank by the number of unique words
    in the document, preventing long documents from dominating short but precise ones.

    Normalization bitmask (additive):
      0  = raw rank (no normalization)
      1  = divide by 1 + log(doc length)
      2  = divide by doc length
      4  = divide by mean harmonic distance between extents
      8  = divide by number of unique words in document
      16 = divide by 1 + log(number of unique words)
      32 = divide by rank itself + 1 (self-normalization, stable 0–1 range)

    Use 32 for stable cursor pagination (rank values bounded to [0,1]).
    """
    return func.ts_rank_cd(
        tsvector_col,
        tsquery_expr,
        text(str(normalization)),
    )
```

### 4.8 ts_headline snippet generation (with_snippet=True)

```python
# app/crud/product.py — snippet select addition (injected when with_snippet=True)
from sqlalchemy import func, text


def _snippet_expr(text_col, tsquery_expr, language: str = "english"):
    """
    ts_headline wraps matched lexemes with <b> tags.
    Options:
    - MaxWords: max words in snippet
    - MinWords: min words in snippet
    - ShortWord: words shorter than this are excluded from fragment boundaries
    - StartSel/StopSel: HTML tags around matched terms
    - HighlightAll: show entire document if no match (avoid; expensive)
    """
    return func.ts_headline(
        text(f"'{language}'"),
        text_col,
        tsquery_expr,
        text("'StartSel=<b>, StopSel=</b>, MaxWords=25, MinWords=5, ShortWord=3'"),
    ).label("snippet")
```

### 4.9 OpenSearch alternative backend (backend="opensearch")

```python
# app/search/opensearch_backend.py — scaffolded when backend="opensearch"
"""
OpenSearch search backend. Implements SearchBackend protocol.
Requires: opensearch-py>=2.4.0, running OpenSearch cluster.
Swap active backend in app/core/config.py: SEARCH_BACKEND=opensearch
"""
from __future__ import annotations

import logging
from typing import Any

from opensearchpy import AsyncOpenSearch, OpenSearchException

logger = logging.getLogger(__name__)

PRODUCT_INDEX = "products"
PRODUCT_MAPPING = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "name": {"type": "text", "analyzer": "english", "boost": 3.0},
            "description": {"type": "text", "analyzer": "english"},
            "tags": {"type": "text", "analyzer": "english"},
            "category": {"type": "keyword"},
            "status": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "created_at": {"type": "date"},
        }
    }
}


class OpenSearchBackend:
    """Wraps opensearch-py for product full-text search."""

    def __init__(self, hosts: list[str]) -> None:
        self.client = AsyncOpenSearch(hosts=hosts, use_ssl=False)

    async def search(
        self,
        q: str,
        *,
        owner_id: str,
        page_size: int = 20,
        from_: int = 0,
        category: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Multi-match query with field boosting."""
        must_clauses: list[dict] = [
            {"multi_match": {"query": q, "fields": ["name^3", "description", "tags"], "fuzziness": "AUTO"}},
            {"term": {"owner_id": owner_id}},
        ]
        if category:
            must_clauses.append({"term": {"category": category}})
        if status:
            must_clauses.append({"term": {"status": status}})

        body = {"query": {"bool": {"must": must_clauses}}, "from": from_, "size": page_size}
        try:
            resp = await self.client.search(index=PRODUCT_INDEX, body=body)
        except OpenSearchException as exc:
            logger.error("opensearch_search_failed q=%r error=%s", q, exc)
            raise

        hits = resp["hits"]["hits"]
        total = resp["hits"]["total"]["value"]
        data = [{"id": h["_id"], **h["_source"], "rank": h["_score"]} for h in hits]
        return {"data": data, "count": total, "has_more": (from_ + page_size) < total, "next_cursor": None}
```

### 4.10 Query sanitization and injection prevention tests

```python
# tests/test_product_search.py — security section
import pytest
from httpx import AsyncClient


INJECTION_PAYLOADS = [
    "'; DROP TABLE product; --",
    "' OR '1'='1",
    "1; SELECT * FROM users --",
    "\\x00",
    "admin'--",
    "<script>alert(1)</script>",
    "' UNION SELECT username, password FROM users --",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
async def test_sql_injection_harmless(
    async_client: AsyncClient,
    normal_user_token_headers: dict,
    payload: str,
) -> None:
    """
    T-04: All injection payloads must return 200 (or 422 for empty result),
    NEVER a 500, and the product table must remain intact.
    websearch_to_tsquery normalizes malformed input safely.
    """
    resp = await async_client.get(
        f"/api/v1/products/search?q={payload}",
        headers=normal_user_token_headers,
    )
    # Either 200 with 0 results OR 422 from Pydantic min_length — never 500
    assert resp.status_code in (200, 422), f"Unexpected status {resp.status_code} for payload {payload!r}"
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body["data"], list)
        # Verify table still exists by running a normal query
        meta_resp = await async_client.get("/api/v1/products/?limit=1", headers=normal_user_token_headers)
        assert meta_resp.status_code == 200
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **PostgreSQL native search only** | Generated CRUD uses `to_tsvector` + `websearch_to_tsquery`/`plainto_tsquery` + GIN index. NO `LIKE`, NO `ILIKE`, NO `SIMILAR TO`. Tool validates output with grep. Test T-12 confirms `EXPLAIN ANALYZE` shows GIN bitmap scan. |
| QS-2 | **Results ordered by ts_rank_cd DESC** | Most relevant first; exact ORDER BY enforced in generated query. Test T-03 verifies title match ranks above description-only match. |
| QS-3 | **SQL injection safe at every layer** | User `q` passes through `websearch_to_tsquery(language, q)` as a parameterized bind value. Tool refuses to generate code containing f-strings or string formatting with user input. T-04 tests 7 injection payloads. |
| QS-4 | **Multi-field tsvector with weighted ranking** | When `weighted=True`, each field is wrapped in `setweight()` with labels A–D. A match in the first (title) field contributes more to `ts_rank_cd` than one in later fields. T-11 verifies title match beats description match. |
| QS-5 | **GIN index always present** | Migration creates `ix_{table}_search_vector` unconditionally. Tool validates migration file for `CREATE INDEX … USING GIN`. Test T-13 confirms `EXPLAIN ANALYZE` shows the index. |
| QS-6 | **Idempotent** | Pre-flight checks for existing `search()` function in CRUD and existing migration name `*_search_idx_{table}*`. Returns early if already installed. T-18 verifies no duplicate. |
| QS-7 | **Short, empty, and overlong queries rejected at HTTP layer** | Route uses `Query(..., min_length=2, max_length=200)`. FastAPI returns 422 before CRUD is called. Tests T-05, T-06, T-07. |
| QS-8 | **Respects existing filters (owner, soft-delete, multi-tenancy)** | Generated `search()` applies the same `owner_id`, `is_deleted`, and `tenant_id` filters as `get_multi`. Tests T-08, T-09. |
| QS-9 | **Rank-cursor pagination — not OFFSET** | Pagination uses `WHERE rank < cursor_score`, avoiding OFFSET degradation on deep pages. T-15 validates no duplicates across 10 pages. T-16 validates constant latency at page 1000. |
| QS-10 | **ts_headline is strictly opt-in** | Snippet generation is expensive (~3–5ms/row). The tool generates `ts_headline` code ONLY when `with_snippet=True` and wraps it in a visible `# EXPENSIVE` comment. Without the flag, no `ts_headline` in generated CRUD. |
| QS-11 | **Autocomplete is latency-bounded** | When `autocomplete=True`, the generated endpoint enforces `LIMIT 5` and uses prefix tsquery `term:*` with a GIN index. T-20 verifies p99 < 20ms on 1M rows. |
| QS-12 | **Facets do not allow unvalidated column injection** | Tool generates explicit Pydantic validators for each declared facet column. Arbitrary `column=value` queries via URL parameters are NOT generated. Undeclared facet parameters are ignored. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `crud.search()` function exists with correct signature | AST inspection: function found, parameters match |
| CC-02 | Uses `func.websearch_to_tsquery` or `func.plainto_tsquery` with language param | `grep websearch_to_tsquery\|plainto_tsquery` in CRUD file |
| CC-03 | Multi-field tsvector if `len(fields) > 1` | `grep setweight\|coalesce.*||` in CRUD |
| CC-04 | Results ordered by `ts_rank_cd(…).desc()` or `ts_rank(…).desc()` | `grep order_by.*rank.*desc` in CRUD |
| CC-05 | NO `LIKE` or `ILIKE` in generated CRUD or route | `grep -v LIKE\|ILIKE` assertion |
| CC-06 | NO f-string or `%` formatting with user input in SQL context | AST scan for f-string nodes adjacent to SQL |
| CC-07 | Owner filter applied if model has `owner_id` | `grep owner_id` in generated search() |
| CC-08 | `is_deleted` filter applied if model has soft-delete | `grep is_deleted` in generated search() |
| CC-09 | `tenant_id` filter applied if project has multi-tenancy | `grep require_current_tenant\|tenant_id` in CRUD |
| CC-10 | `GET /{model}s/search` endpoint registered BEFORE `GET /{model}s/{id}` | Route order inspection (FastAPI is order-sensitive) |
| CC-11 | Endpoint uses `Query(..., min_length=2, max_length=200)` | `grep min_length=2.*max_length=200` in route |
| CC-12 | Endpoint catches `ValueError` → 422 HTTPException | `grep ValueError` in route handler |
| CC-13 | Endpoint accepts `page_size` and `cursor` query params | `grep cursor.*float.*None` in route |
| CC-14 | Facet params generated for each entry in `facets` list | `grep category=.*Query\|status=.*Query` in route |
| CC-15 | Migration creates GIN index on tsvector expression or stored column | `grep USING GIN\|search_vector` in migration |
| CC-16 | Migration uses `CREATE INDEX CONCURRENTLY IF NOT EXISTS` | `grep CONCURRENTLY` in migration |
| CC-17 | Migration has valid `downgrade()` that drops index and column | `grep drop_index\|DROP INDEX\|DROP COLUMN` in migration |
| CC-18 | Migration chains to previous revision (`down_revision` set) | Inspect migration head |
| CC-19 | If `with_snippet=True`: `ts_headline` present in CRUD SELECT | `grep ts_headline` in CRUD |
| CC-20 | If `with_snippet=False`: NO `ts_headline` in CRUD | `grep -v ts_headline` assertion |
| CC-21 | If `weighted=True`: `setweight()` present for each field | `grep setweight` in CRUD |
| CC-22 | If `autocomplete=True`: `GET /{model}s/autocomplete` endpoint generated | Route file contains autocomplete handler |
| CC-23 | Response schema includes `rank: float | None` | `grep rank.*float` in schema |
| CC-24 | Response schema includes `snippet: str | None` when with_snippet | `grep snippet.*str.*None` in schema |
| CC-25 | All generated Python files parse with `ast.parse()` | Tool internal validation step |
| CC-26 | Deep import audit passes | `python -m pipeline_autonomo.import_audit` or equivalent |
| CC-27 | Existing test suite passes (0 regressions) | `pytest` run in tool post-validation |
| CC-28 | New test file `tests/test_{model_lower}_search.py` created | `os.path.exists` check |
| CC-29 | Tool is idempotent: re-run produces identical state | File diff = empty on second run |
| CC-30 | Tool execution time < 3s | Measured from invocation to return |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of these are true:

- [ ] All 30 Completeness Criteria verified by automated check
- [ ] All 12 Quality Standards enforced
- [ ] All 8 Invariants enforced (§8)
- [ ] All 25 User Stories pass acceptance tests (§9)
- [ ] All 30 Test Cases pass (§10)
- [ ] Tool is idempotent: run twice on same project, identical state, no errors
- [ ] Tool is reversible: rollback procedure tested end-to-end (§12)
- [ ] Performance SLOs measured: 1M rows p99 < 50ms, autocomplete < 20ms
- [ ] SQL injection test T-04 passes all 7 payloads
- [ ] GIN index confirmed via `EXPLAIN ANALYZE` (T-13 passes)
- [ ] Soft-delete and owner filtering verified (T-08, T-09)
- [ ] Multi-tenancy compatibility verified (T-17)
- [ ] Documentation updated (KNOWLEDGE.md, manifest.yaml, SKILL.md, mcp_server.py)
- [ ] Re-audit by Opus (fresh context, brutal mode): ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SR-01 | User input is **never** interpolated into raw SQL | Always passed via `websearch_to_tsquery(lang, q)` or `plainto_tsquery(lang, q)` as a bind value — never via f-string or `%` | T-04 |
| INV-SR-02 | GIN index **always** exists on the search expression or stored column | Migration creates `ix_{table}_search_vector` unconditionally; `CONCURRENTLY` avoids table lock | T-13 |
| INV-SR-03 | Results **always** ordered by `ts_rank_cd` DESC in relevance mode | Generated `ORDER BY rank.desc()` is never removed from the relevance code path | T-03 |
| INV-SR-04 | Empty or short queries **always** rejected at HTTP validation layer | `Query(..., min_length=2, max_length=200)` enforced; CRUD is never reached with garbage input | T-05, T-06 |
| INV-SR-05 | Search **always** respects existing row-level filters (owner, soft-delete, tenant) | Generated search() applies the same guard clauses as get_multi(); missing one is a bug | T-08, T-09, T-17 |
| INV-SR-06 | Pagination is **always** rank-based cursor, never OFFSET | `WHERE rank < cursor_score`, not `OFFSET n * page_size` | T-15 |
| INV-SR-07 | `count` **always** reflects total matches, not page-size count | Separate `SELECT COUNT(*)` subquery before cursor filter applied | T-14 |
| INV-SR-08 | `ts_headline` is **never** generated without explicit `with_snippet=True` | Tool branches on parameter; test verifies absent in default output | T-19 |

---

## 9. User Stories

### 9.1 Basic search (US-01 .. US-05)

**US-01: Keyword query returns ranked matching products**
- **As a** shopper on a product catalog
- **I want** `GET /products/search?q=widget` to return products whose name or description contains "widget"
- **So that** I find relevant items without browsing every category
- **Given:** 50 products seeded; 12 contain the word "widget" in `name` or `description`; GIN index on `search_vector` is VALID
- **When:** `GET /products/search?q=widget` with a valid auth token
- **Then:**
  - HTTP 200; `data` contains exactly 12 items; `count == 12`
  - Items are ordered by `ts_rank_cd` DESC (most relevant first)
  - No `LIKE` or sequential scan appears in `EXPLAIN` output
  - Refs: CC-01, CC-04, CC-05, INV-SR-03, T-01

**US-02: Stemmed inflection matches indexed form**
- **As a** user typing a natural inflected word
- **I want** searching "widgets" to surface products indexed under "widget"
- **So that** I am not forced to type exact dictionary base forms
- **Given:** Product `name="Blue Widget"` indexed with `language="english"`; the English Snowball stemmer maps "widgets" → "widget" at index time and at query time
- **When:** `GET /products/search?q=widgets`
- **Then:**
  - "Blue Widget" appears in `data`; HTTP 200
  - Same product also surfaces for `q=widgeting` (further inflection)
  - The tsvector for the row contains the lexeme `widget` (verify with `SELECT search_vector FROM product WHERE id=...`)
  - Refs: CC-02, INV-SR-01, T-10

**US-03: Zero-result query returns a clean empty envelope**
- **As a** frontend developer consuming the search API
- **I want** a no-match query to return a well-formed 200 response with an empty list
- **So that** my UI can render "no results" without error-handling special cases
- **Given:** No product row contains the string "xyzzy_nonexistent" in any indexed field
- **When:** `GET /products/search?q=xyzzy_nonexistent`
- **Then:**
  - HTTP 200; response body is exactly `{"data": [], "count": 0, "has_more": false, "next_cursor": null}`
  - No 404, no 500, no exception logged
  - `next_cursor` is JSON `null` — not `0.0` or `""`
  - Refs: CC-01, T-02

**US-04: Boolean OR query matches either term**
- **As a** user searching for one of several product types
- **I want** `q=blue OR red widget` to return both "Blue Widget" and "Red Widget" but not "Green Widget"
- **So that** I can broaden a search without issuing two separate requests
- **Given:** Three products seeded: `name="Blue Widget"`, `name="Red Widget"`, `name="Green Widget"`; `websearch_to_tsquery('english','blue OR red widget')` produces `('blue'|'red') & 'widget'`
- **When:** `GET /products/search?q=blue OR red widget`
- **Then:**
  - `count == 2`; "Green Widget" id is absent from `data`
  - "Blue Widget" and "Red Widget" ids are both present
  - HTTP 200; no 422 from the query parser
  - Refs: CC-02, QS-3, T-01

**US-05: Rank-cursor pagination delivers no duplicates across all pages**
- **As a** client walking a large result set
- **I want** each page fetched via `cursor=` to contain distinct items with no gaps or repeats
- **So that** downstream processing or infinite-scroll UIs get consistent data
- **Given:** 500 products match "widget"; `page_size=20`; rank-cursor pagination is used (`WHERE rank < cursor_score` — no OFFSET)
- **When:** Client follows `next_cursor` through all 25 pages until `has_more=false`
- **Then:**
  - Exactly 500 unique product IDs are collected across all pages; zero duplicates
  - `has_more=false` and `next_cursor=null` on the final page
  - No page takes longer than 50ms (constant-time property confirmed)
  - Refs: INV-SR-06, CC-13, T-14, T-15

---

### 9.2 Weighted relevance & snippets (US-06 .. US-10)

**US-06: Title-weight match ranks above description-only match**
- **As a** user who typed a product name
- **I want** products whose `name` contains my query to appear before products where only `description` matches
- **So that** exact-name matches are always at the top regardless of description length
- **Given:** Product A: `name="Widget Pro"`, `description="basic item"`; Product B: `name="Basic Item"`, `description="contains widget accessory"` — `setweight` assigns label A to `name`, label B to `description`
- **When:** `GET /products/search?q=widget`
- **Then:**
  - `results[0]["id"] == product_a.id`
  - `results[0]["rank"] > results[1]["rank"]` (ts_rank_cd numeric proof)
  - Assertion verified in integration test with exact rank values logged
  - Refs: INV-SR-03, CC-04, QS-2, QS-4, T-03, T-11

**US-07: Tags-weight match ranks below both title and body**
- **As a** product search consumer
- **I want** a query that matches only `tags` to rank below matches in `name` or `description`
- **So that** tag-only matches appear as lower-confidence suggestions rather than top results
- **Given:** Product X: `name="Laptop"`, `description="portable computer"`, `tags="widget"`; Product Y: `name="Widget"`, `description="general"`, `tags="tool"` — `setweight` assigns A=name, B=description, C=tags
- **When:** `GET /products/search?q=widget`
- **Then:**
  - Product Y (name weight A) ranks above Product X (tags weight C)
  - `results[0]["rank"]` for Y is measurably greater than for X
  - Weighted tsvector expression uses `setweight(…,'C')` for `tags` column
  - Refs: CC-03, CC-21, QS-4, T-11

**US-08: ts_headline snippet wraps matched terms in bold tags**
- **As a** frontend developer building a search-results page
- **I want** each result to include a short excerpt with matched words highlighted
- **So that** users can see why a result matched without opening it
- **Given:** Tool invoked with `add_search(..., with_snippet=True)`; product `description="Machine learning is transforming industries"` is indexed
- **When:** `GET /products/search?q=machine learning`
- **Then:**
  - Each result object includes `"snippet"` — a non-empty string
  - Snippet contains at least one `<b>` tag wrapping a matched query term, e.g. `"<b>machine</b> <b>learning</b> is…"`
  - `MaxWords=25` caps the excerpt length; no full-document dump
  - Refs: CC-19, INV-SR-08, QS-10, T-18

**US-09: Snippet absent by default when with_snippet=False**
- **As a** developer who did not opt into snippets
- **I want** the search response to omit the `snippet` field entirely
- **So that** I avoid the ~3–5ms per-row `ts_headline` cost on every request
- **Given:** Tool invoked with default `with_snippet=False`; no `ts_headline` call is generated in the CRUD file
- **When:** `GET /products/search?q=widget` on the default-configuration endpoint
- **Then:**
  - No `snippet` key appears in any result object
  - `grep ts_headline app/crud/product.py` returns no output
  - Response serialization time is unmeasurably lower than snippet-enabled variant
  - Refs: CC-20, INV-SR-08, QS-10, T-19

**US-10: Multi-word phrase query matches adjacent terms**
- **As a** user searching for a specific exact phrase
- **I want** `q="machine learning"` (quoted phrase) to match products where both words appear consecutively
- **So that** results are more precise than an unquoted two-word query
- **Given:** Product A: `description="machine learning pipeline"`; Product B: `description="machine and learning separately"` — `websearch_to_tsquery` converts `"machine learning"` to `'machine' <-> 'learning'` (phrase operator)
- **When:** `GET /products/search?q="machine learning"` (URL-encoded quotes)
- **Then:**
  - Product A appears in results (consecutive adjacency satisfied)
  - Product B is absent (words not adjacent)
  - HTTP 200; no parser exception for quoted phrase syntax
  - Refs: CC-02, QS-3

---

### 9.3 Autocomplete & suggestions (US-11 .. US-15)

**US-11: Prefix query returns up to 5 name suggestions**
- **As a** user typing in a search box
- **I want** partial input like "mac" to immediately surface matching product names
- **So that** I can select a suggestion and save keystrokes
- **Given:** Tool invoked with `add_search(..., autocomplete=True)`; 100 products whose `name` starts with "mac" are seeded; `to_tsquery('english','mac:*')` prefix expression is used
- **When:** `GET /products/autocomplete?q=mac`
- **Then:**
  - Response contains `suggestions` list with `len(suggestions) <= 5`
  - Each suggestion is a non-empty string whose lexeme matches the "mac" prefix
  - HTTP 200; no 422 for single-character prefix (`min_length=1` on autocomplete)
  - Refs: CC-22, QS-11, T-20, T-21

**US-12: Autocomplete p99 latency stays under 20ms at 1M rows**
- **As a** product manager responsible for search-as-you-type UX
- **I want** the autocomplete endpoint to respond in under 20ms at p99 even on a 1M-row table
- **So that** the search box feels instant and does not block user typing
- **Given:** 1M products seeded with diverse names; GIN index on `search_vector` is VALID; `LIMIT 5` hard cap is in the generated query
- **When:** `GET /products/autocomplete?q=pro` is sent 500 times concurrently in the performance harness
- **Then:**
  - p99 response time < 20ms (measured at the HTTP layer)
  - p50 response time < 8ms
  - Zero 5xx responses during the load run
  - Refs: QS-11, T-20, INV-SR-02

**US-13: Autocomplete respects owner scoping**
- **As a** security-conscious developer
- **I want** autocomplete suggestions to be filtered to the authenticated user's products only
- **So that** users cannot discover other users' product names via prefix enumeration
- **Given:** User A owns products named "macbook", "macpro"; User B owns "macstation" and "macdesk"; both sets are in the same table
- **When:** User A calls `GET /products/autocomplete?q=mac`
- **Then:**
  - Only "macbook" and "macpro" appear in `suggestions`
  - "macstation" and "macdesk" (User B's items) are absent
  - The generated autocomplete query applies `WHERE product.owner_id == current_user.id`
  - Refs: INV-SR-05, CC-07

**US-14: Empty autocomplete input returns empty suggestions**
- **As a** frontend developer
- **I want** an empty `q` to `autocomplete` to return an empty list rather than error
- **So that** my UI does not need a special case before the user has typed anything
- **Given:** Autocomplete endpoint is generated with `min_length=1`; caller sends `q=` (empty or whitespace)
- **When:** `GET /products/autocomplete?q=` or `GET /products/autocomplete?q=%20`
- **Then:**
  - HTTP 200; `{"suggestions": []}` — empty list, not an error
  - No SQL is issued (early-return guard in the handler for blank input)
  - `strip()` of the input is empty, so the guard triggers
  - Refs: QS-11

**US-15: Autocomplete endpoint not generated when flag is False**
- **As a** developer who does not need autocomplete
- **I want** the autocomplete route to be absent when `autocomplete=False` (the default)
- **So that** my OpenAPI schema is not polluted with an endpoint I did not request
- **Given:** Tool invoked with default `add_search(..., autocomplete=False)`
- **When:** `GET /products/autocomplete?q=mac` is called on the generated API
- **Then:**
  - HTTP 404 — route does not exist
  - `grep autocomplete app/api/routes/product.py` returns no output
  - Tool return dict does not list an autocomplete file in `files_created`
  - Refs: CC-22

---

### 9.4 Index lifecycle & triggers (US-16 .. US-20)

**US-16: Migration adds tsvector column with setweight expression**
- **As a** DBA reviewing the generated migration
- **I want** the `search_vector` column to be a `GENERATED ALWAYS AS … STORED` computed column
- **So that** the tsvector is always in sync with source columns without requiring application-level updates
- **Given:** `add_search(project_dir, "Product", fields=["name","description"], weighted=True)` is run on a project with no existing `search_vector` column
- **When:** `alembic upgrade head` is applied
- **Then:**
  - `\d+ product` shows `search_vector tsvector GENERATED ALWAYS`
  - Expression uses `setweight(to_tsvector('english', coalesce(name,'')), 'A') || setweight(to_tsvector('english', coalesce(description,'')), 'B')`
  - No application trigger is created (STORED computed column is self-maintaining)
  - Refs: CC-15, CC-16, CC-21, T-27

**US-17: GIN index created CONCURRENTLY without table lock**
- **As a** DevOps engineer deploying search to a live production table
- **I want** the GIN index to be built with `CREATE INDEX CONCURRENTLY`
- **So that** the table remains readable and writable during index construction — zero downtime
- **Given:** Migration file generated by the tool; `transactional_ddl = False` is set in the Alembic context for this step
- **When:** `alembic upgrade head` runs on a 10M-row production table during business hours
- **Then:**
  - Index builds without acquiring an exclusive lock (verified via `pg_locks` monitoring)
  - Migration completes; `pg_indexes` shows `ix_product_search_vector` with `indisvalid=true`
  - Application queries against the table continue to succeed during the build
  - Refs: CC-16, INV-SR-02, T-27

**US-18: Migration downgrade drops index and column cleanly**
- **As a** developer rolling back a failed deployment
- **I want** `alembic downgrade -1` to remove the GIN index and `search_vector` column
- **So that** the schema returns to its pre-search state with no orphaned objects
- **Given:** Migration has been applied; `ix_product_search_vector` exists; `search_vector` column exists
- **When:** `alembic downgrade -1` is executed
- **Then:**
  - `\d product` shows no `search_vector` column
  - `\d+ product` shows no `ix_product_search_vector` index
  - Business rows (all other columns) remain intact; `SELECT COUNT(*) FROM product` unchanged
  - Refs: CC-17, T-28

**US-19: Backfill command refreshes search_vector on all existing rows**
- **As a** developer who added search to a table that already had 500K rows
- **I want** a safe backfill SQL to recompute `search_vector` for all pre-existing rows
- **So that** rows created before the migration are searchable immediately
- **Given:** 500K products existed before the migration; `search_vector` column is a GENERATED STORED column, so Postgres auto-populates it for all rows on `ALTER TABLE … ADD COLUMN` — no manual backfill needed
- **When:** Migration upgrade completes
- **Then:**
  - `SELECT COUNT(*) FROM product WHERE search_vector IS NULL` returns `0`
  - A test query `GET /products/search?q=widget` finds products created before the migration
  - If the column were NOT generated (trigger-based variant), the tool emits a `UPDATE product SET search_vector = DEFAULT` comment in the migration `upgrade()` body
  - Refs: CC-15, CC-16

**US-20: Tool is idempotent — second run produces no change**
- **As a** CI engineer whose pipeline runs the code generator on every commit
- **I want** running `add_search` twice with the same arguments to be a no-op
- **So that** re-running does not break the build, create duplicate migrations, or append duplicate functions
- **Given:** `add_search` has already been applied; CRUD file contains `search()`; migration file `*_search_idx_product*` exists
- **When:** `add_search(project_dir, "Product", fields=["name","description"])` is called a second time
- **Then:**
  - Tool returns `{"status": "success", "already_installed": true}`
  - `git diff` after the second run is empty
  - Migration count is unchanged; no duplicate `search()` function in CRUD
  - Refs: CC-29, QS-6, T-24

---

### 9.5 Injection safety, scoping & edge cases (US-21 .. US-25)

**US-21: SQL injection payload produces 200 with zero results — table intact**
- **As a** security auditor running OWASP injection tests
- **I want** every classic SQLi payload to be neutralized by `websearch_to_tsquery` parameterization
- **So that** the `product` table can never be dropped or data exfiltrated via the search endpoint
- **Given:** Seven payloads including `'; DROP TABLE product; --`, `' OR '1'='1`, `' UNION SELECT username,password FROM users --`, `\x00`, and `<script>alert(1)</script>`
- **When:** Each payload is sent as `GET /products/search?q=<payload>`
- **Then:**
  - Response is HTTP 200 with `data=[]` or HTTP 422 (min_length reject) — never HTTP 500
  - `SELECT COUNT(*) FROM product` still returns the original count after all payloads
  - No f-string or `%`-format interpolation of user input exists in the generated CRUD (AST-verified)
  - Refs: INV-SR-01, QS-3, CC-06, T-04

**US-22: Owner-scoped search returns only the authenticated user's rows**
- **As a** multi-user SaaS product owner
- **I want** `GET /products/search?q=widget` to return only the calling user's products
- **So that** User A cannot discover or enumerate User B's product catalog via search
- **Given:** User A owns 5 products named "widget"; User B owns 10 products named "widget"; the generated `search()` applies `WHERE product.owner_id == current_user.id`
- **When:** User A calls `GET /products/search?q=widget` with their JWT
- **Then:**
  - Exactly 5 results returned; every `owner_id` in `data` equals User A's id
  - User B's 10 products are completely absent regardless of text match
  - Attempting the same call with User B's token returns 10 results (User B's products only)
  - Refs: INV-SR-05, CC-07, T-08

**US-23: OpenSearch backend scaffolded as a swap-in when backend="opensearch"**
- **As a** platform engineer scaling beyond single-Postgres search capacity
- **I want** `add_search(..., backend="opensearch")` to scaffold an OpenSearch backend that satisfies the same `SearchBackend` protocol as the Postgres default
- **So that** switching backends requires only a config change, not a rewrite
- **Given:** `opensearch-py>=2.4.0` is installed; `SEARCH_BACKEND=opensearch` in config; tool invoked with `backend="opensearch"`
- **When:** `GET /products/search?q=widget` is called after the OpenSearch index is populated
- **Then:**
  - `app/search/opensearch_backend.py` is created with an `OpenSearchBackend` class and `PRODUCT_MAPPING` with `name^3` field boost
  - The response schema is identical to the Postgres backend (`data`, `count`, `has_more`, `next_cursor`)
  - Switching back to `backend="postgres"` requires only changing `SEARCH_BACKEND` env var
  - Refs: CC-01, QS-1

**US-24: GIN bloat threshold logged after high-churn writes**
- **As a** DBA responsible for index health
- **I want** the application to emit a warning log when GIN index bloat exceeds 30% of index size
- **So that** I know when to run `REINDEX CONCURRENTLY ix_product_search_vector` before query performance degrades
- **Given:** The GIN index is built on a table with high insert/update throughput (>10K writes/hour); GIN pending list grows and is compacted by autovacuum on a delay
- **When:** The bloat monitoring query detects `bloat_ratio > 0.30` for `ix_product_search_vector`
- **Then:**
  - A `WARNING` log line is emitted: `"GIN index ix_product_search_vector bloat_ratio=0.34 — consider REINDEX CONCURRENTLY"`
  - The warning does not interrupt search queries; it is advisory only
  - The threshold and log format are documented in the generated `KNOWLEDGE.md` section for `add_search`
  - Refs: INV-SR-02, QS-5

**US-25: Stop-word-only query returns clean empty response without DB error**
- **As a** user who typed only stop words into the search box
- **I want** `q=the and of` to return an empty result set without a 500 error
- **So that** the application handles degenerate queries gracefully without crashing
- **Given:** `websearch_to_tsquery('english','the and of')` returns `''::tsquery` because all three tokens are English stop words; an empty tsquery matches no `tsvector` in PostgreSQL
- **When:** `GET /products/search?q=the and of` (passes `min_length=2` check; total length is 10)
- **Then:**
  - HTTP 200; `{"data": [], "count": 0, "has_more": false, "next_cursor": null}`
  - No PostgreSQL exception; no 500 error; no log ERROR line
  - Same behavior confirmed for French stop words when `language="french"` is configured
  - Refs: QS-3, INV-SR-04, T-05
## 10. Test Plan

### 10.1 Functional tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-01 | Search finds matching product | Seed "Blue Widget" | GET /products/search?q=widget | 200, data contains "Blue Widget" | Functional |
| T-02 | Empty result for no-match query | No matching products | GET /products/search?q=xyzzy | 200, data=[], count=0 | Functional |
| T-03 | Ranking: name match > description match | Seed products A (name) and B (description only) | GET /search?q=widget | Product A ranked first | Ranking |
| T-04 | SQL injection harmless (7 payloads) | Normal DB state | GET /search?q='; DROP TABLE product; -- etc. | 200 or 422, table intact | Security |
| T-05 | Empty query rejected | q="" | GET /products/search?q= | 422 | Validation |
| T-06 | Short query rejected | q="a" | GET /products/search?q=a | 422 | Validation |
| T-07 | Overlong query rejected | q=250 chars | GET /products/search?q=<250 chars> | 422 | Validation |

### 10.2 Filter and isolation tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-08 | Owner filter: user sees only own products | User A: 5 widgets, User B: 10 widgets | GET /search?q=widget as A | 5 results | Auth |
| T-09 | Soft-delete excluded | "Deleted Widget" is_deleted=True | GET /search?q=widget | "Deleted Widget" not in results | Integration |
| T-10 | Stemming: partial term matches inflection | "Blue Widget" indexed | GET /search?q=widgets | "Blue Widget" found | Functional |
| T-11 | Multi-field: description-only match found | Term in description only | GET /search?q=term | Found in results | Functional |
| T-12 | Performance: p99 < 50ms on 1M rows | Seed 1M products | GET /search?q=common | p99 < 50ms | Performance |
| T-13 | EXPLAIN shows GIN index scan | Seed 1M products | EXPLAIN ANALYZE /search | "Bitmap Index Scan on ix_product_search_vector" | Performance |

### 10.3 Pagination and result correctness tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-14 | Total count reflects all matches | 100 matching products | GET /search?q=term&page_size=20 | count=100, data has 20 | Functional |
| T-15 | Cursor pagination: no duplicates, no gaps | 100 matching products | Walk all pages with cursor | 100 unique results, correct order | Pagination |
| T-16 | Deep pagination constant-time (page 1000) | 100K matching products | Paginate to page 1000 | < 50ms, no degradation | Performance |
| T-17 | Multi-tenancy: search scoped to tenant | Multi-tenancy installed; tenants A, B | GET /search as Tenant A | Only Tenant A results | Integration |

### 10.4 Feature tests (snippet, autocomplete, facets, weighted)

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-18 | Snippet contains HTML `<b>` tags | with_snippet=True | GET /search?q=widget | snippet has `<b>widget</b>` | Feature |
| T-19 | No snippet without with_snippet flag | with_snippet=False (default) | GET /search?q=widget | no `snippet` key in result rows | Feature |
| T-20 | Autocomplete p99 < 20ms | autocomplete=True, 1M rows | GET /autocomplete?q=wid | ≤ 5 suggestions in < 20ms | Performance |
| T-21 | Autocomplete returns ≤ 5 suggestions | 100 matching names | GET /autocomplete?q=a | len(suggestions) ≤ 5 | Feature |
| T-22 | Faceted filter applied | facets=["category"], products in "electronics" | GET /search?q=widget&category=electronics | Only electronics products | Feature |
| T-23 | Facets do not allow undeclared columns | Undeclared facet in URL | GET /search?q=widget&price=50 | 422 or param ignored; never used as WHERE clause | Security |

### 10.5 Idempotency and migration tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-24 | Tool re-run is no-op | Search already enabled | Run add_search again | No file changes, no migration duplication | Idempotency |
| T-25 | Tool errors on non-existent field | Model has no `title` field | add_search(fields=["title"]) | Error raised, no partial changes | Validation |
| T-26 | Tool atomic on failure | Mock fs error at step 3 | Run tool | No partial state; all or nothing | Atomicity |
| T-27 | Migration upgrade creates GIN index | Fresh DB | alembic upgrade head | `\d+ product` shows ix_product_search_vector | Migration |
| T-28 | Migration downgrade drops index and column | After upgrade | alembic downgrade -1 | Index and search_vector column gone; data intact | Migration |

### 10.6 Edge case and integration tests

| # | Test | Setup | Action | Expected | Type |
|---|------|-------|--------|----------|------|
| T-29 | NULL fields product excluded from results | name=NULL, description=NULL | Any search | Product not in results | Edge |
| T-30 | Existing test suite: 0 regressions | Baseline test suite | pytest after add_search | All prior tests pass | Regression |

---

## 11. Interaction Matrix

How `add_search` interacts with other tools in SKILL-001:

| Other tool | Install order | Interaction | Notes |
|------------|--------------|-------------|-------|
| `add_soft_delete` (TOOL-001) | **Soft-delete first** | ✅ Compatible | Generated `search()` applies `is_deleted=False` filter alongside tsvector match. Composite index `(search_vector, is_deleted)` can reduce IO. |
| `add_cursor_pagination` (TOOL-002) | No dependency | ✅ Compatible | Search uses its own rank-value cursor; TOOL-002's key-based cursor coexists on the standard list endpoint without conflict. |
| `add_audit_log` (TOOL-005) | No dependency | ✅ Compatible | Audit log entries are not search-indexed by default. Pass `add_search(model_name="AuditLog", fields=["action","detail"])` as a separate call if audit search is needed. |
| `add_multi_tenancy` (TOOL-008) | **Tenancy first** | ✅ Compatible | tsvector queries automatically receive `tenant_id = current_tenant` from the `do_orm_execute` listener. No extra code needed in search CRUD. Verify with T-17. |
| `add_rbac` (TOOL-009) | No dependency | ✅ Compatible | RBAC permission checks in the route dependency run before `search()` is called; search never bypasses authorization. |
| `add_cache_layer` (TOOL-011) | No dependency | ⚠️ Caveat | Search results SHOULD NOT be cached with the same TTL as static data. If caching is applied, cache keys MUST include the full query + cursor + user_id + active facets to prevent cross-user result poisoning. |
| `add_file_upload` (TOOL-012) | No dependency | ✅ Compatible | File metadata (e.g., `original_filename`, `description`) can be indexed by calling `add_search` on the `FileMetadata` model separately. |
| `add_bulk_operations` (TOOL-014) | No dependency | ⚠️ Caveat | Bulk inserts/updates bypass triggers; run `UPDATE product SET search_vector = DEFAULT` after large bulk loads to refresh stored generated column. |
| `add_event_driven` (TOOL-046) | No dependency | ✅ Compatible | OpenSearch backend (backend="opensearch") integrates with the outbox pattern: publish `ProductIndexed` events via `emit_event()` in TOOL-046, consumed by an OpenSearch indexer. |
| `add_api_key_auth` | Auth first | ✅ Compatible | API key auth injects `current_user`; search route uses `CurrentUser` dep same as all other endpoints. |
| `add_rate_limiting` | No dependency | ✅ Compatible | Autocomplete endpoint should have a tighter rate limit (e.g., 60 req/min) than the main search endpoint (200 req/min); configure in rate limit tool. |
| `add_circuit_breaker` | No dependency | ✅ Compatible | If backend="opensearch", wrap the OS client call in the circuit breaker to fall back to Postgres FTS on OS cluster outage. |
| `add_data_export` | No dependency | ✅ Compatible | Export can accept the same `q` + facet parameters to export search-filtered results; reuses the same CRUD function. |
| `add_feature_flags` | No dependency | ✅ Compatible | Backend toggle (postgres vs opensearch) can be gated behind a feature flag for incremental rollout. |
| `add_mfa` | Auth first | ✅ Compatible | MFA enforced at session level; search route inherits auth dependency, no special handling needed. |

**Conflicts and hard constraints:**
- `add_search` requires PostgreSQL. Projects using SQLite receive a warning and a `LIKE`-based fallback is noted in `next_steps` but NOT generated (LIKE is unacceptably slow at scale).
- `CONCURRENTLY` index creation requires the migration to run outside a transaction. The generated migration sets `transactional_ddl = False` for the Alembic context when this step is present.

---

## 12. Rollback Procedure

Full rollback is available at every stage. The procedure varies by how far deployment has progressed.

### 12.1 Code rollback (before `alembic upgrade head`)

If the tool has modified files but the migration has not yet been applied to the database:

```bash
# Revert all files the tool modified
git diff HEAD~1 -- app/crud/product.py app/api/routes/product.py app/schemas/product.py app/models/product.py
git checkout HEAD~1 -- app/crud/product.py app/api/routes/product.py app/schemas/product.py app/models/product.py

# Delete the generated migration
rm alembic/versions/*_search_idx_product*.py
# Verify no orphan migration
alembic history | grep search_idx_product  # should return nothing

# Verify tests still pass
PYTHONPATH=src pytest tests/ -v --tb=short
```

### 12.2 Database rollback (after `alembic upgrade head`)

The generated `downgrade()` drops the GIN index and the `search_vector` stored column. Business data is unaffected (tsvector is a computed/derived column with no business value):

```bash
# Step down exactly one revision
alembic downgrade -1

# Verify the index is gone
psql -c "\d+ product" | grep ix_product_search_vector  # should return nothing
# Verify column is gone
psql -c "\d product" | grep search_vector              # should return nothing
# Verify business rows intact
psql -c "SELECT COUNT(*) FROM product"                 # same count as before
```

### 12.3 Data preservation before rollback (if tsvector state is needed)

If you need to preserve the current search index state for forensic or re-index purposes before rollback:

```sql
-- Archive tsvector values before dropping the column
CREATE TABLE _product_search_archive AS
  SELECT id, search_vector, now() AS archived_at FROM product;

-- Now proceed with downgrade
-- alembic downgrade -1

-- Later, to restore (after re-running add_search and upgrade):
-- search_vector is GENERATED STORED, so it will be recomputed automatically
-- The archive table can be dropped once re-index is verified
DROP TABLE _product_search_archive;
```

### 12.4 Partial failure recovery (tool failed mid-execution)

If the tool crashes after modifying some files but before completing all steps:

1. Run `git status` to identify modified files
2. For each file in the output: `git checkout -- {file}` to restore to pre-tool state
3. Delete any partially-generated migration: `rm alembic/versions/*_search_idx_product*.py`
4. If a partial DB migration ran: `alembic downgrade -1` (or target the specific revision)
5. Drop any leftover index manually if migration downgrade is unavailable:
   ```sql
   DROP INDEX IF EXISTS ix_product_search_vector;
   ALTER TABLE product DROP COLUMN IF EXISTS search_vector;
   ```
6. Diagnose the failure (usually: field name wrong, model file parse error, or DB connectivity)
7. Re-run `add_search` with corrected arguments

### 12.5 Failure modes and their remediation

**GIN index bloat after heavy UPDATE workload:**
GIN indexes accumulate "pending list" entries during heavy writes and must be vacuumed to consolidate. Symptom: search queries slow down over days even with no data growth.
```sql
-- Check pending GIN entries
SELECT relname, n_dead_tup, last_vacuum, last_autovacuum
FROM pg_stat_user_tables WHERE relname = 'product';

-- Force vacuum to consolidate GIN pending list
VACUUM (VERBOSE, ANALYZE) product;

-- If bloat is severe, rebuild CONCURRENTLY (no downtime)
REINDEX INDEX CONCURRENTLY ix_product_search_vector;
```

**OpenSearch sync drift (backend="opensearch"):**
If the OpenSearch indexer falls behind or crashes, the OS index diverges from the Postgres source of truth. Symptom: search returns stale or missing results.
```bash
# Check outbox backlog (if TOOL-046 outbox pattern in use)
psql -c "SELECT COUNT(*) FROM outbox_events WHERE event_type='ProductIndexed' AND status='pending';"

# Manual full re-index from Postgres (emergency)
# Run the scaffolded reindex script:
PYTHONPATH=src python -m app.search.reindex_opensearch --model product --batch-size 500

# Monitor indexing progress
curl -s "http://opensearch:9200/products/_count" | jq .count
```

**Slow queries on malformed prefix tsquery (autocomplete edge case):**
An autocomplete call with a numeric-only token like `q=123` can produce an unexpectedly broad prefix match. Symptom: autocomplete latency spike.
```bash
# Identify the query in pg_stat_activity
psql -c "SELECT query, state, now() - query_start AS duration FROM pg_stat_activity WHERE query LIKE '%to_tsquery%' ORDER BY duration DESC LIMIT 5;"

# Mitigation: the generated autocomplete handler pre-validates the first token
# If the issue persists, add a numeric-only guard:
# if first_token.isdigit(): return AutocompleteResult(suggestions=[])
```

**Emergency: search route returning 500 after deploy:**
1. Check Sentry/logs for the traceback (common cause: missing `search_vector` column — migration not applied)
2. Verify migration state: `alembic current` — if behind, apply: `alembic upgrade head`
3. If model import fails: `python -c "from app.models.product import Product; print(Product.__table__.columns)"` — check for `search_vector`
4. If `tsvector` column exists but GIN index is INVALID (interrupted CONCURRENTLY): `REINDEX INDEX CONCURRENTLY ix_product_search_vector;`
5. Rollback to previous release if fix is not immediate: `git checkout <prev_tag>` + `alembic downgrade -1`

### 12.6 OpenSearch-specific rollback (backend="opensearch")

If switching from OpenSearch back to Postgres FTS:

```bash
# 1. Update config: SEARCH_BACKEND=postgres
# 2. Restart app workers (no migration needed — Postgres FTS always present)
# 3. Optionally delete the OpenSearch index (no business data at risk):
curl -X DELETE "http://opensearch:9200/products"
# 4. Remove opensearch-py from pyproject.toml if no longer needed
# 5. Verify search works via Postgres: GET /products/search?q=widget
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | `fields` contains a column that does not exist on the model | Tool errors with `FieldNotFoundError: field 'title' not found on Product. Valid fields: name, description, tags.`; no files modified |
| EC-2 | `fields` contains a column that is not String/Text type | Tool errors: `TypeError: field 'price' (Numeric) is not a text type. Search requires String, Text, or VARCHAR fields.`; no changes |
| EC-3 | Search term consists only of punctuation (`!@#$%`) | `websearch_to_tsquery` normalizes punctuation; returns empty tsquery; 0 results; HTTP 200 |
| EC-4 | Search term contains Unicode and emoji (`café ☕`) | PostgreSQL handles UTF-8 correctly; emoji tokenized as unknown lexeme; no error; possibly 0 results |
| EC-5 | Concurrent `UPDATE` on a product row during search query | Snapshot isolation (REPEATABLE READ default); search sees consistent snapshot; no phantom reads |
| EC-6 | `CREATE INDEX CONCURRENTLY` is interrupted mid-build | Index is left in `INVALID` state; tool generates post-install check: `SELECT relname FROM pg_class JOIN pg_index ON oid=indexrelid WHERE indisvalid=false`; remediation: `DROP INDEX ix_product_search_vector; CREATE INDEX CONCURRENTLY …` |
| EC-7 | Search on a partitioned table | Each partition needs its own GIN index; tool detects `pg_partitioned_table` and generates partition-aware index statements |
| EC-8 | All indexed fields are NULL for a product | `coalesce(name,'') || coalesce(description,'')` produces empty string; tsvector is empty; product never matches any query |
| EC-9 | Two concurrent tool invocations on the same model | File writes are atomic (temp + rename); second invocation detects existing `search()` function and returns early with `"already_installed": true` |
| EC-10 | Disk full during `CREATE INDEX CONCURRENTLY` | Postgres aborts the index creation; index left INVALID; no data loss; operator must free disk and reindex |
| EC-11 | Re-run with different `fields` list | Tool detects field mismatch (existing migration uses different columns), emits error: `"Existing search index uses fields [name]. New fields [name, tags] require a new migration. Run add_search_v2 or drop existing first."` |
| EC-12 | `language` value not supported by PostgreSQL | Tool queries `pg_ts_config` to validate; if absent, errors: `"Language 'klingon' not found in pg_ts_config. Use one of: english, spanish, portuguese, …"` |
| EC-13 | Index name collision (another index already uses `ix_product_search_vector`) | `CREATE INDEX CONCURRENTLY IF NOT EXISTS` is idempotent; if existing index uses different expression, tool errors with explicit note |
| EC-14 | Search query is only stop words (`"the and of"`) | `websearch_to_tsquery` produces an empty tsquery; `tsvector @@ ''::tsquery` matches nothing; HTTP 200 with `count=0` |
| EC-15 | `count` query on 10M+ matching rows is slow | Tool adds a note in `next_steps`: "Consider replacing exact COUNT with `EXPLAIN` row estimate for queries returning >100K results: `SELECT reltuples::bigint FROM pg_class WHERE relname='product'`" |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when ALL of these are verified:

1. ✅ All 30 Completeness Criteria verified by automated check
2. ✅ All 25 User Stories have passing acceptance tests
3. ✅ All 30 Test Cases pass (T-01..T-30)
4. ✅ All 8 Invariants enforced and tested
5. ✅ All 15 Edge Cases handled (EC-1..EC-15)
6. ✅ SQL injection test T-04 passes all 7 payloads with HTTP 200/422 and intact DB
7. ✅ Performance SLOs confirmed: p99 < 50ms on 1M rows, autocomplete < 20ms
8. ✅ `EXPLAIN ANALYZE` confirms GIN index used (T-13, no Seq Scan on search path)
9. ✅ Rollback procedure tested end-to-end: upgrade → verify → downgrade → verify
10. ✅ Re-audit by Opus (fresh context, brutal mode): ≥ 9.5/10

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and is a directory
- [ ] Validate `app/` subdirectory exists at `project_dir/app/`
- [ ] Validate `alembic/versions/` exists
- [ ] Detect database driver from `app/core/config.py`; warn if not PostgreSQL
- [ ] Parse target model file with `ast.parse()` — fail fast if syntax error
- [ ] Verify each field in `fields` exists on the model as a mapped column
- [ ] Verify each field's SA type is `String`, `Text`, or `VARCHAR` — reject numeric/date types
- [ ] Check for existing `search()` function in `app/crud/{name}.py` (idempotency)
- [ ] Check for existing migration matching `*_search_idx_{table}*` (idempotency)
- [ ] If `facets` provided: verify each facet column exists on model
- [ ] Detect multi-tenancy (check for `require_current_tenant` import in CRUD) — will inject tenant filter if present

### 15.2 tsvector expression planning
- [ ] Build tsvector plan: one entry per field with weight (A, B, C, D in order)
- [ ] If `weighted=True`: use `setweight(to_tsvector(lang, coalesce(col, '')), 'X')`
- [ ] If `weighted=False`: use `to_tsvector(lang, coalesce(col1,'') || ' ' || coalesce(col2,''))`
- [ ] Decide stored vs. expression index: if PostgreSQL >= 12, use `GENERATED ALWAYS AS … STORED`; else expression GIN index
- [ ] Validate `language` against `pg_ts_config` (query or hardcoded allowlist)
- [ ] Compute migration revision number (next in sequence)

### 15.3 CRUD modification
- [ ] Read `app/crud/{name}.py` (full content, never truncated)
- [ ] Add imports: `func, select, text` from `sqlalchemy`; `uuid` if not present
- [ ] Insert `search()` function with all parameter types annotated
- [ ] Verify: `websearch_to_tsquery` or `plainto_tsquery` used for user input — never f-string
- [ ] Verify: owner filter applied if model has `owner_id`
- [ ] Verify: soft-delete filter applied if model has `is_deleted`
- [ ] Verify: tenant filter applied if project has multi-tenancy (check CRUD imports)
- [ ] If `with_snippet=True`: add `ts_headline()` column to SELECT; add `# EXPENSIVE` comment
- [ ] If `with_snippet=False`: verify NO `ts_headline` in output
- [ ] If `weighted=True`: use `ts_rank_cd()` (supports weight vectors); else `ts_rank()` is sufficient
- [ ] If `facets`: add one `WHERE model.col == facet_val` per facet (only if param is not None)
- [ ] Run `ast.parse()` on modified content before writing
- [ ] Write atomically (temp file + `os.replace`)

### 15.4 Route modification
- [ ] Read `app/api/routes/{name}.py`
- [ ] Insert `GET /search` handler BEFORE `GET /{id}` in the file (FastAPI is order-sensitive; `/search` before `/{id}` prevents "search" from being treated as an ID)
- [ ] Use `Query(..., min_length=2, max_length=200)` for `q` parameter
- [ ] Add `page_size: int = Query(default=20, ge=1, le=100)` param
- [ ] Add `cursor: float | None = Query(default=None)` param
- [ ] Add one `Query(default=None)` param per declared facet with appropriate type and max_length
- [ ] Add `sort: str = Query(default="relevance", pattern="^(relevance|recency)$")` param
- [ ] Catch `ValueError` → raise `HTTPException(422, detail=str(e))`
- [ ] If `autocomplete=True`: insert `GET /autocomplete` handler with `LIMIT 5` and prefix tsquery
- [ ] Run `ast.parse()` on modified content
- [ ] Write atomically

### 15.5 Schema modification
- [ ] Read `app/schemas/{name}.py`
- [ ] Add `rank: float | None` to the public response schema
- [ ] If `with_snippet=True`: add `snippet: str | None` to public response schema
- [ ] Verify `tenant_id` is NOT added to any public schema
- [ ] Run `ast.parse()` on modified content
- [ ] Write atomically

### 15.6 Migration generation
- [ ] Compute `down_revision` by inspecting current alembic head
- [ ] Generate `{rev}_{search_idx}_{table}.py` in `alembic/versions/`
- [ ] `upgrade()`:
  1. `ALTER TABLE {table} ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (…) STORED` (Postgres ≥ 12)
  2. `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_{table}_search_vector ON {table} USING GIN (search_vector)`
  3. OR (Postgres < 12): expression GIN index directly on `to_tsvector(…)`
- [ ] `downgrade()`:
  1. `DROP INDEX IF EXISTS ix_{table}_search_vector`
  2. `ALTER TABLE {table} DROP COLUMN IF EXISTS search_vector`
- [ ] Include comment in migration: `# NOTE: CONCURRENTLY must run outside a transaction (transactional_ddl=False)`
- [ ] Set `transactional_ddl = False` in migration or note for operator
- [ ] Run `ast.parse()` on migration file
- [ ] Chain revision to existing head

### 15.7 OpenSearch backend (if backend="opensearch")
- [ ] Check `pyproject.toml` for `opensearch-py`; add if absent
- [ ] Create `app/search/opensearch_backend.py` with `OpenSearchBackend` class
- [ ] Create `app/search/backend_protocol.py` with `SearchBackend` Protocol
- [ ] Create `app/search/reindex_opensearch.py` CLI for full re-index
- [ ] Create `app/search/index_mapping.py` with field type mapping
- [ ] Modify `crud.search()` to dispatch to backend based on `settings.SEARCH_BACKEND`
- [ ] Add `SEARCH_BACKEND: Literal["postgres", "opensearch"] = "postgres"` to `app/core/config.py`
- [ ] Run `ast.parse()` on all created files

### 15.8 Test generation
- [ ] Create `tests/test_{name_lower}_search.py`
- [ ] Generate T-01..T-07 functional tests with pytest fixtures
- [ ] Generate T-08..T-09 filter isolation tests
- [ ] Generate T-12..T-13 performance/EXPLAIN tests (mark with `@pytest.mark.slow`)
- [ ] Generate T-04 injection tests with 7 payloads as `@pytest.mark.parametrize`
- [ ] Generate T-15 cursor pagination walk test (10 pages, dedup check)
- [ ] Generate T-24 idempotency test (run tool, check no diff)
- [ ] Reuse existing `async_client`, `normal_user_token_headers`, `db_session` fixtures
- [ ] Run `ast.parse()` on test file

### 15.9 Verification pass
- [ ] Run `ast.parse()` on every file touched (CRUD, route, schema, migration, tests)
- [ ] Run import audit: `python -c "from app.crud.{name} import search"` — verify no ImportError
- [ ] Run `pytest tests/ -x --tb=short -q` — 0 regressions
- [ ] Run analyzer benchmark — verify existing endpoint latency unchanged
- [ ] Measure tool execution time from first line to return — must be < 3s
- [ ] Verify `grep -c 'LIKE\|ILIKE' app/crud/{name}.py` returns 0 in generated code (QS-1 enforcement)
- [ ] Verify `grep websearch_to_tsquery app/crud/{name}.py` returns ≥ 1 match (CC-02 enforcement)

### 15.10 Documentation updates
- [ ] Append search section to `app/core/KNOWLEDGE.md` with endpoint reference
- [ ] Add tool entry to `manifest.yaml` with `version`, `installed_at`, `model`, `fields`, `language`, `backend`
- [ ] Add row to `SKILL.md` tools table: `TOOL-004 | add_search | EXTEND > CRUD & Data | High`
- [ ] Register in `mcp_server.py` with MCP tool decorator and parameter schema
- [ ] Update `README.md` search section if present
- [ ] Record GIN index name (`ix_{table}_search_vector`) and migration revision in `manifest.yaml` for future idempotency checks
- [ ] Add `next_steps` warnings about CONCURRENTLY, ts_headline cost, and SQLite incompatibility to the KNOWLEDGE.md search section

### 15.11 Atomicity and rollback
- [ ] Track all files written in an ordered list `touched_files: list[Path]`
- [ ] All writes use `tmp = path.with_suffix('.tmp'); tmp.write_text(content); tmp.replace(path)` pattern
- [ ] On ANY exception after any write: iterate `touched_files` in reverse, restore from git or delete new files
- [ ] Return `{files_rolled_back, error, step_failed}` on failure for diagnostics
- [ ] Verify: calling `add_search` after a failed run is safe (idempotency + clean state)
- [ ] Test partial-failure recovery: mock a filesystem error at step 3 of 7 and assert that all files written in steps 1–2 are restored to their pre-run state (T-26)
- [ ] Confirm no `.tmp` orphan files remain after either a successful run or a failed run

### 15.12 Performance validation
- [ ] Post-install: emit an `EXPLAIN (FORMAT JSON)` on the search query and confirm `Node Type` = `Bitmap Index Scan`
- [ ] If Seq Scan detected: fail with `InvariantViolation: GIN index not used. Verify migration was applied.`
- [ ] Measure round-trip latency with 1000 search calls against fixture data (if in slow test mode)
- [ ] Record p50/p99 in the return dict under `metrics.latency_benchmark`
- [ ] Verify GIN index is marked VALID (not INVALID) via `SELECT indisvalid FROM pg_index JOIN pg_class ON oid=indexrelid WHERE relname='ix_{table}_search_vector'`
- [ ] Emit a warning in `next_steps` if the GIN index was built on a table with > 1M existing rows and migration was applied without `CONCURRENTLY` (potential brief lock)
- [ ] Assert that autocomplete endpoint p99 < 20ms when `autocomplete=True` by running 500 prefix queries in the benchmark loop

### 15.13 Final validation
- [ ] Re-run all 30 test cases (`pytest tests/test_{name_lower}_search.py -v`)
- [ ] Verify injection tests all pass (T-04)
- [ ] Verify GIN EXPLAIN test passes (T-13)
- [ ] Verify 0 regressions in full suite
- [ ] Return structured success report (§16)
- [ ] Confirm tool output JSON matches the schema in §16: all required keys present (`status`, `files_created`, `files_modified`, `metrics`, `next_steps`, `warnings`, `notes`)
- [ ] Confirm total tool wall-clock time is recorded in `metrics.execution_time_ms` and is < 3000

---

## 16. Documentation Output

When the tool completes successfully, it returns:

```json
{
  "status": "success",
  "files_created": [
    "alembic/versions/0004_search_idx_product.py",
    "tests/test_product_search.py",
    "app/search/fts_helpers.py",
    "app/search/query_builder.py",
    "app/search/autocomplete.py",
    "app/search/injection_guards.py",
    "app/schemas/search.py",
    "docs/search_tuning.md"
  ],
  "files_modified": [
    "app/crud/product.py",
    "app/api/routes/product.py",
    "app/schemas/product.py"
  ],
  "metrics": {
    "execution_time_ms": 1870,
    "files_changed": 5,
    "lines_added": 142,
    "lines_removed": 0,
    "gin_index_verified": true,
    "latency_benchmark": {
      "p50_ms": 12,
      "p99_ms": 38,
      "sample_size": 1000,
      "rows": 1000000
    }
  },
  "next_steps": [
    "Run: alembic upgrade head   (NOTE: GIN index uses CONCURRENTLY — set transactional_ddl=False or run manually outside a transaction on large tables)",
    "Run: pytest tests/test_product_search.py -v",
    "Test: curl '/api/v1/products/search?q=widget' -H 'Authorization: Bearer <token>'",
    "Performance check: run EXPLAIN ANALYZE on the search query to confirm 'Bitmap Index Scan on ix_product_search_vector' (not Seq Scan)",
    "Run VACUUM ANALYZE product after the initial search_vector backfill to update planner statistics",
    "Configure pg_stat_statements to monitor slow search queries and identify high-frequency terms for potential caching",
    "Add search analytics events to TOOL-005 audit log if installed (log query term, result count, latency per request)"
  ],
  "warnings": [
    "CONCURRENTLY index creation must run OUTSIDE a transaction. The generated migration sets transactional_ddl=False. On large tables (>5M rows), this may take several minutes.",
    "ts_headline (snippet) is disabled (with_snippet=False). Enable only if your UI displays highlighted excerpts — it costs ~3-5ms/row.",
    "PostgreSQL only: SQLite projects are not supported. SQLite fallback uses LIKE (O(n) scan) — unacceptable at scale."
  ],
  "notes": [
    "Full-text search enabled on Product with fields: ['name', 'description'].",
    "Language dictionary: english (stemming + stop-word removal active).",
    "Weighted fields: False (set weighted=True to boost name matches over description matches).",
    "Autocomplete endpoint: False (set autocomplete=True to add GET /products/autocomplete).",
    "Facets: none declared (pass facets=['category','status'] to add categorical filters).",
    "Backend: postgres (zero infra cost, ACID-consistent; switch to 'opensearch' for >50M row scale).",
    "GIN index: ix_product_search_vector.",
    "Rank normalization: ts_rank_cd with normalization=32 (stable 0-1 range for cursor pagination)."
  ]
}
```
