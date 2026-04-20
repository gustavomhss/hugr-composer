# search

**Status:** extracted-staged (needs human review).
**Namespace:** `data`
**Source tool:** `adapt/extend/crud_data/add_search.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:03+00:00.
Unresolved symbols (requires manual import/stub): ['_SearchSession', '_get_dialect_name', '_search_like_fallback', '_search_postgres'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `search.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_search.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
