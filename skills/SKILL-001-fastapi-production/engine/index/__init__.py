"""Single source of truth for the dual-index (LLM + human).

See `/docs/research/DUAL_INDEX_DESIGN.md` for the full design contract.

The manifest is the authoritative registry of every tool, primitive,
and recipe the skill exposes. It is generated deterministically from
on-disk sources and consumed by (a) the MCP server to register tools /
resources / prompts, and (b) the human catalog page.

Anything downstream that drifts from the manifest is a CONTRACT §A8 bug.
"""

MANIFEST_SCHEMA_VERSION = "2"
