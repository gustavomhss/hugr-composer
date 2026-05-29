# Agent memory pointer (repo-local, machine-checked)

This file is the **deterministic, repo-committed** anchor read by
`engine.audit.contract_check` rule **B0.6**. It is the in-repo equivalent
of the per-developer `~/.claude/projects/.../venous_architecture.md`
memory file: any agent (Claude Code, Cursor, Cline, Zed, or a fresh CI
runner) that operates on this repository should land on this file and
follow the pointers it carries.

The audit gate is repo-local on purpose. Before the C2 audit, B0.6 read
`Path.home() / ".claude" / "projects" / ...`, which made the 40/40
contract-check gate non-deterministic: a fresh clone or a CI runner
could fail `B0.6` for reasons unrelated to repository state. The
acceptance-gate contract (see `docs/wp/WP-CONTRACT-TEMPLATE.md`)
requires every `B*` item to be a deterministic function of the
working tree. This pointer file restores that property.

## Canonical contract surface

Every agent reading this repo should treat the following files as
authoritative:

- `PRODUCT.md`        — product contract (what HuGR Arsenal ships).
- `CONTRACT.md`       — execution contract (the §A/§B/§C/§D/§E gates
                       this audit enforces).
- `ROADMAP.md`        — phased delivery plan.
- `SKILL.md`          — agent-facing skill manifest.
- `INVENTORY.md`      — canonical counts (primitives, tools, recipes).

## Audit semantics

`B0.6` passes iff this file exists AND mentions both `PRODUCT.md` and
`CONTRACT.md` (so the pointer cannot silently drift away from the two
files the contract gate hinges on). The rule no longer touches the
user's home directory.
