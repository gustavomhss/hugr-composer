"""TOOL-105: add_data_seeder — smart test data seeder respecting FK relationships.

Generates a DataSeeder that reads SQLAlchemy models, uses smart generators
(names, emails, prices per field type), performs topological sort of models
by FK with DependencyGraph, and exposes a POST /dev/seed endpoint (dev only)
and a scripts/seed.py CLI.

The tool is idempotent: a second run detects the ``DataSeeder``
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_data_seeder import add_data_seeder

    result = add_data_seeder(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/seeder/__init__.py", ...]
    print(result.next_steps)    # ["Set SEEDER_ENABLED=true in dev .env", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_testing_add_data_seeder",
    "description": "Add a smart test data seeder that respects FK relationships via topological sort.",
    "tags": ["extend", "testing_tools"],
    "entry": "add_data_seeder",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_data_seeder(inp: ToolInput) -> ToolResult:
    """Add a smart data seeder with FK-aware topological sort and dev-only endpoint.

    Creates DataSeeder, smart generators, DependencyGraph, POST /dev/seed route,
    and seeds CLI script.  Patches ``app/core/config.py`` with seeder settings.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.BASE_MODEL,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # Idempotency guard
    seeder_init = app_dir / "seeder" / "__init__.py"
    if seeder_init.exists() and "DataSeeder" in seeder_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["DataSeeder already present — data seeder is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/seeder/ (DataSeeder, generators, DependencyGraph),",
                "         POST /dev/seed?count=N route (dev/staging only),",
                "         scripts/seed.py CLI.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — seeder package with DataSeeder
    seeder_dir = app_dir / "seeder"
    seeder_dir.mkdir(parents=True, exist_ok=True)
    _write_seeder_init(seeder_init)
    files_created.append(str(seeder_init))

    # Step 2 — smart generators
    generators_file = seeder_dir / "generators.py"
    _write_generators_module(generators_file)
    files_created.append(str(generators_file))

    # Step 3 — dependency graph (topological sort)
    graph_file = seeder_dir / "graph.py"
    _write_graph_module(graph_file)
    files_created.append(str(graph_file))

    # Step 4 — dev/seed HTTP route
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    seeder_route = routes_dir / "seeder.py"
    _write_seeder_route(seeder_route)
    files_created.append(str(seeder_route))

    # Step 5 — register seeder route in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 6 — scripts/seed.py CLI
    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    seed_script = scripts_dir / "seed.py"
    _write_seed_script(seed_script)
    files_created.append(str(seed_script))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Validate generated Python files
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Data seeder added: DataSeeder, smart generators, DependencyGraph.",
            "Topological sort ensures FKs are seeded before referencing models.",
            "POST /dev/seed?count=100 route enabled only when SEEDER_ENABLED=true.",
            "scripts/seed.py CLI: python scripts/seed.py --count 100",
        ],
        next_steps=[
            "Set SEEDER_ENABLED=true in your dev .env (default is false in production)",
            "Seed data: python scripts/seed.py --count 50",
            "Or via HTTP: POST /dev/seed?count=50 (dev only)",
            "SEEDER_DEFAULT_COUNT controls the default count (default: 10)",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_seeder_init(dest: Path) -> None:
    """Write ``app/seeder/__init__.py`` with DataSeeder.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Smart data seeder — generates realistic test data respecting FK constraints.

        Usage::

            from app.seeder import DataSeeder

            seeder = DataSeeder(session)
            await seeder.seed(count=50)
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.seeder.graph import DependencyGraph
        from app.seeder.generators import FieldGenerator

        logger = logging.getLogger(__name__)


        class DataSeeder:
            \"\"\"Seed the database with realistic test data in FK-safe order.

            Attributes:
                session: Async SQLAlchemy session to use for inserts.
            \"\"\"

            def __init__(self, session: AsyncSession) -> None:
                \"\"\"Initialise with an active async database session.

                Args:
                    session: Async SQLAlchemy session for database writes.
                \"\"\"
                self.session = session
                self._generator = FieldGenerator()

            async def seed(self, count: int = 10) -> dict[str, int]:
                \"\"\"Seed all discovered models with *count* rows each.

                Models are seeded in FK-safe topological order so foreign key
                constraints are never violated.

                Args:
                    count: Number of rows to generate per model table.

                Returns:
                    Dict mapping model class name to number of rows inserted.
                \"\"\"
                models = self._discover_models()
                graph = DependencyGraph(models)
                ordered = graph.topological_order()
                results: dict[str, int] = {}
                for model_cls in ordered:
                    inserted = await self._seed_model(model_cls, count)
                    results[model_cls.__name__] = inserted
                    logger.info("Seeded %d rows into %s", inserted, model_cls.__name__)
                return results

            async def _seed_model(
                self,
                model_cls: Any,
                count: int,
            ) -> int:
                \"\"\"Seed *count* rows for *model_cls*.

                Args:
                    model_cls: SQLAlchemy ORM model class.
                    count: Number of rows to insert.

                Returns:
                    Number of rows successfully inserted.
                \"\"\"
                inserted = 0
                for _ in range(count):
                    instance = self._generator.generate_instance(model_cls)
                    self.session.add(instance)
                    inserted += 1
                await self.session.flush()
                return inserted

            def _discover_models(self) -> list[Any]:
                \"\"\"Auto-discover registered SQLAlchemy ORM models.

                Returns:
                    List of ORM model classes found in the app registry.
                \"\"\"
                try:
                    from app.models.base import Base
                    return list(Base.registry.mappers)
                except Exception:
                    logger.warning("Could not discover models from Base.registry")
                    return []
    """)
    dest.write_text(content)


