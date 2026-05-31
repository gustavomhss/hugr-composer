# Round-7 Validation — Wave 1+2 Reality Check

- **Date:** 2026-05-31
- **Base commit:** `c4aec5e416d1178a4977adb1bf0829591f91a983` (main, post-W2 final B0.15 lifespan closure, PR #112)
- **Jurors (R7 transcript IDs):**
  - O1 (auth blast): `a33bbe595e5cb0663`
  - O2 (data integrity): `acf6cfb0d0192f60a`
  - O3 (rule anti-bypass): `a48ef5aba2b9e97cd`
  - O4 (honesty meta): `a92f61c2635b7da5e`
  - S1 (obs+deploy): `a19bd443f59be2e2e`
  - S2 (5-tool sample): `ad9113f785a3f2bc9`
- **Purpose:** Canonical compilation of Round-7 juror findings post Wave-1+2 (33 PRs, 47/47 contract green on main). Companion to [`ROUND5_6_TRIAGE.md`](./ROUND5_6_TRIAGE.md). Establishes Wave A/B/C/D follow-on plan.

---

## §1 Executive verdict

| Surface | Score | Trend vs R5/R6 |
|---|---|---|
| Engine + kit infra | 9/10 | ↑ from 7 |
| Auth/security compose | 5-6/10 | ↑ from 2 (but 3 NEW HIGHs) |
| Data integrity compose | 3/10 | ≈ flat (BLOCKERs untouched) |
| Observability/deploy | 7-9/10 | ↑ from 4 |
| **Overall compose** | **5/10** | up from 0-2 |

**Plain statement:** Wave 1+2 (33 PRs) closed ~85 findings structurally via 7 anti-pattern rules (B0.10 – B0.16). Round-7 revealed the rule scopes have systematic blind spots **and** some fixes opened new attack vectors. Engine infrastructure is genuinely strong (9/10). Compose layer — the paid IP — is **not ship-ready** at 5/10 overall, with data integrity stuck at 3/10 because R5/R6 BLOCKERs in `add_event_sourcing`, `add_audit_log`, `add_data_export`, `add_data_import`, and `add_file_upload` were structurally out of scope for the rules we shipped.

---

## §2 NEW criticals (created by Wave-1/2 fixes themselves)

These did **not** exist in R5/R6 — they are regressions or newly-exposed surfaces introduced by Wave-1/2 PRs.

| ID | Sev | Source | File | Summary |
|---|---|---|---|---|
| R7-N1 | HIGH | O1 (`a33bbe595e5cb0663`) | `add_multi_tenancy/_patches.py:192-211` | `/users/signup` patch reads `X-Tenant-ID` from anonymous request → anyone who knows a tenant slug self-enrolls into it |
| R7-N2 | **CRITICAL** | O1 | `add_api_key_auth/{schemas,crud,routes}.py.tmpl` | `POST /api-keys/` accepts `scopes: list[str]` unchecked → ordinary user issues `["*:*"]` key, bypasses every `require_scope(...)`. Wave-2 #105 added `extra="forbid"` (envelope) but not value allowlist |
| R7-N3 | HIGH | O1 | `add_adaptive_throttle/throttle_core.py.tmpl:61-76` | Fingerprint uses `request.client.host` + header NAMES — behind any LB/CDN every user shares fingerprint → DoS amplifier. Wave-2 #100 made tool "real"; before that it was inert and harmless |
| R7-N4 | MED | O1 | `add_adaptive_throttle/throttle_middleware.py.tmpl:171-181` | Escalation only triggers on downstream 429 — without upstream SlowAPI producing 429s, never escalates. Docstring claims behavioral fingerprint detection, code only reacts to status codes |
| R7-N5 | LOW | O1 | `add_bulk_operations/crud_addition.py.tmpl:154-161` | `succeeded += 1` without `rowcount` check — false success when tenant filter rewrites to no-op |

**Pattern:** Two of the five (R7-N2, R7-N3) are the result of making previously-inert tools "real". Wave-2 promoted tools from no-op stubs to working code without re-running adversarial review on the now-live attack surface. R7-N2 in particular is shipping-blocker severity: any authenticated user mints unlimited-scope API keys.

---

## §3 EXISTING R5/R6 BLOCKERs still open (Wave-1/2 didn't reach)

| Original ID | Tool | Status | Why not fixed |
|---|---|---|---|
| R5-O2-D6 + D7 | `add_event_sourcing` | in-memory store + endpoints have no auth | adapter `EventSourcedStoreAdapter.py` lives outside `templates/`; B0.11 only scans `templates/` |
| R5-S1-F1 + F2 + F5 | `add_audit_log` | endpoints no auth, actor caller-controlled, in-memory ledger | same scope gap: `AuditLogAdapter.py` mounts routes; B0.11 misses |
| R5-O2-D9 | `add_bulk_operations` | idempotency-key cross-tenant cache replay | Wave-2 #98 closed schemas + lifespan; didn't touch key namespacing |
| R5-O2-D3 | `add_data_versioning` | `content_type` ignored in lookup → cross-type collision | Wave-2 #97 closed auth + schemas; scope limited |
| R5-S1-F8 / R6-O3-P3 | `add_file_upload` | `stored_key` still leaked in `PresignedUploadResponse` | Wave-1 #85 fixed only `add_s3_storage`, not file_upload presign |
| R5-O3-F4 | `add_stripe_refund_flow` | no `payment_id` ownership check — **NOW LIVE** (was latent behind F3) | Wave-1 #88 fixed F3 (real Stripe call); F4 wasn't in scope; refund-flow now exploitable for cross-user refunds |
| R5-S4-F6 | `add_data_export` | CSV formula injection (`=cmd(...)`) in exported cells | not touched |
| R5-S4-F7 | `add_data_import` | stored CSV formula injection (chains with F6) | not touched |
| R5-S8-F1 | `add_search` | NUL in `q` on Postgres `search()` path → uncaught `DataError` 500 | Wave-1 closed autocomplete path; main search not touched |
| R5-S8-F2 | `add_search` | LIKE `%`/`_` wildcard bleed on SQLite fallback | not touched |
| R6-S5-F1 | `add_prometheus_metrics` | path cardinality (raw `request.url.path` used as label) | Wave-1 #83 fixed divisor, not normalization |
| R6-S11-F1 | `add_kubernetes_manifests` | liveness probe == readiness probe == `/healthz` | Wave-1 #89 fixed `GracefulShutdown`, K8s template untouched |
| (no R5/R6 ID) | `add_outbox_pattern` admin | no auth on `/outbox/metrics` + `/outbox/dlq`; B0.11 regex misses `outbox` keyword | Wave-2 #106 closed honesty test only; admin endpoints not scoped |
| (no R5/R6 ID) | `add_compliance_engine` decrypt | `decrypt_field` symmetric to old encrypt — silent passthrough on empty key | Wave-1 #96 closed encrypt only; decrypt path not symmetric-fixed |

**Pattern:** every untouched item is either (a) outside the rule's path scope (adapters in `core/venous/_adapters/fastapi/`) or (b) outside the rule's regex keyword set (`outbox`, `compliance`, `refunds`). These are scope problems, not rule-design problems.

---

## §4 Rule scope-gaps (the SYSTEMIC finding)

The 7 anti-pattern rules work within their scope but the scope is narrower than the attack surface. Compiled from O3 (`a48ef5aba2b9e97cd`) + S2 (`ad9113f785a3f2bc9`).

### §4.1 Scope expansion needed

- **B0.11** does NOT scan `core/venous/_adapters/fastapi/*.py` — `AuditLogAdapter`, `EventSourcedStoreAdapter` mount routes invisible to the rule. Massive blind spot.
- **B0.11** regex omits `outbox|compliance|refunds|presence|webhook|websocket|notif` keywords → admin endpoints in those tools pass green.
- **B0.13** scans only `notes=` — misses `description` (catalog-level oversells), `MCP_TOOL["description"]` framework claims, and `next_steps` foot-guns.
- **B0.16** scans `extend/auth_access/**` + a few keywords — misses `realtime/` (WebSocket JWT handlers) and `core/venous/_adapters/`.

### §4.2 Pattern bypasses (31 found, ~22 HIGH; cite O3 `a48ef5aba2b9e97cd`)

- **B0.10:** `raise NotImplementedError` evades (worse than `pass`); TODO in docstring inside function body evades.
- **B0.11:** `dependencies=[Depends(...)]` decorator-form not consistently recognized; dynamic `app.add_api_route(...)` evades.
- **B0.12:** `SimpleNamespace(d={})` not in allow-list; `type('X',(),{})` dynamic class evades; `setattr(module,'_X',{})` from function evades.
- **B0.13:** f-string token may evade AST literal scan; vacuous test (`def test_word: assert True`) passes the keyword check while testing nothing.
- **B0.14:** `typing.Dict` (capital) evades; `TypedDict` instead of `BaseModel` evades; schema name without `Create|Update|Request` suffix evades; `dict[Any, str]` (Any in KEY) evades.
- **B0.15:** init in `if __name__ == "__main__"` evades; init via decorator side-effect evades.
- **B0.16:** `del e; pass` evades; `except Exception: ...` (ellipsis) evades; **`except Exception: return False` evades — and this is the exact rate-limit fail-open shape we keep seeing in the wild.**

### §4.3 Meta-pattern (worst)

All 7 rules use **substring matching for bypass disclosure** (warnings text, pragma reason). An attacker — or, in our case, a busy contributor — satisfies disclosure with literal noise that contains the keyword but conveys no real waiver context.

**Move to structured markers:** `# pragma: B0.NN: reason="<one-line semantic explanation>"` parsed as key/value rather than substring.

---

## §5 Honesty meta findings (O4 `a92f61c2635b7da5e`)

Top oversells that survived Wave 2:

- **R7-O4-F1 HIGH** — `add_runtime_sentinel` claims "24h auto-promotion" — no timer exists; gated by env var only.
- **R7-O4-F2 HIGH** — `add_data_export` claims "registry stays consistent" — depends on operator wiring that the tool never instructs.
- **R7-O4-F3 HIGH** — `add_long_running_task` claims "deterministic replay" — primitive docstring it depends on explicitly denies the claim.
- **R7-O4-F6 / F7 / F9 / F10 MED** — description/notes-vs-warnings contradictions in `compliance_engine`, `audit_log`, `secret_rotation`, `cache_layer`.

These are not subtle. They are the kind of claim a paying customer will quote back to us when the feature doesn't deliver. They are also the cluster B0.13 was supposed to catch — and would, if its scope were expanded per §4.1.

---

## §6 Cumulative position

| | Verdict | Score |
|---|---|---|
| Round-2 (2026-05-27) | 4/4 don't-ship | ~0/10 |
| Round-5+6 (2026-05-30) | 27 don't-ship | ~2/10 |
| Post-Wave-1+2 (Round-7, 2026-05-31) | mixed | **5/10 compose, 9/10 engine** |

Wave 1+2 cost: **33 PRs across ~5 sessions**. ROI: meaningful structural floor but not ship-ready. The engine/kit infrastructure is genuinely production-quality. The compose layer still has shipping-blocker findings, and three of them are NEW (R7-N1/N2/N3) — created by the very PRs that closed older blockers.

---

## §7 Recommended waves (the plan)

### Wave A — Rule scope expansion (highest ROI per PR)

Each PR widens 1-2 rules to close a CLUSTER of findings rather than one-off patches.

1. **B0.11 expand** to scan `core/venous/_adapters/fastapi/*.py` → closes audit_log + event_sourcing admin-auth findings in one shot.
2. **B0.11 regex add** `outbox|compliance|refunds|presence|webhook|websocket|notif` → closes outbox admin + multiple HIGH.
3. **B0.13 expand** to scan `description` + `next_steps` + `MCP_TOOL["description"]` → catches `load_profile` k6/Locust over-sell and many others.
4. **B0.16 add** `realtime/` + adapters to scope → catches `websocket_presence` JWT broad-catch.
5. **Close 5-10 pattern bypasses** found in O3 (priority: B0.16 `return False`, B0.10 `raise NotImplementedError`, B0.14 `typing.Dict`).

**Estimated:** 5-8 PRs. **Closes ~30 findings.**

### Wave B — 3 NEW CRITICALs (security urgency)

6. R7-N2 `api_key_auth` scope allowlist (CRITICAL — ship-blocker).
7. R7-N1 `multi_tenancy` signup invite-required.
8. R7-N3 `adaptive_throttle` proxy-aware fingerprint.

**Estimated:** 3 PRs.

### Wave C — R5/R6 untouched BLOCKERs

Per §3 table above. Some bundle naturally (audit + event_sourcing both adapter-mounted; data_export + data_import both CSV formula-injection).

**Estimated:** 8-10 PRs.

### Wave D — Honesty meta (O4 fixes)

Tone down 4 HIGH oversells; reconcile description/notes/warnings ordering across the 7 tools cited in §5.

**Estimated:** 1-2 batch PRs.

---

## §8 Source juror transcripts

| Juror | Scope | Agent ID |
|---|---|---|
| O1 | auth blast surface | `a33bbe595e5cb0663` |
| O2 | data integrity tools | `acf6cfb0d0192f60a` |
| O3 | rule anti-bypass / scope | `a48ef5aba2b9e97cd` |
| O4 | honesty meta (description vs warnings) | `a92f61c2635b7da5e` |
| S1 | observability + deploy | `a19bd443f59be2e2e` |
| S2 | 5-tool deep sample | `ad9113f785a3f2bc9` |

— End Round-7 Validation —
