# Opus v9 Audit — Wave I-1.N closure re-audit on HEAD `bb407ef`

**Auditor:** Claude Opus 4.7 (1M), session-isolated re-audit
**Audit HEAD:** `bb407efc9e8cd5bea6d2bd57a4b9081eb267108b` (the prompt-stated target)
**Prior verdicts:**
- v7 (HEAD `80cf12c`): NO with 5 BLOCKERs + 13 HIGHs
- v8 (HEAD `d84e94b`): NO with 2 trivial conditions
**Method:** spot-checked closure log claims via `git show`, ran `--verify-fast`
(passed), inspected EVIDENCE.md / README.md / artefact headers / 3 evolve tools
/ reproduce.sh diff at file:line. Did NOT wait for full `--verify` (long pole
~30 min cross_composition); the closure-claim proof points are the artefact
contents and source-of-truth files, not the verifier exit code.

> **Note:** the working tree at audit time also contains a Wave-I-1.P commit
> (`b4986b7`) that the prompt did not list. I did the audit at the
> prompt-stated HEAD `bb407ef` after `git checkout bb407ef`, then restored.
> P is non-blocking for this verdict — it closes Opus v8 N8 (bandit `|| true`
> swallow), which I had marked LOW informational.

---

## Q1 — v8 closure verification

### C8.Q2.1 / O8.Q1.1 BLOCKER — three-SHA drift atomic regen

**Status:** ⚠️ PARTIAL.

`grep -h '"commit"' evidence/deterministic/*.json evidence/deterministic/*/SUMMARY.json | sort -u` at HEAD `bb407ef` returns **exactly one SHA: `bedb9f5...`** across all 12 deterministic JSONs. Atomicity check from prompt §4 step 5 PASSES: zero drift. The three-SHA split (`6d2dfb3` / `06263c7` / `b0080a9`) that v8 caught is gone.

BUT: every artefact pins to `bedb9f5` (the prior commit), not `bb407ef` (the audit HEAD). At HEAD `bb407ef`, `freshness_proof.log:11-15` records:
```
commit:  bedb9f56ecffad2ccdf54129e02aa2027979a533
clean:   5 modified/untracked paths
```

That's "commit ≠ HEAD" (off by one — the regen-only commit) AND "clean: 5 modified/untracked paths" recorded on a dirty tree at regen time. The grading line at `freshness_proof.log:7` says "commit SHA must equal the tag commit at v1.0.0 cut" — currently violated. The original v7/v8 HIGH-M6 finding ("artefacts not pinned to tag SHA on a clean tree") is **half-closed**: drift across artefacts is gone, but pin-to-HEAD is off by one and the dirty-tree status leaks.

This pattern (substantive-fix commit followed by regen-only commit with the regen pinned to substantive-fix SHA) is honest and reasonable, but if `bb407ef` is the tag-cut SHA, `freshness_proof.log:7`'s grading is violated by definition. v1.0.0 needs ONE more atomic regen on a clean tree at the tag commit.

### C8.Q2.2 HIGH — `--verify` install_docker + cross_composition coverage

**Status:** ⚠️ PARTIAL with hidden weakness.

`evidence/reproduce.sh:435-440` does invoke `grading_check` on both files. But this is grading-line greppable matching, NOT byte-diff. See Q2-N1 below for why the grading patterns are dangerously loose.

### C8.Q2.3 HIGH — `--deterministic` 2nd-pass full surface

**Status:** ✅ CLOSED. `evidence/reproduce.sh:473-483` second-pass diff covers scan summaries via byte-diff plus suite logs / pytest / install_docker via grading_check (same shape as `--verify`).

### C8.Q2.4 HIGH — `--external-eval` fail-closed on partial keys

**Status:** ✅ CLOSED. `evidence/reproduce.sh:502-510` requires ALL THREE provider keys; missing any single one returns exit 2 with explicit "Tag-gate runs require ALL THREE keys" note. Verified by file read.

### C8.Q2.5 HIGH — per_tool ast.parse exemption tightened

**Status:** ✅ CLOSED. `evidence/_harness/per_tool_pattern_audit.py:79` — `evolve` category now requires `CORE_PATTERNS | WRITE_PATTERNS` (full stack including ast_parse_validation). `:88-91` `EVOLVE_NON_PYTHON_EMITTERS = {generate_sdk, generate_admin_panel}` is the per-tool exemption set. The 3 evolve tools that emit Python now have ast.parse:
- `add_event_driven.py:210-221` — real loop over `files_created`, returns ToolResult error on SyntaxError, success only after all parses cleared (NOT dead code, on the success path)
- `add_i18n.py:210-214` — same shape
- `add_migration_data.py:171-175` — same shape

### C8.Q2.6 / O8.N3 HIGH/MEDIUM — framework_free 124/124 vs 122/124

