# verify

**Status:** extracted-staged (needs human review).
**Namespace:** `extras`
**Source tool:** `adapt/extend/testing_tools/add_sbom_guardian.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:04+00:00.
Unresolved symbols (requires manual import/stub): ['detect_confusion', 'find_critical_vulns', 'hash_lockfile', 'logger', 'parse_requirements', 'query_osv'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `verify.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_verify.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
