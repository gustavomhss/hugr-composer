# F821 Waivers — HuGR Arsenal

This file documents intentional F821 (undefined-name) suppressions in CI.
Each entry must list scope, reason, mitigation, owner, and a target.

---

## W-F821-001 — `core/venous/**/*.py` (in-tree primitives)

**Scope:** all files under `core/venous/**/*.py` (recursive).

**Count:** ~2215 F821 occurrences (verified via `ruff check core/venous/ --select F821`).

**Reason:** systemic debt pre-dating v1.0. `core/venous/` holds the framework-free
primitive skeletons (123 registered + 174 staged); they are intentionally
under-specified (forward references to not-yet-defined sibling types) so the
generated `.protocol.py` emission, scaffold layout, and `scaffold_venous`
synthesis can all consume them. Removing the F821 here would mean pre-typing
every primitive — which is exactly what the generators do downstream.

**Mitigation (today):** emitted projects are kept clean by the scaffold.
`tests/test_lint_generated.py::TestRuffPyflakes::F821_THRESHOLD = 0`
asserts zero F821 in any generated app. `*.protocol.py` files are emitted with
explicit `from <ModuleName> import <Sibling>` lines so consumer code never
sees an undefined name.

**Mitigation (future):** track in the debt-reduction work package. The
target is **0 emitted-side F821** (already met) and a steady reduction of
in-tree F821 as primitives mature and get promoted out of `_staging/`.

**Owner:** TBD — assign during the next WP triage rotation.

**Review cadence:** quarterly; re-measure with
`PYTHONPATH=. .venv/bin/python -m ruff check core/venous/ --select F821`
and update the count above.