"""TOOL-025: add_factory — generate typed test-data factories for a FastAPI project.

Generates a ``tests/factories/`` package with one polyfactory ``SQLAlchemyFactory``
subclass per discovered model, a conftest fixture per factory, sub-factories for
FK relationships, deterministic seed support, and a ``FACTORY_REGISTRY`` for dynamic
access.  The ``factory_boy`` backend is available as a fallback for legacy codebases.

The tool is idempotent: a second run detects the ``tests/factories/`` fingerprint and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.testing_tools.add_factory import add_factory

    result = add_factory(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/tests/factories/__init__.py", ...]
    print(result.next_steps)    # ["pip install polyfactory faker", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Literal

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_factory",
    "description": "Add factory_boy fixtures for all models to accelerate test authoring.",
    "tags": ["extend", "testing"],
    "entry": "add_factory",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_factory(
    inp: ToolInput,
    models: list[str] | None = None,
    backend: Literal["polyfactory", "factory_boy"] = "polyfactory",
) -> ToolResult:
    """Generate typed test-data factories for each SQLAlchemy model.

    Discovers models under ``app/models/``, writes a factory class per model
    in ``tests/factories/``, and patches ``tests/conftest.py`` with per-model
    pytest fixtures.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        models: Explicit list of PascalCase model names to generate factories
            for.  ``None`` means all discovered models.
        backend: Factory library — ``"polyfactory"`` (default, Pydantic-v2
            native) or ``"factory_boy"`` (legacy SQLAlchemy codebases).

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
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

    factories_dir = project / "tests" / "factories"

    # --- Pre-flight: already installed? -------------------------------------
    if (factories_dir / "__init__.py").exists():
        init_src = (factories_dir / "__init__.py").read_text()
        if "Factory" in init_src or "FACTORY_REGISTRY" in init_src:
            return ToolResult(
                status="no_op",
                notes=["tests/factories/ already contains factories — skipped."],
                execution_time_ms=_elapsed_ms(start),
            )

    # --- Discover models ----------------------------------------------------
    discovered = _discover_models(project / "app")
    # Use explicit models list if provided (even if empty), else auto-discover.
    target_models = models if models is not None else discovered
    if not target_models:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would generate {backend} factories for: {', '.join(target_models)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Create tests/factories/ package ----------------------------
    factories_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 2: Write per-model factory files ------------------------------
    for model_name in target_models:
        factory_file = factories_dir / f"{model_name.lower()}_factory.py"
        _write_factory(factory_file, model_name, target_models, backend)
        files_created.append(str(factory_file))

    # --- Step 3: Write factories/__init__.py --------------------------------
    init_file = factories_dir / "__init__.py"
    _write_factories_init(init_file, target_models)
    files_created.append(str(init_file))

    # --- Step 4: Patch tests/conftest.py with fixtures ----------------------
    conftest_file = project / "tests" / "conftest.py"
    if conftest_file.exists():
        _patch_conftest(conftest_file, target_models)
        files_modified.append(str(conftest_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Generated {backend} factories for: {', '.join(target_models)}",
            "Each factory exposes .build() / .build_batch(n) for in-memory instances.",
            "Use factory.random.reseed_random(seed) for deterministic CI reproducibility.",
        ],
        next_steps=[
            f"pip install {'polyfactory faker' if backend == 'polyfactory' else 'factory-boy faker'}",
            "Import factories in tests: from tests.factories import ItemFactory, UserFactory",
            "Use item_factory / user_factory pytest fixtures from conftest.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names from ``app/models/``, excluding scaffolding files.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item", "User"]``).
    """
    models_dir = app_dir / "models"
    if not models_dir.exists():
        return []
    skip = {"base", "mixins", "__init__"}
    return [f.stem.capitalize() for f in sorted(models_dir.glob("*.py")) if f.stem not in skip]


def _sub_factory_imports(model_name: str, all_models: list[str]) -> str:
    """Build sub-factory import lines for FK relationships.

    Imports every other model factory so that FK fields can be resolved in-memory
    without hitting the database during ``.build()`` calls.

    Args:
        model_name: Current model being generated (excluded from imports).
        all_models: Full list of model names to generate imports for.

    Returns:
        Newline-separated import string, empty if no FK deps exist.
    """
    others = [m for m in all_models if m != model_name]
    if not others:
        return ""
    lines = [
        f"from tests.factories.{m.lower()}_factory import {m}Factory  # sub-factory (FK)"
        for m in others
    ]
    # Join with newline + 12-space indent so that, after the first line is
    # placed inline in the template (which already supplies 12 leading spaces),
    # all subsequent lines also align correctly at the top-level indentation
    # used by textwrap.dedent().
    return ("\n" + "            ").join(lines) + "\n"


def _write_factory(dest: Path, model_name: str, all_models: list[str], backend: str) -> None:
    """Write a single factory module for *model_name*.

    Args:
        dest: Destination path for the factory file.
        model_name: PascalCase model class name.
        all_models: Full model list (used for sub-factory imports).
        backend: ``"polyfactory"`` or ``"factory_boy"``.
    """
    lower = model_name.lower()
    sub_imports = _sub_factory_imports(model_name, all_models)

    if backend == "polyfactory":
        content = textwrap.dedent(f"""\
            \"\"\"polyfactory test-data factory for {model_name}.

            Generated by add_factory tool (TOOL-025).
            Re-run the tool after model changes to regenerate.
            \"\"\"

            from __future__ import annotations

            import uuid
            from datetime import datetime, timedelta, timezone

            from faker import Faker
            from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory

            from app.models.{lower} import {model_name}
            {sub_imports}
            _faker = Faker()

            # ---------------------------------------------------------------------------
            # Factory
            # ---------------------------------------------------------------------------


            class {model_name}Factory(SQLAlchemyFactory[{model_name}]):
                \"\"\"Typed factory for {model_name} instances.

                Usage::

                    obj = {model_name}Factory.build()           # unsaved, in-memory
                    batch = {model_name}Factory.build_batch(5)   # list of 5 unsaved
                    # For deterministic tests:
                    import factory
                    factory.random.reseed_random(42)

                Attributes:
                    __model__: Bound SQLAlchemy model class.
                    __faker__: Shared Faker instance (locale=en_US).
                \"\"\"

                __model__ = {model_name}

                # --- Primary key ---------------------------------------------------
                id = SQLAlchemyFactory.__faker__.uuid4  # type: ignore[assignment]

                # --- Timestamp columns --------------------------------------------
                created_at = lambda: datetime.now(timezone.utc) - timedelta(  # noqa: E731
                    days=_faker.random_int(min=0, max=365)
                )
                updated_at = lambda: datetime.now(timezone.utc)  # noqa: E731

                # --- Traits -------------------------------------------------------

                @classmethod
                def stub(cls, **kwargs: object) -> {model_name}:
                    \"\"\"Build a minimal stub (only required fields populated).

                    Args:
                        **kwargs: Field overrides.

                    Returns:
                        Unsaved {model_name} instance.
                    \"\"\"
                    return cls.build(**kwargs)

                @classmethod
                def build_batch_seeded(cls, size: int, seed: int = 42) -> list[{model_name}]:
                    \"\"\"Build a batch with a fixed Faker seed for reproducibility.

                    Args:
                        size: Number of instances to build.
                        seed: Random seed for deterministic output.

                    Returns:
                        List of *size* unsaved {model_name} instances.
                    \"\"\"
                    _faker.seed_instance(seed)
                    return cls.build_batch(size)
            """)
    else:
        # factory_boy backend
        content = textwrap.dedent(f"""\
            \"\"\"factory_boy test-data factory for {model_name}.

            Generated by add_factory tool (TOOL-025).
            \"\"\"

            from __future__ import annotations

            from datetime import datetime, timezone

            import factory
            from factory import Faker as FFaker

            from app.models.{lower} import {model_name}
            {sub_imports}

            class {model_name}Factory(factory.Factory):
                \"\"\"factory_boy factory for {model_name}.

                Usage::

                    obj = {model_name}Factory.build()
                    factory.random.reseed_random(42)
                \"\"\"

                class Meta:
                    model = {model_name}

                id = factory.LazyFunction(lambda: __import__("uuid").uuid4())
                created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
                updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))

                @classmethod
                def build_batch_seeded(cls, size: int, seed: int = 42) -> list[{model_name}]:
                    \"\"\"Build deterministic batch via reseed.

                    Args:
                        size: Batch size.
                        seed: Random seed.

                    Returns:
                        List of *size* unsaved instances.
                    \"\"\"
                    factory.random.reseed_random(seed)
                    return cls.build_batch(size)
            """)

    dest.write_text(content)


def _write_factories_init(dest: Path, model_names: list[str]) -> None:
    """Write ``tests/factories/__init__.py`` with registry and re-exports.

    Args:
        dest: Destination path.
        model_names: PascalCase names of all generated factories.
    """
    import_lines = "\n".join(
        f"from tests.factories.{m.lower()}_factory import {m}Factory"
        for m in model_names
    )
    all_names = ", ".join(f'"{m}Factory"' for m in model_names)
    registry_entries = "\n    ".join(
        f'"{m}": {m}Factory,' for m in model_names
    )
    # Build content via explicit string construction to avoid textwrap.dedent
    # misbehaving when interpolated variables have no leading whitespace.
    content = (
        '"""Test-data factories package.\n'
        "\n"
        "Generated by add_factory tool (TOOL-025).  Re-run after model changes.\n"
        "\n"
        "Usage::\n"
        "\n"
        "    from tests.factories import ItemFactory, UserFactory\n"
        "    item = ItemFactory.build()\n"
        "    users = UserFactory.build_batch(10)\n"
        "\n"
        "    # Dynamic access\n"
        "    from tests.factories import get_factory\n"
        "    AnyFactory = get_factory(\"Item\")\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        f"{import_lines}\n"
        "\n"
        f"__all__ = [{all_names}]\n"
        "\n"
        "# ---------------------------------------------------------------------------\n"
        "# Registry — dynamic access by model name\n"
        "# ---------------------------------------------------------------------------\n"
        "\n"
        "FACTORY_REGISTRY: dict[str, type] = {\n"
        f"    {registry_entries}\n"
        "}\n"
        "\n"
        "\n"
        "def get_factory(model_name: str) -> type:\n"
        '    """Return the factory class for *model_name*.\n'
        "\n"
        "    Args:\n"
        '        model_name: PascalCase model name (e.g. ``"Item"``).\n'
        "\n"
        "    Returns:\n"
        "        Factory class.\n"
        "\n"
        "    Raises:\n"
        "        ValueError: If no factory is registered for *model_name*.\n"
        '    """\n'
        "    factory_cls = FACTORY_REGISTRY.get(model_name)\n"
        "    if factory_cls is None:\n"
        "        registered = list(FACTORY_REGISTRY.keys())\n"
        "        raise ValueError(\n"
        '            f"No factory registered for {model_name!r}. "\n'
        '            f"Registered: {registered}"\n'
        "        )\n"
        "    return factory_cls\n"
    )
    dest.write_text(content)


