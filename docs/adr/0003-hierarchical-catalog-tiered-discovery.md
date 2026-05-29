# ADR-0003: Hierarchical catalog (skills × bundles × tools) + tiered discovery

- **Status:** accepted
- **Date:** 2026-05-28
- **Deciders:** Gustavo + maintainers (recorded by tech-lead; see ratification line)

## Context
HuGR Arsenal ships its tool surface over MCP. Today the catalog is **flat**:
201 tools land in one `tools` array, and the tier-1 router exposes seven
always-loaded meta tools (home, search, describe, scaffold, compose, audit,
verify) that index into that flat array. This worked at v1.0-rc; it stops
working soon.

Three forces force the shape change:

1. **Federation handoff (imminent).** Strategy B brings 552 additional tools
   from a partner skill, taking the catalog from 201 to 753 in a single PR.
   Projections place the total at **10K+ tools within 12 months** as more
   skills onboard. Anthropic's own degradation finding (30–50 tools) means a
   flat `tools/list` of even 500 entries is already past the cliff; 10K is a
   non-starter.

2. **Cognition cap on the tier-1 surface.** Research holds the always-loaded
   surface at ≤ 8 tools before the agent starts ignoring descriptions. The
   current tier-1.py has seven names but one (`MCP_TOOL_HOME`) was a dummy
   alias of `MCP_TOOL`; the real distinct count was six. There is exactly
   enough headroom to add bundle-routing without busting the cap.

3. **User brings their own agent.** Post-PRODUCT-pivot (`PRODUCT.md` §3),
   HuGR ships a gated MCP server + a thin Skill router; the user's agent
   handles tool dispatch. We CANNOT rely on a custom harness to lazy-load
   the surface — `tools/list` IS the surface visible to the agent, so the
   server itself has to do the slicing.

The current flat catalog + flat tier-1 audit framework (`engine/audit/
contract_check.py` B0.5 + B4.7) hardcodes the v1 `counts.tools` key shape
in three places: the rule, the INVENTORY.md emitter, and the tier-1 router
itself. No external consumer of `catalog.json` exists today — internal
consumers can move together.

## Decision

**Hierarchical catalog (skills × bundles × tools), tiered discovery via
session-scoped bundle activation. Concretely:**

1. **Catalog schema v1 → v2.** `engine/index/catalog.json` now carries a
   top-level `skills` array. Each skill exposes a `bundles` array; each
   bundle has a `name`, `tool_count`, and `tags`. Every tool entry gains
   `skill` + `bundle` fields. `counts` extends to `tools_total` +
   `tools_local` + `tools_federated` + `skills` + `bundles` (plus the
   existing `primitives` + `recipes`). `schema_version` bumps to `"2.0"`.

2. **Tier-1 router grows by 2 to exactly 8 distinct tools (in
   `mcp_tools/tier1.py`).** Adds `fastapi_meta_list_bundle` (list tools in
   a bundle) + `fastapi_meta_activate_bundle` (session-scoped surface
   filter). The redundant `MCP_TOOL_HOME` alias is retired in the same PR
   so the distinct-dict count is at the cap, not above.

3. **Discovery filter on `tools/list`.** A FastMCP middleware in
   `mcp_tools/discovery.py` reads a `contextvars.ContextVar` named
   `_ACTIVE_BUNDLES` and returns:
       (a) every always-visible tool (the eight tier-1 + compose + the two
           legacy discovery tools + the nine `fastapi_<domain>` tree
           dispatchers), unconditionally;
       (b) every catalog tool whose `bundle` is in the active set.

   `tools/call` is NOT touched. Activation is **clutter management, not
   access control** — tools/call still resolves any tool by name; the auth
   scope on each tool decides what actually executes.

4. **Audit framework adapts (B0.x + B2.x + B4.7).** B0.5 + B4.7 are
   extended to read hierarchical counts from INVENTORY.md and reconcile
   them against `catalog.json`'s `counts` block. **Two new rules** land:
   B2.7 asserts exactly 8 `MCP_TOOL*` dicts in tier1.py (cap); B2.8 pins
   `catalog.json.schema_version == "2.0"` and validates every tool carries
   the v2 `skill`/`bundle` fields. Total: 37 → **39** machine-checkable
   rules, all green.

