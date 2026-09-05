# CedarAuthzMiddleware

**Status:** extracted-staged (needs human review).
**Namespace:** `auth`
**Source tool:** `adapt/extend/auth_access/add_cedar_policies.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:01+00:00.
Unresolved symbols (requires manual import/stub): ['_DEFAULT_SKIP', 'logger'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `CedarAuthzMiddleware.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_CedarAuthzMiddleware.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