def _write_generators_module(dest: Path) -> None:
    """Write ``app/seeder/generators.py`` with FieldGenerator.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Smart field value generators for the data seeder.

        Generates realistic values based on field name patterns and column types.
        No external faker library required — uses stdlib random + string.
        \"\"\"

        from __future__ import annotations

        import logging
        import random
        import string
        import uuid
        from typing import Any

        logger = logging.getLogger(__name__)

        _FIRST_NAMES = [
            "Alice", "Bob", "Carol", "David", "Emma", "Frank",
            "Grace", "Henry", "Isabel", "Jack",
        ]
        _LAST_NAMES = [
            "Smith", "Jones", "Williams", "Brown", "Davis",
            "Wilson", "Taylor", "Anderson", "Thomas", "Jackson",
        ]
        _DOMAINS = ["example.com", "test.org", "demo.net", "fake.io"]
        _WORDS = [
            "alpha", "beta", "gamma", "delta", "epsilon",
            "zeta", "eta", "theta", "iota", "kappa",
        ]


        class FieldGenerator:
            \"\"\"Generate realistic field values by column name and type hints.\"\"\"

            def generate_instance(self, model_cls: Any) -> Any:
                \"\"\"Generate an unsaved ORM instance of *model_cls* with realistic values.

                Args:
                    model_cls: SQLAlchemy ORM model class (mapper object or class).

                Returns:
                    Unsaved ORM model instance populated with generated data.
                \"\"\"
                if hasattr(model_cls, "class_"):
                    cls = model_cls.class_
                else:
                    cls = model_cls
                kwargs: dict[str, Any] = {}
                try:
                    mapper = cls.__mapper__
                    for col in mapper.columns:
                        if col.primary_key or col.foreign_keys:
                            continue
                        kwargs[col.name] = self._value_for_column(col)
                except Exception as exc:
                    logger.warning("Could not inspect %s: %s", cls.__name__, exc)
                return cls(**kwargs)

            def _value_for_column(self, column: Any) -> Any:
                \"\"\"Generate a realistic value for *column* by name and type.

                Args:
                    column: SQLAlchemy Column object.

                Returns:
                    Generated value appropriate for the column.
                \"\"\"
                name = column.name.lower()
                col_type = type(column.type).__name__.lower()
                if self._is_nullable(column):
                    if random.random() < 0.1:
                        return None
                if "email" in name:
                    return self._email()
                if "name" in name and "username" not in name:
                    return self._full_name()
                if "username" in name:
                    return self._username()
                if "price" in name or "amount" in name or "cost" in name:
                    return round(random.uniform(1.0, 999.99), 2)
                if "url" in name or "link" in name:
                    return f"https://example.com/{self._slug()}"
                if "phone" in name:
                    return f"+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
                if "bool" in col_type or "boolean" in name:
                    return random.choice([True, False])
                if "int" in col_type or "integer" in col_type:
                    return random.randint(1, 1000)
                if "float" in col_type or "numeric" in col_type:
                    return round(random.uniform(0.0, 1000.0), 2)
                if "date" in col_type:
                    return self._random_date()
                if "uuid" in col_type or "uuid" in name:
                    return str(uuid.uuid4())
                return self._text(col_type)

            def _is_nullable(self, column: Any) -> bool:
                \"\"\"Return True when *column* allows NULL values.

                Args:
                    column: SQLAlchemy Column object.

                Returns:
                    True if column is nullable.
                \"\"\"
                return getattr(column, "nullable", True)

            def _email(self) -> str:
                \"\"\"Generate a realistic-looking email address.

                Returns:
                    Email string like 'alice.smith@example.com'.
                \"\"\"
                first = random.choice(_FIRST_NAMES).lower()
                last = random.choice(_LAST_NAMES).lower()
                domain = random.choice(_DOMAINS)
                return f"{first}.{last}@{domain}"

            def _full_name(self) -> str:
                \"\"\"Generate a realistic full name.

                Returns:
                    Full name string like 'Alice Smith'.
                \"\"\"
                return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

            def _username(self) -> str:
                \"\"\"Generate a unique username.

                Returns:
                    Username string like 'alice_7423'.
                \"\"\"
                return f"{random.choice(_FIRST_NAMES).lower()}_{random.randint(1000, 9999)}"

            def _slug(self) -> str:
                \"\"\"Generate a URL-safe slug.

                Returns:
                    Slug string like 'alpha-beta-42'.
                \"\"\"
                return "-".join(random.choices(_WORDS, k=2)) + f"-{random.randint(1, 99)}"

            def _text(self, col_type: str) -> str:
                \"\"\"Generate generic text appropriate for the column type.

                Args:
                    col_type: Lowercase SQLAlchemy type name string.

                Returns:
                    Short random text string.
                \"\"\"
                if "text" in col_type:
                    return " ".join(random.choices(_WORDS, k=random.randint(5, 15)))
                length = 12
                return "".join(random.choices(string.ascii_lowercase, k=length))

            def _random_date(self) -> str:
                \"\"\"Generate a random ISO date string within a reasonable range.

                Returns:
                    ISO 8601 date string like '2024-07-15'.
                \"\"\"
                year = random.randint(2020, 2025)
                month = random.randint(1, 12)
                day = random.randint(1, 28)
                return f"{year}-{month:02d}-{day:02d}"
    """)
    dest.write_text(content)


