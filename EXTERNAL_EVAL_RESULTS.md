# External Evaluation — 4 independent judges (2026-05-27)

Four frontier models, fresh context, no knowledge of how the kit was built, each
invented its own cold spec, drove the kit, and judged it against a fixed
adversarial rubric (see EXTERNAL_EVAL_PACKET.md). Vendors: Anthropic (Opus,
Sonnet) + OpenAI (Codex ×2).

## Scorecard

| Judge | Cold spec | Code (1-5) | Ship (1-5) | Would pay | Verdict |
|---|---|---|---|---|---|
| **Opus** | Vet clinic | 4 | 3 | YES, ~$25/seat/mo (conditional) | ship base, distrust extend |
| **Sonnet** | Vet clinic | 2 | 1 | NO ($0) | don't ship |
| **Codex #1** | Pharma cold-chain (multi-tenant) | 2 | 1 | NO ($0) | don't ship |
| **Codex #2** | Pharma cold-chain | 2 | 1 | NO ($0) | don't ship |

**3 of 4 say DON'T SHIP / wouldn't pay a cent. Opus alone says the base is good but the extend layer is a minefield.** All four agree the base auth/security is genuinely strong.

## What ALL agree is good (the real asset)
Base scaffold auth/config/security: PyJWT HS256 with algorithm whitelist, argon2id, timing-attack mitigation, user-enumeration prevention, SECRET_KEY fail-fast, security headers, owner-scoped CRUD with real per-object IDOR checks, parameterized SQL in `add_search`. "Better than a mid-level dev writes from scratch" (Opus).

## Convergent failures (the signal — independent vendors agreeing)

1. **FK / table-name heuristic emits a broken schema — `NoReferencedTableError`** — **ALL 4 + reproduced.**
   `generators/database/model.py` (~L73-88) turns ANY field ending `_id` into a UUID ForeignKey to a pluralized table, ignoring the declared type and with no escape hatch. Two failure modes:
   - phantom table: `microchip_id: str` → FK→`microchips` (no such table) [Sonnet]
   - pluralization/multiword mismatch: model `VaccineLot`→table `vaccinelots`, but FK `vaccine_lot_id`→`vaccine_lots` [Codex #1]; `excursioncases` vs `excursion_cases` [Codex #2]
   Breaks the emitted pytest suite at schema setup (37/37 → 37 errors) on realistic, idiomatic field/model names. **#1 blocker.**

2. **Compose/extend tools report `status: "success"` while emitting inert / unwired / partial code** — **ALL 4.**
   - `add_rbac` → `resolve_principal()` hardcoded to `anonymous()`, no route uses `require_roles` [Opus, Codex #1, Codex #2]
   - `add_audit_log` → `main.py` never calls `install_audit_log` [Codex #1, Codex #2]
   - `add_soft_delete` → no `is_deleted` column/migration; guards always-False [Opus]
   - tenant router generated but not registered in `routes/__init__.py`; `tenant.py` uses `CurrentUser` without importing it [Codex #1, Codex #2]
   - copied primitives (GracefulShutdown) never wired into `main.py` [Sonnet]
   A user told "RBAC added" / "audit added" ships a security control that does nothing. **#2 systemic: `success` is untrustworthy.**

3. **Compose tools patch only SOME models (silent partial composition)** — **Codex #1 + #2.**
   `add_multi_tenancy` patched 2 of 5 models because its model-rediscovery lowercases filenames and rebuilds CamelCase wrong (`add_multi_tenancy.py:262-310`). Inconsistent tenant isolation across related tables = cross-tenant leak vector. Also writes a tenant index at **module scope** (same class as the cursor_pagination indentation bug).

4. **BOLA on ownerless / tenant models (auth without authz)** — **Sonnet + Codex #1.**
   Models not in `owner_models` get auth-required routes with ZERO authorization checks, while docstrings claim "403 owner check". HIPAA-class exposure. No role/resource-policy mechanism; ownership is binary (user-FK or nothing). Tenant chosen via free-form `X-Tenant-ID` header, not a token claim.

5. **`add_search` SQL-injection vector (latent)** — **Opus + Sonnet.**
   `_text("'" + language + "'")` string-concat into `websearch_to_tsquery`; safe today (constant) but a footgun the moment `language` is user-fed.

6. **No cross-model relationships; shallow/misleading tests; thin domain logic** — **Sonnet, Codex #1.**
   `owner_models` only does `{model: "user"}`; no peer-model FKs → limited to flat user-owned lists. Emitted tests bypass app lifespan, use superuser happy-paths, insert against fake FK UUIDs. `CRUDBase.create` is generic; no domain workflows.

## Honest meta-lesson
This panel proves the long-standing self-critique (memory: "benchmark 100/100 is self-eval; resolves only with an external spec run"). The internal 100/100 + my own green cold runs were **misleading**: I avoided the triggering field/model names and only checked "boots + tests green", never "is the feature actually wired, enforced, and correct across all models under realistic naming". External validation found in ~30 min what 200+ internal commits did not.
