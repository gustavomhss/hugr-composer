# Contributing

The minimum a contributor needs to know. See [`repo-standard.md`](repo-standard.md) for
the enforced rules and [`architecture.md`](architecture.md) for the layering.

## One-time setup
```bash
# from repo root
pre-commit install                  # local hygiene on every commit
make verify                         # ensure the local stack is green
```
Local Postgres for the DB-backed gates (e2e/behavior): `localhost:5432`, user/pass/db =
`skill`/`skill`/`skill_e2e`. See `docs/guides/` for setup.

## Loop (per change)
1. Branch: `wp/<id>-<slug>` for a Work Package, `fix/<slug>` for a fix, `chore/<slug>` for hygiene.
2. Make the change. **Touch the smallest set of files needed.**
3. `make verify` — `scripts/verify.sh` auto-picks the tier from `git diff`:
   - Tier 0 (touched a tool): that tool's tests + property, ~30s.
   - Tier 1 (default pre-merge): composition gates (boot, e2e, behavior, regression gates), ~5min.
   - Tier 2 (changed cross-cutting: generators/contracts/engine): full unit suite + tier 1, ~6min.
4. Commit. Conventional message: `fix(...)`, `refactor(...)`, `test(...)`, `docs(...)`, `chore(...)`.
   End every commit message with the `Co-Authored-By:` trailer used in this repo.
5. Push and open a PR. The template's DoD checklist is mandatory — paste the gate output.

## Definition of Done
- [ ] The right tier of `make verify` is green and pasted in the PR.
- [ ] Regression gates pass (`tests/test_p0_regression_gates.py`).
- [ ] No file outside the intended scope touched.
- [ ] No new narrative markdown outside `docs/`; no tracked venv/emitted/db.
- [ ] Logic files within the size cap (templates externalized).
- [ ] Honest: no tool reports success for something it doesn't enforce.
- [ ] ADR added/updated if this is an architectural decision.

## When to write an ADR
Add `docs/adr/NNNN-title.md` (copy `0000-template.md`) for any decision that:
- changes a layer or contract,
- adds/removes a dependency,
- changes how tools compose or how the kit is packaged,
- you'd want a future maintainer to find the rationale for.

## When to open a Work Package
The big refactor work runs as Work Packages (`docs/wp/`). Copy
[`WP-CONTRACT-TEMPLATE.md`](wp/WP-CONTRACT-TEMPLATE.md) and fill every section before
dispatching an agent or starting work.
