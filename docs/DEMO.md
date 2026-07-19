# Demo scripts (for asciinema / GIF)

Record these with `asciinema rec` (or a terminal GIF tool) and drop the cast
into the README. Each is short, reproducible, and shows a *different* pillar.
Commands are verified from a fresh checkout with the project venv on PATH.

> Recording tip: `asciinema rec demo.cast -c "bash demo_snippet.sh"`, keep each
> clip under ~60s, and set the terminal to ~90 cols for GitHub embeds.

---

## Demo A — "the counts aren't marketing" (~20s)

Shows the single source of truth regenerating, and the audit refusing drift.

```bash
python -m engine.inventory            # regenerates INVENTORY.md from the tree
python -m engine.audit.contract_check # 47/47 machine-checked rules, incl. doc-drift
```

Beat: end on `47/47 contract items satisfied — ALL GREEN`. The story is that
every number in every doc is machine-verified, and drift is a failing rule.

## Demo B — "the generated code is real" (~20s)

```bash
cd examples/01-todos-crud
python -m pytest -q                   # owner-scoping + keyset-pagination invariants, green
```

Beat: a green test run on an agent-built app. Pair with a glance at
`AGENT_SESSION.md` to show the plan the agent followed.

## Demo C — "the toolset earns its place" (the crown jewel, ~45s)

The blind A/B harness driving the same agent *naked* vs *kit*, then judging
the emitted apps on five sealed layers.

```bash
# reproducible offline run against pre-baked fixtures (no API calls):
python -m engine.bench.blind.runner --stub --spec calibration/02_basic_user_crud
```

This prints the `naked` vs `kit` × seed matrix and a per-attempt score.

> Env note: the judge boots each emitted app in a subprocess and runs a sealed
> pytest suite; on a cold machine the fixtures can hit `boot_timeout` (score
> 0) until their runtime deps are warm. For a portfolio clip, record the
> **live** run (`--condition kit` without `--stub`, needs the Claude CLI) on a
> warmed environment so the layer scores and the A/B delta are visible — that
> delta is the whole point of the harness.

## Demo D — "progressive disclosure" (optional, ~30s)

Show the agent-facing surface: 8 tier-1 meta tools instead of 202, then
narrowing through a domain dispatcher.

```bash
python -c "from mcp_tools.tier1 import *; print('8 tier-1 metas front a 202-tool catalog')"
```

Pair with the architecture diagram in the README.

---

### Suggested README embed order

1. Demo C (crown jewel — the eval delta) as the hero cast.
2. Demo A (machine-verified discipline) as the credibility beat.
3. Demo B (real generated app) as the proof-of-output.
