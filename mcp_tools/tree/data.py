"""`fastapi_data` — the data-domain tree dispatcher.

ONE MCP tool that routes to 13 slice tool(s) + 19 primitive(s) under the `data` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

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
# Shared envelope (same shape as tier-1 meta tools)
# ---------------------------------------------------------------------------


def _envelope(*, ok: bool, what: str, result: Any, next_steps: list[str], t0: float) -> dict:
    return {
        "ok": ok,
        "what_happened": what,
        "result": result,
        "next_steps": next_steps[:5],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# Slice routing
# ---------------------------------------------------------------------------


def _call_slice(slice_name: str, **kwargs) -> dict:
    """Route to the underlying `<pkg>.<mod>` tool.

    Multi-bucket aware: each SLICES entry carries its own `pkg`
    because data tools span multiple adapt/ subtrees. Routes through
    the shared `dispatch_via_toolinput` helper so the public contract
    matches the central MCP discovery wrapper + `tree/auth.py`
    (closes Codex 3 F-001).
    """
    from mcp_tools._tree_dispatch import dispatch_via_toolinput

    meta = SLICES[slice_name]
    return dispatch_via_toolinput(
        module_path=f"{meta['pkg']}.{meta['mod']}",
        entry_name=meta["mod"],
        slice_name=slice_name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Primitive routing
# ---------------------------------------------------------------------------


def _is_non_empty(p: Path) -> bool:
    """Return True if *p* exists, is a directory, and has at least one child."""
    return p.is_dir() and any(p.iterdir())


def _copy_primitive(name: str, output_dir: str, *, force: bool = False) -> dict:
    """Copy core/venous/data/<Name>/ into <output_dir>/core/venous/data/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json +
    _evidence/ (per .gitignore). Also copies the matching fastapi
    adapter under _adapters/fastapi/ if one exists.

    F-002 (Codex 3): default non-destructive. When ``force=False`` and the
    target directory exists with content, return ``status="skipped"``
    instead of wiping the user's customizations. Pass ``force=True`` to
    opt back into the legacy overwrite behaviour.

    F-003 (Codex 3): target layout is ``<output_dir>/core/venous/<ns>/<Name>/``
    (no ``app/`` prefix) so emitted imports
    ``from core.venous.<ns>.<Name>.<Name> import <Name>`` resolve.
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain data. Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_DIR / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "core" / "venous" / "data" / name
    warnings: list[str] = []
    if _is_non_empty(target) and not force:
        return {
            "primitive": name,
            "status": "skipped",
            "reason": (
                f"target exists and is non-empty: {target.relative_to(output_dir)}. "
                "Pass params={'force': True} to overwrite (destructive)."
            ),
            "files_created": [],
            "target": str(target.relative_to(output_dir)),
        }
    if target.exists() and force:
        warnings.append(
            f"force=True: removed existing {target.relative_to(output_dir)} "
            "before copy (user customisations lost)."
        )
        shutil.rmtree(target)
    shutil.copytree(
        src,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "_t0_report.json",
            "_evidence",
            "*.pyc",
        ),
    )
    files_created = sorted(str(p.relative_to(output_dir)) for p in target.rglob("*") if p.is_file())
    adapter_name = f"{name}Adapter.py"
    adapter_src = ADAPTERS_FASTAPI / adapter_name
    if adapter_src.exists():
        adapter_target = Path(output_dir) / "core" / "venous" / "_adapters" / "fastapi"
        adapter_target.mkdir(parents=True, exist_ok=True)
        shutil.copy(adapter_src, adapter_target / adapter_name)
        files_created.append(str((adapter_target / adapter_name).relative_to(output_dir)))
        test_src = ADAPTERS_FASTAPI / f"test_{adapter_name}"
        if test_src.exists():
            shutil.copy(test_src, adapter_target / f"test_{adapter_name}")
            files_created.append(
                str((adapter_target / f"test_{adapter_name}").relative_to(output_dir))
            )
    result = {
        "primitive": name,
        "status": "copied",
        "files_created": files_created,
        "target": str(target.relative_to(output_dir)),
    }
    if warnings:
        result["warnings"] = warnings
    return result


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