def _patch_conftest(conftest_file: Path, model_names: list[str]) -> None:
    """Append per-model pytest fixtures and create_* helpers to conftest.py.

    Args:
        conftest_file: Path to ``tests/conftest.py``.
        model_names: PascalCase model names for which to add fixtures.
    """
    src = conftest_file.read_text()
    if "FACTORY_REGISTRY" in src or "ItemFactory" in src:
        return

    import_line = (
        "from tests.factories import FACTORY_REGISTRY, "
        + ", ".join(f"{m}Factory" for m in model_names)
    )

    fixture_blocks: list[str] = []
    for m in model_names:
        lower = m.lower()
        fixture_blocks.append(textwrap.dedent(f"""\

            @pytest.fixture
            def {lower}_factory():
                \"\"\"Pytest fixture providing {m}Factory.

                Returns:
                    {m}Factory class (call .build() / .build_batch(n)).
                \"\"\"
                return {m}Factory


            @pytest.fixture
            async def create_{lower}(db, {lower}_factory):
                \"\"\"Async fixture helper: build + persist a {m} row.

                Args:
                    db: SQLAlchemy async session.
                    {lower}_factory: {m}Factory class.

                Returns:
                    Async callable accepting field overrides, returns persisted {m}.
                \"\"\"
                async def _create(**kwargs: object) -> object:
                    obj = {lower}_factory.build(**kwargs)
                    db.add(obj)
                    await db.flush()
                    await db.refresh(obj)
                    return obj
                return _create
            """))

    addition = textwrap.dedent(f"""\


        # ---------------------------------------------------------------------------
        # Factory fixtures — added by add_factory tool (TOOL-025)
        # ---------------------------------------------------------------------------
        import pytest  # noqa: F811 — may already be imported above
        {import_line}

        """) + "".join(fixture_blocks)

    conftest_file.write_text(src + addition)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds.
    """
    return int((time.monotonic() - start) * 1000)
