# RELEASE ATTESTOR (RA) — INVIOLABLE CONTRACT v0.3

# Release Attestor (RA) — Inviolable Contract v0.4.1

> **Status**: Draft for ratification. Closes 100% of Codex v11 (DEFER) + Opus v11 (APPROVE WITH CHANGES) findings on v0.3, plus Opus v12 HIGH findings F1 (RA-GOV-004 PENDING gate) and F3 (advisory SHA pinning). Codex v12 audit pending due to quota reset (May 5, 2026).

## §0 — Document classification

| Field | Value |
|---|---|
| **Document type** | Normative inviolable contract |
| **Status** | DRAFT v0.3 — pending Gustavo redline + cross-backbone audit |
| **Successor doc path** | `agents/release_attestor/CONTRACT.md` (this file) |
| **Authoring lineage** | v0.1 → v0.2 (industry-aligned) → v0.3 (this — normative-rigorous, post Codex+Opus cross-backbone audit) |
| **Authoring author** | Claude Opus 4.7 |
| **Cross-backbone audit** | Codex v10 (GPT-5) — converged on B. Modified verdict |
| **Conformance enforcement** | `agents/release_attestor/contract_check.py` MUST exit 0 for full conformance |
| **Amendment process** | §30 |
| **Effective on** | First merged commit at this doc path |
| **Revocation trigger** | Major version bump (semver) revokes prior signatures (§20) |

## §1 — Reading order + reviewer instructions

For redliners (in order): §5 → §7 → §9 → §11 → §12 → §14 → §17 → §24 → §25.
Skip on first pass: §13, §22.

## §2 — Conformance language (RFC 2119)

This document uses normative keywords with strict meaning per **RFC 2119**:

| Keyword | Meaning | Violation = |
|---|---|---|
| **MUST** | Absolute requirement | Spec violation; non-conformant; release blocked |
| **MUST NOT** | Absolute prohibition | Spec violation; non-conformant; release blocked |
| **SHOULD** | Strong recommendation; deviation requires written justification in audit log | Soft violation; flagged but non-blocking |
| **SHOULD NOT** | Strong recommendation against | Soft violation |
| **MAY** | Permission, optional | No violation regardless of choice |

Every normative clause carries a SPEC ID per §3 and an enforcement mechanism per §25.

## §3 — SPEC ID conventions

Every normative clause has a unique stable identifier of the form `RA-<CLASS>-<NNN>`:

| Prefix | Class |
|---|---|
| `RA-T-` | Threat (with mitigation) |
| `RA-AUTH-` | Authority scope item |
| `RA-IN-` | Input definition |
| `RA-DEC-` | Decision rule |
| `RA-INV-` | Invariant (always-holds) |
| `RA-Q-` | Quality standard |
| `RA-COMP-` | Completeness criterion |
| `RA-AP-` | Anti-pattern (forbidden) |
| `RA-DOD-` | Definition of Done |
| `RA-OBS-` | Observability |
| `RA-FM-` | Failure mode |
| `RA-GOV-` | Governance |
| `RA-SCH-` | Schema |
| `RA-MAN-` | Manual founder sign-off |

IDs are **immutable**. Once assigned, an ID's number is permanent. Removed clauses are marked `DEPRECATED` in §27 registry but never reassigned.

## §4 — Glossary

| Term | Definition |
|---|---|
| **Release Attestor (RA)** | The automation system specified by this contract. Machine attests evidence; never substitutes founder commitment. |
| **Founder** | The natural human Gustavo Schneiter, sole holder of commitment-signing authority for HuGR projects. |
| **Founder commitment** | A signature on a document where the founder MUST personally affirm acceptance (FREEZE.md §4, CONTRACT.md §E, ROADMAP §11, security disclosures, license). The machine MUST NOT substitute. |
| **Machine attestation** | A signed assertion that "given gates G1..GN evaluated to outputs O1..ON at commit C at time T". Never an acceptance/commitment. |
| **Gate** | An input from §11 evaluated against pass-conditions. May be programmatic (deterministic) or document (LLM-reviewed advisory). |
| **Verifier** | The deterministic component that evaluates programmatic gates. Never substituted by LLM. |
| **Reviewer** | Optional advisory LLM that produces a non-binding opinion on document gates. NOT a release precondition. |
| **Authority surface** | The allow-list and deny-list of operations RA may perform (§8). |
| **Conformance** | The state in which `contract_check.py` exits 0 for all SPEC IDs. |
| **Cross-backbone** | Property where two LLM reviewers come from different model families. Advisory in this contract — see §23. |
| **DSSE** | Dead Simple Signing Envelope — Sigstore's standard signing wrapper. |
| **in-toto Statement** | A signed predicate about an artefact (e.g., "build provenance" predicate over a release artefact). |
| **Repo `CONTRACT.md`** | The parent skill-kit `CONTRACT.md` at `/CONTRACT.md` (repo root). Contains §A1..§A12 + §B/§C/§D/§E. References to "CONTRACT.md §E" (the ratification block) throughout this document refer to that file, NOT this RA contract. |
| **RA `CONTRACT.md`** | This file at `agents/release_attestor/CONTRACT.md`. Specifies the Release Attestor inviolable contract. References to "this contract" or "§N" without further qualification refer to sections of this file. |

---

## §5 — Mission (single sentence, normative)

The Release Attestor MUST attest, via cryptographically-signed and externally-witnessed assertions, that a defined set of programmatic gates evaluated to specific outputs against a specific git commit at a specific time, and MUST NOT substitute the founder's personal acceptance of any commitment-bearing document.

## §6 — Scope inclusion (allow-list)

The RA MAY:

| ID | Operation |
|---|---|
| `RA-AUTH-101` | Read `git rev-parse HEAD` and other read-only `git` operations |
| `RA-AUTH-102` | Execute deterministic gate-check subprocesses (per §11) with documented timeouts |
| `RA-AUTH-103` | Emit a Decision artefact (Pydantic schema per §13) with verdict ∈ {ATTEST, REFUSE} |
| `RA-AUTH-104` | Sign the Decision artefact via Sigstore-keyless DSSE in a GitHub Actions runner with `id-token: write` |
| `RA-AUTH-105` | Emit an in-toto Statement (predicateType: `https://hugr.dev/release-attestation/v1`) wrapping the Decision artefact |
| `RA-AUTH-106` | Append the signed artefact to `agents/release_attestor/attestations/<release-tag>.intoto.jsonl` (one entry per attestation; never modified) |
| `RA-AUTH-107` | Optionally invoke a cross-backbone LLM reviewer (advisory only; output stored, NOT a precondition) |
| `RA-AUTH-108` | Emit a structured Refusal artefact (`RA-SCH-004`) at `agents/release_attestor/refusals/<invocation-id>.json` when any precondition fails (one file per invocation; never modified after write) |
| `RA-AUTH-109` | Run `contract_check.py` against itself (self-conformance) before any attestation |

## §7 — Scope exclusion (CRITICAL — deny-list)

The RA **MUST NOT** under any circumstance:

| ID | Forbidden Operation | Reason |
|---|---|---|
| `RA-AUTH-201` | Sign FREEZE.md §4 ratification line | Founder commitment; only Gustavo's natural-person identity |
| `RA-AUTH-202` | Sign CONTRACT.md §E ratification block | Founder commitment |
| `RA-AUTH-203` | Sign ADR Proposed→Ratified transitions | Founder commitment |
| `RA-AUTH-204` | Sign ROADMAP.md §11 founder-signature row | Founder commitment |
| `RA-AUTH-205` | Sign LICENSE, SECURITY.md disclosure SLAs | Legal commitment |
| `RA-AUTH-206` | Create or push git tags annotated as "founder approves release" | Tag annotation MUST distinguish "RA attests gates" from "Founder approves release" — separate signature lines |
| `RA-AUTH-207` | Execute `git push`, `git reset --hard`, `git rebase`, `git checkout --` | Destructive / network egress |
| `RA-AUTH-208` | Edit any file under `agents/release_attestor/` **EXCEPT** append-only writes to `agents/release_attestor/attestations/<release-tag>.intoto.jsonl` (per RA-AUTH-106) and `agents/release_attestor/refusals/<invocation-id>.json` (per RA-AUTH-108) | Self-modification forbidden; append-only output paths are explicitly carved out and constitute the only legal write surface |
| `RA-AUTH-209` | Spend money beyond gate-checks; paid runs require explicit `--authorize-paid` per §12 | Budget control |
| `RA-AUTH-210` | Read or modify environment variables not in the documented allow-list (§11.4) | Capability boundary |
| `RA-AUTH-211` | Read network resources during gate-check phase | Hermeticity (§9 RA-T-005) |
| `RA-AUTH-212` | Override or modify a previously-emitted attestation | Audit log immutability (§14 RA-INV-003) |
| `RA-AUTH-213` | Substitute the founder's signature with the machine's | Category-error mitigation (§9 RA-T-001) |

## §8 — Authority surface (machine vs founder dichotomy)

| Authority | Who MUST sign | Form |
|---|---|---|
| Gate evaluation outputs | RA | Sigstore-keyless DSSE on Decision artefact |
| in-toto release-attestation predicate | RA | DSSE-wrapped in-toto Statement |
| FREEZE.md §4 ratification | Gustavo | Manual text edit + git commit signed by Gustavo |
| CONTRACT.md §E ratification block | Gustavo | Manual text edit + git commit signed by Gustavo |
| ADR Proposed→Ratified transitions | Gustavo | Manual YAML frontmatter update + signed commit |
| ROADMAP §11 row | Gustavo | Manual edit + signed commit |
| Tag annotation (combined) | Gustavo + RA | Tag message: founder block (Gustavo's words) + machine block (RA's DSSE attestation reference) |
| Tag itself (`git tag -s vX.Y.Z`) | Gustavo | GPG- or SSH-signed by Gustavo's key |

---

## §9 — Threat model (RA-T-001..012, all enforced)

### `RA-T-001` — Substitution attack (founder signature replaced by machine)

**Threat**: A future maintainer extends RA's authority to sign founder commitments, eliminating the human-in-the-loop.

**Mitigation**: §7 RA-AUTH-201..205 are absolute. `contract_check.py` MUST scan all RA source code for any `sign_freeze`, `sign_contract`, `sign_adr`, `sign_roadmap` references and FAIL if found.

**Enforcement**: `test_no_substitution_authority()` — runtime grep + AST check.

### `RA-T-002` — Verifier silent failure

**Threat**: Verifier component returns "PASS" regardless of input due to bug, tampering, or trivially-passing predicate. Reviewer rubber-stamps without detecting.

**Mitigation**: Every gate MUST emit a known-failing canary on every run. The canary's failure is asserted by `contract_check.py`. If the canary passes, the verifier is broken and RA REFUSES.

**Enforcement**: `test_verifier_canary_fails_intentionally()` — runs each gate's canary, asserts FAIL.

### `RA-T-003` — Subprocess hang

**Threat**: A gate subprocess hangs indefinitely; RA blocks forever.

