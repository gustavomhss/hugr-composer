"""`fastapi_data` — the data-domain tree dispatcher.

ONE MCP tool that routes to slice tool(s) + primitive(s) under the `data` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical template this file mirrors.

M3.2 fan-out: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing, and primitive copy live in ``hugr_core.dispatch`` — the generic
engine shared by every domain. The data tables (SLICES / PRIMITIVES /
BUNDLE_SLICES / MCP_TOOL) are unchanged, so the public contract is
byte-identical to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "data"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the data domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_audit_log": {
        "mod": "add_audit_log",
        "pkg": "adapt.extend.crud_data",
        "desc": "Copy AuditEvent + TamperEvidentAuditLog primitives and the AuditLogAdapter into the project,...",
    },
    "add_bulk_operations": {
        "mod": "add_bulk_operations",
        "pkg": "adapt.extend.crud_data",
        "desc": "Add bulk create/update/delete endpoints for all models",
    },
    "add_cursor_pagination": {
        "mod": "add_cursor_pagination",
        "pkg": "adapt.extend.crud_data",
        "desc": "Replace offset pagination with cursor-based pagination across all list endpoints",
    },
    "add_data_export": {
        "mod": "add_data_export",
        "pkg": "adapt.extend.crud_data",
        "desc": "Add CSV/XLSX data export endpoints for all major resources",
    },
    "add_data_import": {
        "mod": "add_data_import",
        "pkg": "adapt.extend.crud_data",
        "desc": "Add CSV/Excel upload with async processing, validation and error reporting",
    },
    "add_data_versioning": {
        "mod": "add_data_versioning",
        "pkg": "adapt.extend.crud_data",
        "desc": "Add draft/published/archived lifecycle with diff to any content type",
    },
    "add_event_driven": {
        "mod": "add_event_driven",
        "pkg": "adapt.evolve",
        "desc": "Add event-driven architecture with domain events and async handlers",
    },
    "add_event_sourcing": {
        "mod": "add_event_sourcing",
        "pkg": "adapt.extend.crud_data",
        "desc": "Copy EventSourcedStore + DomainEvent primitives and the EventSourcedStoreAdapter into the pr...",
    },
    "add_file_upload": {
        "mod": "add_file_upload",
        "pkg": "adapt.extend.crud_data",
        "desc": "Add file upload support (multipart/form-data) with S3-compatible storage backend",
    },
    "add_outbox_pattern": {
        "mod": "add_outbox_pattern",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add transactional outbox pattern for reliable event publishing",
    },
    "add_saga": {
        "mod": "add_saga",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Copy SagaOrchestrator primitive + SagaAdapter into the project and wire a ≤20-line app/saga....",
    },
    "add_search": {
        "mod": "add_search",
        "pkg": "adapt.extend.crud_data",
        "desc": "Add full-text search endpoints backed by PostgreSQL tsvector or Elasticsearch",
    },
    "add_soft_delete": {
        "mod": "add_soft_delete",
        "pkg": "adapt.extend.crud_data",
        "desc": "Copy UnitOfWork primitive + FastAPI adapter into the project and wire a ≤20-line app/soft_de...",
    },
}

PRIMITIVES: dict[str, str] = {
    "Aggregate": "Define a consistency boundary around a cluster of entities and value objects governed by a s...",
    "AntiCorruptionLayer": "Translate between a local model and a foreign or legacy model so upstream semantics cannot l...",
    "BoundedContext": "Declare the explicit linguistic and model boundary within which one ubiquitous language and...",
    "ChangeDataCapture": "Publish an ordered stream of row-level changes from a source database so downstream systems...",
    "ConfigBinding": "Bind a namespaced slice of runtime configuration to a typed record, validated at startup so...",
    "DataMapper": "Move state between in-memory domain objects and rows in storage while keeping both ignorant...",
    "DiContainer": "Registry that resolves a typed request for a dependency into a constructed instance obeying...",
    "IdentityMap": "Cache loaded domain objects by identity inside one session so the same row is never represen...",
    "LegalHold": "Suspend retention-driven deletion and erasure cascades for records covered by a litigation o...",
    "LifetimeScope": "Typed enumeration that fixes how long a resolved instance lives: the whole process, one requ...",
    "MaterializedView": "Maintain a pre-computed query result kept up to date by an incremental feed so read queries...",
    "OptimisticConcurrency": "Compare-and-swap write pattern; write fails cleanly when the stored version changed since th...",
    "PiiClassification": "Tag every persisted field with a sensitivity class so serialization goes through one central...",
    "Repository": "Mediate between the domain model and the data-mapping layer with a collection-like interface...",
    "ShardedCounter": "Hot-key-safe monotonic per-key counter distributed across N fixed shards; value() sums acros...",
    "Specification": "Encapsulate a predicate over a domain object so selection, validation, and criteria share on...",
    "TransactionalBatch": "Offer cross-key atomicity against one state store without application-level two-phase commit...",
    "UnitOfWork": "Track object changes during a business transaction and flush them to storage as one atomic c...",
    "ValueObject": "Represent a descriptive concept whose identity is defined by its attributes and which is imm...",
}

# Curated 'bundle' — 8 canonical data slices.
# Rationale: Core CRUD + persistence essentials: audit trail, soft-delete, pagination, bulk ops, import/export, outbox reliability, and search.

BUNDLE_SLICES: tuple[str, ...] = (
    "add_audit_log",
    "add_soft_delete",
    "add_cursor_pagination",
    "add_bulk_operations",
    "add_data_export",
    "add_data_import",
    "add_outbox_pattern",
    "add_search",
)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_data",
    "description": (
        "Data domain dispatcher (HuGR tree pattern). ONE tool that routes to every data-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full data tree + primitive catalog.\n  • 'bundle' → one-shot: installs 8 curated data slices (add_audit_log, add_soft_delete, add_cursor_pagination, add_bulk_operations, add_data_export, add_data_import, ...).\n  • '<slice>' → install ONE slice (add_audit_log, add_bulk_operations, add_cursor_pagination, add_data_export, add_data_import, add_data_versioning, add_event_driven, add_event_sourcing, add_file_upload, add_outbox_pattern, add_saga, add_search, add_soft_delete).\n  • 'primitive' → copy ONE Lego block (Aggregate, AntiCorruptionLayer, BoundedContext, ChangeDataCapture, ConfigBinding, DataMapper, DiContainer, IdentityMap, LegalHold, LifetimeScope, MaterializedView, OptimisticConcurrency, PiiClassification, Repository, ShardedCounter, Specification, TransactionalBatch, UnitOfWork, ValueObject).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["data", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_data",
}


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="data",
    tool_name="fastapi_data",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="data domain tree (8 bundle + 13 slices + 19 primitives)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    toolinput_factory=_toolinput_factory,
    primitive_missing_args_next_steps=(
        "Example: fastapi_data(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
        "Call fastapi_data(action='list') to see available primitive names.",
    ),
)

fastapi_data = make_dispatcher(_CONFIG)
