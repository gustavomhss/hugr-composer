"""WP-17 — compose-data constants: paths + taxonomy.

Path constants for the skill root, venous tree, and the §B1.1 registry
output. Plus the two taxonomy dicts (``CONCERN_BY_NS`` namespace→concern,
``DATA_CONCERN`` per-name split for the ``data`` namespace) and the
``concern_for`` helper. Read by every entries module's downstream consumer
(``_assembly``, ``_build``) and by the engine.audit._build_compose facade.

``SKILL_ROOT`` resolves to ``skills/SKILL-001-fastapi-production`` via
``parents[3]`` from this file (``engine/audit/compose_data/_constants.py``
— one nesting level deeper than the pre-split ``engine/audit/_build_compose.py``
which used ``parents[2]``).
"""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]
VENOUS = SKILL_ROOT / "core" / "venous"
REGISTRY = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"


# ---------------------------------------------------------------------------
# Concern mapping  (namespace → concern, with data split)
# ---------------------------------------------------------------------------
# Fixed taxonomy: auth, data.persistence, data.modelling, data.schema,
# events, observability, resiliency, security, compliance, policy, llm,
# cost, jobs, cache, api, flags, extras.

CONCERN_BY_NS = {
    "api": "api",
    "auth": "auth",
    "cache": "cache",
    "compliance": "compliance",
    "events": "events",
    "extras": "extras",
    "flags": "flags",
    "jobs": "jobs",
    "llm": "llm",
    "obs": "observability",
    "policy": "policy",
    "resiliency": "resiliency",
    "security": "security",
}

# Data namespace splits across persistence / modelling / schema.
DATA_CONCERN = {
    # data.persistence — storage mechanics, transaction semantics, caching
    "Repository": "data.persistence",
    "UnitOfWork": "data.persistence",
    "IdentityMap": "data.persistence",
    "DataMapper": "data.persistence",
    "TransactionalBatch": "data.persistence",
    "ChangeDataCapture": "data.persistence",
    "MaterializedView": "data.persistence",
    # data.modelling — DDD tactical/strategic patterns
    "Aggregate": "data.modelling",
    "ValueObject": "data.modelling",
    "Specification": "data.modelling",
    "BoundedContext": "data.modelling",
    "AntiCorruptionLayer": "data.modelling",
    # data.schema — typed bindings, classification, wiring
    "ConfigBinding": "data.schema",
    "DiContainer": "data.schema",
    "LifetimeScope": "data.schema",
    "PiiClassification": "data.schema",
    "LegalHold": "data.schema",
}


# ---------------------------------------------------------------------------
# concern_for helper
# ---------------------------------------------------------------------------


def concern_for(namespace: str, name: str) -> str:
    if namespace == "data":
        return DATA_CONCERN[name]
    return CONCERN_BY_NS[namespace]