**Mitigation**: Every subprocess invocation MUST use `subprocess.run(..., timeout=N)` with N ≤ 60s for fast gates and N ≤ 1800s for heavy gates (per-gate documented). On timeout: SIGKILL + log + REFUSE.

**Enforcement**: `test_subprocess_timeout_enforced()` — invokes a hang-forever subprocess fixture, asserts RA exits with REFUSE within timeout + 5s.

### `RA-T-004` — Goalpost shift (contract amended in same commit as attestation)

**Threat**: A maintainer amends `CONTRACT.md` (this doc) AND signs an attestation in the same commit, escaping the contract version that was supposed to gate the attestation.

**Mitigation**: Every Decision artefact MUST pin `contract_sha` to the SHA at HEAD time. `contract_check.py` MUST refuse to run if working-tree CONTRACT.md != HEAD CONTRACT.md.

**Enforcement**: `test_contract_sha_pinned_and_clean()` — verify pin + clean working tree.

### `RA-T-005` — Hermeticity violation (network during gate-check)

**Threat**: A gate makes a network call during verifier phase, allowing dynamic input injection.

**Mitigation**: RA MUST run gate-check phase with network egress blocked OR with a documented egress allow-list audited at attestation time. Network egress MAY occur ONLY in the explicit `--authorize-paid` LLM-call phase, which is separate.

**Enforcement**: `test_gate_check_no_network()` — run with network blocked, assert all gates pass; assert any network call raises.

### `RA-T-006` — Audit log tampering via force-push

**Threat**: A maintainer with force-push rights rewrites attestation history.

**Mitigation**: Attestations MUST be pushed to the public Sigstore Rekor instance (default) OR to a private Rekor instance with non-Gustavo CODEOWNER + branch-protection-deny-force-push. The local `attestations/*.intoto.jsonl` is a mirror; the source of truth is the external transparency log.

**Enforcement**: `test_attestation_in_rekor()` — fetch from Rekor by inclusion proof; refuse if absent.

### `RA-T-007` — Authorization commit forgery

**Threat**: An attacker with repo write access creates a fake "Gustavo authorization" commit and points RA at it.

**Mitigation**: Authorization MUST be a Sigstore-keyless signature against Gustavo's GitHub OIDC identity. RA verifies the authorization's signature against `agents/release_attestor/root_identities.json` that ONLY Gustavo's offline key can update.

**Enforcement**: `test_authorization_signature_verifies()` — verify against root_identities.json; refuse if mismatch.

### `RA-T-008` — Cross-backbone advisory misuse

**Threat**: A future maintainer escalates the optional cross-backbone reviewer (§23) to a release precondition.

**Mitigation**: §23 is normatively advisory. `contract_check.py` MUST refuse if any code path makes cross-backbone reviewer output a release precondition.

**Enforcement**: `test_cross_backbone_is_advisory_only()` — AST scan + decision-graph audit.

### `RA-T-009` — Sigstore Rekor unavailability

**Threat**: The Sigstore public Rekor instance (or self-hosted Rekor) is unreachable, returns 5xx, or has degraded transparency-log availability during attestation. Without inclusion in Rekor, the audit log is not externally witnessed.

**Mitigation**: RA MUST treat Rekor unreachability as a hard REFUSE — **no local-only fallback**. Per §9 RA-T-006, the external transparency log is the source of truth; absent it, the attestation has no audit anchor and MUST NOT be emitted. RA MUST retry up to 3 times with exponential backoff (1s, 4s, 16s) before declaring REFUSE. Failure mode mapped to `RA-FM-001` in §21.

**Enforcement**: `test_rekor_unavailable_refuses()` — mock Rekor 503; assert RA emits structured `Refusal` with `failed_gates=["RA-IN-001-publication"]` and exits non-zero.

### `RA-T-010` — Founder OIDC compromise + rotation

**Threat**: Gustavo's GitHub OIDC identity (or SSH key in `root_identities.json`) is compromised. An attacker creates a fraudulent founder commitment that RA verifies as authentic.

**Mitigation**: Three layers: (a) `root_identities.json` is checked into the repo with append-only `rotation_log` (per RA-SCH-009 + §28.4 RATIFIED). Emergency rotation procedure documented in §20 RA-GOV-003. (b) Any change to `root_identities.json` MUST be a Gustavo-signed commit OR (during rotation when Gustavo identity is compromised) a 2-of-N quorum from a backup identity set. (c) RA MUST verify the founder commitment's signed_payload SHA against the commit object bytes — not just trust the GitHub API answer to "is this commit verified".

**Enforcement**: `test_oidc_rotation_invalidates_prior_signatures()` — simulate ROTATE_OUT + signed-by-old-key commit; assert RA refuses; `test_emergency_rotation_quorum()` — simulate compromised primary identity, assert quorum-only rotation succeeds.

### `RA-T-011` — Clock skew / time-attack

**Threat**: The runner's wall clock is NTP-skewed (forward or backward) due to misconfiguration or attack. RA emits attestations with `timestamp_utc` / `expires_at` outside their intended bounds, escaping the 90-day validity ceiling or backdating to satisfy stale gate-evaluation windows.

**Mitigation**: Before any attestation, RA MUST query an authoritative time source (system clock + at least one trusted NTP via Sigstore TUF metadata or `pool.ntp.org`) and compute observed skew. If `|observed_skew| > 300s` (5 minutes), RA MUST REFUSE with `RA-FM-002`. Computed skew is recorded in `RuntimeEnvironment.clock_skew_max_seconds_observed` (RA-SCH-008).

**Enforcement**: `test_clock_skew_refuses_above_ceiling()` — mock 600s skew; assert REFUSE.

### `RA-T-012` — in-toto subject confusion

**Threat**: An attacker crafts a `Decision` predicate where the in-toto `subject` field is empty, contains a bogus name, or points to a digest that doesn't match the actual release artefact. Verifiers downstream may match against wrong artefacts and accept attestations for releases that weren't actually verified.

**Mitigation**: `RA-SCH-003.subject` is now `list[Subject]` with `min_length=1`, and each `Subject` requires non-empty `digest` map (RA-SCH-003 model_validator). RA MUST populate `subject[0].name = release_target` and `subject[0].digest = {"gitCommit": git_head_at_invocation}`. Optional additional subjects (e.g., a built tarball SHA-256) MAY be appended; each MUST be independently digestable.

**Enforcement**: `test_subject_shape_locked()` — invalid: empty subject, missing digest, mismatched name vs release_target → all raise validation errors.

### Non-goals (RA explicitly does NOT)

- Make business decisions (release timing, scope cuts, pricing).
- Override audit verdicts.
- Hold legal/regulatory accountability.
- Wait for wall-clock gates (CI 48h streak).
- Self-modify.
- Auto-rerun on REFUSE.
- Substitute the founder's personal acceptance.

---

## §10 — Trust model (expository — no new SPEC IDs)

This section names the trust assumptions implicit in §6/§7/§8/§9 so reviewers can attack them explicitly.

### Trust roots

| Trust root | What is trusted | How it is anchored | Failure mode |
|---|---|---|---|
| **Founder identity** | An `ACTIVE` entry in `agents/release_attestor/root_identities.json` (RA-SCH-009). Currently a single founder (Gustavo Schneiter, GitHub `gustavomhss`). | The file is checked into the repo; mutation requires a Gustavo-signed commit OR a documented quorum rotation per RA-GOV-003 (§20). | T-007 forgery, T-010 compromise. |
| **Sigstore Fulcio** | OIDC issuer `https://token.actions.githubusercontent.com` mapped to GitHub Actions runner identity. | Public Sigstore PKI; root rotation tracked via Sigstore TUF metadata. | Out of scope — Sigstore root compromise breaks the entire ecosystem; RA inherits this trust. |
| **Sigstore Rekor** | Public transparency log (default) per §28.2 RATIFIED. | Inclusion proof verified at attestation time; absence of Rekor entry → REFUSE (T-009 + RA-FM-001). | T-006 force-push, T-009 unavailability. |
| **Verifier determinism** | Programmatic gates (RA-IN-001..008) produce identical outputs across runs given identical inputs. | RA-INV-001 + canary integrity (RA-T-002). | T-002 silent verifier. |
| **GitHub Actions runner integrity** | Hosted runner is hermetic enough for SLSA Build L1/L2 (NOT L3 — see §22). | GitHub-managed; documented egress policy in `RuntimeEnvironment`. | T-005 hermeticity violation. |

### Trust NON-roots

The cross-backbone reviewer (§23) is **explicitly NOT trusted** for release decisions. Its output is a weak forensic signal stored alongside the signed Decision (`RA-SCH-007`), not inside it. The Preference-Leakage research (Li et al., ICLR 2026) shows same-author/same-corpus reviewer pairs fail to surface independent failure modes; until empirically validated cross-backbone gates exist, this remains advisory.

### Trust delegation chain (single-line)

```
Founder commitment (Gustavo SSH-sig commit on FREEZE/CONTRACT/ADR/ROADMAP)
   ↓ verified by RA against root_identities.json (RA-IN-022)
RA Decision predicate (deterministic gates only)
   ↓ signed by RA via Sigstore-keyless DSSE (Fulcio + GitHub OIDC)
in-toto Statement (predicateType: hugr.dev/release-attestation/v1)
   ↓ included in Sigstore Rekor (public transparency log)
Verifiable artefact: any party can fetch + re-verify chain
```

**The chain stops at the founder commitment.** RA never substitutes the first link.

---

## §11 — Inputs (RA-IN-001..024 + RA-IN-ENV-001..009)

The verifier MUST read exactly these inputs and NO OTHERS. v0.4 expanded RA-IN-NNN to 24 (was 20) to satisfy `RA-COMP-001` cardinality (Codex v11 finding) and added an explicit env-allow-list of 9 IDs (`RA-IN-ENV-NNN`) including the 2 OIDC vars Sigstore keyless requires.

### A. Programmatic gates (deterministic, no LLM)

| ID | Input | Pass condition | Subprocess timeout |
|---|---|---|---|
| `RA-IN-001` | `git rev-parse HEAD` | non-empty 40-char SHA | 5s |
| `RA-IN-002` | `git status --porcelain` | exactly empty | 5s |
| `RA-IN-003` | `engine.audit.contract_check --quiet` | exit 0 + body contains "37/37 ALL GREEN" | 60s |
| `RA-IN-004` | `evidence/reproduce.sh --verify` | exit 0 + head_pin atomicity + 14 byte-diff matches + 7 grading-line matches | 1800s |
| `RA-IN-005` | head_pin_check (atomic + reachable from HEAD) | exit 0 | 5s |
| `RA-IN-006` | `pytest adapt/ core/venous/ engine/ -q --tb=line` | summary regex `^[0-9]+ passed.*0 failed` | 1800s |
| `RA-IN-007` | `tests/property_tests.py` | exit 0 (8/8 properties) | 600s |
| `RA-IN-008` | `engine.index.manifest verify` | stable_hash idempotent | 60s |

