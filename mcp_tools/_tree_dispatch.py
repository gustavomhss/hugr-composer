"""Shared dispatcher for `mcp_tools/tree/*.py` domain routers.

Single source of truth for the `dispatcher kwargs → ToolInput → slice
entry → dict` translation. Closes Codex 3 finding F-001 (the central
discovery wrapper and `tree/auth.py` both translated kwargs into
``ToolInput``, but the other tree dispatchers passed raw kwargs through
— a public-contract drift).

Every `mcp_tools/tree/<domain>.py:_call_slice` MUST route through
:func:`dispatch_via_toolinput` so the public surface stays uniform.
"""

from __future__ import annotations

import importlib
from typing import Any


def dispatch_via_toolinput(
    *,
    module_path: str,
    entry_name: str,
    slice_name: str,
    **kwargs: Any,
) -> dict:
    """Resolve a slice entry function and invoke it through ``ToolInput``.

    Slice entry functions follow the adapt convention: they accept a
    single ``ToolInput`` dataclass (``project_dir`` + ``dry_run``), not
    raw kwargs. This helper performs the canonical translation:

      1. Import ``module_path`` and look up ``entry_name``.
      2. Pop ``output_dir`` (or ``project_dir``) + ``dry_run`` from
         ``kwargs``.
      3. Discard the remaining slice-specific extras (they would
         otherwise raise ``TypeError`` on the slice entry).
      4. Build ``ToolInput(project_dir=..., dry_run=...)`` and call
         ``entry_fn(inp)``.
      5. Normalise the ``ToolResult`` return into a plain ``dict``.

    Args:
        module_path: Dotted module path, e.g.
            ``adapt.extend.crud_data.add_audit_log``.
        entry_name: Name of the public entry function in that module,
            usually the same as the slice name.
        slice_name: Human-readable slice identifier (only used in error
            messages so the caller sees which dispatch failed).
        **kwargs: Dispatcher-level keyword arguments. Must contain
            either ``output_dir`` or ``project_dir``.

    Returns:
        The ``ToolResult`` flattened to a ``dict``.

    Raises:
        RuntimeError: If the entry function cannot be located.
        ValueError: If neither ``output_dir`` nor ``project_dir`` is in
            ``kwargs``.
    """
    # Local import: avoid pulling pydantic at module-load time for
    # tools that never dispatch a slice (e.g. `action="list"`).
    from adapt.contracts import ToolInput

    mod = importlib.import_module(module_path)
    entry = getattr(mod, entry_name, None)
    if entry is None or not callable(entry):
        raise RuntimeError(
            f"slice {slice_name!r}: entry function {entry_name!r} not found in {module_path}"
        )

    project_dir = kwargs.pop("output_dir", None) or kwargs.pop("project_dir", None)
    if not project_dir:
        raise ValueError(f"slice {slice_name!r}: output_dir (or project_dir) is required")
    dry_run = bool(kwargs.pop("dry_run", False))

    # Remaining kwargs are slice-specific extras (providers=['google'],
    # name='X', force=True, …) that the contract-level ToolInput does
    # not carry. Drop them; slices read their own env/config. This
    # mirrors the behaviour `mcp_tools.tree.auth._call_slice` shipped
    # with before the F-001 extraction.
    inp = ToolInput(project_dir=str(project_dir), dry_run=dry_run)
    result = entry(inp)

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if hasattr(result, "_asdict"):
        return result._asdict()
    return dict(result) if not isinstance(result, dict) else result
