# Codex Audit v9 — Wave I-1.N closures (re-audit on post-N HEAD)

You are running a SECOND RE-AUDIT against the same `/evidence/` package
you audited as v7 (Wave-H state) and v8 (post-Wave-I-1.J/K/L state).

Your earlier verdicts:
- **v7** (HEAD `80cf12c`): NO with 4 BLOCKERS + 7 HIGHs
- **v8** (HEAD `d84e94b`): NO with 1 BLOCKER + 6 HIGHs + 1 LOW (after Wave-I-1.J/K/L)

Wave I-1.N attempted to close every v8 finding via two commits:
- `bedb9f5` — substantive fixes (EVIDENCE staleness, per_tool exemption
  tightening, 3 evolve tools ast.parse, reproduce.sh contract hardening,
  reviewer_signoffs README §5.1 timeline)
- `bb407ef` — atomic regen + final reproduce.sh contract finalisation
  (grading_check for content-rich logs)

Your verdict files from v7 + v8 are archived at:
- `evidence/external-eval/reviewer_signoffs/transcripts/wave-i-1__codex_v7__verdict.md`
- `evidence/external-eval/reviewer_signoffs/transcripts/wave-i-1__codex_v8__verdict.md`

Wave-I-1.N closure mapping is at:
- `evidence/external-eval/reviewer_signoffs/wave-i-1__closure_log_v8.md`

## Repo + HEAD context

- **Repo:** `humangr-labs/HuGR_Skills` at `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills`
- **Audit HEAD:** `bb407ef` (2 commits past your v8 audit point)

## Verification protocol

Your job: confirm whether each v8 BLOCKER + HIGH is actually closed in N
(or is theatrical), and find any NEW defects introduced in N.

The closure log claims:

| v8 finding | claimed closure |
|---|---|
| C8.Q2.1 BLOCKER (3-way SHA drift) | atomic regen at bedb9f5 → all _meta.commit pinned |
| C8.Q2.2 HIGH (--verify omits install_docker + cross_composition) | reproduce.sh:415-440 grading_check on both |
| C8.Q2.3 HIGH (--deterministic 2nd-pass omits scan summaries + suite logs + install-docker + pytest) | reproduce.sh:441-465 includes them all |
| C8.Q2.4 HIGH (--external-eval fail-open partial keys) | reproduce.sh:480-495 requires ALL 3 keys |
| C8.Q2.5 HIGH (per_tool evolve ast_parse exemption too broad) | per_tool_pattern_audit.py:73-79 + EVOLVE_NON_PYTHON_EMITTERS per-tool refinement; 3 evolve tools got ast.parse |
| C8.Q2.6 HIGH (framework_free 124 vs 122) | EVIDENCE.md:33 says 122/124 with 2 cross-prim ImportErrors |
| C8.Q2.7 MEDIUM (emitted_glue measures whole-file) | open — flagged for v1.1+ |
| C8.Q2.8 MEDIUM (reviewer_signoffs README contradiction) | reviewer_signoffs/README.md restructured into 4 categories with §5.1 timeline |
| C8.Q2.9 LOW (127 vs 123 stale) | EVIDENCE.md:43 says "123 adapt tools" |

## The questions

### Q1 — v8 closure verification

For each row above (C8.Q2.1 through C8.Q2.9 except 7), spot-check:

1. `git show <closure-commit>` for the cited file
2. Run `./evidence/reproduce.sh --verify` to confirm probes still pass
3. Read EVIDENCE.md / reviewer_signoffs/README.md for the doc claims

For each finding mark: ✅ CLOSED / ⚠️ PARTIAL / ❌ THEATRE / 🆕 REGRESSION

### Q2 — New defects introduced by N

Look at:
- `bedb9f5` substantive diff
- `bb407ef` atomic regen diff
- The grading_check approach in reproduce.sh — is "grading-line greppable summary + presence" an honest substitute for byte-diff on content-rich logs? Or does it MISS structural defects (e.g., a test that prints "5387 passed" but actually failed silently)?
- Was anything ELSE moved off byte-diff into grading-check that should NOT have been?

### Q3 — Sign-off verdict

> "Would you sign off on `/evidence/` at HEAD `bb407ef` as sufficient
> proof for the v1.0.0 tag cut today, given the original prompt's
> framing AND the conditional-YES from your v8 verdict?"

- **Yes / No / Yes-conditional**
- If conditional: top 3 conditions
- If No: hard blockers

This is your THIRD pass; the question is whether v8's "would flip to YES
if N closes these conditions" actually held. The §5.1 reviewer-
independence gate hinges on this answer.

## Rules of engagement

- Cite specific file:line for every claim
- Spot-check, do NOT accept on faith
- ≤2000 words, structured Q1/Q2/Q3
- Try to write to `/tmp/codex-audit-wave-i-1-v9-verdict.md` — sandbox is
  read-only so write may fail; emit to stdout (captured from CLI transcript).
