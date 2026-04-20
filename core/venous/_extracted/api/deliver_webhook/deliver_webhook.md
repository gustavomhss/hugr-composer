# deliver_webhook

**Status:** extracted-staged (needs human review).
**Namespace:** `api`
**Source tool:** `adapt/extend/realtime/add_webhook_sender.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:01+00:00.
Unresolved symbols (requires manual import/stub): ['_attempt_delivery', 'async_session_maker', 'crud_wh', 'delay_for_attempt'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `deliver_webhook.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_deliver_webhook.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
