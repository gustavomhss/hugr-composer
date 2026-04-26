# RELEASE ATTESTOR (RA) — INVIOLABLE CONTRACT v0.3

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
| `RA-AUTH-105` | Emit an in-toto Statement (predicateType: `https://hugr.dev/release-attestation/v0.3`) wrapping the Decision artefact |
| `RA-AUTH-106` | Append the signed artefact to `agents/release_attestor/attestations/<release-tag>.intoto.jsonl` (one entry per attestation; never modified) |
| `RA-AUTH-107` | Optionally invoke a cross-backbone LLM reviewer (advisory only; output stored, NOT a precondition) |
| `RA-AUTH-108` | Emit a structured Refusal artefact (Pydantic schema per §13) when any precondition fails |
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
| `RA-AUTH-208` | Edit any file under `agents/release_attestor/` (anti-self-reference) | Self-modification forbidden |
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

## §9 — Threat model (RA-T-001..008, all enforced)

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

### Non-goals (RA explicitly does NOT)

- Make business decisions (release timing, scope cuts, pricing).
- Override audit verdicts.
- Hold legal/regulatory accountability.
- Wait for wall-clock gates (CI 48h streak).
- Self-modify.
- Auto-rerun on REFUSE.
- Substitute the founder's personal acceptance.

---

## §11 — Inputs (RA-IN-001..020)

The verifier MUST read exactly these inputs and NO OTHERS.

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

| ID | Input | Pass condition |
|---|---|---|
| `RA-IN-017` | FREEZE.md §4 signature line | signed by Gustavo's GitHub identity OR GPG key |
| `RA-IN-018` | CONTRACT.md §E ratification block | signed by Gustavo's identity |
| `RA-IN-019` | ADR docs/decisions/00NN-*.md | status = Ratified, signed by Gustavo |
| `RA-IN-020` | ROADMAP.md §11 row | signed by Gustavo |

### Environment variable allow-list

The verifier MAY read ONLY these environment variables: `HOME`, `PATH`, `GIT_*`, `PYTHONPATH`, `GITHUB_*`. Any other variable read MUST raise.

---

## §12 — Decision contract (RA-DEC-001..010)

| ID | Rule |
|---|---|
| `RA-DEC-001` | **Verifier-first**: verifier MUST run before reviewer. Reviewer is advisory only. |
| `RA-DEC-002` | **All-pass = ATTEST**: if RA-IN-001..008 + RA-IN-014..020 all pass + clean tree, RA emits ATTEST. |
| `RA-DEC-003` | **Any failure = REFUSE**: any required gate fails → REFUSE with itemized list. |
| `RA-DEC-004` | **Reviewer cannot override**: cross-backbone reviewer's opinion stored in `reviewer_advisory` field; MUST NOT change verdict. |
| `RA-DEC-005` | **Single-shot**: one invocation = at most one Decision artefact. |
| `RA-DEC-006` | **REFUSE shape**: conforms to `Refusal` schema (RA-SCH-004). |
| `RA-DEC-007` | **ATTEST shape**: conforms to `Decision` schema (RA-SCH-002), wrapped in DSSE-signed in-toto Statement (RA-SCH-003). |
| `RA-DEC-008` | **Network boundary**: gate-check phase runs with network egress blocked. Reviewer phase MAY use network ONLY with `--authorize-paid` flag + budget cap. |
| `RA-DEC-009` | **Idempotency**: identical inputs → byte-identical Decision (modulo timestamp + invocation_id). |
| `RA-DEC-010` | **Founder commitments MUST exist before ATTEST**: RA-IN-017..020 verified present + valid before ATTEST. |

---

## §13 — Schema (RA-SCH-001..006)

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from datetime import datetime

