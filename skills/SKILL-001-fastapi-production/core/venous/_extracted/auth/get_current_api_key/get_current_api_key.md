# get_current_api_key

**Status:** extracted-staged (needs human review).
**Namespace:** `auth`
**Source tool:** `adapt/extend/auth_access/add_api_key_auth.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:02+00:00.
Unresolved symbols (requires manual import/stub): ['APIKey', 'Annotated', 'SessionDep', '_api_key_header', '_check_api_key_validity', '_fetch_api_key', '_parse_header'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `get_current_api_key.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_get_current_api_key.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