### B. Document gates (LLM advisory only — NOT release precondition)

| ID | Input | Advisory pass criterion |
|---|---|---|
| `RA-IN-009` | `LAUNCH.md` §1 row state | every checkbox checked OR explicit Gustavo carve-out |
| `RA-IN-010` | `evidence/EVIDENCE.md` rows vs `evidence/metrics_summary.json` | every claim matches JSON value |
| `RA-IN-011` | `evidence/not-yet-covered.md` | every "open" gap has milestone + target version |
| `RA-IN-012` | `evidence/external-eval/reviewer_signoffs/README.md` §5.1 timeline | reviewer-signoff status reaches §5.1 satisfaction |
| `RA-IN-013` | `evidence/external-eval/reviewer_signoffs/transcripts/*.md` | every BLOCKER/HIGH mapped to closure-commit |

### C. Repo state (cross-check, deterministic)

| ID | Input | Pass condition |
|---|---|---|
| `RA-IN-014` | VERSION triplet (root + skill + STATUS.md) | three values consistent |
| `RA-IN-015` | CHANGELOG `[X.Y.Z]` block | placeholder `YYYY-MM-DD` OR today's date |
| `RA-IN-016` | working-tree | no uncommitted changes |

### D. Founder-commitment artefacts (verified PRESENT, NOT signed by RA)

Per §28.3 RATIFIED: founder uses **SSH-sig** (`git commit -S` with `gpg.format = ssh`). RA verifies via `git verify-commit` against `agents/release_attestor/root_identities.json` (RA-SCH-009).

| ID | Input | Pass condition |
|---|---|---|
| `RA-IN-017` | `<repo>/FREEZE.md` §4 signature line | SSH-sig'd commit landing the line, signer matches an `ACTIVE` identity in `root_identities.json` |
| `RA-IN-018` | `<repo>/CONTRACT.md` §E ratification block (parent skill `CONTRACT.md`, NOT this RA contract — see §4 Glossary) | SSH-sig'd commit, signer is `ACTIVE` founder |
| `RA-IN-019` | `<repo>/docs/decisions/00NN-*.md` ADR | YAML frontmatter `status: Ratified`, SSH-sig'd commit landing the flip, signer is `ACTIVE` founder |
| `RA-IN-020` | `<repo>/ROADMAP.md` §11 row | SSH-sig'd commit, signer is `ACTIVE` founder |

### E. Internal trust artefacts (read by RA itself; required by RA-COMP-001 cardinality equality)

These inputs are read by RA for self-pinning, identity verification, and self-conformance. v0.4 adds them explicitly so `RA-COMP-001`'s cardinality identity holds (Codex v11 caught the v0.3 violation: RA reads CONTRACT.md / root_identities.json / own code without enumeration).

| ID | Input | Pass condition |
|---|---|---|
| `RA-IN-021` | `agents/release_attestor/CONTRACT.md` (this contract) | exists; SHA matches `Decision.contract_sha_pinned`; working tree == HEAD copy |
| `RA-IN-022` | `agents/release_attestor/root_identities.json` | parses against `RA-SCH-009` schema; ≥1 `ACTIVE` founder; `rotation_log` strictly append-only across HEAD vs HEAD~1 |
| `RA-IN-023` | RA source tree under `agents/release_attestor/{schemas,verifier,signer,decision,refusal,quality_check,anti_pattern_check,contract_check}.py` | file tree-hash recorded in `RuntimeEnvironment`; AST scan (RA-INV-014) passes |
| `RA-IN-024` | RA test suite under `agents/release_attestor/tests/test_*.py` | all tests pass (recorded in gate `RA-IN-006` summary); test count ≥ floor documented in §24 |

### Environment variable allow-list

The verifier MAY read ONLY these environment variables. Any other variable read MUST raise.

| ID | Variable | Purpose |
|---|---|---|
| `RA-IN-ENV-001` | `HOME` | User home directory (for `~/.gitconfig`, etc.) |
| `RA-IN-ENV-002` | `PATH` | Subprocess execution |
| `RA-IN-ENV-003` | `GIT_*` (any) | Git operation environment |
| `RA-IN-ENV-004` | `PYTHONPATH` | Python module resolution |
| `RA-IN-ENV-005` | `GITHUB_*` (any) | GitHub Actions context (run ID, repo, ref, etc.) |
| `RA-IN-ENV-006` | `ACTIONS_ID_TOKEN_REQUEST_URL` | **REQUIRED for Sigstore keyless OIDC** — GitHub Actions OIDC token retrieval endpoint |
| `RA-IN-ENV-007` | `ACTIONS_ID_TOKEN_REQUEST_TOKEN` | **REQUIRED for Sigstore keyless OIDC** — GitHub Actions OIDC bearer for token exchange |
| `RA-IN-ENV-008` | `RUNNER_TEMP` | GitHub Actions ephemeral workspace (for transient artefacts) |
| `RA-IN-ENV-009` | `SIGSTORE_*` (any) | Sigstore client overrides (e.g., custom Rekor URL for self-hosted) |

---

## §12 — Decision contract (RA-DEC-001..010)

| ID | Rule |
|---|---|
| `RA-DEC-001` | **Verifier-first**: verifier MUST run before reviewer. Reviewer is advisory only. |
| `RA-DEC-002` | **All-pass = ATTEST**: if RA-IN-001..008 + RA-IN-014..020 all pass + clean tree, RA emits ATTEST. |
| `RA-DEC-003` | **Any failure = REFUSE**: any required gate fails → REFUSE with itemized list. |
| `RA-DEC-004` | **Reviewer cannot override**: cross-backbone reviewer's opinion stored in a SEPARATE `ReviewerAdvisory` artefact (`RA-SCH-007`) emitted alongside the Decision but NEVER inside the signed predicate. RA's signed Decision predicate contains deterministic gate evidence ONLY. The advisory MUST NOT change the verdict. |
| `RA-DEC-005` | **Single-shot**: one invocation = at most one Decision artefact. |
| `RA-DEC-006` | **REFUSE shape**: conforms to `Refusal` schema (RA-SCH-004). |
| `RA-DEC-007` | **ATTEST shape**: conforms to `Decision` schema (RA-SCH-002), wrapped in DSSE-signed in-toto Statement (RA-SCH-003). |
| `RA-DEC-008` | **Network boundary**: gate-check phase runs with network egress blocked. Reviewer phase MAY use network ONLY with `--authorize-paid` flag + budget cap. |
| `RA-DEC-009` | **Idempotency**: identical inputs → byte-identical Decision (modulo timestamp + invocation_id). |
| `RA-DEC-010` | **Founder commitments MUST exist before ATTEST**: RA-IN-017..020 verified present + valid before ATTEST. |

---

## §13 — Schema (RA-SCH-001..010)

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, Annotated
from datetime import datetime, timedelta
from re import compile as re_compile

# Common typed primitives
_GATE_ID_PATTERN = re_compile(r"^RA-IN-(0[0-9][0-9]|1[0-9][0-9]|2[0-4])$")
_SHA256_HEX_PATTERN = re_compile(r"^[a-f0-9]{64}$")
_SHA1_HEX_PATTERN = re_compile(r"^[a-f0-9]{40}$")

GateID = Annotated[str, Field(pattern=r"^RA-IN-\d{3}$", description="RA-IN-NNN identifier")]
Sha256Hex = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", description="lowercase 64-char SHA-256 hex digest")]
GitSha = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$", description="40-char git commit SHA")]

