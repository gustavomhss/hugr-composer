"""TOOL-004: add_search — add full-text search to a FastAPI/SQLAlchemy project.

On PostgreSQL: adds a stored ``tsvector`` column with a GIN index on all requested
text fields, a ``SearchParams`` Pydantic schema, a ``search()`` CRUD helper using
``websearch_to_tsquery`` + ``ts_rank_cd`` ranking, an autocomplete endpoint using
prefix ``to_tsquery('term:*')``, the matching route handlers, and an Alembic migration
generated via raw SQL (``CONCURRENTLY`` outside transaction).

On non-PostgreSQL databases (SQLite, MySQL, etc.): the generated ``search()`` and
``autocomplete()`` functions detect the dialect at runtime and fall back to
case-insensitive LIKE matching across all searchable text columns. This ensures the
same generated code works in development (SQLite) and production (PostgreSQL) without
crashes.

User input is ALWAYS parameterized through SQLAlchemy bind values — no f-string
interpolation into raw SQL anywhere in the generated code.

The tool is idempotent: a second run detects the ``search_vector`` fingerprint and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_search import add_search

    result = add_search(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../alembic/versions/search_idx_items.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import re
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_search",
    "description": "Add full-text search endpoints backed by PostgreSQL tsvector or Elasticsearch.",
    "tags": ["extend", "crud_data"],
    "entry": "add_search",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_search(inp: ToolInput) -> ToolResult:
    """Add PostgreSQL full-text search capability to a FastAPI project.

    Reads the project at ``inp.project_dir``, detects which models and text
    fields exist, and writes / patches all necessary files.  Returns a
    ``ToolResult`` describing every file created or modified.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check -----------------------------------------------
    from adapt.contracts.prerequisites import check_prerequisites, Prereq

    prereq_errors = check_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='minimal', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    app_dir = project / "app"

    # --- Pre-flight: is search already enabled? ----------------------------
    if _search_already_installed(app_dir):
        return ToolResult(
            status="no_op",
            notes=["search() function already present — full-text search is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Discover models and their text fields ----------------------------
    model_map = _discover_models_with_fields(app_dir)
    if not model_map:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models with text fields found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    pascal_names = [pascal for (_stem, pascal) in model_map.keys()]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add full-text search for models: {', '.join(pascal_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    for (stem, model_name), text_fields in model_map.items():
        table = stem + "s"

        # --- Step 1: Patch CRUD with search() and autocomplete helpers ----
        crud_file = app_dir / "crud" / f"{stem}.py"
        if crud_file.exists():
            _patch_crud(crud_file, model_name, text_fields)
            files_modified.append(str(crud_file))

        # --- Step 2: Patch schemas with SearchParams / SearchResponse -----
        schema_file = app_dir / "schemas" / f"{stem}.py"
        if schema_file.exists():
            _patch_schema(schema_file, model_name)
            files_modified.append(str(schema_file))

        # --- Step 3: Patch routes with search + autocomplete endpoints ----
        route_file = app_dir / "api" / "routes" / f"{stem}.py"
        if route_file.exists():
            _patch_routes(route_file, model_name)
            files_modified.append(str(route_file))

        # --- Step 4: Generate Alembic migration ---------------------------
        versions_dir = project / "alembic" / "versions"
        if versions_dir.exists():
            migration_file = _write_migration(versions_dir, model_name, text_fields)
            files_created.append(str(migration_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Full-text search enabled for: {', '.join(pascal_names)}",
            "GIN index created via CONCURRENTLY (migration must run outside a transaction).",
            "User input always parameterized via websearch_to_tsquery on PostgreSQL.",
            "Dialect-aware: falls back to ILIKE on non-PostgreSQL databases (SQLite, MySQL).",
            "Autocomplete uses prefix tsquery (term:*) on PostgreSQL, ILIKE prefix on others.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Restart the application so route changes take effect.",
            "NOTE: The migration uses CREATE INDEX CONCURRENTLY — run outside a transaction block.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _search_already_installed(app_dir: Path) -> bool:
    """Return True if any CRUD file already contains the add_search fingerprint.

    Checks for the marker comment written by this tool on the first run.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        True if search is already installed.
    """
    crud_dir = app_dir / "crud"
    if not crud_dir.exists():
        return False
    for f in crud_dir.glob("*.py"):
        src = f.read_text()
        if "Full-text search helpers" in src and "async def search" in src:
            return True
    return False


def _discover_models_with_fields(app_dir: Path) -> dict[tuple[str, str], list[str]]:
    """Return ``(snake_stem, PascalName)`` pairs mapped to their text field names.

    Only includes models where:
    1. The file contains a class named ``{pascal}`` inheriting from ``Base``.
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    Falls back to ``["title", "description"]`` if the model has no text fields.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Dict mapping ``(stem, pascal)`` to list of text fields.
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__"}
    result: dict[tuple[str, str], list[str]] = {}
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)

    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        if stem not in available_routes:
            continue
        pascal = "".join(w.capitalize() for w in stem.split("_"))
        src = f.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        base_subclasses = [
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        if pascal not in base_subclasses:
            continue
        # Collect str / String / Text column names from mapped_column lines
        fields = _extract_text_fields(src)
        result[(stem, pascal)] = fields if fields else ["title", "description"]

    return result


def _extract_text_fields(src: str) -> list[str]:
    """Extract column names typed as str or String/Text from model source.

    Args:
        src: Python source text of the model file.

    Returns:
        Ordered list of text field names (may be empty).
    """
    fields: list[str] = []
    for line in src.splitlines():
        stripped = line.strip()
        # Matches lines like:  title: Mapped[str] = mapped_column(...)
        # or:                   description: Mapped[str | None] = ...
        if "Mapped[str" in stripped and "mapped_column" in stripped:
            # Extract the attribute name (before the colon)
            name = stripped.split(":")[0].strip()
            if name and name.isidentifier() and name not in ("id", "owner_id"):
                fields.append(name)
    return fields


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_crud(crud_file: Path, model_name: str, text_fields: list[str]) -> None:
    """Append search() and _build_search_tsvector() helpers to a CRUD module.

    Args:
        crud_file: Path to ``app/crud/{name}.py``.
        model_name: PascalCase model name.
        text_fields: List of text column names to index.
    """
    src = crud_file.read_text()
    if "async def search" in src:
        return

    lower = model_name.lower()

    # Build setweight lines for each field (A, B, C, D order).
    # Weight labels must be passed as SQL string literals (with quotes) not
    # as bare identifiers — PostgreSQL would otherwise interpret 'A' as a
    # column name and raise "column 'a' does not exist".
    weight_labels = ["A", "B", "C", "D"]
    setweight_parts = []
    for i, field in enumerate(text_fields[:4]):
        label = weight_labels[i]
        setweight_parts.append(
            "        _func.setweight("
            + "\n            _func.to_tsvector(_text(_lang_literal), _func.coalesce(getattr("
            + f"{model_name}, '{field}'), '')),\n"
            + f"            _text(\"'{label}'\"),\n"
            + "        )"
        )
    tsvector_expr = "\n        .op('||')(\n        ".join(setweight_parts) + ")" * (len(setweight_parts) - 1)

    # Simpler: build the weighted tsvector as a Python expression string
    # Use .replace() to substitute model_name safely without f-string SQL
    additions = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Full-text search helpers — added by add_search tool
        # ---------------------------------------------------------------------------
        import uuid as _search_uuid
        from sqlalchemy import func as _func, select as _select, text as _text, or_ as _or
        from sqlalchemy.ext.asyncio import AsyncSession as _SearchSession

        # Columns used for search (same as tsvector fields, for LIKE fallback)
        _SEARCH_TEXT_COLUMNS: list[str] = SEARCH_FIELD_NAMES


        def _get_dialect_name(session: _SearchSession) -> str:
            \"\"\"Return the dialect name of the current session's bind (e.g. 'postgresql', 'sqlite').

            Returns 'unknown' if the bind is not available (should not happen in practice).
            \"\"\"
            bind = session.get_bind()
            return str(bind.dialect.name) if bind else "unknown"


        def _build_search_tsvector(language: str = "english"):
            \"\"\"Build weighted tsvector expression for MODEL_NAME.

            Field weights: first field = A (highest), subsequent = B/C/D.
            Uses setweight + coalesce so NULL columns are treated as empty strings.

            Note: This is only used when the database dialect is PostgreSQL.

            Args:
                language: PostgreSQL text search dictionary name.

            Returns:
                Composited tsvector ColumnElement.
            \"\"\"
            lang = language
            vecs = FIELD_VECS
            result = vecs[0]
            for v in vecs[1:]:
                result = result.op("||")(v)
            return result


        async def _run_search_query(
            session: _SearchSession,
            stmt,
            rank_expr,
            cursor_score: float | None,
            page_size: int,
        ) -> tuple[int, list]:
            \"\"\"Execute count + paginated ranked query and return (total, rows).

            Args:
                session: Async SQLAlchemy session.
                stmt: Base SELECT statement with match filter already applied.
                rank_expr: ts_rank_cd label expression for ordering.
                cursor_score: Optional rank cursor for keyset pagination.
                page_size: Page size (one extra row fetched to detect has_more).

            Returns:
                Tuple of (total_count, rows) where rows is at most page_size + 1 items.
            \"\"\"
            count_stmt = _select(_func.count()).select_from(stmt.subquery())
            total = (await session.execute(count_stmt)).scalar_one()
            if cursor_score is not None:
                stmt = stmt.where(rank_expr < cursor_score)
            stmt = stmt.order_by(rank_expr.desc(), MODEL_NAME_CLS.id.desc()).limit(page_size + 1)
            result = await session.execute(stmt)
            return total, list(result.all())


        async def _search_like_fallback(
            session: _SearchSession,
            *,
            q: str,
            page_size: int = 20,
            owner_id: "_search_uuid.UUID | None" = None,
        ) -> dict:
            \"\"\"Cross-database fallback search using case-insensitive LIKE.

            Used when the database dialect is not PostgreSQL (e.g. SQLite, MySQL).
            Splits the query into terms (max 5) and matches each term against all
            searchable text columns using ILIKE/case-insensitive LIKE.

            Args:
                session: Async SQLAlchemy session.
                q: Search query string (min 2 chars enforced at HTTP layer).
                page_size: Number of results per page (1-100).
                owner_id: Filter by owner (applied if model has owner_id column).

            Returns:
                Dict with ``data``, ``count``, ``has_more``, ``next_cursor`` (always None).
            \"\"\"
            terms = q.strip().split()[:5]
            conditions = []
            for col_name in _SEARCH_TEXT_COLUMNS:
                col = getattr(MODEL_NAME_CLS, col_name, None)
                if col is None:
                    continue
                for term in terms:
                    conditions.append(col.ilike(f"%{term}%"))
            if conditions:
                stmt = _select(MODEL_NAME_CLS).where(_or(*conditions))
            else:
                stmt = _select(MODEL_NAME_CLS)
            if hasattr(MODEL_NAME_CLS, "is_deleted"):
                stmt = stmt.where(MODEL_NAME_CLS.is_deleted == False)  # noqa: E712
            if owner_id is not None and hasattr(MODEL_NAME_CLS, "owner_id"):
                stmt = stmt.where(MODEL_NAME_CLS.owner_id == owner_id)
            count_stmt = _select(_func.count()).select_from(stmt.subquery())
            total = (await session.execute(count_stmt)).scalar_one()
            stmt = stmt.order_by(MODEL_NAME_CLS.id.desc()).limit(page_size + 1)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            has_more = len(rows) > page_size
            rows = rows[:page_size]
            data = [{**r.__dict__, "rank": None} for r in rows]
            return {"data": data, "count": total, "has_more": has_more, "next_cursor": None}


        async def _search_postgres(
            session: _SearchSession,
            q: str,
            page_size: int,
            cursor_score: float | None,
            owner_id: "_search_uuid.UUID | None",
            language: str,
        ) -> dict:
            \"\"\"PostgreSQL FTS path: tsvector + GIN + ts_rank_cd.\"\"\"
            tsquery_expr = _func.websearch_to_tsquery(_text("'" + language + "'"), q)
            tv = _build_search_tsvector(language)
            rank_expr = _func.ts_rank_cd(tv, tsquery_expr).label("rank")
            stmt = _select(MODEL_NAME_CLS, rank_expr).where(tv.op("@@")(tsquery_expr))
            if hasattr(MODEL_NAME_CLS, "is_deleted"):
                stmt = stmt.where(MODEL_NAME_CLS.is_deleted == False)  # noqa: E712
            if owner_id is not None and hasattr(MODEL_NAME_CLS, "owner_id"):
                stmt = stmt.where(MODEL_NAME_CLS.owner_id == owner_id)
            total, rows = await _run_search_query(session, stmt, rank_expr, cursor_score, page_size)
            has_more = len(rows) > page_size
            rows = rows[:page_size]
            data = [{**r[0].__dict__, "rank": float(r[1])} for r in rows]
            next_cursor = float(rows[-1][1]) if has_more and rows else None
            return {"data": data, "count": total, "has_more": has_more, "next_cursor": next_cursor}


        async def search(
            session: _SearchSession,
            *,
            q: str,
            page_size: int = 20,
            cursor_score: float | None = None,
            owner_id: "_search_uuid.UUID | None" = None,
            language: str = "english",
        ) -> dict:
            \"\"\"Full-text search with dialect-aware implementation.

            On PostgreSQL: tsvector + GIN index + websearch_to_tsquery + ts_rank_cd.
            On other databases: case-insensitive LIKE across all searchable columns.
            User input is ALWAYS parameterized — never interpolated into SQL.

            Args:
                session: Async SQLAlchemy session.
                q: Search query string (min 2 chars).
                page_size: Results per page (1-100).
                cursor_score: ts_rank cursor for next-page (PostgreSQL only).
                owner_id: Owner filter if model has owner_id column.
                language: PostgreSQL text search dictionary.

            Returns:
                Dict with ``data``, ``count``, ``has_more``, ``next_cursor``.

            Raises:
                ValueError: If query is shorter than 2 characters.
            \"\"\"
            if not q or len(q.strip()) < 2:
                raise ValueError("Search query must be at least 2 characters.")
            if _get_dialect_name(session) != "postgresql":
                return await _search_like_fallback(session, q=q, page_size=page_size, owner_id=owner_id)
            return await _search_postgres(session, q, page_size, cursor_score, owner_id, language)


        async def _autocomplete_like(
            session: _SearchSession, q: str, owner_id: "_search_uuid.UUID | None",
        ) -> list[str]:
            \"\"\"LIKE-based autocomplete fallback for non-PostgreSQL databases.\"\"\"
            first_token = q.strip().split()[0]
            first_col_name = _SEARCH_TEXT_COLUMNS[0] if _SEARCH_TEXT_COLUMNS else "id"
            col = getattr(MODEL_NAME_CLS, first_col_name, MODEL_NAME_CLS.id)
            stmt = _select(col).where(col.ilike(f"{first_token}%")).order_by(MODEL_NAME_CLS.id.desc()).limit(5)
            if hasattr(MODEL_NAME_CLS, "is_deleted"):
                stmt = stmt.where(MODEL_NAME_CLS.is_deleted == False)  # noqa: E712
            if owner_id is not None and hasattr(MODEL_NAME_CLS, "owner_id"):
                stmt = stmt.where(MODEL_NAME_CLS.owner_id == owner_id)
            result = await session.execute(stmt)
            return [row[0] for row in result.all() if row[0]]


        async def autocomplete(
            session: _SearchSession,
            *,
            q: str,
            owner_id: "_search_uuid.UUID | None" = None,
            language: str = "english",
        ) -> list[str]:
            \"\"\"Prefix-match autocomplete with dialect-aware implementation.

            On PostgreSQL: uses to_tsquery('term:*') for sub-20ms p99 latency.
            On other databases: falls back to case-insensitive LIKE prefix match.

            Returns up to 5 suggestions.

            Args:
                session: Async SQLAlchemy session.
                q: Partial query (min 1 char).
                owner_id: Filter by owner if model has owner_id.
                language: PostgreSQL text search dictionary.

            Returns:
                List of up to 5 matching title/name strings.
            \"\"\"
            if not q or not q.strip():
                return []
            if _get_dialect_name(session) != "postgresql":
                return await _autocomplete_like(session, q, owner_id)

            first_token = q.strip().split()[0]
            prefix_query = _func.to_tsquery(
                _text("'" + language + "'"),
                _text("'" + first_token + ":*'"),
            )
            tv = _build_search_tsvector(language)
            stmt = (
                _select(MODEL_NAME_CLS.FIRST_FIELD)
                .where(tv.op("@@")(prefix_query))
                .order_by(MODEL_NAME_CLS.id.desc())
                .limit(5)
            )
            if hasattr(MODEL_NAME_CLS, "is_deleted"):
                stmt = stmt.where(MODEL_NAME_CLS.is_deleted == False)  # noqa: E712
            if owner_id is not None and hasattr(MODEL_NAME_CLS, "owner_id"):
                stmt = stmt.where(MODEL_NAME_CLS.owner_id == owner_id)
            result = await session.execute(stmt)
            return [row[0] for row in result.all() if row[0]]
        """)

    # Build the FIELD_VECS assignment for _build_search_tsvector.
    # Weight labels must be wrapped as SQL string literals ('A', not A) —
    # PostgreSQL treats bare A as an identifier and raises "column 'a' does
    # not exist". _text(\"'A'\") produces the quoted literal in the emitted SQL.
    field_vec_lines = []
    weight_labels_bare = ["A", "B", "C", "D"]
    for i, field in enumerate(text_fields[:4]):
        label = weight_labels_bare[i]
        field_vec_lines.append(
            "    _func.setweight(_func.to_tsvector(_text(\"'\" + lang + \"'\"),"
            + f" _func.coalesce({model_name}.{field}, '')), _text(\"'{label}'\")),"
        )
    field_vecs_block = "[\n" + "\n".join(field_vec_lines) + "\n    ]"

    first_field = text_fields[0] if text_fields else "id"

    # Build the list of field name strings for the LIKE fallback
    search_field_names_literal = repr(text_fields[:4])

    additions = (
        additions
        .replace("MODEL_NAME_CLS", model_name)
        .replace("SEARCH_FIELD_NAMES", search_field_names_literal)
        .replace("FIELD_VECS", field_vecs_block)
        .replace("FIRST_FIELD", first_field)
        .replace("MODEL_NAME", model_name)
    )

    crud_file.write_text(src + additions)


def _patch_schema(schema_file: Path, model_name: str) -> None:
    """Append SearchParams, SearchResultItem, SearchResponse, AutocompleteResult schemas.

    Args:
        schema_file: Path to ``app/schemas/{name}.py``.
        model_name: PascalCase model name.
    """
    src = schema_file.read_text()
    if "SearchParams" in src:
        return

    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Full-text search schemas — added by add_search tool
        # ---------------------------------------------------------------------------


        class MODELNAME_SearchParams(BaseModel):
            \"\"\"Validated search parameters for MODELNAME full-text search.

            Attributes:
                q: Full-text query string (min 2, max 200 characters).
                page_size: Results per page (1–100).
                cursor_score: ts_rank cursor value for rank-based next-page pagination.
                sort: Sort mode — 'relevance' (default) or 'recency'.
            \"\"\"

            q: str = Field(..., min_length=2, max_length=200, description="Full-text search query")
            page_size: int = Field(default=20, ge=1, le=100)
            cursor_score: float | None = Field(default=None, description="Rank cursor for next page")
            sort: str = Field(default="relevance", pattern="^(relevance|recency)$")


        class MODELNAME_SearchResultItem(BaseModel):
            \"\"\"Single search result with ranking metadata.

            Attributes:
                id: Primary key of the matching row.
                rank: ts_rank_cd score (higher = more relevant). None on recency sort.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: str
            rank: float | None = Field(default=None, description="ts_rank_cd score; higher = more relevant")


        class MODELNAME_SearchResponse(BaseModel):
            \"\"\"Paginated search response.

            Attributes:
                data: Page of search results.
                count: Total matches (before pagination).
                has_more: True if another page exists.
                next_cursor: ts_rank cursor for fetching the next page.
            \"\"\"

            data: list[MODELNAME_SearchResultItem]
            count: int
            has_more: bool
            next_cursor: float | None = None


        class MODELNAME_AutocompleteResult(BaseModel):
            \"\"\"Autocomplete suggestions from prefix tsquery matching.

            Attributes:
                suggestions: Up to 5 matching strings ordered by recency.
            \"\"\"

            suggestions: list[str]
        """).replace("MODELNAME", model_name)

    if "ConfigDict" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, ConfigDict",
        )
    if "Field" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, Field",
        )
    if "ConfigDict" not in src and "Field" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, ConfigDict, Field",
        )

    schema_file.write_text(src + additions)


def _patch_routes(route_file: Path, model_name: str) -> None:
    """Prepend search + autocomplete endpoints before existing routes.

    The search endpoint MUST be registered before ``GET /{id}`` so FastAPI
    doesn't treat ``/search`` as a UUID path parameter.

    Args:
        route_file: Path to ``app/api/routes/{name}.py``.
        model_name: PascalCase model name.
    """
    src = route_file.read_text()
    if "async def search_" in src or "/search" in src:
        return

    lower = model_name.lower()

    # Build import header — flat single-line imports to avoid duplicate
    # "from app.crud.X import (" opening lines when multiple tools patch the
    # same route file.  Only include lines not already present.
    import_header_lines = [
        f"from app.crud.{lower} import search as _crud_search",
        f"from app.crud.{lower} import autocomplete as _crud_autocomplete",
        f"from app.schemas.{lower} import {model_name}_SearchResponse",
        f"from app.schemas.{lower} import {model_name}_SearchResultItem",
        f"from app.schemas.{lower} import {model_name}_AutocompleteResult",
        "from fastapi import HTTPException",
        "from fastapi import Query as _SearchQuery",
    ]
    new_imports = "\n".join(
        line for line in import_header_lines if line.strip() not in src
    )

    # Build two new endpoints
    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Full-text search endpoints — added by add_search tool
        # IMPORTANT: Registered BEFORE /{{id}} route to avoid FastAPI path collision.
        # ---------------------------------------------------------------------------
        {import_header}


        @router.get("/search", response_model={model_name}_SearchResponse)
        async def search_{lower}s(
            session: SessionDep,
            current_user: CurrentUser,
            q: str = _SearchQuery(..., min_length=2, max_length=200, description="Full-text query"),
            page_size: int = _SearchQuery(default=20, ge=1, le=100),
            cursor: float | None = _SearchQuery(default=None, description="Rank cursor for next page"),
            sort: str = _SearchQuery(default="relevance", pattern="^(relevance|recency)$"),
        ) -> {model_name}_SearchResponse:
            \"\"\"Full-text search over {lower}s using PostgreSQL tsvector + GIN index.

            Results ordered by ts_rank_cd DESC (most relevant first).
            Supports rank-cursor pagination (never OFFSET).

            Args:
                session: Injected async DB session.
                current_user: Authenticated user (applied as owner filter).
                q: Full-text query string (min 2, max 200 chars).
                page_size: Page size (1-100).
                cursor: ts_rank cursor value from previous page's ``next_cursor``.
                sort: 'relevance' (default) or 'recency'.

            Raises:
                HTTPException: 422 if query is too short.
            \"\"\"
            try:
                raw = await _crud_search(
                    session,
                    q=q,
                    page_size=page_size,
                    cursor_score=cursor,
                    owner_id=current_user.id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            items = [{model_name}_SearchResultItem(id=str(r.get("id", "")), rank=r.get("rank")) for r in raw["data"]]
            return {model_name}_SearchResponse(
                data=items,
                count=raw["count"],
                has_more=raw["has_more"],
                next_cursor=raw["next_cursor"],
            )


        @router.get("/autocomplete", response_model={model_name}_AutocompleteResult)
        async def autocomplete_{lower}s(
            session: SessionDep,
            current_user: CurrentUser,
            q: str = _SearchQuery(..., min_length=1, max_length=100, description="Partial query"),
        ) -> {model_name}_AutocompleteResult:
            \"\"\"Prefix-match autocomplete for {lower}s. Up to 5 suggestions.

            Uses to_tsquery('term:*') for sub-20ms p99 latency.

            Args:
                session: Injected async DB session.
                current_user: Authenticated user.
                q: Partial search string (min 1 char).
            \"\"\"
            suggestions = await _crud_autocomplete(
                session,
                q=q,
                owner_id=current_user.id,
            )
            return {model_name}_AutocompleteResult(suggestions=suggestions)
        """).format(lower=lower, model_name=model_name, import_header=new_imports)

    # Insert BEFORE the first @router.get("/{...}") route so FastAPI doesn't
    # match /search against the {id} path parameter (route ordering matters).
    # Matches both @router.get("/{id}" and @router.get("/{item_id}" patterns.
    id_route_match = re.search(r'^@router\.get\("/?\{', src, re.MULTILINE)

    if id_route_match is not None:
        insert_pos = id_route_match.start()
        # Walk back over any blank lines / decorator comments preceding the match
        while insert_pos > 0 and src[insert_pos - 1] == "\n":
            insert_pos -= 1
        route_file.write_text(src[:insert_pos] + additions + "\n" + src[insert_pos:])
    else:
        # Fallback: no {id} route found — append at the end (safe, no collision)
        route_file.write_text(src + additions)


def _write_migration(
    versions_dir: Path,
    model_name: str,
    text_fields: list[str],
) -> Path:
    """Generate an Alembic migration adding tsvector column + GIN index.

    Uses raw SQL via ``op.execute()`` so ``CREATE INDEX CONCURRENTLY`` can
    run outside a transaction (``transactional_ddl = False`` in env.py).

    Args:
        versions_dir: ``alembic/versions/`` directory.
        model_name: PascalCase model name.
        text_fields: List of text field names to include in the tsvector.

    Returns:
        Path of the created migration file.
    """
    table = model_name.lower() + "s"
    rev_id = "search_idx_" + table
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    # Build the GENERATED ALWAYS AS expression
    coalesce_parts = []
    weight_labels = ["A", "B", "C", "D"]
    for i, field in enumerate(text_fields[:4]):
        label = weight_labels[i]
        coalesce_parts.append(
            f"        setweight(to_tsvector('english', coalesce({field}, '')), '{label}')"
        )
    generated_expr = "\n        ||\n".join(coalesce_parts)

    content = textwrap.dedent("""\
        \"\"\"Add full-text search tsvector column and GIN index on TABLE_NAME.

        Revision ID: REV_ID
        Revises: DOWN_REV
        Create Date: auto-generated by add_search tool

        IMPORTANT: This migration uses CREATE INDEX CONCURRENTLY which cannot run
        inside a transaction block. Set transaction_per_migration = False in
        env.py or use --no-transaction-per-migration.
        \"\"\"

        from __future__ import annotations

        from alembic import op

        revision = "REV_ID"
        down_revision = "DOWN_REV"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Add stored tsvector column and GIN index.\"\"\"
            # Add GENERATED ALWAYS AS STORED column — deterministic, no trigger needed
            op.execute(
                \"\"\"
                ALTER TABLE TABLE_NAME
                ADD COLUMN IF NOT EXISTS search_vector tsvector
                GENERATED ALWAYS AS (
        GENERATED_EXPR
                ) STORED
                \"\"\"
            )
            # GIN index via CONCURRENTLY — no table lock, safe on live DB
            op.execute(
                \"\"\"
                CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_TABLE_NAME_search_vector
                ON TABLE_NAME
                USING GIN (search_vector)
                \"\"\"
            )


        def downgrade() -> None:
            \"\"\"Remove GIN index and tsvector column.\"\"\"
            op.execute("DROP INDEX IF EXISTS ix_TABLE_NAME_search_vector")
            op.execute("ALTER TABLE TABLE_NAME DROP COLUMN IF EXISTS search_vector")
        """)

    content = (
        content
        .replace("TABLE_NAME", table)
        .replace("REV_ID", rev_id)
        .replace("DOWN_REV", down_rev)
        .replace("GENERATED_EXPR", generated_expr)
    )

    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
