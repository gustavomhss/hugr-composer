# SKILL-001 — `fastapi-production`

The FastAPI production skill: macro scaffolds + slice generators + the
registered primitive library backing them. Installed by the repo-root
`install.sh` into `~/.hugr-skills/skills/SKILL-001-fastapi-production/`.

> **This file is a pointer.** Narrative lives elsewhere — by design, per
> [`/docs/repo-standard.md`](../../docs/repo-standard.md) §1.

## What's here

| Surface | Where | Count |
|---|---|---:|
| MCP tool catalog | `engine/index/catalog.json` | 201 tools |
| Primitive registry | `core/venous/<ns>/<Name>/` | 124 registered |
| Recipes (compositions) | `core/venous/_recipes/` | 392 |
| Adapters (FastAPI wiring) | `core/venous/_adapters/fastapi/` | 17 |
| Module bundles | `modules/<package>/` | 28 |
| Examples | `../../examples/` | 20 |

Per-bucket breakdown: see [`INVENTORY.md`](INVENTORY.md) (the canonical,
machine-generated count source).

## Start here

| You want | Read |
|---|---|
| What this skill ships, with live counts | [`INVENTORY.md`](INVENTORY.md) |
| Release status + freeze cuts | [`STATUS.md`](STATUS.md) |
| The agent-facing entry point | [`SKILL.md`](SKILL.md) |
| How to extend / land a new tool | [`/CONTRIBUTING.md`](../../CONTRIBUTING.md) |
| The 3-layer architecture | [`/docs/architecture.md`](../../docs/architecture.md) |
| Repo-wide product framing | [`/README.md`](../../README.md) + [`/PRODUCT.md`](../../PRODUCT.md) |

## Verify the install

```bash
# from this skill directory
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check
# expect: 40/40 contract items satisfied — ALL GREEN
```

If the audit is red on a fresh install, stop and open an issue against
[`humangr-labs/HuGR-Arsenal`](https://github.com/humangr-labs/HuGR-Arsenal).
