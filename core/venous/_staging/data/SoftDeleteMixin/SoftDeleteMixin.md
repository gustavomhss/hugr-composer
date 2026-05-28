# SoftDeleteMixin

**Status:** extracted-staged (needs human review).
**Namespace:** `data`
**Source tool:** `adapt/extend/crud_data/add_soft_delete.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:02+00:00.
Unresolved symbols (requires manual import/stub): ['_sd_Boolean', '_sd_DateTime', '_sd_ForeignKey', '_sd_Mapped', '_sd_Uuid', '_sd_datetime', '_sd_declared_attr', '_sd_mapped_column', '_sd_uuid'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `SoftDeleteMixin.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_SoftDeleteMixin.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
