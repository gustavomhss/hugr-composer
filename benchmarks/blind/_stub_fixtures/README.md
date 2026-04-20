# Stub fixtures

Pre-baked emissions used by `engine.bench.blind.runner --stub` to
validate the harness plumbing WITHOUT calling a live LLM. Layout:

```
<spec_id_with_double_underscore>/
  naked/emitted/     ← deliberately-flawed implementation (naked-like)
  kit/emitted/       ← high-quality implementation (kit-like)
```

These fixtures are **not** the scoring reference — the real thing is
the sealed judge under `specs/<tier>/<id>/judge/`. The fixtures exist
so the harness can be regression-tested end-to-end (boot → judge →
publish) on every commit, even when API credits / network are unavailable.

Rules for fixture authoring:
- Minimal dependencies: FastAPI + uvicorn + stdlib only.
- Naked fixture: passes Layer A (functional smoke) but fails B/C/D/E
  in predictable ways (float money, race condition, no idempotency,
  no audit chain). Score expected: 15-35.
- Kit fixture: passes all layers. Score expected: 90-100.
- Both: boot under `uvicorn app.main:app --port {PORT}` per the spec's
  `boot_command`.

Adding a new spec requires new fixtures under the matching slug.
