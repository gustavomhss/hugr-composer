# MeteringMiddleware

**Status:** extracted-staged (needs human review).
**Namespace:** `resiliency`
**Source tool:** `adapt/extend/infrastructure/add_api_monetization.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:05+00:00.
Unresolved symbols (requires manual import/stub): ['JSONResponse', 'MeterEvent', 'RequestResponseEndpoint', '_check_usage_alerts', '_event_buffer', '_extract_tenant_id', '_is_metered_path', '_quota_cache'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `MeteringMiddleware.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_MeteringMiddleware.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
