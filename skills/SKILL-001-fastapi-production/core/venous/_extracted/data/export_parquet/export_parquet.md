# export_parquet

**Status:** extracted-staged (needs human review).
**Namespace:** `data`
**Source tool:** `adapt/extend/crud_data/add_data_export.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:03+00:00.
Unresolved symbols (requires manual import/stub): ['Select', '_serialize', '_stream_batches', 'io'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `export_parquet.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_export_parquet.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