def fastapi_data(action: str, params: dict | None = None) -> dict:
    """See MCP_TOOL description.

    Signature note: `params` is a polymorphic dict whose expected keys
    depend on `action`. FastMCP doesn't support **kwargs in tool
    signatures, so a single `params` dict is the uniform contract.
    """
    t0 = time.perf_counter()
    params = params or {}

    if action == "list":
        return _envelope(
            ok=True,
            what="data domain tree (8 bundle + 13 slices + 19 primitives)",
            result={
                "domain": "data",
                "bundle": {
                    "description": (
                        "Install the curated production data stack: "
                        f"{len(BUNDLE_SLICES)} slices composed in order."
                    ),
                    "slices_installed": list(BUNDLE_SLICES),
                    "required_params": {"output_dir": "str"},
                },
                "slices": {
                    name: {"description": meta["desc"]} for name, meta in sorted(SLICES.items())
                },
                "primitives": {
                    name: {"purpose": purpose} for name, purpose in sorted(PRIMITIVES.items())
                },
                "usage_examples": [
                    "fastapi_data(action='bundle', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_data(action='add_audit_log', params={'output_dir':'/tmp/my-app'})",
                    "fastapi_data(action='primitive', params={'name':'Aggregate','output_dir':'/tmp/my-app'})",
                ],
            },
            next_steps=[
                "action='bundle' → install everything for a new project.",
                "action='<slice>' → install one slice for an existing project.",
                "action='primitive' + name=X → copy one Lego surgically.",
            ],
            t0=t0,
        )

    if action == "bundle":
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what="bundle requires output_dir",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project'}."],
                t0=t0,
            )
        installed: list[dict] = []
        errors: list[str] = []
        for slice_name in BUNDLE_SLICES:
            try:
                res = _call_slice(slice_name, **{**params, "output_dir": output_dir})
                installed.append({"slice": slice_name, "result": res})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{slice_name}: {exc}")
        ok = not errors
        return _envelope(
            ok=ok,
            what=f"bundle: {len(installed)}/{len(BUNDLE_SLICES)} slices installed"
            + (f"; {len(errors)} failure(s)" if errors else ""),
            result={"installed": installed, "errors": errors},
            next_steps=(
                [
                    "Bundle complete. Boot the app and exercise the new endpoints.",
                    "For remaining slices, call action=<slice> individually.",
                    "Call fastapi_meta_audit() to verify the contract.",
                ]
                if ok
                else ["Fix errors above. Retry failing slices individually via action=<slice>."]
            ),
            t0=t0,
        )

    if action == "primitive":
        name = params.get("name")
        output_dir = params.get("output_dir")
        force = bool(params.get("force", False))
        if not name or not output_dir:
            return _envelope(
                ok=False,
                what="primitive action requires name + output_dir",
                result={},
                next_steps=[
                    "Example: fastapi_data(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
                    "Call fastapi_data(action='list') to see available primitive names.",
                ],
                t0=t0,
            )
        try:
            res = _copy_primitive(name, output_dir, force=force)
        except (ValueError, FileNotFoundError) as exc:
            return _envelope(
                ok=False,
                what=str(exc),
                result={},
                next_steps=["Call fastapi_data(action='list') for valid primitive names."],
                t0=t0,
            )
        skipped = res.get("status") == "skipped"
        return _envelope(
            ok=True,
            what=(
                f"primitive {name} skipped (target exists; pass force=True)"
                if skipped
                else f"primitive {name} copied into {output_dir}"
            ),
            result=res,
            next_steps=(
                [
                    res["reason"],
                    "Re-run with params={'force': True} to overwrite the existing target.",
                ]
                if skipped
                else [
                    f"Import in your handler: from core.venous.data.{name}.{name} import {name}",
                    f"Call fastapi_meta_describe(name='{name}') for Protocol + invariants.",
                ]
            ),
            t0=t0,
        )

    if action in SLICES:
        output_dir = params.get("output_dir")
        if not output_dir:
            return _envelope(
                ok=False,
                what=f"slice {action!r} requires output_dir in params",
                result={},
                next_steps=["Pass params={'output_dir':'/path/to/project', ...}."],
                t0=t0,
            )
        try:
            res = _call_slice(action, **params)
        except Exception as exc:  # noqa: BLE001
            return _envelope(
                ok=False,
                what=f"slice {action!r} failed: {exc}",
                result={},
                next_steps=[
                    f"Check params for {action!r}. "
                    f"Call fastapi_meta_describe(name='fastapi_{SLICES[action]['mod']}') for the schema."
                ],
                t0=t0,
            )
        return _envelope(
            ok=True,
            what=f"slice {action} installed",
            result=res if isinstance(res, dict) else {"raw": repr(res)[:500]},
            next_steps=[
                "Boot the emitted app + hit the new endpoints to verify.",
                "Additional features? call fastapi_data(action='list') for more slices.",
            ],
            t0=t0,
        )

    valid = ["list", "bundle", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_data(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