def _write_graph_module(dest: Path) -> None:
    """Write ``app/seeder/graph.py`` with DependencyGraph topological sort.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"DependencyGraph — topological sort of SQLAlchemy models by FK relationships.

        Ensures that models with FK dependencies are seeded AFTER the models
        they reference, so no FK constraint violations occur during seeding.
        \"\"\"

        from __future__ import annotations

        import logging
        from collections import defaultdict, deque
        from typing import Any

        logger = logging.getLogger(__name__)


        class DependencyGraph:
            \"\"\"Build a dependency graph and produce a topological seed order.

            Args:
                models: List of SQLAlchemy mapper objects or model classes.
            \"\"\"

            def __init__(self, models: list[Any]) -> None:
                \"\"\"Initialise with a list of SQLAlchemy model classes/mappers.

                Args:
                    models: SQLAlchemy mapper objects or ORM classes.
                \"\"\"
                self._models = models

            def topological_order(self) -> list[Any]:
                \"\"\"Return models sorted by FK dependency (parents before children).

                Uses Kahn's algorithm (BFS-based topological sort) to produce a
                stable ordering where every model appears after all its FK parents.

                Returns:
                    List of model classes/mappers in safe insert order.
                    Cycles are broken by removing the back-edge and logging a warning.
                \"\"\"
                classes = self._resolve_classes()
                name_to_cls: dict[str, Any] = {
                    cls.__name__: cls for cls in classes
                }
                graph: dict[str, list[str]] = defaultdict(list)
                in_degree: dict[str, int] = {name: 0 for name in name_to_cls}

                for cls in classes:
                    deps = self._get_dependencies(cls, name_to_cls)
                    for dep in deps:
                        if dep in name_to_cls and dep != cls.__name__:
                            graph[dep].append(cls.__name__)
                            in_degree[cls.__name__] += 1

                queue: deque[str] = deque(
                    name for name, deg in in_degree.items() if deg == 0
                )
                ordered: list[Any] = []
                while queue:
                    name = queue.popleft()
                    ordered.append(name_to_cls[name])
                    for dependent in graph[name]:
                        in_degree[dependent] -= 1
                        if in_degree[dependent] == 0:
                            queue.append(dependent)

                remaining = [n for n, d in in_degree.items() if d > 0]
                if remaining:
                    logger.warning(
                        "Cycle detected in model dependencies, seeding %s last: %s",
                        remaining,
                        remaining,
                    )
                    for name in remaining:
                        ordered.append(name_to_cls[name])
                return ordered

            def _resolve_classes(self) -> list[Any]:
                \"\"\"Resolve mapper objects to their underlying ORM classes.

                Returns:
                    List of ORM model classes.
                \"\"\"
                classes: list[Any] = []
                for model in self._models:
                    cls = model.class_ if hasattr(model, "class_") else model
                    if hasattr(cls, "__mapper__"):
                        classes.append(cls)
                return classes

            def _get_dependencies(
                self,
                cls: Any,
                known: dict[str, Any],
            ) -> list[str]:
                \"\"\"Return names of models that *cls* depends on via FK columns.

                Args:
                    cls: ORM model class.
                    known: Mapping of class name to class for registered models.

                Returns:
                    List of model class names that *cls* has FK references to.
                \"\"\"
                deps: list[str] = []
                try:
                    for rel in cls.__mapper__.relationships:
                        related_cls = rel.mapper.class_
                        if related_cls.__name__ in known:
                            deps.append(related_cls.__name__)
                except Exception:
                    pass
                return deps
    """)
    dest.write_text(content)


