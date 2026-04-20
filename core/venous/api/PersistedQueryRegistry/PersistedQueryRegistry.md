# PersistedQueryRegistry

## What it does (plain language)

An allow-list of pre-registered queries keyed by the sha-256 of the query
text. Clients send 64-char ids on the wire; the server hydrates the real
query from the registry. An id that is not in the registry is rejected —
arbitrary-query surface is closed in production.

## Purpose

SHA-256 → query map so production clients send deterministic ids instead
of raw queries; unregistered ids are rejected; tampering is detected.

## When to use and when NOT to use

- USE: GraphQL or parametric-SQL production traffic where the client code
  ships a known set of queries and you want to close ad-hoc query surface.
- USE: as a pre-flight gate in combination with rate-limit + auth: only
  registered ids may even enter the pipeline.
- DO NOT USE: when the query is dynamic per-request (e.g. a search DSL
  built from user input). Use `InputValidator` to bound the dynamism.
- DO NOT USE: as a cache for query *results* — this registry maps id →
  query text only.

## API surface

`PersistedQueryRegistry.contract.json` is the authority. Callers call
`register(query)` in build-time or warm-up; the server `get(id)` at
request-time; `contains(id)` for pre-flight checks. There is NO public
enumeration API by design (PQR_INV_05).

## Invariants

| ID | Rule |
|---|---|
| PQR_INV_01 | Hash id is lowercase sha-256 hex of UTF-8 query bytes; registration is idempotent. |
| PQR_INV_02 | `get()` never returns a query whose re-hash differs from the id (tamper detection). |
| PQR_INV_03 | Registry is read-only in production mode; `register()` raises `PQRImmutableError`. |
| PQR_INV_04 | Lookup is O(1) in the backing store. |
| PQR_INV_05 | Callers cannot enumerate registered ids (no public `list()` — privacy). |

## Invariant -> test mapping

Each invariant has a `test_inv_<slug>_{confirms,prevents}` pair in
`test_PersistedQueryRegistry.py`.

## Thread and async safety

- Reads are lock-free (dict lookups); writes during warm-up are not
  concurrent-safe — callers MUST register queries before freezing and
  accepting traffic.
- After `freeze()`, the registry is immutable and therefore trivially
  thread-safe for all readers.

## Operational characteristics (for SRE)

- `pqr.unknown_id_rate` (counter) — how many requests arrive with an id
  the registry does not know. Sudden spikes suggest client rollout drift.
- `pqr.tamper_events` (counter) — re-hash mismatch detections; a nonzero
  rate is a security incident.
- Registry load time at warm-up is bounded; `freeze()` is a no-op from
  that point onward.

## Security considerations

- Hash is NOT a secret; it is stable and predictable. The allow-list is
  the defense, not the hash.
- Tamper detection (INV_02) catches on-disk corruption between warm-up
  and runtime; it does not prevent an attacker with write access to the
  registry from registering new queries.
- No enumeration (INV_05) keeps the set of active queries private —
  important when query shape leaks business logic.

## Provenance

- Primary source: Apollo APQ spec / apollographql/apollo-server:
  https://github.com/apollographql/apollo-server — APQ protocol section.
- Reference implementation (~80 LoC) is stdlib-only; a Redis or S3 backed
  adapter is appropriate for multi-instance production.

## Alternatives considered and rejected

- Server-side query string allow-list keyed by exact text — leaks through
  whitespace differences; sha-256 canonicalizes.
- Signed-query JWT — solves integrity but not allow-listing; an attacker
  with a valid signer still runs arbitrary queries.
- Disabling introspection only — closes discovery, not the arbitrary
  query vector.

## Extension contract

Adopters pass an optional `snapshot_sink` at construction that is invoked
with a dict copy after each successful registration — pluggable for
persistence (disk, Redis, S3). The hash function itself is sealed; callers
MUST NOT substitute a weaker hash.

## Usage

```python
reg = InMemoryPersistedQueryRegistry()
qid = reg.register("query UserById($id: ID!) { user(id:$id){ name } }")
reg.freeze()  # production
...
if not reg.contains(req.id):
    raise HTTPException(400, "unknown persisted query")
query = reg.get(req.id)
```

## Compose with:

- **Pre-flight request gate** → `InputValidator` + `RequestGuard`
  The persisted-id format is validated (`InputValidator` — 64 hex chars)
  and only then handed to the registry; `RequestGuard` refuses any request
  whose id `contains()` is false. Invariant gained: arbitrary-query DoS
  surface cannot reach the resolvers.

- **Tamper-evident audit** → `AuditEvent` + `InputValidator`
  Each unknown-id or tamper-error event is appended to the audit log;
  correlated spikes become a security signal. Invariant gained:
  tamper/unknown attempts are visible not silent.

- **Rate-limited allow-list** → `RequestGuard` + `InputValidator`
  RequestGuard checks both the persisted-id and the rate-limit in the
  same pass; attackers cannot brute-force ids because the allow-list
  makes every miss a reject and every reject a rate-limit tick.
