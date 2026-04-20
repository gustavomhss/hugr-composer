# compensate_payment

**Status:** extracted-staged (needs human review).
**Namespace:** `resiliency`
**Source tool:** `adapt/extend/infrastructure/add_temporal_workflow.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:06+00:00.
Unresolved symbols (requires manual import/stub): none.

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `compensate_payment.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_compensate_payment.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