def _write_seeder_route(dest: Path) -> None:
    """Write ``app/api/routes/seeder.py`` POST /dev/seed route (dev only).

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"POST /dev/seed — seed the database with test data (dev/staging only).

        This route is only active when ``SEEDER_ENABLED=true`` in settings.
        In production it returns 404 immediately.
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Annotated

        from fastapi import APIRouter, Depends, HTTPException, Query
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.config import settings

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/dev", tags=["dev"])


        async def _get_session() -> AsyncSession:
            \"\"\"Get async database session dependency.

            Returns:
                An async SQLAlchemy session.

            Raises:
                ImportError: When the session module is unavailable.
            \"\"\"
            from app.core.session import get_session
            async for session in get_session():
                return session


        @router.post("/seed")
        async def seed_database(
            count: Annotated[int, Query(ge=1, le=1000)] = 10,
            session: AsyncSession = Depends(_get_session),
        ) -> dict:
            \"\"\"Seed the database with realistic test data.

            Only available when ``SEEDER_ENABLED=true`` in settings.
            Seeds all registered models in FK-safe topological order.

            Args:
                count: Number of rows to insert per model (1-1000, default 10).
                session: Injected async database session.

            Returns:
                Dict with seeded row counts per model.

            Raises:
                HTTPException: 404 when seeding is disabled (production guard).
                HTTPException: 500 when seeding fails.
            \"\"\"
            if not settings.SEEDER_ENABLED:
                raise HTTPException(
                    status_code=404,
                    detail={"detail": "Seeder not enabled in this environment."},
                )
            try:
                from app.seeder import DataSeeder
                seeder = DataSeeder(session)
                results = await seeder.seed(count=count)
                await session.commit()
                total = sum(results.values())
                logger.info("Seeded %d total rows across %d models", total, len(results))
                return {"seeded": results, "total_rows": total}
            except Exception as exc:
                logger.error("Seeding failed: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail={"detail": f"Seeding failed: {exc}"},
                ) from exc
    """)
    dest.write_text(content)


