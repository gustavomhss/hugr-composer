# Round-8 Validation — Adversarial Re-attack of the Round-7 Fix Wave

- **Date:** 2026-06-02
- **Base commit:** `048b995` → **Head:** `b89acca` (the 20 fix PRs #142–#160 + rule-engine foundation work)
- **Method:** 8 adversarial jurors (distinct attack lenses) fan out across the exact `048b995..b89acca` changed surface, READ-ONLY, Arsenal-only. Every juror finding passes an **adversarial refutation gate** (a skeptic that tries to disprove it against the real code, default-INVALID unless a concrete file:line exploit path is shown) before it enters this report.
- **Jurors:** J1 auth-blast · J2 data-integrity · J3 durability-NEW (#159/#160) · J4 rule-anti-bypass (§4) · J5 honesty-meta · J6 obs+deploy · J7 regression-hunter · J8 scope-gap
- **Tally:** 30 raw findings → **24 confirmed**, **6 refuted/invalid**. Several survivors down-graded during refutation (J3-1 HIGH→MED, J4-3 HIGH→MED, J7-2 MED→LOW, J5-3 MED→LOW).
- **Top-3 independently re-verified by the tech-lead** against the actual templates (J8-1, J1-1, J8-2).
- Companion to [`ROUND7_VALIDATION.md`](./ROUND7_VALIDATION.md).

---

## §1 Executive verdict

**The Round-7 fixes held on their core security goals. Zero NEW criticals were introduced this session.** The one CRITICAL on the board (`R8-J8-1`) is a *pre-existing, knowingly-waived* gap that #142–#160 did not touch — not a regression.

The four headline auth/escalation closures are genuine and survived direct re-attack:
- **R7-N2** (api_key scope escalation) — deny-by-default allow-list applied *before* key generation; wildcards categorically rejected; no second mint/update path. **Closed.**
- **R7-N1** (multi-tenancy self-enrollment) — `allow_public_signup` defaults false in model + migration; authenticated tenant resolve validates against the user's own `tenant_id`. **Closed.**
- **R7-N3** (throttle fingerprint) — trusted-proxy XFF resolver with fail-safe peer-IP pinning. **Closed as designed** (but enabled a regression, below).
- **#152/#153 adapter auth** — `auth_dependency` now a required kwarg, every route gated, audit `actor` derived server-side. **Closed**, and B0.11 widened to scan the adapter tree.

**Dominant theme — the Round-7 lesson repeating: making inert tools "real" opens second-order vectors.** The R7-N4 quota path (#156) converted the contained R7-N3 shared-fingerprint collision into a self-inflicted mass-ban DoS amplifier (`R8-J1-1`, HIGH) *and* introduced an unbounded per-worker fallback dict (`R8-J7-1`, MED). The two brand-new durable stores (#159/#160) are sound on their advertised happy path but ship with integrity/error-contract *parity* regressions vs the in-memory reference (`R8-J3-1`, `R8-J3-2`).

**The §4.3 meta-finding remains fully unfixed:** every disclosure/waiver path is still pure substring matching or bare frozenset membership, not the structured `reason=` parsing Round-7 recommended (`R8-J4-1`, `R8-J4-2`). The waiver mechanism is satisfiable with literal noise — which is *how* a CRITICAL like J8-1 ships green.

### Updated per-surface scores (vs Round-7 §1)

| Surface | R7 | R8 | Δ | Note |
|---|:--:|:--:|:--:|---|
| engine / contract rules | 9/10 | 7/10 | ▼ | Rules genuinely hardened (B0.10/11/12/14/15 close most §4.2 evasions), but §4.3 disclosure-noise thesis fully confirmed; B0.14 name-suffix + add_api_route + WS blind spots remain. |
| auth / adapters | 5-6/10 | 8/10 | ▲ | Four headline closures real and unbreakable on the bypass axis; residual damage is DoS/honesty, not auth bypass. |
| data integrity | 3/10 | 7/10 | ▲▲ | Refund ownership, CSV/search injection, idempotency cross-tenant replay, rowcount guard all real and complete. Residual = authz depth + atomicity honesty, pre-existing. |
| durability (NEW) | n/a | 6/10 | new | Hash-chain/concurrency/opt-in-off solid; durable store fails input-validation + 409 error-contract parity. |
| obs / deploy | 7-9/10 | 6/10 | ▼ | Path-cardinality + probe-distinctness fixes real; method-axis cardinality still open, k8s probe hard-dep undocumented. |
| compose | 5/10 | 5/10 | = | Not re-attacked this session. |

---

## §2 Confirmed findings (sorted by severity)

| ID | Sev | Regr? | Surface | File:line | One-line | Fix sketch |
|---|---|:--:|---|---|---|---|
| R8-J8-1 | **CRITICAL** | no | compliance erasure (waived B0.11) | `add_compliance_engine/templates/compliance_routes.py.tmpl:45-82` | Unauth `DELETE /compliance/erasure/{user_id}` cascade-redacts ANY user's PII cross-tenant; router auto-wired, gated only by `COMPLIANCE_ENABLED`, tool in `_WAIVED_TOOLS` so B0.11 ships green | Add `Depends(get_current_superuser)` + tenant-scope cascade; remove from `_WAIVED_TOOLS`. (issue #135) |
| R8-J1-1 | HIGH | **yes** | adaptive_throttle (#156) | `add_adaptive_throttle/__init__.py:163,171` | Default-ON throttle + empty `TRUSTED_PROXIES` collapses a proxy's users into one fingerprint; new volume-escalation path bans them up to 24h | Default `ENABLED=False`; refuse volume-escalation/ban when `client_ip()` returned bare peer and no trusted proxy set. |
| R8-J8-2 | HIGH | no | ws_presence REST (waived B0.11) | `add_websocket_presence/templates/presence_http_routes.py.tmpl:14-59` | Unauth user enumeration + presence/device disclosure; #139 added `presence` regex AND its neutralizing waiver in the same session | Add `Depends(get_current_user)`; remove from `_WAIVED_TOOLS`. (issue #138) |
| R8-J1-2 | MED | yes | adaptive_throttle honesty (#156) | `add_adaptive_throttle/__init__.py:144 vs 163` | `next_steps` says "set ENABLED=true to activate" but default is `True` — throttle is live on first boot | Make code/docs agree: default OFF, or state plainly it's ON and proxies MUST be set. |
| R8-J1-3 | MED | yes | api_key_auth overcorrection (#142) | `add_api_key_auth/templates/scopes.py.tmpl:42 vs 10` | Grantable allow-list defaults to bare `{read,write}` but evaluator is `resource:action`-only; default self-service keys authorize nothing | Seed allow-list with `resource:action` literals or document `API_KEY_GRANTABLE_SCOPES` must be set; fix in-file example. |
| R8-J2-2 | MED | no | bulk_operations update path | `add_bulk_operations/templates/crud_addition.py.tmpl:191-222` | `mode='all_or_nothing'` accepted but ignored on update path; per-item savepoints commit partial writes silently | Branch on `mode` like the create path; single-txn rollback for all_or_nothing. |
| R8-J2-3 | MED | no | stripe_refund_flow | `add_stripe_refund_flow/templates/refunds_routes.py.tmpl:193-220` | No local amount-vs-payment or cumulative-refund cap; per-row idempotency key lets repeated/over refunds reach Stripe | Pre-check `amount + already_refunded ≤ payment.amount`. |
| R8-J3-1 | MED | yes | durable event store (#160) | `add_event_sourcing/templates/event_store_store.py.tmpl:81-123` | `SqlEventSourcedStore` skips guards in-memory enforces: empty aggregate_id, bool version, snapshot out-running log, snapshot rewind — ESS-INV-03 violable on durable path | Port reference guards into the SQL store; validate snapshot version under the lock. |
| R8-J3-2 | MED | yes | durable event store race (#160) | `add_event_sourcing/templates/event_store_store.py.tmpl:89-108` | UNIQUE-backstop `IntegrityError` escapes as raw 500 instead of the contract's 409 | Translate `IntegrityError` on the version constraint into `ConcurrencyError` → 409. |
| R8-J3-3 | MED | no | audit export route | `AuditLogAdapter.py:104-109` | `GET /audit-logs/export` default `since_seq=0` raises `TamperEvidentAuditLogError` → 500 on documented default | Default `since_seq=1` or wrap → 400. |
| R8-J4-1 | MED | no | B0.15 disclosure noise | `r_init_inside_lifespan.py:294-305,607-624` | Bypass is substring-only: `warnings=['...lifespan...']` + `# pragma: B0.15: .` ships a real init regression green | Parse structured `reason="..."` with min length; require warning to name the offending init fn. |
| R8-J4-2 | MED | no | B0.12 disclosure fiction | `r_no_module_state.py:63-71,526-576` | Documented dual-signal bypass never enforced — waiver is pure frozenset membership; rule never reads `_SINGLE_PROCESS_OK`/`warnings=` | Make `_WAIVED_TOOLS` conditional: verify both signals before skipping. |
| R8-J4-3 | MED | no | B0.14 name-suffix evasion | `r_write_schemas_strict.py:282-287,593-598` | Write schema named `UserForm`/`UserInput`/`NewUser` classifies as neither write nor read → `extra=forbid` never required | Require `extra=forbid` on every non-READ BaseModel; read allow-list as sole exemption. |
| R8-J4-5 | MED | no | B0.11 dynamic mount | `r_admin_routes_auth.py:285-310,387-406` | `app.add_api_route(...)`-mounted admin routes invisible to B0.11 (latent; no in-repo use) | Detect `*.add_api_route(...)`, extract path/methods/endpoint. |
| R8-J6-1 | MED | no | prometheus method cardinality | `add_prometheus_metrics/templates/metrics_middleware.py.tmpl:65-70` | #148 normalized `path` but `method` stays attacker-controlled — random methods mint unbounded time series | Collapse non-allowlisted methods to `OTHER`; add behavior test. |
| R8-J6-2 | MED | yes | k8s probe hard-dep (#149) | `add_kubernetes_manifests/__init__.py:146-163` | Probes retargeted to `/readyz`+`/startupz` which the tool neither emits nor documents → `/healthz`-only apps get never-Ready pod | Scaffold the health router or add explicit next_step naming the 3 endpoints. |
| R8-J7-1 | MED | yes | throttle fallback OOM (#156) | `add_adaptive_throttle/templates/throttle_middleware.py.tmpl:108-131` | New always-on quota path's Redis-down `_counts` dict is unbounded, keyed by attacker-varyable fingerprint → memory-exhaustion DoS | Purge expired on write / cap as OrderedDict, or skip quota when Redis unavailable. |
| R8-J1-4 | LOW | no | EventSourcedStoreAdapter (#153) | `EventSourcedStoreAdapter.py:53-71` | Routes gate auth but no per-aggregate ownership; relies on integrator passing superuser dep | Runtime warn for superuser-grade dep; optional owner-resolver callback. |
| R8-J2-4 | LOW | no | data_export async path | `add_data_export/templates/arq_worker.py.tmpl:50-56` | Large exports buffer whole file into `BytesIO` → worker OOM; contradicts "memory-bounded"; async filters omit tenant_id | Stream chunks to multipart; pass tenant_id into async filters. |
| R8-J4-7 | LOW | no | B0.12 setattr smuggle | `r_no_module_state.py:458-497` | `setattr(sys.modules[__name__], '_X', {})` installs module state with no assign target → zero offenders (latent) | Detect `setattr(<module-ref>, name, <mutable>)`. |
| R8-J5-3 | LOW | no | compliance "engine" wording | `add_compliance_engine/__init__.py:31-33,1` | #158 downgraded fn docstring to "scaffold" but `MCP_TOOL.description` + module header still say "engine" | Change description + module header to "compliance scaffold". |
| R8-J7-2 | LOW | yes | api_key default-scope coherence | `add_api_key_auth/templates/scopes.py.tmpl:42,125-139` | Default seed tokens `{read,write}` don't fit the `resource:action` evaluator; deny-by-default with a 422 | Default seed to concrete `resource:action` strings, or surface required form. |
| R8-J8-3 | MED | no | compliance decrypt asymmetry | `add_compliance_engine/templates/compliance_engine_core.py.tmpl:125-138` | `encrypt_field` fails closed but `decrypt_field` fails open (`if not key: return token`) → ciphertext-as-plaintext if key unset | Make `decrypt_field` raise on empty key, mirroring encrypt. (issue #135) |
| R8-J8-4 | LOW | no | B0.11 WS blindness | `r_admin_routes_auth.py:153,285-310` | `_HTTP_VERBS` excludes `websocket` → WS handlers structurally invisible (shipped one is auth-gated; latent) | Recognize `@router.websocket`; check in-body token verification. |

**Refuted/invalid (6):** `R8-J2-1, R8-J4-4, R8-J4-6, R8-J5-1, R8-J5-2, R8-J5-4` — raised by jurors, disproved against real code by the refutation gate.

---

## §3 Single most important takeaway

**Not clean — but the blocker is a `git diff` mirage, not the new work.** The 20 fixes themselves are the highest-quality wave in this repo: every auth bypass / escalation / injection / cross-tenant-replay vector the session set out to close is genuinely and durably closed.

**Fix first, in order:**
1. **`R8-J8-1` (CRITICAL) — `add_compliance_engine` unauthenticated cross-tenant PII erasure.** A live, remotely-exploitable, *irreversible data-destruction* endpoint that ships GREEN only because the tool sits in `_WAIVED_TOOLS`. The session expanded the B0.11 regex to *match* `compliance` and then waived the very tool — so the rule performatively "knows about" a route it is deliberately blinded to. **Ship-blocker.** Tracked under #135 (not closed). `R8-J8-2` (unauth presence/device disclosure, #138) and `R8-J8-3` (decrypt fail-open) are the same waiver-blinding family and belong in the same batch.
2. **`R8-J1-1` (HIGH, regression) — default-ON throttle mass-ban.** The only NEW high-severity damage this session caused. One config-default flip (`ENABLED=False`) plus a fail-open guard neutralizes it and `R8-J1-2`/`R8-J7-1` along the same path.
3. **The §4.3 meta-rot (`R8-J4-1/2`)** is the strategic debt: the audit gate's own waiver mechanism is satisfiable with literal noise, which is *how* a CRITICAL like J8-1 ships green. Hardening the rules (which this session did well) is undermined as long as the disclosure layer is cosmetic.

---

## §4 Verify gate accounting

The adversarial refutation gate did real work: **6 of 30 raw findings were refuted/invalidated** before this list was compiled, and several survivors were down-graded with precision corrections. The 24 confirmed findings are each grounded in a file+line code path that was read; most were reproduced. The top CRITICAL + 2 HIGH were additionally re-verified by hand against the live templates. No CRITICAL or HIGH in this list is a free-floating "might".

— End Round-8 Validation —