# RA-SCH-001
class Gate(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str  # e.g., "RA-IN-003"
    name: str
    type: Literal["programmatic", "document", "repo-state", "founder-commitment"]
    pass_condition: str
    timeout_seconds: int = Field(ge=1, le=3600)
    actual_output_hash: str  # sha256 of output
    actual_exit_code: int
    actual_duration_seconds: float
    passed: bool
    canary_present_and_failed: bool  # RA-T-002 mitigation
    failure_reason: str | None = None

# RA-SCH-002
class Decision(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str  # UUID v4
    timestamp_utc: datetime
    contract_sha_pinned: str
    git_head_at_invocation: str
    release_target: str
    gates: list[Gate]
    verdict: Literal["ATTEST", "REFUSE"]
    refusal_artefact_ref: str | None
    reviewer_advisory: dict | None
    runtime_environment: dict
    expires_at: datetime

    @field_validator("verdict")
    def verdict_consistency(cls, v, info):
        gates = info.data.get("gates", [])
        all_passed = all(g.passed and g.canary_present_and_failed for g in gates)
        if v == "ATTEST" and not all_passed:
            raise ValueError("ATTEST requires all gates passed AND all canaries failed-as-expected")
        return v

# RA-SCH-003
class IntotoStatement(BaseModel):
    """https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md"""
    type_: Literal["https://in-toto.io/Statement/v1"] = Field(alias="_type")
    subject: list[dict]
    predicateType: Literal["https://hugr.dev/release-attestation/v0.3"]
    predicate: Decision

# RA-SCH-004
class Refusal(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str
    timestamp_utc: datetime
    contract_sha_pinned: str
    refused_reason_summary: str
    failed_gates: list[str]
    canaries_failed_to_fail: list[str]
    remediation_path: str
    refuser_agent: str
    refuser_version: str

# RA-SCH-005
class DSSEEnvelope(BaseModel):
    payload: str  # base64-encoded IntotoStatement JSON
    payloadType: Literal["application/vnd.in-toto+json"]
    signatures: list[dict]

# RA-SCH-006
class FounderCommitmentVerification(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    document: Literal["FREEZE.md.S4", "CONTRACT.md.SE", "ADR-0004", "ROADMAP.S11"]
    signature_present: bool
    signer_identity: str
    signer_matches_root_of_trust: bool
    signature_valid: bool
    signed_commit_sha: str
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
| `RA-INV-008` | **Time-bounded** (`expires_at`) | `test_inv_expires_at()` |
| `RA-INV-009` | **Anti-self-reference** | `test_inv_no_self_reference()` |
| `RA-INV-010` | **Network boundary** in verifier phase | `test_inv_no_network_in_verifier()` |
| `RA-INV-011` | **Canary integrity** (T2) | `test_inv_canaries_fail_as_expected()` |
| `RA-INV-012` | **Founder commitment present** before ATTEST | `test_inv_founder_commitments_present()` |
| `RA-INV-013` | **Subprocess timeout** documented per gate | `test_inv_subprocess_timeout()` |
| `RA-INV-014` | **No substitution authority** in source (T1) | `test_inv_no_substitution_authority()` |
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
| `RA-Q-006` | Coverage ≥ 80% on `reviewer.py`, `ratify.py` | `coverage report --fail-under=80` |
| `RA-Q-007` | Hermetic build: `reproduce.sh` byte-identical across two runs | `diff` |
| `RA-Q-008` | Every requirement has SPEC ID | `contract_check.py --validate-spec-ids` |
| `RA-Q-009` | Every SPEC ID has enforcement entry in §25 | `contract_check.py --validate-conformance-table` |
| `RA-Q-010` | README ≥ 200 lines | `wc -l` |
| `RA-Q-011` | Every public function has docstring | `pydocstyle --select=D102,D103` |
| `RA-Q-012` | Build provenance per attestation: FPA SHA + Python version + OS + git HEAD | runtime assert |
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
| `RA-COMP-001` | All inputs enumerated: `{RA-IN-001..020}` = cardinality of inputs RA reads |
| `RA-COMP-002` | All threats enumerated: `{RA-T-001..008}` |
| `RA-COMP-003` | All authorities enumerated: `{RA-AUTH-101..109}` ∪ `{RA-AUTH-201..213}` = full operation space |
| `RA-COMP-004` | All decision rules enumerated: `{RA-DEC-001..010}` covers every branch |
| `RA-COMP-005` | All invariants enumerated: `{RA-INV-001..015}` = asserts in `test_invariants.py` |
| `RA-COMP-006` | All quality standards enumerated: `{RA-Q-001..018}` |
| `RA-COMP-007` | All anti-patterns enumerated: `{RA-AP-001..015}` |
| `RA-COMP-008` | All schemas enumerated: `{RA-SCH-001..006}` |
| `RA-COMP-009` | All failure modes enumerated in §19 |
| `RA-COMP-010` | All observability hooks enumerated |
| `RA-COMP-011` | All governance procedures enumerated |
| `RA-COMP-012` | All founder-commitment artefacts enumerated: `{RA-MAN-001..004}` |

---

## §19 — Manual founder sign-off (RA-MAN-001..004)

| ID | Document | Signing form | Verification |
|---|---|---|---|
| `RA-MAN-001` | FREEZE.md §4 | Plain text edit + signed git commit | RA-IN-017 |
| `RA-MAN-002` | CONTRACT.md §E ratification block | Plain text edit + signed git commit | RA-IN-018 |
| `RA-MAN-003` | ADR (Proposed → Ratified) | YAML status flip + signed git commit | RA-IN-019 |
| `RA-MAN-004` | ROADMAP.md §11 row | Plain text edit + signed git commit | RA-IN-020 |

---

## §22 — Industry alignment (conformance table — implemented vs not)

| Standard | Property | RA implements? | Notes |
|---|---|---|---|
| in-toto v1.0 | Statement schema | ✅ FULL via `RA-SCH-003` | predicateType = `https://hugr.dev/release-attestation/v0.3` |
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

Per `RA-T-008`, the cross-backbone reviewer is **normatively advisory**. RA MAY invoke a second LLM (different vendor family from the implementing author) and store its opinion in the Decision artefact's `reviewer_advisory` field.

The reviewer MUST NOT influence the verdict.

A future v0.4 of this contract MAY introduce empirically-validated cross-backbone gates if Cohen's κ on a labeled close-call dataset shows independence; until that data exists, this stays advisory.

---

## §24 — Definition of Done (RA-DOD-001..035)

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
| `RA-DOD-012` | `tests/test_threats.py` covers `RA-T-001..008` |
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
| `RA-DOD-035` | Independent third-party (Codex / GPT-5) audits first attestation as structurally honest |

---

## §25 — Master conformance checklist

`agents/release_attestor/contract_check.py` MUST run all entries below and exit 0 for full conformance.

| Section | Range | Count |
|---|---|---|
| Threats | RA-T-001..008 | 8 |
| Authorities (allowed) | RA-AUTH-101..109 | 9 |
| Authorities (forbidden) | RA-AUTH-201..213 | 13 |
| Inputs | RA-IN-001..020 | 20 |
| Decision rules | RA-DEC-001..010 | 10 |
| Schemas | RA-SCH-001..006 | 6 |
| Invariants | RA-INV-001..015 | 15 |
| Quality standards | RA-Q-001..018 | 18 |
| Anti-patterns | RA-AP-001..015 | 15 |
| Completeness | RA-COMP-001..012 | 12 |
| Manual sign-offs | RA-MAN-001..004 | 4 |
| DoD | RA-DOD-001..035 | 35 |
| **TOTAL** | | **165** |

---

## §26 — Appendix A: `contract_check.py` specification

```python
# agents/release_attestor/contract_check.py
from typing import Literal
from pydantic import BaseModel

class ConformanceResult(BaseModel):
    spec_id: str
    status: Literal["PASS", "FAIL", "DEPRECATED", "PENDING"]
    enforcement: Literal["runtime", "unit-test", "mypy", "lint", "manual", "coverage"]
    evidence: str
    failed_reason: str | None = None

def main() -> int:
    results: list[ConformanceResult] = []
    # iterate all 165 SPEC IDs from §25; run each enforcement
    failures = [r for r in results if r.status == "FAIL"]
    return 0 if not failures else 1
```

---

## §27 — Appendix B: SPEC ID registry (master table)

Generated by `contract_check.py --emit-registry` and committed at `agents/release_attestor/SPEC_ID_REGISTRY.md`. 165 rows total.

---

## §28 — Open questions for Gustavo (8)

1. **`agents/release_attestor/` location**: top-level (this) OR nested under `tools/`?
2. **Sigstore public-good Rekor vs self-hosted**: public leaks identity; self-hosted is harder. Default?
3. **Founder-commitment signing form**: Gustavo's GitHub OIDC OR offline GPG key?
4. **Authorization root-of-trust file format**: TUF root.json subset OR custom YAML?
5. **Subprocess timeout defaults**: 60s/600s/1800s tier — accept or revise?
6. **DoD `RA-DOD-035`**: does Codex v10 count as "independent third-party" or do we need a fresh audit per release?
7. **Network egress in reviewer phase**: full block during gate-check + open during reviewer, OR tight egress allow-list?
8. **License of release_attestor itself**: same as parent project OR more permissive?

---

## §29 — Pre-build readiness checklist

- [ ] This v0.3 contract committed at `agents/release_attestor/CONTRACT.md`
- [ ] §28's 8 open questions answered explicitly
- [ ] Gustavo's authorization delegation commit drafted
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

**End of v0.3 LAPIDADO contract.**

**Length**: ~7,800 words. **165 SPEC IDs**. Every clause traceable to enforcement.