**Status:** ✅ CLOSED. `evidence/EVIDENCE.md:33` row reads "**122/124 boot clean under blocked-framework meta_path; 2 ImportErrors are CROSS-PRIMITIVE (`events/DeadLetterRoute` + `events/TopicBus` import sibling `EventEnvelope`), 0 framework violations**". Honest reading.

### C8.Q2.8 / O8 — reviewer_signoffs README contradiction

**Status:** ❌ THEATRE / REGRESSION.

The closure-log claim is that `reviewer_signoffs/README.md` is restructured into 4 categories with §5.1 status timeline that says `Wave-I-1.N: SATISFIED`. That's true — `:107` does say so.

But `evidence/EVIDENCE.md:93` — the source-of-truth verdict file — STILL says **"PARTIALLY SATISFIED"** with the disclaimer "Status converges to SATISFIED on the next atomic commit if v8 conditions hold closed". So:
- README.md `:107`: §5.1 SATISFIED at Wave-I-1.N (this commit)
- EVIDENCE.md `:93`: PARTIALLY SATISFIED, will flip if conditions hold

This is the **same internal contradiction Codex v8 C8.Q2.8 flagged** — README says one thing, EVIDENCE says another, both at the closure HEAD. The closure log is internally inconsistent: it claims fixed by "EVIDENCE.md §3 reviewer row aligned" (closure log line 24), but `EVIDENCE.md:93` is NOT aligned. **The fix shipped to README but not to EVIDENCE.md.**

The §5.1 satisfaction question circles back: the claim "post-N SATISFIED" depends on the v8 reviewers' conditions being closed; v8 conditions are claimed closed by N; verifying that is the job of v9 (this audit). Marking SATISFIED in README before v9 lands is **author-self-attestation circular reference**, exactly the failure mode Codex v8 flagged. The v9 sign-off must come BEFORE README can credibly say SATISFIED. Until then, EVIDENCE.md:93 is the honest line.

### C8.Q2.9 LOW — "127 adapt tools" stale

**Status:** ✅ CLOSED. `EVIDENCE.md:43` reads "123 adapt tools (excludes `contracts/` helper-code)". Verified.

### O8.N2 HIGH — EVIDENCE.md RUFF 7/8 staleness

**Status:** ✅ CLOSED. `EVIDENCE.md:63` row says "**8/8 ALL PASSED — 984/984 tool-checks**". `EVIDENCE.md:108` strikes through the prior 7/8 line and marks CLOSED with commit pin `b0080a9`. Both lines updated.

### O8.N5 LOW — not-yet-covered.md §2 staleness on 2 generator non-determinisms

**Status:** ✅ CLOSED (per closure log) — verified §2 row exists with audit trail in earlier read; not re-checked here.

### Q1 verdict

8 of 9 v8 findings substantively closed. Two remain:
- **C8.Q2.1 / O8.Q1.1 PARTIAL** — atomic regen drift across artefacts CLOSED, but artefact pin (`bedb9f5`) is off-by-one from audit HEAD (`bb407ef`) AND the freshness_proof says regen ran on a 5-path-dirty tree. v1.0.0 still needs a final clean-tree atomic regen at tag SHA.
- **C8.Q2.8 REGRESSION** — README.md §5.1 timeline says SATISFIED but EVIDENCE.md §3 still says PARTIALLY SATISFIED. The §5.1 status contradiction Codex v8 flagged is not actually fixed; it just moved from one file to a different file pair.

---

## Q2 — New defects introduced by Wave I-1.N

### N1 — HIGH. `grading_check` is silent-fail-prone by header collision.

`evidence/reproduce.sh:357-369` `grading_check` uses `grep -qE "${pattern}" "${file}"`. The patterns:
- `8/8 properties|ALL PASSED` (line 432)
- `100/100 tools boot` (line 431)
- `12/12 tests passed|Result: 12/12` (line 433)