def _write_seed_script(dest: Path) -> None:
    """Write ``scripts/seed.py`` CLI entry point.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"CLI script: seed the database with test data.

        Usage::

            python scripts/seed.py --count 100

        Requires SEEDER_ENABLED=true in the environment or .env file.
        \"\"\"

        from __future__ import annotations

        import argparse
        import asyncio
        import os
        import sys
        from pathlib import Path


        def _setup_path() -> None:
            \"\"\"Add project root to sys.path so app imports work.\"\"\"
            project_root = Path(__file__).parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))


        async def _run(count: int) -> None:
            \"\"\"Run the seeder asynchronously.

            Args:
                count: Number of rows to seed per model.
            \"\"\"
            from app.core.config import settings
            if not settings.SEEDER_ENABLED:
                print("ERROR: SEEDER_ENABLED=false. Set it to true in .env to use the seeder.")
                sys.exit(1)
            from app.core.session import async_session
            async with async_session() as session:
                from app.seeder import DataSeeder
                seeder = DataSeeder(session)
                results = await seeder.seed(count=count)
                await session.commit()
            total = sum(results.values())
            print(f"Seeded {total} total rows:")
            for model, rows in sorted(results.items()):
                print(f"  {model}: {rows} rows")


        def main() -> None:
            \"\"\"Parse CLI arguments and run the seeder.\"\"\"
            _setup_path()
            parser = argparse.ArgumentParser(description="Seed the database with test data.")
            parser.add_argument(
                "--count",
                type=int,
                default=int(os.environ.get("SEEDER_DEFAULT_COUNT", "10")),
                help="Number of rows to seed per model (default: SEEDER_DEFAULT_COUNT or 10).",
            )
            args = parser.parse_args()
            asyncio.run(_run(args.count))


        if __name__ == "__main__":
            main()
    """)
    dest.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the seeder router in app/routes/__init__.py idempotently.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    content = routes_init.read_text()
    import_line = "from app.api.routes.seeder import router as seeder_router"
    include_line = "api_router.include_router(seeder_router)"
    if import_line in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Append SEEDER_* settings to app/core/config.py idempotently.

    Args:
        config_file: Path to the project's ``app/core/config.py``.
    """
    content = config_file.read_text()
    fields = [
        "    SEEDER_ENABLED: bool = False",
        "    SEEDER_DEFAULT_COUNT: int = 10",
    ]
    new_lines: list[str] = []
    for field in fields:
        field_name = field.strip().split(":")[0]
        if field_name not in content:
            new_lines.append(field)
    if not new_lines:
        return
    if "settings = Settings()" in content:
        content = content.replace(
            "settings = Settings()",
            "\n".join(new_lines) + "\n\nsettings = Settings()",
        )
    else:
        content = content.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n"
    config_file.write_text(content)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: ``time.monotonic()`` snapshot taken at function entry.

    Returns:
        Elapsed time in integer milliseconds.
    """
    return int((time.monotonic() - start) * 1000)
