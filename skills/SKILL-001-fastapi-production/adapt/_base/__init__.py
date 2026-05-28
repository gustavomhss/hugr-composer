"""Shared phase primitives for compose tools — the hexagon's plug board.

A compose tool (``adapt/extend/<category>/<tool>/__init__.py``) imports its
discovery/patching/rendering helpers from this package and stays focused on
orchestration:

* Phase 1 (``discover``) — :func:`probe_project`, :func:`discover_models`,
  :data:`INFRA_SKIP`, :func:`inventory_existing`.
* Phase 4 (``patch``) — :func:`patch_add_import`,
  :func:`patch_append_class_body_after_field`,
  :func:`patch_append_router_endpoint`, :func:`patch_append_module_block`,
  :func:`atomic_write`.
* Phase 3 (``write``) — :func:`load_template`, :func:`render`, :func:`render_to`.

The public surface is frozen by WP-WAVE0-F1: changes here ripple to every
migrated tool, so any addition lives behind a new symbol — existing signatures
are stable.
"""

from __future__ import annotations

from adapt._base.discover import (
    INFRA_SKIP,
    DiscoveredModel,
    FileInventory,
    ProbeError,
    ProjectProbe,
    discover_models,
    inventory_existing,
    probe_project,
)
from adapt._base.patch import (
    PatchError,
    atomic_write,
    patch_add_import,
    patch_append_class_body_after_field,
    patch_append_module_block,
    patch_append_router_endpoint,
)
from adapt._base.render import (
    TemplateError,
    load_template,
    render,
    render_to,
)

__all__ = [
    # discover
    "INFRA_SKIP",
    "DiscoveredModel",
    "FileInventory",
    "ProbeError",
    "ProjectProbe",
    "discover_models",
    "inventory_existing",
    "probe_project",
    # patch
    "PatchError",
    "atomic_write",
    "patch_add_import",
    "patch_append_class_body_after_field",
    "patch_append_module_block",
    "patch_append_router_endpoint",
    # render
    "TemplateError",
    "load_template",
    "render",
    "render_to",
]