Every test_suites/*.log file is generated with a header that ALREADY contains the grading pattern. From `evidence/reproduce.sh:259-273` the header writes `# grading:  ${grade}` BEFORE the test runs. Concrete proof at `test_suites/property_tests.log`:
```
Line 7:  # grading:  8/8 properties (LAUNCH §1.2 met after Wave I-1.L)
Line 25: RESULT: ALL PASSED — 8/8 properties × 123 tools (984/984 tool-checks passed)
```
Both lines match the grep pattern.

**Failure mode:** if `tests/property_tests.py` crashes at iteration 1 (e.g., import error, assertion in property #1), the regen wrapper at line 276 swallows the non-zero exit via `|| true`. The output file then contains ONLY the header (with grading-pattern match) plus a partial traceback — and `grading_check` returns 0 anyway because the header line satisfies the regex. **A silently-failed test passes `--verify`.**

This is the exact silent-fail concern the prompt asked v9 to specifically scrutinise (Q2 in the audit prompt). The new contract is a regression vs. byte-diff. The honest fix: anchor the regex with `^` to require the test-runner's actual emitted summary line (e.g., `^RESULT: ALL PASSED` or `^Boot test result:`), or grep the SUMMARY pattern on lines AFTER the `# ---` header separator.

### N2 — MEDIUM. README §5.1 SATISFIED claim is author-self-attestation circular reference.

`reviewer_signoffs/README.md:83-90` Category 4 declares "post-Wave-I-1.N: SATISFIES §5.1" and lists the satisfaction signature as "wave-i-1__closure_log.md shows all v7 + v8 findings ✅ CLOSED, plus a `verify` run on the post-N HEAD returns exit 0". That's the author setting the bar AND declaring the bar met, in the same commit, before v9 audits whether the bar IS met. Pure circularity. The honest framing is what `EVIDENCE.md:93` does: PARTIALLY SATISFIED, awaiting v9.

### N3 — LOW. freshness_proof.log records dirty tree.

`evidence/deterministic/freshness_proof.log:14` says `clean:   5 modified/untracked paths` at the closure HEAD `bb407ef`. The grading line at `:7` says "commit SHA must equal the tag commit at v1.0.0 cut". 5 modified paths means regen ran in a non-pristine state. This bleeds into Q1-C8.Q2.1.

### N4 — LOW. `regen_test_suites` swallows test failures.

`evidence/reproduce.sh:276` ends with `|| true` on the test-runner invocation. Combined with N1, this lets `--deterministic` quietly produce broken test logs that pass downstream `grading_check`. The two together compose into a real CI honesty defect, not just a stylistic quirk.

---

## Q3 — Sign-off verdict

> Would I sign off on `/evidence/` at HEAD `bb407ef` as sufficient proof for the
> v1.0.0 tag cut today?

**Verdict: NO — Conditional YES on three fixes (≤30 min wall-clock).**

The substantive engineering of Wave-I-1.N is real:
- 3 evolve tools genuinely have ast.parse on the success path (not dead code)
- per_tool exemption logic correctly tightened to per-tool, not per-category
- `--external-eval` correctly fail-closed on partial keys
- `EVIDENCE.md` RUFF 7/8 → 8/8 + framework 124 → 122 + tools 127 → 123 all updated
- atomic regen across all 12 JSON artefacts (single SHA pin) restored

But three issues block unconditional YES:

### Conditions for unconditional YES

1. **`grading_check` regex anchoring (HIGH).** Add `^` anchors or grep below
   the `# ---` separator so a header line cannot satisfy the test-runner
   summary check. Without this, a test crash during `--deterministic` regen
   silently passes `--verify`. File: `evidence/reproduce.sh:431-440, 475-483`.
   Cost: ≤10 min.

2. **EVIDENCE.md / README.md §5.1 status alignment (MEDIUM).** Either flip
   `EVIDENCE.md:93` from "PARTIALLY SATISFIED" to "SATISFIED (Wave-I-1.N
   closure log + this v9 verdict)" once v9 lands, OR back the README.md
   `:107` Category 4 line off SATISFIED to PARTIALLY SATISFIED until v9
   ratifies. Pick one, stop having the two source-of-truth files
   contradict each other. Cost: ≤5 min.

3. **Final atomic regen at tag SHA on a clean tree (LOW-MEDIUM).** When
   `bb407ef` (or whatever lands after this v9 verdict) is selected as the
   tag cut, run `./evidence/reproduce.sh --deterministic` once more on a
   clean tree, commit the resulting artefacts atomically, and check
   `freshness_proof.log:14 clean: 0 modified/untracked paths` plus
   `freshness_proof.log:11 commit: <tag SHA>`. Cost: ≤15 min wall.

### What changed v8 → v9

v8 conditions were: atomic regen + EVIDENCE.md cleanup. Both were attempted in
N. The atomic regen fix is genuine (1 SHA pin across 12 JSONs). The EVIDENCE.md
fix is real for RUFF + framework + tools-count rows, but the §5.1 row (line 93)
went unfixed AND the README claimed satisfaction prematurely — a NEW (or
recursive) flavour of the same v8 contradiction. Plus N introduced the
grading_check silent-fail surface.

Net: v8 had 2 trivial conditions; v9 has 3 (1 genuinely-new HIGH from N's
grading_check, 1 recursive MEDIUM from N's incomplete §5.1 alignment, 1
LOW-MEDIUM holdover for the final clean-tree regen). The tag is reachable
after a focused 30-minute fix-pass.

### Bottom line

Wave-I-1.N is genuine progress, not paperwork. But it's not yet the clean
hand-off the closure log claims. Fix the grading_check anchoring + the
README/EVIDENCE.md §5.1 contradiction + do the clean-tree regen at tag SHA,
and v10 should flip to unconditional YES. As-is, v9 = **NO with 3 conditions**.

*Audited 2026-04-25 by Claude Opus 4.7 (1M).
v8 → v9 delta: 8/9 v8 findings closed; 1 partial (atomic-regen pin off-by-one
+ dirty tree); 1 regression (§5.1 README/EVIDENCE.md contradiction);
1 new HIGH (grading_check header collision).
Net: substantial progress toward tag, not yet there.*
