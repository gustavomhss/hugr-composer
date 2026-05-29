"""Domain-tree dispatchers — one MCP tool per domain with action+granularity.

Design contract: /docs/research/DUAL_INDEX_DESIGN.md §4 (revised tree variant).

Replaces flat `fastapi_add_<slice>` exposure with a domain-level dispatcher:

    fastapi_<domain>(action=<verb_noun>, ...)

Each dispatcher supports three granularities:
  - "bundle"     : install a curated set of slices (Rails-style one-shot)
  - "<slice>"    : one legacy slice (e.g. add_oauth2)
  - "primitive"  : copy a single Lego block from core/venous/<ns>/<Name>/

And one introspection action:
  - "list"       : returns the domain tree (actions + params + primitives)

This file ships `auth` first as the proof-of-concept. On live-run
success we expand to the other 9 domains in subsequent commits.
"""

DOMAIN_TREE_VERSION = "1"
