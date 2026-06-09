"""`fastapi_compliance` — the compliance-domain tree dispatcher.

ONE MCP tool that routes to 0 slice tool(s) + 7 primitive(s) under the `compliance` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.

M3.2 fan-out: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing, and primitive copy live in ``hugr_core.dispatch`` — the generic
engine shared by every domain. Compliance is the empty-bundle (primitives-only)
domain: with no slice tools / no curated bundle, the dispatcher reproduces the
hand-rolled surface (action="list" omits the ``bundle`` key, action="bundle"
fails with the "no slice tools" message, unknown-action valid list omits
"bundle"). The data tables are unchanged, so the public contract is
byte-identical to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

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


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="compliance",
    tool_name="fastapi_compliance",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="compliance domain tree (0 bundle + 0 slices + 7 primitives)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    toolinput_factory=_toolinput_factory,
    primitive_missing_args_next_steps=(
        "Example: fastapi_compliance(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
        "Call fastapi_compliance(action='list') to see available primitive names.",
    ),
    list_usage_examples=(
        "fastapi_compliance(action='primitive', params={'name':'AuditEvent','output_dir':'/tmp/my-app'})",
    ),
)

fastapi_compliance = make_dispatcher(_CONFIG)
