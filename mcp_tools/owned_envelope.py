"""Canonical ``hugr-owned-tool-v1`` envelope for the two Composer tools that write.

``hugr-compose`` (``fastapi_meta_compose``) and ``hugr-scaffold`` (``fastapi_meta_scaffold``)
merge the fields built here into their legacy envelope, which keeps ``ok``, ``code``,
``what_happened``, ``result``, ``next_steps`` and ``elapsed_ms`` unchanged. The legacy ``code``
stays the Composer closed set (``error_codes.py``); the canonical failure code lives in
``error.code`` and the legacy one is repeated in ``error.producer_code``.

``observed_changes`` is measured, not claimed: the tool stats the tree it may write before and
after the write and reports the difference. Its reach is that tree (compose: ``<output_dir>/app``,
scaffold: ``<output_dir>``); writes outside it are not observable. When the tree cannot be
walked within ``MAX_ENTRIES`` the effects are ``unknown``. Directories appear with a trailing
``/``.

``interrupted`` is never produced here: cancellation and timeout are decided by the caller.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SCHEMA = "hugr-owned-tool-v1"
TOOLS = frozenset({"hugr-compose", "hugr-scaffold"})
STATUSES = frozenset({"previewed", "generated", "blocked", "failed", "interrupted"})
EFFECTS = frozenset({"none", "observed", "partial", "unknown"})
MAX_ENTRIES = 200_000

# status -> (allowed effects, allowed error codes; empty = no error)
_LEGALITY: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "previewed": (frozenset({"none"}), frozenset()),
    "generated": (frozenset({"observed"}), frozenset()),
    "blocked": (
        frozenset({"none"}),
        frozenset(
            {
                "INVALID_INPUT",
                "CAPABILITY_UNAVAILABLE",
                "SELECTION_UNAVAILABLE",
                "UNSUPPORTED_OUTPUT",
                "OUTPUT_CONFLICT",
                "PERMISSION_DENIED",
            }
        ),
    ),
    "failed": (
        EFFECTS,
        frozenset(
            {"PRODUCER_FAILED", "INVALID_PRODUCER_RESULT", "OUTPUT_CONFLICT", "PERMISSION_DENIED"}
        ),
    ),
    "interrupted": (frozenset({"none", "partial", "unknown"}), frozenset({"CANCELLED", "TIMEOUT"})),
}

# Pre-mutation refusals: Composer closed-set code -> canonical blocked code.
BLOCKED_BY_PRODUCER_CODE = {
    "missing-selection": "INVALID_INPUT",
    "recipe-mismatch": "INVALID_INPUT",
    "unknown-recipe": "SELECTION_UNAVAILABLE",
    "unknown-primitive": "SELECTION_UNAVAILABLE",
    "domain-boundary": "UNSUPPORTED_OUTPUT",
    "path-rejected": "PERMISSION_DENIED",
    "target-exists": "OUTPUT_CONFLICT",
    "backend-unavailable": "CAPABILITY_UNAVAILABLE",
}

Snapshot = dict[str, tuple[int, int]]


def snapshot(base: str | Path, sub: str = ".") -> Snapshot | None:
    """Stat every entry under ``base/sub``, keyed by path relative to ``base``; ``None`` if unobservable."""
    root = Path(base)
    start = root / sub
    entries: Snapshot = {}
    try:
        if not os.path.lexists(start):
            return entries
        entries[os.path.relpath(start, root).replace(os.sep, "/") + "/"] = (0, 0)
        for dirpath, dirnames, filenames in os.walk(start):
            for name, suffix in [(n, "/") for n in dirnames] + [(n, "") for n in filenames]:
                full = os.path.join(dirpath, name)
                stat = os.lstat(full)
                entries[os.path.relpath(full, root).replace(os.sep, "/") + suffix] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )
                if len(entries) > MAX_ENTRIES:
                    return None
    except OSError:
        return None
    return entries


def changes(before: Snapshot | None, after: Snapshot | None) -> list[dict[str, str]] | None:
    """Created / modified / deleted entries between two snapshots; ``None`` when either is unobservable."""
    if before is None or after is None:
        return None
    return sorted(
        (
            [{"path": p, "change": "created"} for p in after.keys() - before.keys()]
            + [{"path": p, "change": "deleted"} for p in before.keys() - after.keys()]
            + [
                {"path": p, "change": "modified"}
                for p in before.keys() & after.keys()
                if before[p] != after[p] and not p.endswith("/")
            ]
        ),
        key=lambda c: c["path"],
    )


def owned(
    *,
    tool: str,
    status: str,
    effects: str,
    observed_changes: list[dict[str, str]] | None = None,
    mode: str | None = None,
    artifact_kind: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    planned_files: list[str] | None = None,
    code: str | None = None,
    producer_code: str | None = None,
) -> dict:
    """Build the canonical fields, refusing any status / effects / code combination outside the legal table."""
    allowed_effects, allowed_codes = _LEGALITY[status]
    if tool not in TOOLS:
        raise ValueError(f"unknown owned tool {tool!r}")
    if effects not in allowed_effects:
        raise ValueError(f"status {status!r} cannot carry effects {effects!r}")
    if (code is None) != (not allowed_codes) or (code is not None and code not in allowed_codes):
        raise ValueError(f"status {status!r} cannot carry code {code!r}")
    changed = observed_changes or []
    if status in ("previewed", "blocked") and changed:
        raise ValueError(f"status {status!r} cannot report observed changes")
    if effects == "none" and changed:
        raise ValueError("effects 'none' cannot report observed changes")
    if status == "generated" and not changed:
        raise ValueError("status 'generated' needs a non-empty change inventory")
    if status == "previewed" and not artifacts:
        raise ValueError("status 'previewed' needs recoverable artifacts")
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "tool": tool,
        "status": status,
        "effects": effects,
        "observed_changes": changed,
        "mode": mode,
        "artifact_kind": artifact_kind,
    }
    if artifacts:
        out["artifacts"] = artifacts
    if planned_files:
        out["planned_files"] = planned_files
    if code is not None:
        out["error"] = {"code": code, "producer_code": producer_code}
    return out


def blocked(tool: str, producer_code: str, mode: str | None = None) -> dict:
    """A refusal decided before any mutation; the code is derived from the Composer closed-set code."""
    return owned(
        tool=tool,
        status="blocked",
        effects="none",
        mode=mode,
        code=BLOCKED_BY_PRODUCER_CODE[producer_code],
        producer_code=producer_code,
    )


def failed(
    tool: str,
    code: str,
    producer_code: str,
    before: Snapshot | None,
    after: Snapshot | None,
    mode: str | None = None,
) -> dict:
    """A failure after work began: effects follow what the before/after snapshots show.

    ``none`` when nothing changed, ``partial`` with the complete list when something did, ``unknown`` when the
    tree could not be observed.
    """
    seen = changes(before, after)
    return owned(
        tool=tool,
        status="failed",
        effects="unknown" if seen is None else "partial" if seen else "none",
        observed_changes=seen,
        mode=mode,
        code=code,
        producer_code=producer_code,
    )
