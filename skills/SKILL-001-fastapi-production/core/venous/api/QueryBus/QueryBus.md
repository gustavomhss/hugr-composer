# QueryBus

**Status:** extracted-staged (needs human review).
**Namespace:** `api`
**Source tool:** `adapt/extend/api_design/add_cqrs.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:01+00:00.
Unresolved symbols (requires manual import/stub): ['Handler', 'logger'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `QueryBus.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_QueryBus.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_staging/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.

## Compose with:

- **Read-side dispatch** → `CommandQuerySeparator` + `Specification`
  Query handlers take Specifications and return read models; the bus is the single seam where read-only semantics are enforced — no handler issues a write.

- **Cached query results** → `KeyValueBucket` + `MaterializedView`
  Hot queries hit the bucket or view; cache miss falls through to the handler — response times stay bounded under spike.

- **Principal-scoped queries** → `CurrentPrincipal` + `RequestGuard`
  Every query is scoped by principal + tenant; cross-tenant reads are a policy decision at the bus, not a developer oversight.
