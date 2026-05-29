"""`fastapi_compliance` — the compliance-domain tree dispatcher.

ONE MCP tool that routes to 0 slice tool(s) + 7 primitive(s) under the `compliance` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "compliance"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the compliance domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {}

PRIMITIVES: dict[str, str] = {
    "AuditEvent": "Emit a tamper-evident, append-only record of a security-relevant action with actor, subject,...",
    "BreachNotificationQueue": "Track suspected and confirmed personal-data incidents with the GDPR Article 33 72-hour clock...",
    "ConsentLedger": "Record, revoke, and prove consent grants with a per-purpose, per-subject, timestamped ledger...",
    "DataSubjectRequest": "Coordinate the GDPR access/portability/erasure/rectification lifecycle with a 30-day clock a...",
    "ProcessingRecord": "Generate GDPR Article 30 Records of Processing Activities from handler decorators so the ROP...",
    "RetentionPolicy": "Implement GDPR storage limitation and PCI retention controls in code: each data class declar...",
    "TamperEvidentAuditLog": "Provide one signed, chain-verified evidence stream so SOC 2 non-repudiation and HIPAA audit-...",
}

# No curated bundle for this domain (no slice tools — primitives only).
BUNDLE_SLICES: tuple[str, ...] = ()


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
    because compliance tools span multiple adapt/ subtrees. Routes
    through the shared `dispatch_via_toolinput` helper so the public
    contract matches the central MCP discovery wrapper + `tree/auth.py`
    (closes Codex 3 F-001).

    Note: the compliance domain currently ships zero slice tools
    (``SLICES = {}``); this helper is kept so the surface stays
    uniform when slices are added later.
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
    """Copy core/venous/compliance/<Name>/ into <output_dir>/core/venous/compliance/<Name>/.

    Follows ADR 0002 (copy-in distribution). Skips _t0_report.json +
    _evidence/ (per .gitignore). Also copies the matching fastapi
    adapter under _adapters/fastapi/ if one exists.

    F-002 (Codex 3): default non-destructive. Pass ``force=True`` to
    overwrite an existing populated target.
    F-003 (Codex 3): target layout matches the generator + compose
    import path (``core/venous/<ns>/<Name>/<Name>.py``).
    """
    if name not in PRIMITIVES:
        raise ValueError(
            f"unknown primitive {name!r} in domain compliance. Available: {sorted(PRIMITIVES)}"
        )
    src = VENOUS_DIR / name
    if not src.is_dir():
        raise FileNotFoundError(f"primitive source missing: {src}")
    target = Path(output_dir) / "core" / "venous" / "compliance" / name
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
    "name": "fastapi_compliance",
    "description": (
        "Compliance domain dispatcher (HuGR tree pattern). ONE tool that routes to every compliance-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full compliance tree + primitive catalog.\n  • 'bundle' → N/A for this domain (no slice tools). Use 'primitive'.\n  • 'primitive' → copy ONE Lego block (AuditEvent, BreachNotificationQueue, ConsentLedger, DataSubjectRequest, ProcessingRecord, RetentionPolicy, TamperEvidentAuditLog).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["compliance", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_compliance",
}


def fastapi_compliance(action: str, params: dict | None = None) -> dict:
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
            what="compliance domain tree (0 bundle + 0 slices + 7 primitives)",
            result={
                "domain": "compliance",
                "slices": {
                    name: {"description": meta["desc"]} for name, meta in sorted(SLICES.items())
                },
                "primitives": {
                    name: {"purpose": purpose} for name, purpose in sorted(PRIMITIVES.items())
                },
                "usage_examples": [
                    "fastapi_compliance(action='primitive', params={'name':'AuditEvent','output_dir':'/tmp/my-app'})"
                ],
            },
            next_steps=["action='primitive' + name=X → copy one Lego surgically."],
            t0=t0,
        )

    if action == "bundle":
        return _envelope(
            ok=False,
            what="domain 'compliance' has no slice tools — no bundle to install",
            result={},
            next_steps=[
                "Use action='primitive' with name=<PrimitiveName> + output_dir.",
                "Call fastapi_compliance(action='list') to see available primitives.",
            ],
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
                    "Example: fastapi_compliance(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
                    "Call fastapi_compliance(action='list') to see available primitive names.",
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
                next_steps=["Call fastapi_compliance(action='list') for valid primitive names."],
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
                    f"Import in your handler: from core.venous.compliance.{name}.{name} import {name}",
                    f"Call fastapi_meta_describe(name='{name}') for Protocol + invariants.",
                ]
            ),
            t0=t0,
        )

    # No slice actions for this domain.

    valid = ["list", "primitive"] + sorted(SLICES)
    return _envelope(
        ok=False,
        what=f"unknown action {action!r}",
        result={"valid_actions": valid},
        next_steps=[
            "Call fastapi_compliance(action='list') to see the full tree.",
            f"Did you mean one of: {', '.join(valid[:5])}, ...?",
        ],
        t0=t0,
    )