5. **INVENTORY.md template gains §2 Skills × Bundles** + a new headline
   shape (`**Catalog:** N skill, N bundles, N tools (N local + N
   federated), N primitives, N recipes`). The §`generators/`, §`modules/`,
   §`core/venous`, §`_staging` sections renumber from §2 onward.

## Alternatives considered

- **Tier-2 consolidation only (no bundle activation).** Keep the catalog
  flat and rely on `tools/list` pagination + BM25 search. Rejected: at
  10K tools every paged list is still > 30; the agent's first-call
  decisions degrade across the whole session. Pagination addresses
  scrolling, not cognition.

- **Per-bundle separate MCP servers.** Federation = run N MCP servers.
  Rejected for the single-skill case: today we have one skill, multiple
  servers add ops + auth surface without solving the per-session bundle
  filter problem. Kept for cross-skill federation (separate WP).

- **Static `disable()` / `enable()` per session-init.** Use FastMCP's
  `disable()` API instead of a middleware filter. Rejected: shares mutable
  state across sessions — multi-tenant unsafe; the ContextVar pattern
  matches the planned bearer-forwarding axis (orthogonal isolation).

- **Drop the `MCP_TOOL_HOME` alias without adding new tools (1 saving + 0
  additions = 6).** Rejected: the bundle routing must exist or the
  schema-v2 hierarchy is invisible to the agent. The mission requires
  list_bundle + activate_bundle for the agent to actually USE the
  hierarchy.

## Consequences

- **Positive:**
  - Federation handoff Strategy B becomes implementable without a second
    schema change (`tools_federated` is already a column).
  - `tools/list` size becomes O(active bundles × tools/bundle) instead of
    O(catalog) — at the projected 10K-tool catalog this is ≤ 100 entries.
  - The INVENTORY.md → catalog.json → tier-1 router triangle has a single
    audited source of truth: `counts.skills` + `counts.bundles` +
    `counts.tools_total`.
  - The 8-tool tier-1 cap is now machine-enforced (B2.7), preventing
    accidental surface growth.

- **Negative / trade-offs:**
  - Tier-1 surface is at the cognition cap (8 / 8) — no further additions
    without a Tier-2 consolidation effort.
  - Schema v1 → v2 is a breaking change for internal consumers (manifest
    builder, tier-1 router, audit framework, INVENTORY emitter, the
    relevant pytest suites). All of them upgrade in this same PR; there
    are no external consumers of `catalog.json` today.
  - Activation state lives in a session-scoped `ContextVar`. Assumes the
    single-event-loop model FastMCP currently uses; multi-tenant
    isolation will require a per-tenant context variable when the
    bearer-forwarding pattern lands (orthogonal axis — see PRODUCT.md
    §6).

- **Follow-ups:**
  - **Federation HTTP proxy** — separate WP. Strategy B needs a per-skill
    proxy + an aggregator at the MCP layer.
  - **Tier-1 BM25 sharding** — re-visit when total catalog exceeds 1K
    tools; the current single-index search remains adequate at < 1K.
  - **SKILL-002 onward** — the schema now supports `bundles[*].tool_count`
    per skill; the manifest builder's `_BUNDLE_NAMES` + bundle-tag map
    will need a per-skill override mechanism. Defer to SKILL-002 landing.
  - **Migration of WP manifests to cite skill/bundle** — cosmetic, defer.

---

### Ratification

> Ratified 2026-05-28 by Gustavo (recorded by the tech-lead on Gustavo's
> verbal approval — design discussed and approved out-of-band; ADR exists
> for posterity). Supersedes the implicit "flat catalog + 7-tool tier-1"
> contract embedded in `/docs/research/DUAL_INDEX_DESIGN.md` §4.1.
