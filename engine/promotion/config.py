"""skill-001 configuration for the shared promotion pipeline.

Binds this skill's filesystem layout + framework-coupling vocabulary (the data
``hugr_core.promotion`` is generic over) into a :class:`PromotionConfig`. The
vocabulary stays here as code — adding/removing a framework module is a skill
decision, not a core change.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hugr_core.promotion import PromotionConfig

SKILL_ROOT = Path(__file__).resolve().parents[2]

# Layout-aware CONTRACT.md resolution (mirrors the old promote.py): in the
# Arsenal monorepo the skill lived under `skills/SKILL-001-…/`, so CONTRACT.md
# was two levels up; in this standalone repo the skill root IS the repo root.
_CONTRACT_PATH = (
    SKILL_ROOT.parents[1] / "CONTRACT.md"
    if SKILL_ROOT.parent.name == "skills"
    else SKILL_ROOT / "CONTRACT.md"
)

# Registered primitives may not import these (CONTRACT §B1.0.1) — skill-owned.
_FRAMEWORK_MODULES = frozenset(
    {
        "fastapi",
        "starlette",
        "sqlalchemy",
        "sqlmodel",
        "pydantic",
        "django",
        "flask",
        "tornado",
        "aiohttp",
    }
)

_IMPLICIT_FRAMEWORK_TOKENS = {
    # SQLAlchemy 2.0 ORM
    "Mapped[": "sqlalchemy",
    "mapped_column(": "sqlalchemy",
    "DeclarativeBase": "sqlalchemy",
    "class Base(": "sqlalchemy",
    "(Base)": "sqlalchemy",
    # FastAPI / Starlette
    "APIRouter(": "fastapi",
    "Depends(": "fastapi",
    "FastAPI(": "fastapi",
    "Request(": "starlette",
    "BaseHTTPMiddleware": "starlette",
    # Pydantic v2 hints
    "class Config:\n": "pydantic",
}

# Quarantine tool-path-prefix → registry namespace (skill bucket vocabulary).
_QUARANTINE_NAMESPACE_MAP = {
    "api_design": "api",
    "auth_access": "auth",
    "crud_data": "data",
    "infrastructure": "resiliency",
    "realtime": "api",
    "testing_tools": "extras",
}


def build_config() -> PromotionConfig:
    """Assemble the PromotionConfig from this skill's layout (read per call)."""
    return PromotionConfig(
        skill_root=SKILL_ROOT,
        registry_path=SKILL_ROOT / "engine" / "primitives_by_concern.yaml",
        catalog_path=SKILL_ROOT / "engine" / "index" / "catalog.json",
        staging_root=SKILL_ROOT / "core" / "venous" / "_staging",
        adapters_dir=SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi",
        benchmark_specs_dir=SKILL_ROOT / "benchmarks" / "specs",
        ledger_json_path=SKILL_ROOT / "engine" / "promotion" / "ledger.json",
        ledger_md_path=SKILL_ROOT / "engine" / "promotion" / "LEDGER.md",
        signal_roots=(
            SKILL_ROOT / "generators",
            SKILL_ROOT / "modules",
            SKILL_ROOT / "adapt",
            SKILL_ROOT / "benchmarks" / "specs",
        ),
        framework_modules=_FRAMEWORK_MODULES,
        implicit_framework_tokens=_IMPLICIT_FRAMEWORK_TOKENS,
        quarantine_namespace_map=_QUARANTINE_NAMESPACE_MAP,
        # Executor (M2.5) fields — the lite-ratification CONTRACT.md and the
        # post-flight catalog-rebuild + contract-audit subprocess argvs.
        contract_path=_CONTRACT_PATH,
        catalog_rebuild_cmd=[sys.executable, "-m", "engine.index.manifest", "build"],
        contract_check_cmd=[sys.executable, "-m", "engine.audit.contract_check"],
        contract_check_success_marker="ALL GREEN",
    )
