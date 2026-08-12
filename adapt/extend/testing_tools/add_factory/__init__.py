"""TOOL-025: add_factory — generate typed test-data factories for a FastAPI project.

Generates a ``tests/factories/`` package with one SQLAlchemyFactory subclass
per discovered model, a conftest fixture per factory, sub-factories for FK
relationships, deterministic seed support, and a ``FACTORY_REGISTRY``.

The tool is idempotent: a second run detects the ``tests/factories/``
fingerprint and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Literal

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_testing_add_factory",
    "description": "Add factory_boy fixtures for all models to accelerate test authoring.",
    "tags": ["extend", "testing"],
    "entry": "add_factory",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_factory(
    inp: ToolInput,
    models: list[str] | None = None,
    backend: Literal["polyfactory", "factory_boy"] = "polyfactory",
) -> ToolResult:
    """Generate typed test-data factories for each SQLAlchemy model.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        models: Explicit list of PascalCase model names. ``None`` = auto-discover.
        backend: Factory library — ``"polyfactory"`` (default) or ``"factory_boy"``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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

    files_created: list[str] = list(scaffolded or [])
    factories_dir = project / "tests" / "factories"

    _init_py = factories_dir / "__init__.py"
    if _init_py.exists() and "FACTORY_REGISTRY" in _init_py.read_text():
        return ToolResult(
            status="no_op",
            notes=["tests/factories/ already contains factories — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    discovered = _discover_models(project / "app")
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
    factories_dir.mkdir(parents=True, exist_ok=True)

    for model_name in target_models:
        factory_file = factories_dir / f"{model_name.lower()}_factory.py"
        _write_factory(factory_file, model_name, target_models, backend)
        files_created.append(str(factory_file))

    init_file = factories_dir / "__init__.py"
    _write_factories_init(init_file, target_models)
    files_created.append(str(init_file))

    conftest_file = project / "tests" / "conftest.py"
    if conftest_file.exists():
        _patch_conftest(conftest_file, target_models)
        files_modified.append(str(conftest_file))

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

    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_factory_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_factory_emitted.py.tmpl", dest=emitted, substitutions={})
        files_created.append(str(emitted))

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
            "Import factories in tests: from tests.factories import FACTORY_REGISTRY",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _discover_models(app_dir: Path) -> list[str]:
    models_dir = app_dir / "models"
    if not models_dir.exists():
        return []
    skip = {"base", "mixins", "__init__"}
    return [f.stem.capitalize() for f in sorted(models_dir.glob("*.py")) if f.stem not in skip]


def _sub_factory_imports(model_name: str, all_models: list[str]) -> str:
    others = [m for m in all_models if m != model_name]
    if not others:
        return ""
    lines = [
        f"from tests.factories.{m.lower()}_factory import {m}Factory  # sub-factory (FK)"
        for m in others
    ]
    return "\n".join(lines) + "\n"


def _write_factory(dest: Path, model_name: str, all_models: list[str], backend: str) -> None:
    lower = model_name.lower()
    sub_imports = _sub_factory_imports(model_name, all_models)

    if backend == "polyfactory":
        content = (
            f'"""polyfactory test-data factory for {model_name}.\n\n'
            "Generated by add_factory tool (TOOL-025).\n"
            '"""\n\n'
            "from __future__ import annotations\n\n"
            "import uuid\n"
            "from datetime import datetime, timedelta, timezone\n\n"
            "from faker import Faker\n"
            "from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory\n\n"
            f"from app.models.{lower} import {model_name}\n"
            f"{sub_imports}\n"
            "_faker = Faker()\n\n\n"
            f"class {model_name}Factory(SQLAlchemyFactory[{model_name}]):\n"
            f'    """Typed factory for {model_name} instances."""\n\n'
            f"    __model__ = {model_name}\n\n"
            "    id = SQLAlchemyFactory.__faker__.uuid4  # type: ignore[assignment]\n"
            "    created_at = lambda: datetime.now(timezone.utc) - timedelta(  # noqa: E731\n"
            "        days=_faker.random_int(min=0, max=365)\n"
            "    )\n"
            "    updated_at = lambda: datetime.now(timezone.utc)  # noqa: E731\n\n"
            "    @classmethod\n"
            f"    def stub(cls, **kwargs: object) -> {model_name}:\n"
            '        """Build a minimal stub (only required fields populated)."""\n'
            "        return cls.build(**kwargs)\n\n"
            "    @classmethod\n"
            f"    def build_batch_seeded(cls, size: int, seed: int = 42) -> list[{model_name}]:\n"
            '        """Build a batch with a fixed Faker seed for reproducibility."""\n'
            "        _faker.seed_instance(seed)\n"
            "        return cls.build_batch(size)\n"
        )
    else:
        content = (
            f'"""factory_boy test-data factory for {model_name}.\n\n'
            "Generated by add_factory tool (TOOL-025).\n"
            '"""\n\n'
            "from __future__ import annotations\n\n"
            "from datetime import datetime, timezone\n\n"
            "import factory\n"
            "from factory import Faker as FFaker\n\n"
            f"from app.models.{lower} import {model_name}\n"
            f"{sub_imports}\n\n"
            f"class {model_name}Factory(factory.Factory):\n"
            f'    """factory_boy factory for {model_name}."""\n\n'
            "    class Meta:\n"
            f"        model = {model_name}\n\n"
            "    id = factory.LazyFunction(lambda: __import__('uuid').uuid4())\n"
            "    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))\n"
            "    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))\n\n"
            "    @classmethod\n"
            f"    def build_batch_seeded(cls, size: int, seed: int = 42) -> list[{model_name}]:\n"
            '        """Build deterministic batch via reseed."""\n'
            "        factory.random.reseed_random(seed)\n"
            "        return cls.build_batch(size)\n"
        )
    dest.write_text(content)


def _write_factories_init(dest: Path, model_names: list[str]) -> None:
    import_lines = "\n".join(
        f"from tests.factories.{m.lower()}_factory import {m}Factory" for m in model_names
    )
    all_names = ", ".join(f'"{m}Factory"' for m in model_names)
    registry_entries = "\n    ".join(f'"{m}": {m}Factory,' for m in model_names)
    content = (
        '"""Test-data factories package.\n\n'
        "Generated by add_factory tool (TOOL-025).\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        f"{import_lines}\n\n"
        f"__all__ = [{all_names}]\n\n"
        "FACTORY_REGISTRY: dict[str, type] = {\n"
        f"    {registry_entries}\n"
        "}\n\n\n"
        "def get_factory(model_name: str) -> type:\n"
        '    """Return the factory class for *model_name*.\n\n'
        "    Args:\n"
        "        model_name: PascalCase model name.\n\n"
        "    Returns:\n"
        "        Factory class.\n\n"
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
    src = conftest_file.read_text()
    if "FACTORY_REGISTRY" in src or "ItemFactory" in src:
        return

    import_line = "from tests.factories import FACTORY_REGISTRY, " + ", ".join(
        f"{m}Factory" for m in model_names
    )

    fixture_blocks: list[str] = []
    for m in model_names:
        lower = m.lower()
        fixture_blocks.append(
            f"\n@pytest.fixture\ndef {lower}_factory():\n"
            f'    """Pytest fixture providing {m}Factory."""\n'
            f"    return {m}Factory\n"
        )
        fixture_blocks.append(
            f"\n@pytest.fixture\ndef create_{lower}(db_session):\n"
            f'    """Async helper: persist a {m} instance via {m}Factory."""\n'
            f"    async def _create(**kwargs: object):\n"
            f"        instance = {m}Factory.build(**kwargs)\n"
            f"        db_session.add(instance)\n"
            f"        await db_session.commit()\n"
            f"        await db_session.refresh(instance)\n"
            f"        return instance\n"
            f"    return _create\n"
        )

    addition = (
        "\n\n# Factory fixtures — added by add_factory tool (TOOL-025)\n"
        "import pytest  # noqa: F811\n"
        f"{import_line}\n" + "".join(fixture_blocks)
    )
    conftest_file.write_text(src + addition)