# RA-SCH-001 — Gate evaluation result (one per RA-IN-NNN)
class Gate(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: GateID                                                # e.g., "RA-IN-003"
    name: str = Field(min_length=1)
    type: Literal["programmatic", "document", "repo-state", "founder-commitment"]
    pass_condition: str = Field(min_length=1)
    # Tier ceilings: 5s (read-only git ops), 60s (contract_check), 600s (property_tests),
    # 1800s (heavy gates: pytest full sweep, reproduce.sh). Justification per gate in §11.
    # le=3600 was the v0.3 ceiling; raised to 7200 in v0.4 to accommodate future heavy gates,
    # but new constants > 1800 require contract amendment per §30 + per-gate justification.
    timeout_seconds: int = Field(ge=1, le=7200)
    actual_output_hash: Sha256Hex                             # SHA-256 of subprocess stdout
    actual_exit_code: int
    actual_duration_seconds: float = Field(ge=0)
    passed: bool
    canary_present_and_failed: bool                           # RA-T-002 mitigation
    failure_reason: str | None = None

# RA-SCH-002 — Decision artefact (signed predicate; deterministic evidence ONLY)
# v0.4: reviewer_advisory MOVED OUT of Decision (was inside in v0.3). Decision now contains
# ONLY deterministic gate evaluation evidence. The cross-backbone reviewer's opinion (if any)
# is emitted as a separate RA-SCH-007 ReviewerAdvisory artefact, not signed by RA, stored
# alongside in attestations/<release-tag>.advisory.json.
class Decision(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")  # UUID v4
    timestamp_utc: datetime
    contract_sha_pinned: GitSha
    git_head_at_invocation: GitSha
    release_target: str = Field(min_length=1, pattern=r"^v\d+\.\d+\.\d+(-rc\.\d+)?$")  # semver tag
    gates: list[Gate] = Field(min_length=1)
    verdict: Literal["ATTEST", "REFUSE"]
    refusal_artefact_ref: str | None = None                   # path to Refusal artefact (only when REFUSE)
    runtime_environment: "RuntimeEnvironment"                 # typed (was dict in v0.3)
    expires_at: datetime
    # v0.4.1: cryptographic binding to optional ReviewerAdvisory artefact (Opus v12 finding F3).
    # When a cross-backbone reviewer was invoked (§23 + RA-SCH-007), the SHA-256 of the advisory
    # JSON file MUST be pinned here so the advisory cannot be substituted/forged post-hoc by
    # an attacker with repo write access. None when no advisory was emitted.
    advisory_sha256_optional: Sha256Hex | None = None

    @model_validator(mode="after")
    def cross_field_consistency(self) -> "Decision":
        # RA-DEC-002 + RA-DEC-003: ATTEST iff all gates passed AND all canaries failed-as-expected
        all_passed = all(g.passed and g.canary_present_and_failed for g in self.gates)
        if self.verdict == "ATTEST" and not all_passed:
            raise ValueError("ATTEST requires all gates passed AND all canaries failed-as-expected")
        if self.verdict == "REFUSE" and all_passed:
            raise ValueError("REFUSE requires at least one gate failed OR canary did not fail-as-expected")
        # RA-DEC-006: REFUSE MUST reference a Refusal artefact
        if self.verdict == "REFUSE" and not self.refusal_artefact_ref:
            raise ValueError("REFUSE requires non-null refusal_artefact_ref pointing to RA-SCH-004 artefact")
        if self.verdict == "ATTEST" and self.refusal_artefact_ref is not None:
            raise ValueError("ATTEST MUST NOT reference a Refusal artefact")
        # RA-INV-008: expires_at strictly after timestamp_utc
        if self.expires_at <= self.timestamp_utc:
            raise ValueError("expires_at MUST be strictly after timestamp_utc")
        # 90-day default ceiling (machine convention, see RA-INV-008 rationale)
        if self.expires_at - self.timestamp_utc > timedelta(days=90):
            raise ValueError("expires_at MUST NOT exceed timestamp_utc + 90 days (machine policy)")
        return self

# RA-SCH-003 — in-toto v1 Statement wrapping Decision
# v0.4: predicateType bumped from /v0.3 → /v1 (major-only). Minor contract bumps no longer
# invalidate predicates; the precise contract version is recoverable from `predicate.contract_sha_pinned`.
class Subject(BaseModel):
    """in-toto subject: name + digest map. v0.4 typed (was list[dict] in v0.3)."""
    name: str = Field(min_length=1)
    digest: dict[Literal["sha256", "sha1", "gitCommit"], str]

    @field_validator("digest")
    @classmethod
    def at_least_one_digest(cls, v: dict) -> dict:
        if not v:
            raise ValueError("digest map MUST contain at least one entry")
        return v

class IntotoStatement(BaseModel):
    """https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md"""
    type_: Literal["https://in-toto.io/Statement/v1"] = Field(alias="_type")
    subject: list[Subject] = Field(min_length=1)
    predicateType: Literal["https://hugr.dev/release-attestation/v1"]
    predicate: Decision

# RA-SCH-004 — Structured Refusal artefact (emitted instead of attestation when verdict=REFUSE)
class Refusal(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    timestamp_utc: datetime
    contract_sha_pinned: GitSha
    refused_reason_summary: str = Field(min_length=1)
    failed_gates: list[GateID] = Field(min_length=1)
    canaries_failed_to_fail: list[GateID]
    remediation_path: str = Field(min_length=1)
    refuser_agent: str = Field(min_length=1)
    refuser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")

# RA-SCH-005 — DSSE envelope (Sigstore-keyless signed)
class Signature(BaseModel):
    """DSSE signature entry. v0.4 typed (was list[dict] in v0.3)."""
    keyid: str = ""                                           # Sigstore keyless: empty by convention
    sig: str = Field(min_length=1)                            # base64-encoded signature bytes
    cert: str | None = None                                   # PEM-encoded X.509 cert (Fulcio-issued)

class DSSEEnvelope(BaseModel):
    payload: str = Field(min_length=1)                        # base64-encoded IntotoStatement JSON
    payloadType: Literal["application/vnd.in-toto+json"]
    signatures: list[Signature] = Field(min_length=1)

# RA-SCH-006 — Founder commitment verification record
# v0.4: ADDED signature_bytes + verification_method so an auditor can independently re-verify
# RA's claim about the founder commitment (not just trust RA's boolean).
# Per §28.3 RATIFIED: founder uses SSH-sig (`git commit -S` with `gpg.format=ssh`).
class FounderCommitmentVerification(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    document: Literal["FREEZE.md.S4", "CONTRACT.md.SE", "ADR-Ratified", "ROADMAP.S11"]
    signature_present: bool
    signer_identity: str                                      # e.g., "gustavomhss" GitHub login
    signer_matches_root_of_trust: bool
    signature_valid: bool
    signed_commit_sha: GitSha
    # New v0.4 fields — independent reproducible verification:
    verification_method: Literal["ssh-sig", "github-oidc-commit", "gpg"]
    signature_bytes_b64: str | None = Field(default=None, description="base64-encoded raw signature blob; None when unavailable")
    signed_payload_sha256: Sha256Hex | None = Field(default=None, description="SHA-256 of the payload that was signed (commit object bytes), for re-verification")
    public_key_fingerprint: str | None = Field(default=None, description="SSH key SHA256 fingerprint or GPG long ID matching root_identities.json")

# RA-SCH-007 — ReviewerAdvisory (NEW in v0.4)
# Cross-backbone LLM reviewer opinion. NOT signed by RA. Stored alongside attestation
# at attestations/<release-tag>.advisory.json. Verifiers MUST ignore for release decisions.
#
# v0.4.1 (Opus v12 F3): The advisory file is forgeable post-hoc by anyone with repo write
# access. To prevent substitution attacks, when an advisory IS emitted, its SHA-256 MUST be
# computed AT EMISSION TIME and stored in Decision.advisory_sha256_optional BEFORE the Decision
# is signed. Verifiers consuming an advisory MUST recompute the SHA and reject if mismatched.
# This makes the advisory's CONTENT cryptographically pinned even though the file ITSELF is
# unsigned.
class ReviewerAdvisory(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str                                        # MUST match Decision.invocation_id
    backbone_family: str = Field(min_length=1)                # e.g., "claude-opus-4.7", "gpt-5.4"
    advisory_text: str = Field(min_length=1)
    advisory_verdict_label: Literal["concur", "concur-with-concerns", "dissent", "no-opinion"]
    advisory_concerns: list[str]                              # itemized concerns; informational only
    timestamp_utc: datetime
    reviewer_runtime: dict                                    # for forensics; NOT signed
    # Self-pin: SHA-256 of this entire artefact's canonical JSON serialization (computed AFTER
    # all other fields are finalized, EXCLUDING this field). Pinned in Decision.advisory_sha256_optional.
    self_sha256: Sha256Hex                                    # MUST equal sha256 of the JSON without this field

# RA-SCH-008 — RuntimeEnvironment (NEW in v0.4 typed wrapper, was dict in v0.3)
class RuntimeEnvironment(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    os_release: str = Field(min_length=1)                     # uname -r equivalent
    runner_kind: Literal["github-actions-hosted", "github-actions-self-hosted", "local-dev"]
    runner_id: str | None = None                              # GITHUB_RUN_ID when applicable
    rekor_endpoint: str = Field(min_length=1, pattern=r"^https://")  # public or self-hosted Rekor URL
    sigstore_issuer: str = Field(min_length=1, pattern=r"^https://")
    network_egress_policy: Literal["block-all", "allow-list-documented"]
    clock_skew_max_seconds_observed: int = Field(ge=0, le=300)  # NTP skew check; > ceiling → REFUSE (RA-T-011)

# RA-SCH-009 — RootIdentities (NEW in v0.4)
# Per §28.4 RATIFIED: JSON checked-in at agents/release_attestor/root_identities.json
# with append-only rotation_log. RA verifies founder commitments against this file.
class FounderIdentity(BaseModel):
    name: str = Field(min_length=1)
    github_user: str = Field(min_length=1, pattern=r"^[A-Za-z0-9-]+$")
    ssh_pubkey_fp_sha256: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/=]{43}$")
    gpg_long_id: str | None = Field(default=None, pattern=r"^[A-F0-9]{16}$")  # optional fallback
    status: Literal["ACTIVE", "ROTATED_OUT", "REVOKED"]

class RotationLogEntry(BaseModel):
    timestamp_utc: datetime
    operation: Literal["ADD", "ROTATE_OUT", "REVOKE", "REINSTATE"]
    target_github_user: str
    rationale: str = Field(min_length=1)
    approver_commit_sha: GitSha                                # Gustavo's signed commit landing this rotation

class RootIdentities(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    founders: list[FounderIdentity] = Field(min_length=1)
    rotation_log: list[RotationLogEntry]                      # append-only history

    @model_validator(mode="after")
    def at_least_one_active(self) -> "RootIdentities":
        if not any(f.status == "ACTIVE" for f in self.founders):
            raise ValueError("RootIdentities MUST contain at least one ACTIVE founder")
        return self

# RA-SCH-010 — ConformanceResult (used by contract_check.py per §26)
class ConformanceResult(BaseModel):
    spec_id: str = Field(pattern=r"^RA-[A-Z]+-\d{3}$")
    status: Literal["PASS", "FAIL", "DEPRECATED", "PENDING", "EXTERNAL"]
    enforcement_class: Literal["machine", "ci-gated", "external-witness", "manual-founder"]
    enforcement_mechanism: str = Field(min_length=1)          # e.g., "test_inv_no_substitution_authority"
    evidence: str
    failed_reason: str | None = None
```

---

## §14 — Invariants (RA-INV-001..015)

| ID | Invariant | Test |
|---|---|---|
| `RA-INV-001` | **Determinism on programmatic gates** | `test_inv_determinism_programmatic()` |
| `RA-INV-002` | **Single-shot** | `test_inv_single_shot()` |
| `RA-INV-003` | **Audit log immutability** | `test_inv_attestations_immutable()` |
| `RA-INV-004` | **No private state** | `test_inv_stateless()` |
| `RA-INV-005` | **Disclosure** (agent + version + backbone) | `test_inv_disclosure()` |
| `RA-INV-006` | **Verifier > Reviewer** | `test_inv_verifier_authority()` |
| `RA-INV-007` | **Contract-pinning** | `test_inv_contract_pinned()` |
| `RA-INV-008` | **Time-bounded** (`expires_at`): `expires_at = timestamp_utc + 90 days` (machine convention, not founder commitment). Verifiers MAY require fresher attestations within shorter windows. Schema validator (RA-SCH-002) enforces strict `expires_at > timestamp_utc` AND ceiling 90 days. | `test_inv_expires_at()` + Pydantic model_validator |
| `RA-INV-009` | **Anti-self-reference** | `test_inv_no_self_reference()` |
| `RA-INV-010` | **Network boundary** in verifier phase | `test_inv_no_network_in_verifier()` |
| `RA-INV-011` | **Canary integrity** (T2) | `test_inv_canaries_fail_as_expected()` |
| `RA-INV-012` | **Founder commitment present** before ATTEST | `test_inv_founder_commitments_present()` |
| `RA-INV-013` | **Subprocess timeout** documented per gate | `test_inv_subprocess_timeout()` |
| `RA-INV-014` | **No substitution authority** in source (T1) — three independent layers: (a) grep-based name scan for `sign_freeze`, `sign_contract`, `sign_adr`, `sign_roadmap`; (b) AST scan for any function whose return value flows into `Decision.verdict` AND whose body references `FREEZE.md` / `CONTRACT.md` / `ADR-` / `ROADMAP.md` paths; (c) integration test that mocks `Sigstore.sign()` and asserts the in-toto `subject` field never names a founder-commitment document. ALL THREE MUST PASS. | `test_inv_no_substitution_authority()` (3 sub-tests) |
| `RA-INV-015` | **Conformance self-check** before ATTEST | `test_inv_self_conformance()` |

---

## §15 — Quality standards (RA-Q-001..018)

| ID | Standard | Verification |
|---|---|---|
| `RA-Q-001` | mypy strict 100% | `mypy --strict agents/release_attestor/` |
| `RA-Q-002` | No `Any` in security-critical | grep |
| `RA-Q-003` | No catch-all `except Exception:` in security-critical | grep |
| `RA-Q-004` | All Pydantic models have `schema_version` | runtime assert |
| `RA-Q-005` | Coverage ≥ 95% line / 85% branch on security-critical | `coverage report --fail-under=95` |
| `RA-Q-006` | Coverage ≥ 80% on `reviewer.py` (cross-backbone advisory module) | `coverage report --fail-under=80` |
| `RA-Q-007` | Hermetic build: `reproduce.sh` byte-identical across two runs | `diff` |
| `RA-Q-008` | Every requirement has SPEC ID | `contract_check.py --validate-spec-ids` |
| `RA-Q-009` | Every SPEC ID has enforcement entry in §25 | `contract_check.py --validate-conformance-table` |
| `RA-Q-010` | README ≥ 200 lines | `wc -l` |
| `RA-Q-011` | Every public function has docstring | `pydocstyle --select=D102,D103` |
| `RA-Q-012` | Build provenance per attestation: RA package SHA (this contract's commit + RA source dir tree-hash) + Python version + OS + git HEAD | runtime assert |
| `RA-Q-013` | Pinned dependencies; lockfile committed | `git diff --exit-code uv.lock` |
| `RA-Q-014` | Tests pass on Linux + macOS | CI matrix |
| `RA-Q-015` | mypy strict-equality | `mypy --strict --strict-equality` |
| `RA-Q-016` | Every `subprocess.run()` has explicit `timeout=` | AST check |
| `RA-Q-017` | Audit log entries: JSON + human-readable Markdown twin | runtime assert |
| `RA-Q-018` | All emitted artefacts validated against `RA-SCH-001..006` | runtime assert |

---

## §16 — Anti-patterns (RA-AP-001..015)

| ID | Anti-pattern | Detection |
|---|---|---|
| `RA-AP-001` | Verdict that reads "looks good" without per-gate citation | Pydantic schema |
| `RA-AP-002` | Signature in same commit that drafts founder-commitment doc | git log scan |
| `RA-AP-003` | Reading files outside §11 input boundary | strace / fs-mock |
| `RA-AP-004` | Cached previous verdict reuse | invocation_id MUST be fresh UUID v4 |
| `RA-AP-005` | Hidden delegation (chained agent calls without disclosure) | audit log MUST list every LLM call |
| `RA-AP-006` | Self-modifying RA source | RA-INV-009 |
| `RA-AP-007` | Auto-rerun on REFUSE | post-REFUSE requires explicit re-invocation |
| `RA-AP-008` | LLM reviewer overriding programmatic FAIL | RA-INV-006 |
| `RA-AP-009` | Working-tree state assumption | always read from HEAD |
| `RA-AP-010` | Network call during gate-check phase | RA-INV-010 |
| `RA-AP-011` | Subprocess without timeout | RA-Q-016 |
| `RA-AP-012` | Signing founder-commitment documents | RA-AUTH-201..205 |
| `RA-AP-013` | Cross-backbone reviewer treated as release precondition | RA-T-008 |
| `RA-AP-014` | "SLSA L3+ aligned" claim without conformance table | RA-Q-008 |
| `RA-AP-015` | "TUF-aligned delegation" claim without 4-role partition | conformance table check |

---

## §17 — Completeness criteria (RA-COMP-001..012)

| ID | Criterion |
|---|---|
| `RA-COMP-001` | All inputs enumerated: `{RA-IN-001..024}` ∪ `{RA-IN-ENV-001..009}` = cardinality of inputs RA reads. **Enforcement**: AST scan + runtime read-tracker (RA-AP-003) cross-references actual `open()` / `subprocess.run()` / `os.environ` / `os.getenv` sites against this set; any unlisted read raises. |
| `RA-COMP-002` | All threats enumerated: `{RA-T-001..012}` |
| `RA-COMP-003` | All authorities enumerated: `{RA-AUTH-101..109}` ∪ `{RA-AUTH-201..213}` = full operation space. **Enforcement**: every public function in RA source MUST carry `@authority("RA-AUTH-NNN")` decorator OR be name-prefixed `_private`; `contract_check.py` AST-walks for module-level `def` and validates. |
| `RA-COMP-004` | All decision rules enumerated: `{RA-DEC-001..010}` covers every branch |
| `RA-COMP-005` | All invariants enumerated: `{RA-INV-001..015}` = asserts in `test_invariants.py` |
| `RA-COMP-006` | All quality standards enumerated: `{RA-Q-001..018}` |
| `RA-COMP-007` | All anti-patterns enumerated: `{RA-AP-001..015}` |
| `RA-COMP-008` | All schemas enumerated: `{RA-SCH-001..010}` (v0.4 expanded from 006: added 007 ReviewerAdvisory, 008 RuntimeEnvironment, 009 RootIdentities, 010 ConformanceResult) |
| `RA-COMP-009` | All failure modes enumerated: `{RA-FM-001..NNN}` in §21 |
| `RA-COMP-010` | All observability hooks enumerated: `{RA-OBS-001..NNN}` in §18 |
| `RA-COMP-011` | All governance procedures enumerated: `{RA-GOV-001..NNN}` in §20 |
| `RA-COMP-012` | All founder-commitment artefacts enumerated: `{RA-MAN-001..004}` |

---

## §18 — Observability (RA-OBS-001..010)

Every operation RA performs MUST be observable for forensic review. All log output is structured JSON (machine-parseable) with a Markdown-twin for human review (RA-Q-017).

| ID | Hook | Mechanism | Tested by |
|---|---|---|---|
| `RA-OBS-001` | Every gate evaluation emits a structured event with `{gate_id, name, type, started_utc, finished_utc, exit_code, output_sha256, passed, canary_present_and_failed}` | `verifier.py` log-decorator on each gate function | `test_obs_gate_event_emitted()` |
| `RA-OBS-002` | Every `subprocess.run()` logged before-and-after with `{command_shape, timeout_seconds, exit_code, duration_seconds, stdout_sha256, stderr_sha256}`. Command-shape redacts secrets (`SIGSTORE_*`, OIDC tokens). | `verifier._safe_subprocess()` wrapper | `test_obs_subprocess_logged()` |
| `RA-OBS-003` | Every `Decision` artefact emission logged with `{invocation_id, verdict, gate_count, expires_at}` | `decision.emit()` exit-log | `test_obs_decision_emission_logged()` |
| `RA-OBS-004` | Every `Refusal` artefact emission logged with `{invocation_id, refused_reason_summary, failed_gates}` | `refusal.emit()` exit-log | `test_obs_refusal_emission_logged()` |
| `RA-OBS-005` | Every Sigstore signing call logged with `{Fulcio_endpoint, signed_sha256, signature_length, ephemeral_key_kind, oidc_issuer}` (NEVER the OIDC bearer token itself) | `signer.sign()` log | `test_obs_signing_logged_no_secrets()` |
| `RA-OBS-006` | Every Rekor inclusion proof logged with `{rekor_uuid, log_index, integrated_time, inclusion_proof_size}` | `signer.publish()` log | `test_obs_rekor_inclusion_logged()` |
| `RA-OBS-007` | Every cross-backbone reviewer call logged with `{backbone_family, prompt_sha256, response_sha256, latency_ms, advisory_verdict_label}` | `reviewer.invoke()` log | `test_obs_reviewer_call_logged()` |
| `RA-OBS-008` | Every `RootIdentities` (RA-SCH-009) read logged with `{file_sha256, active_count, rotation_log_count, integrity_check_passed}` | `verifier._read_root_identities()` log | `test_obs_root_identities_read_logged()` |
| `RA-OBS-009` | Markdown-twin: every JSON log entry emitted to `attestations/<release-tag>.log.jsonl` MUST also produce a human-readable Markdown summary at `attestations/<release-tag>.log.md` (per RA-Q-017) | `obs.write_event()` produces both | `test_obs_markdown_twin_present()` |
| `RA-OBS-010` | All log writes are append-only fsync'd to disk before subsequent operations (no log-loss-on-crash) | `obs.write_event()` calls `os.fsync()` after `f.write()` | `test_obs_logs_durable_on_crash()` |

### Secret redaction floor

`RA-OBS-002` and `RA-OBS-005` redact secrets via deny-list: `ACTIONS_ID_TOKEN_REQUEST_TOKEN`, `GITHUB_TOKEN`, `SIGSTORE_*` token-bearing values. Redaction is tested by `test_obs_no_secret_leakage()` (mocked secret values; assert log files contain `[REDACTED]` not the values).

### Forensics retention

Logs are committed alongside attestations under `agents/release_attestor/attestations/`. Retention is governed by repo retention policy (currently: indefinite, since these are authoritative audit artefacts).

---

## §19 — Manual founder sign-off (RA-MAN-001..004)

Per **§28.3 RATIFIED**: founder signs via **SSH-sig** (`git commit -S` with `gpg.format = ssh`). Founder-side setup: `git config --global gpg.format ssh && git config --global user.signingkey ~/.ssh/<pubkey>.pub && git config --global commit.gpgsign true`. Signature is verifiable by any party via `git verify-commit <sha>` against the `ACTIVE` `ssh_pubkey_fp_sha256` in `agents/release_attestor/root_identities.json` (RA-SCH-009).

| ID | Document | Signing form | Verification |
|---|---|---|---|
| `RA-MAN-001` | `<repo>/FREEZE.md` §4 | Plain text edit + SSH-sig'd git commit | RA-IN-017 |
| `RA-MAN-002` | `<repo>/CONTRACT.md` §E ratification block (parent skill `CONTRACT.md`) | Plain text edit + SSH-sig'd git commit | RA-IN-018 |
| `RA-MAN-003` | `<repo>/docs/decisions/0NNN-*.md` ADR | YAML frontmatter `status: Ratified` flip + SSH-sig'd git commit | RA-IN-019 |
| `RA-MAN-004` | `<repo>/ROADMAP.md` §11 row | Plain text edit + SSH-sig'd git commit | RA-IN-020 |

---

## §20 — Versioning + governance (RA-GOV-001..008)

Procedures for evolving this contract, rotating root identities, and revoking attestations.

| ID | Procedure | Owner | Trigger | Mechanism |
|---|---|---|---|---|
| `RA-GOV-001` | **Contract amendment** (minor) | Founder | Drift between contract text and reality, or new requirement | New draft → Gustavo redline + signed approval commit → `contract_check.py` adapted → migration script for prior signatures (if affected) → ADR documenting rationale (per §30) |
| `RA-GOV-002` | **Major version revocation** | Founder | Breaking semantics change (e.g., schema renaming, threat model overhaul) | Bump MAJOR (v1.0 → v2.0) in `predicateType`. All prior attestations flagged `expired-by-major-bump` via `contract_check.py --revalidate`. Attestations remain valid as historical record but are NOT re-trusted. |
| `RA-GOV-003` | **Root-of-trust rotation** (planned) | Founder | Personnel change OR scheduled key rotation (recommended every 12 months) | PR landing changes to `agents/release_attestor/root_identities.json`: append `RotationLogEntry` (RA-SCH-009) with operation ∈ {ADD, ROTATE_OUT}; flip `FounderIdentity.status` accordingly. PR MUST be SSH-sig'd by an existing `ACTIVE` founder. |
| `RA-GOV-004` | **Emergency root-of-trust rotation** (compromise). **STATUS = PENDING** until §28.10 backup identity provisioned. | Quorum of `ACTIVE` backup identities (target: 2-of-N once §28.10 closes). | Founder OIDC/SSH key suspected compromised | Append `RotationLogEntry` with `operation="REVOKE"` + `rationale`. **Until backup-identity quorum is provisioned (§28.10)**: this procedure is structurally unenforceable — a compromised primary has push rights and could patch `root_identities.json` to exclude the legitimate founder. RA acknowledges this as a residual single-point-of-failure for the v1.0.0 window and gates the procedure as `PENDING` in §25 (Opus v12 finding F1). When §28.10 closes (≥1 backup `ACTIVE` identity exists), this status flips to `ACTIVE` via amendment per RA-GOV-001. |
| `RA-GOV-005` | **Pre-attestation revalidation** (after contract amendment) | RA itself | Any commit landing on `agents/release_attestor/CONTRACT.md` | `contract_check.py --revalidate-prior` re-runs all conformance gates against existing attestations. Attestations whose pinned `contract_sha` is older AND whose new contract has incompatible mandatory checks are flagged `revalidation-failed`. Verifiers downstream MUST treat such attestations as expired. |
| `RA-GOV-006` | **Security incident SLA** | Founder | Reported vulnerability in RA implementation | Acknowledge within 72h. Triage to fix-or-defer within 7 days. CVSS ≥ 7.0 → emergency contract amendment (RA-GOV-001) within 14 days. CVSS ≥ 9.0 → major revocation (RA-GOV-002) within 7 days. |
| `RA-GOV-007` | **`SPEC_ID_REGISTRY.md` regeneration** | RA | Any commit changing CONTRACT.md SPEC IDs | `contract_check.py --emit-registry` regenerates `agents/release_attestor/SPEC_ID_REGISTRY.md`. CI MUST `git diff --exit-code` this file (drift = pre-merge fail). |
| `RA-GOV-008` | **Contract amendment requires cross-backbone review** | Founder + RA | Any contract amendment per `RA-GOV-001` | Codex (GPT-5.4) + Opus (Claude 4.x) MUST audit the amendment in parallel. Both verdicts archived under `evidence/external-eval/reviewer_signoffs/transcripts/contract_v<X.Y>__{codex,opus}__verdict.md`. Disagreement (one APPROVE one REJECT) is permitted; the founder breaks ties and documents the rationale in the amendment ADR. |

### Backup founder identity pre-provisioning (TODO before v1.0.0)

Until at least 2 `ACTIVE` founder identities exist in `root_identities.json`, `RA-GOV-004` emergency rotation is single-point-of-failure-prone. Tracked as open question §28.10 (added in v0.4).

---

## §21 — Failure modes + recovery (RA-FM-001..012)

Every threat in §9 maps to one or more failure modes here. Each failure mode has a structured recovery path.

| ID | Failure mode | Detected by | RA action | Operator recovery path |
|---|---|---|---|---|
| `RA-FM-001` | Sigstore Rekor unreachable (5xx, network error, timeout) after 3 retries with exponential backoff | `signer.publish()` returns non-success | REFUSE; emit `Refusal` (RA-SCH-004) with `failed_gates=["RA-IN-PUB-rekor"]` | Wait for Rekor recovery (status.sigstore.dev) OR switch to self-hosted Rekor via `SIGSTORE_REKOR_URL` env var (RA-IN-ENV-009); re-invoke RA. Maps to `RA-T-009`. |
| `RA-FM-002` | Wall-clock skew > 300s (NTP) | `verifier._check_clock_skew()` | REFUSE; record observed skew in `RuntimeEnvironment.clock_skew_max_seconds_observed` | Sync runner clock (`sudo ntpdate pool.ntp.org` or runner reboot); re-invoke. Maps to `RA-T-011`. |
| `RA-FM-003` | Subprocess hang (timeout exceeded) | `subprocess.run(timeout=N)` raises `TimeoutExpired` | SIGKILL the subprocess; REFUSE with `failed_gates=[<gate_id>]` and `failure_reason="subprocess timeout exceeded N seconds"` | Diagnose hang root cause (locked DB, infinite loop, unreachable network); fix; re-invoke. Maps to `RA-T-003`. |
| `RA-FM-004` | OIDC token retrieval failure (`ACTIONS_ID_TOKEN_REQUEST_*` env unset OR endpoint returns non-200) | `signer._fetch_oidc_token()` | REFUSE; emit `Refusal` with `failed_gates=["RA-IN-OIDC"]` | Verify `id-token: write` permission in workflow YAML; verify runner is GitHub-hosted with OIDC enabled; re-invoke. |
| `RA-FM-005` | Disk full (cannot write attestation OR log) | `OSError [Errno 28]` | Best-effort REFUSE log to stderr; exit non-zero | Free disk space (`df -h`); re-invoke. RA does NOT auto-rerun (RA-AP-007). |
| `RA-FM-006` | Working tree dirty at attestation time | `RA-IN-002` `git status --porcelain` non-empty | REFUSE with `failure_reason="working tree dirty: <git status output>"` | Commit or discard pending changes; re-invoke. |
| `RA-FM-007` | `contract_sha_pinned` mismatch (working-tree CONTRACT.md ≠ HEAD CONTRACT.md) | `verifier._check_contract_pin()` | REFUSE | This means CONTRACT.md was amended in the same working tree as the attestation attempt — the contract version is ambiguous. Commit the contract change first (per RA-GOV-001) BEFORE attesting; re-invoke. Maps to `RA-T-004`. |
| `RA-FM-008` | Network egress detected during gate-check phase | strace / process-tree audit (`RA-AP-003`) detects DNS resolution or socket() during `RA-IN-001..008` | REFUSE; emit `Refusal` with `failed_gates=[<offending_gate>]` and stack trace of the syscall | Identify offending gate; either remove network call or move it to the explicit `--authorize-paid` phase. Maps to `RA-T-005`. |
| `RA-FM-009` | Canary did not fail-as-expected (verifier silent failure) | `Gate.canary_present_and_failed == False` | REFUSE | Verifier is broken (returning PASS regardless of input). Bisect verifier change OR revert to last-known-good `verifier.py`; re-invoke. Maps to `RA-T-002`. |
| `RA-FM-010` | Founder commitment signature invalid (signer not in `root_identities.json`, OR signature bytes don't verify against pubkey) | `verifier._verify_founder_commitment()` returns `signature_valid=False` | REFUSE with `failure_reason="<RA-MAN-NNN> signature invalid: <reason>"` | Re-sign the commit with an `ACTIVE` SSH key (per `RA-MAN-NNN` + `RA-IN-017..020`); push; re-invoke. Maps to `RA-T-007` + `RA-T-010`. |
| `RA-FM-011` | in-toto subject confusion (subject empty, name mismatch with `release_target`, or digest map invalid) | `IntotoStatement` validation (`RA-SCH-003`) | REFUSE during artefact construction (Pydantic raises) | Programming error in `decision.py`; fix subject construction; re-invoke. Maps to `RA-T-012`. |
| `RA-FM-012` | Self-conformance check fails (`RA-INV-015`) — `contract_check.py` exits non-zero before attestation emission | `verifier._self_check()` | REFUSE; emit `Refusal` listing the failing SPEC IDs | Fix the failing SPEC ID(s); re-run `contract_check.py` until 0; re-invoke. |

### Recovery non-goals

- RA does NOT auto-retry on REFUSE (`RA-AP-007`). Operator recovery is explicit.
- RA does NOT degrade gracefully (no "partial attestation" mode). Either ATTEST or REFUSE.
- RA does NOT cache prior REFUSE outcomes; every invocation is fresh (`RA-AP-004`).

---

## §22 — Industry alignment (conformance table — implemented vs not)

| Standard | Property | RA implements? | Notes |
|---|---|---|---|
| in-toto v1.0 | Statement schema | ✅ FULL via `RA-SCH-003` | predicateType = `https://hugr.dev/release-attestation/v1` (major-only — minor contract bumps no longer invalidate predicates; precise contract version recoverable from `predicate.contract_sha_pinned`) |
| in-toto v1.0 | Layouts (steps/actors/rules) | ❌ NOT IMPLEMENTED | Out of scope for v0.3 |
| SLSA v1.2 | Build L1 (provenance exists) | ✅ FULL via DSSE-signed Decision | |
| SLSA v1.2 | Build L2 (signed provenance) | ✅ FULL via Sigstore keyless | |
| SLSA v1.2 | Build L3 (hosted, isolated) | ⚠️ PARTIAL | Runs in GH Actions runner |
| Sigstore Cosign | Keyless OIDC | ✅ FULL via `sigstore-python` | OIDC issuer: `https://token.actions.githubusercontent.com` |
| Sigstore Rekor | Public transparency log | ✅ FULL | Trade-off: signing identity becomes public |
| Sigstore Rekor | Inclusion proof | ✅ FULL via `sigstore-python` API | |
| TUF v1.0 | Root role | ⚠️ PARTIAL | `root_identities.json` lists allowed identities; rotation manual |
| TUF v1.0 | targets/snapshot/timestamp | ❌ NOT IMPLEMENTED | Out of scope for v0.3 |
| DSSE | Envelope | ✅ FULL via Sigstore | |
| RFC 8392 | Time-bounded validity | ✅ FULL via `expires_at` (90-day default) | |

---

## §23 — Cross-backbone reviewer (advisory only — NOT release gate)

Per `RA-T-008`, the cross-backbone reviewer is **normatively advisory**. RA MAY invoke a second LLM (different vendor family from the implementing author) and emit its opinion as a SEPARATE `ReviewerAdvisory` artefact (`RA-SCH-007`) at `agents/release_attestor/attestations/<release-tag>.advisory.json`.

**The advisory artefact is NEVER inside the signed Decision predicate.** RA's signed predicate (DSSE-wrapped in-toto Statement) contains deterministic gate evaluation evidence only. Verifiers consuming the attestation MUST NOT treat the advisory as authoritative for release decisions.

The reviewer MUST NOT influence the verdict.

### Cryptographic binding (v0.4.1 — Opus v12 F3)

While the advisory artefact itself is unsigned (it is "content alongside" the signed Decision, not part of the signed payload), its **SHA-256 IS pinned inside the signed Decision** via `Decision.advisory_sha256_optional`. This means: an attacker with repo write access can drop a fabricated `<release-tag>.advisory.json` next to the signed attestation, but a verifier comparing `sha256(advisory.json)` against `Decision.advisory_sha256_optional` will detect the substitution.

**Verifier MUST**:
1. If `Decision.advisory_sha256_optional is not None` → fetch `<release-tag>.advisory.json`, compute SHA-256, compare; mismatch ⇒ reject the entire attestation as tampered.
2. If `Decision.advisory_sha256_optional is None` → no advisory was emitted; presence of an unsigned advisory file beside the attestation is a tampering indicator (verifier MUST flag).

**RA MUST** compute the advisory's `self_sha256` at emission time AFTER all other ReviewerAdvisory fields are finalized, EXCLUDING `self_sha256` itself, and pin it in `Decision.advisory_sha256_optional` BEFORE signing the Decision.

A future contract version MAY introduce empirically-validated cross-backbone gates if Cohen's κ on a labeled close-call dataset shows independence; until that data exists, this stays advisory.

---

## §24 — Definition of Done (RA-DOD-001..044)

> **Honest time estimate (v0.4 correction)**: 60–150 hours for an experienced contributor with prior Sigstore + GitHub Actions familiarity. The v0.3 implication of "5–10 hours" was wrong. Major time sinks: Sigstore keyless integration debugging (15–25h), `reproduce.sh` byte-identical determinism (10–20h), 30+ adversarial threat-defense tests (15–30h), self-hosted Rekor evaluation if §28.2 reverses to private (additional 15–20h).

### Build phase

| ID | DoD item |
|---|---|
| `RA-DOD-001` | `agents/release_attestor/CONTRACT.md` (this doc) committed + Gustavo-redlined |
| `RA-DOD-002` | `agents/release_attestor/THREAT_MODEL.md` per §9 |
| `RA-DOD-003` | `schemas.py` with all 6 Pydantic models |
| `RA-DOD-004` | `verifier.py` implements all programmatic + repo-state gates |
| `RA-DOD-005` | `signer.py` emits DSSE-wrapped in-toto Statement via Sigstore |
| `RA-DOD-006` | `decision.py` implements `RA-DEC-001..010` |
| `RA-DOD-007` | `refusal.py` emits structured Refusal |
| `RA-DOD-008` | `quality_check.py` runs all `RA-Q-001..018` |
| `RA-DOD-009` | `anti_pattern_check.py` lints all `RA-AP-001..015` |
| `RA-DOD-010` | `contract_check.py` master orchestrator |
| `RA-DOD-011` | `tests/test_invariants.py` covers `RA-INV-001..015` |
| `RA-DOD-012` | `tests/test_threats.py` covers `RA-T-001..008` (v0.4 adds `tests/test_threats_v04.py` for `RA-T-009..012` per `RA-DOD-036`) |
| `RA-DOD-013` | `tests/test_completeness.py` covers `RA-COMP-001..012` |
| `RA-DOD-014` | `tests/test_decision.py` matrix (≥30 cases) |
| `RA-DOD-015` | `tests/test_refusal.py` |
| `RA-DOD-016` | `tests/test_anti_capture.py` for T1-T8 |
| `RA-DOD-017` | `tests/test_canary.py` for T2 |
| `RA-DOD-018` | `tests/test_founder_commitments.py` for RA-IN-017..020 |
| `RA-DOD-019` | `tests/test_schemas.py` Pydantic v2 strict-mode |
| `RA-DOD-020` | mypy strict on entire `agents/release_attestor/` |
| `RA-DOD-021` | Coverage ≥95% line / ≥85% branch on security-critical |
| `RA-DOD-022` | `reproduce.sh` byte-identical across two runs |
| `RA-DOD-023` | `README.md` ≥200 lines |
| `RA-DOD-024` | `MIGRATION.md` documenting v0.2 FPA → v0.3 RA deprecation |
| `RA-DOD-025` | `.github/workflows/release-attestor.yml` CI workflow |

### Validate phase

| ID | DoD item |
|---|---|
| `RA-DOD-026` | RA dry-run against post-Wave-I-1 evidence package matches expected verdict |
| `RA-DOD-027` | RA refuses on each `RA-T-NNN` simulated trigger |
| `RA-DOD-028` | T1 substitution attack defended |
| `RA-DOD-029` | T2 canary integrity test passes |
| `RA-DOD-030` | T3 hang test passes |
| `RA-DOD-031` | T6 audit log force-push detection |
| `RA-DOD-032` | T7 forged authorization commit detection |

### Operate phase

| ID | DoD item |
|---|---|
| `RA-DOD-033` | Gustavo authorization delegation commit landed |
| `RA-DOD-034` | First production attestation: RA emits ATTEST + Rekor inclusion confirmed |
| `RA-DOD-035` | Independent third-party audit of first attestation. **Definition of "independent" tightened in v0.4**: a fresh Codex (GPT-5.4) invocation with NO prior chat history given only the artefact + RA contract, AND a fresh Opus (Claude 4.x) invocation with the same constraint, in parallel. Codex auditing its own previous audit's outcome does NOT count. Both verdicts archived under `evidence/external-eval/reviewer_signoffs/`. |

### Build phase — v0.4 additions (RA-DOD-036..044)

| ID | DoD item |
|---|---|
| `RA-DOD-036` | `tests/test_threats_v04.py` covers `RA-T-009..012` (Rekor outage, OIDC rotation, clock skew, subject confusion) |
| `RA-DOD-037` | `tests/test_observability.py` covers `RA-OBS-001..010` (event emission + secret redaction + log durability) |
| `RA-DOD-038` | `tests/test_failure_modes.py` covers `RA-FM-001..012` |
| `RA-DOD-039` | `tests/test_governance.py` covers `RA-GOV-007` (registry regen drift) and `RA-GOV-005` (revalidation flagging) |
| `RA-DOD-040` | `agents/release_attestor/lints/check_authority_decorator.py` + `lints/check_timeouts.py` (custom AST scripts per RA-Q-016 + RA-COMP-003) |
| `RA-DOD-041` | `agents/release_attestor/observability/obs.py` module implementing RA-OBS-001..010 |
| `RA-DOD-042` | `tests/test_root_identities.py` covers RA-SCH-009 + RA-IN-022 (parse + validate + rotation_log monotonicity) |
| `RA-DOD-043` | `tests/test_clock_skew.py` covers RA-T-011 (mock NTP skew) |
| `RA-DOD-044` | `tests/test_subject_shape.py` covers RA-T-012 (subject confusion) |

---

## §25 — Master conformance checklist

`agents/release_attestor/contract_check.py` MUST orchestrate all entries below. **Each SPEC ID is classified by enforcement mechanism** (v0.4 honesty fix — Codex v11 caught that v0.3 conflated "has SPEC ID" with "machine-checkable in single Python script"). `contract_check.py` returns `PASS` / `FAIL` for `machine` IDs, `EXTERNAL` for IDs requiring CI workflow / external-witness / manual-founder action, and `PENDING` for IDs not yet implemented. Full conformance = zero `FAIL` AND every `EXTERNAL` ID has its evidence link present.

| Section | Range | Count | Predominant enforcement class |
|---|---|---|---|
| Threats | RA-T-001..012 | **12** (was 8 in v0.3 — added T-009..T-012) | machine + ci-gated |
| Authorities (allowed) | RA-AUTH-101..109 | 9 | machine (decorator AST scan) |
| Authorities (forbidden) | RA-AUTH-201..213 | 13 | machine (deny-list AST scan) |
| Inputs | RA-IN-001..024 | **24** (was 20 — added 021..024 for self-pinning) | machine |
| Inputs (env) | RA-IN-ENV-001..009 | **9** (NEW in v0.4) | machine |
| Decision rules | RA-DEC-001..010 | 10 | machine (Pydantic + unit tests) |
| Schemas | RA-SCH-001..010 | **10** (was 6 — added 007..010 for advisory/runtime/identities/conformance) | machine (Pydantic strict) |
| Invariants | RA-INV-001..015 | 15 | machine (test_invariants.py) |
| Quality standards | RA-Q-001..018 | 18 | mix: machine + ci-gated (coverage) |
| Anti-patterns | RA-AP-001..015 | 15 | machine (lints) |
| Completeness | RA-COMP-001..012 | 12 | machine + ci-gated |
| Observability | RA-OBS-001..010 | **10** (NEW in v0.4) | machine (test_observability.py) |
| Failure modes | RA-FM-001..012 | **12** (NEW in v0.4) | machine (test_failure_modes.py) |
| Governance | RA-GOV-001..008 | **8** (NEW in v0.4) | manual-founder (mostly) + ci-gated (RA-GOV-007). **RA-GOV-004 is gated `PENDING` until §28.10 closes** (no backup identities exist; emergency rotation is structurally unenforceable until then — Opus v12 F1). |
| Manual sign-offs | RA-MAN-001..004 | 4 | manual-founder |
| DoD | RA-DOD-001..044 | **44** (was 35 — added 036..044 for v0.4 sections) | mix |
| **TOTAL** | | **221** | — |

### Enforcement class definitions

| Class | Meaning | `contract_check.py` status |
|---|---|---|
| `machine` | A single Python check (unit test, AST walk, Pydantic validation, runtime assert) decides PASS/FAIL deterministically. | PASS or FAIL |
| `ci-gated` | The check runs in CI (GitHub Actions) and writes a status; `contract_check.py` reads the CI status via `gh api` or local cached badge. | EXTERNAL (PASS if CI green and within freshness window, FAIL otherwise) |
| `external-witness` | The check requires an external system (Sigstore Rekor, Codex API, Opus API). `contract_check.py` queries the external system. | EXTERNAL (PASS if external attests success and inclusion proof verifies) |
| `manual-founder` | The check requires Gustavo's signed action (e.g., RA-MAN-001..004, most of RA-GOV-001..006). | EXTERNAL (PASS if a Gustavo-signed evidence file at the expected path matches the expected SPEC ID, FAIL otherwise) |

### Honest accounting (v0.4)

The v0.3 claim "all 165 SPEC IDs machine-checkable in a single Python script" was overstated (Codex v11 + Opus v11 finding). The v0.4 truth: **`contract_check.py` is an orchestrator**. Approximately 60% of IDs are pure `machine`; the rest delegate to CI / external systems / manual evidence. `--mode=strict` flags any `EXTERNAL` ID lacking fresh evidence as FAIL.

---

## §26 — Appendix A: `contract_check.py` specification

```python
# agents/release_attestor/contract_check.py
from typing import Literal
from pydantic import BaseModel
from .schemas import ConformanceResult  # imports RA-SCH-010

# Per RA-SCH-010, ConformanceResult has:
#   spec_id, status (PASS/FAIL/DEPRECATED/PENDING/EXTERNAL),
#   enforcement_class (machine/ci-gated/external-witness/manual-founder),
#   enforcement_mechanism, evidence, failed_reason

def main(strict: bool = True) -> int:
    """Orchestrator. Returns 0 if no FAIL; non-zero otherwise.

    --mode=strict (default): EXTERNAL IDs without fresh evidence → FAIL.
    --mode=permissive: EXTERNAL IDs without evidence → PENDING (returns 0 if no FAIL but warns).
    """
    results: list[ConformanceResult] = []
    # Iterate all 221 SPEC IDs from §25 in order:
    # for each, dispatch to the correct enforcement function:
    #   machine  → run the Python check inline
    #   ci-gated → query GH Actions status via `gh api`
    #   external-witness → query Sigstore Rekor / Codex / Opus
    #   manual-founder → check evidence file path + signature
    failures = [r for r in results if r.status == "FAIL"]
    pending = [r for r in results if r.status == "PENDING"]
    if strict and any(r.status == "EXTERNAL" and not r.evidence for r in results):
        failures.extend(r for r in results if r.status == "EXTERNAL" and not r.evidence)
    return 0 if not failures else 1


def emit_registry() -> None:
    """`--emit-registry` flag: regenerates `agents/release_attestor/SPEC_ID_REGISTRY.md`.
    CI (RA-GOV-007) runs `git diff --exit-code SPEC_ID_REGISTRY.md`; drift = pre-merge fail.
    """
    ...
```

### Out-of-band tools required (NOT inside `contract_check.py`)

| Tool | Purpose | SPEC IDs served |
|---|---|---|
| `lints/check_timeouts.py` | Custom AST script: every `subprocess.run()` has explicit `timeout=` kwarg | RA-Q-016 |
| `lints/check_authority_decorator.py` | Custom AST script: every public function carries `@authority(...)` OR is `_private` | RA-COMP-003 |
| `lints/check_substitution_authority.py` | Multi-layer scan: grep + AST + payload-mock | RA-INV-014 |
| `lints/check_decision_graph.py` | AST walk: any function whose return value flows into `Decision.verdict` MUST NOT read `reviewer_advisory` artefact | RA-T-008 |
| `observability/obs.py` | Structured event emitter with secret redaction | RA-OBS-001..010 |

---

## §27 — Appendix B: SPEC ID registry (master table)

Generated by `contract_check.py --emit-registry` and committed at `agents/release_attestor/SPEC_ID_REGISTRY.md`. **221 rows total** in v0.4 (was 165 in v0.3).

Per `RA-GOV-007`: CI MUST `git diff --exit-code SPEC_ID_REGISTRY.md` on every PR touching this CONTRACT.md. Drift between contract text and registry = pre-merge fail. The registry has columns: `spec_id, section, prefix, sequential_index, enforcement_class, enforcement_mechanism, body_excerpt`.

---

## §28 — Open questions for Gustavo + ratified decisions

### RATIFIED in v0.4 (2026-04-30)

1. **(may-defer)** **`agents/release_attestor/` location**: top-level (this) OR nested under `tools/`? → **DEFERRED** to first attestation; current `agents/release_attestor/` accepted for v0.4 build.
2. **(RATIFIED 2026-04-30)** **Sigstore Rekor venue** = **public Rekor (`rekor.sigstore.dev`)**. Trade-off accepted: signing identity (Gustavo's GitHub OIDC sub) and repo URL become public via Rekor entries. Justification: `humangr-labs` is already a public org; founder identity already publicly associated with the project. Migration path to self-hosted Rekor preserved via `SIGSTORE_REKOR_URL` env var (`RA-IN-ENV-009`); will be re-evaluated when enterprise tier requires private-attestation flow.
3. **(RATIFIED 2026-04-30)** **Founder-commitment signing form** = **SSH-sig** (`git commit -S` with `gpg.format = ssh`). Justification: SSH key already authorized; zero-setup beyond `git config gpg.format ssh`; verifiable by any party via `git verify-commit`; no GPG ceremony. RA-MAN-001..004 + RA-IN-017..020 updated. RA-SCH-009 schema fields `ssh_pubkey_fp_sha256` enforced.
4. **(RATIFIED 2026-04-30)** **Root-of-trust format** = **`agents/release_attestor/root_identities.json` checked into repo** with append-only `rotation_log` + `FounderIdentity` entries (RA-SCH-009). Rotation procedure documented in RA-GOV-003 (planned) + RA-GOV-004 (emergency). Custom schema chosen over TUF root.json subset to keep dependency surface minimal; migration path to TUF preserved by mapping `FounderIdentity.ssh_pubkey_fp_sha256` to a future TUF role keypair.
5. **(may-defer)** **Subprocess timeout defaults**: 60s/600s/1800s tier — accept or revise? → **TIERS ACCEPTED** for v0.4; ceiling raised to 7200s in `Gate.timeout_seconds` schema with per-gate justification required for any value > 1800.
6. **(RATIFIED 2026-04-30)** **`RA-DOD-035` definition of "independent third-party"** = a **fresh** Codex (GPT-5.4) invocation with NO prior chat history given only the artefact + RA contract, AND a **fresh** Opus (Claude 4.x) invocation under the same constraint, in parallel. Codex auditing its own previous audit's outcome does NOT count.
7. **(may-defer)** **Network egress in reviewer phase**: full block during gate-check + open during reviewer, OR tight egress allow-list? → **DEFERRED** to first attestation; v0.4 default is `RuntimeEnvironment.network_egress_policy = "block-all"` during gate-check phase, `--authorize-paid` flag opens egress for reviewer phase only.
8. **(may-defer)** **License of release_attestor itself**: same as parent project OR more permissive? → **DEFERRED** to v1.0.0 release; until then, inherits parent `humangr-labs/HuGR-Smith` proprietary license.

### Open questions added in v0.4

9. **Rekor outage policy** — RATIFIED in this same v0.4: REFUSE on Rekor unreachability after 3 retries; no local-only fallback. See `RA-T-009` + `RA-FM-001`. **Resolved.**
10. **(open — security-critical)** **Backup founder identity provisioning** — `RA-GOV-004` emergency rotation requires a quorum of `ACTIVE` identities to rotate out a compromised primary. **Current state: ZERO backup identities. RA-GOV-004 is therefore structurally unenforceable** and gated as `PENDING` in §25 (per Opus v12 finding F1). The "Founder manually" branch acknowledged in earlier v0.4 drafts is the EXACT compromise vector RA-T-010 is supposed to defend: if Gustavo's primary key is compromised, the attacker has push rights and can patch `root_identities.json` to exclude the legitimate founder before any "manual announcement" propagates. Honest framing: **between v0.4 ratification and §28.10 closure, RA's defense against `RA-T-010` reduces to "the attacker hasn't yet realized they have full repo write access"**. Action item BEFORE v1.0.0 release tag: provision at least 1 backup `ACTIVE` identity (one or more of: Gustavo's secondary device SSH key, hardware token like YubiKey, or designated quorum partner). When this lands, RA-GOV-004 status flips PENDING → ACTIVE via amendment per RA-GOV-001.

---

## §29 — Pre-build readiness checklist (v0.4)

- [ ] This v0.4 contract committed at `agents/release_attestor/CONTRACT.md`
- [x] §28 ratifications recorded: Q2=public Rekor, Q3=SSH-sig, Q4=`root_identities.json` checked-in, Q9=Rekor outage REFUSE, plus may-defer Q1/Q5/Q7/Q8
- [ ] §28.10 backup founder identity provisioning planned BEFORE v1.0.0 (currently single-point-of-failure on `RA-GOV-004`)
- [ ] Cross-backbone audit on v0.4: Codex (GPT-5.4) + Opus (Claude 4.x) BOTH return APPROVE OR APPROVE-WITH-MINOR-CHANGES (no DEFER, no SCRAP) on this committed contract
- [ ] Gustavo's authorization delegation commit drafted (lands `root_identities.json` initial entry)
- [ ] First attestation target chosen (v1.0.0 final tag-cut commit)
- [ ] CI workflow stub committed at `.github/workflows/release-attestor.yml`

---

## §30 — Severability + amendment

**Severability**: if any single SPEC ID is found unenforceable in production, that ID is marked `DEPRECATED` in §27; the contract remains in force for all other IDs.

**Amendment**: any change requires:
1. New draft committed with bumped version
2. Gustavo redline + signed approval commit
3. `contract_check.py` adapted
4. Migration script for prior signatures
5. ADR documenting rationale

**Major-version revocation**: when MAJOR component bumps (1.0 → 2.0), all attestations from prior contract versions are flagged `expired-by-major-bump` in `contract_check.py --revalidate`.

---

**End of v0.4.1 LAPIDADO contract.**

**Length**: ~13,400 words. **221 SPEC IDs** (was 165 in v0.3). Every clause classified by enforcement class (machine / ci-gated / external-witness / manual-founder).

**v0.4.1 changelog (close Opus v12 HIGH findings; Codex v12 deferred)**:
- **F1**: `RA-GOV-004` (emergency root-of-trust rotation) gated as `PENDING` in §25 + §20 row + §28.10 honest framing — until §28.10 (backup founder identity provisioning) closes, the procedure is structurally unenforceable and v0.4.1 acknowledges this single-point-of-failure explicitly rather than papering over it.
- **F3**: `Decision.advisory_sha256_optional: Sha256Hex | None` field added — pins SHA-256 of `ReviewerAdvisory` artefact inside the signed predicate. Advisory file remains unsigned but its content is now cryptographically tampered-detectable. RA-SCH-007 gains `self_sha256` field. §23 specifies verifier obligations.

F2/F4/F5/F8 (MEDIUM/LOW) deferred to v0.5 — not blockers for build start. F6/F7/F9/F10/F11 acceptable as-is.

**v0.4 changelog (close v11 audit findings)**:
- **P0 (block-build, 6)**: RA-AUTH-208 carve-out for append-only attestations write path; `reviewer_advisory` MOVED OUT of signed Decision predicate (now RA-SCH-007 separate artefact); FPA residue cleaned (`ratify.py` + "FPA SHA"); §4 Glossary disambiguates "repo `CONTRACT.md`" vs "RA `CONTRACT.md`"; OIDC env vars added (`ACTIONS_ID_TOKEN_REQUEST_*` in RA-IN-ENV-006/007); RA-COMP-001 reconciled by adding RA-IN-021..024 for self-pinning + RA-IN-ENV-001..009 explicit env allow-list.
- **P1 (essential, 8)**: §10 (Trust model), §18 (Observability RA-OBS-001..010), §20 (Versioning + governance RA-GOV-001..008), §21 (Failure modes RA-FM-001..012) WRITTEN — phantom-section problem closed; T-009..T-012 threats added (Rekor outage, OIDC compromise, clock skew, subject confusion); Pydantic validator now uses `model_validator(mode="after")` for cross-field consistency (REFUSE/expires_at/refusal_artefact_ref); structured schemas (`Subject`, `Signature`, `RuntimeEnvironment`, `RootIdentities`, `ReviewerAdvisory`, `ConformanceResult`); `predicateType` bumped to `/v1` (major-only); RA-SCH-006 augmented with `signature_bytes_b64` + `verification_method` (auditor independence); §25 master conformance classifies enforcement-class per ID; §28 Q9 (Rekor outage) added + resolved.
- **P2 (decisions ratified)**: Q2=public Rekor; Q3=SSH-sig; Q4=`root_identities.json` checked-in with `rotation_log`.
- **P3 (nice-to-have)**: DoD honest time estimate (60–150h, was 5–10h); `expires_at` clarified as machine convention; `Gate.timeout_seconds` ceiling raised 3600→7200 with justification rule; RA-INV-014 strengthened to grep+AST+payload-mock (3 layers).

Commit history of v0.3 → v0.4: see git log on this file. Cross-backbone audit verdicts archived under `evidence/external-eval/reviewer_signoffs/transcripts/`.
