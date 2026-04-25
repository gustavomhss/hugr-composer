# reviewer_signoffs/ — independent adversarial reviewer verdicts

## Claim

LAUNCH.md §5.1 gating: "2-of-3 YES on the canonical sign-off question."

## Canonical sign-off question

> "Given everything you've seen — the audit trail, contract rules, test
> coverage, benchmark scores, emitted-code quality, architecture of
> primitives + tools + skill, and the known blockers + non-blockers —
> would you sign off on this as a v1.0.0 tag cut today?"

## Provenance — three categories

### Category 1: Wave-G author-summaries (BELOW BAR for §5.1, retained for historical context)

`codex_v6.md`, `sonnet.md`, `opus.md` are SUMMARIES authored by the
Wave-H author (Claude). `opus.md:31` admits author-reviewer identity
overlap. Raw transcripts of the Wave-G audits were not persisted.
These files are retained as a record of the Wave-G triangulation
discipline; they do NOT individually satisfy §5.1.

Codex v7 (Wave-I-1 audit) flagged this gap as BLOCKER-M4. Opus v7
(Wave-I-1 audit) flagged it as BLOCKER-M4. Wave I-1 acknowledged the
finding and closed it via Category 2 below.

### Category 2: Wave-I-1 raw-transcript audits (SATISFIES §5.1)

Two independent reviewers ran an adversarial audit against the Wave-H
evidence package (HEAD `80cf12c`). Their FULL VERDICTS — including
every BLOCKER + HIGH + MEDIUM finding with file:line citations — are
archived in `transcripts/`:

- `transcripts/wave-i-1__codex_v7__verdict.md`
  Reviewer: GPT-5 Codex (run via `codex exec` CLI in read-only sandbox)
  Verdict: NO (4 BLOCKERS + 7 HIGHs)
  Run date: 2026-04-24

- `transcripts/wave-i-1__opus_v7__verdict.md`
  Reviewer: Claude Opus 4.7 (independent agent, separate session)
  Verdict: NO (5 hard blockers + 13 HIGHs)
  Run date: 2026-04-24

- `transcripts/wave-i-1__audit_prompt.md`
  The exact prompt both reviewers received. Identical for both, so the
  comparison is apples-to-apples.

These ARE the genuine independent passes. Neither was authored by the
evidence-package author at audit-time; both produced unique findings;
both delivered their full reasoning + citations as raw text.

**However**: both verdicts were on the Wave-H state (pre-Wave-I-1).
Wave I-1 closed every BLOCKER + most HIGHs. To convert the conditional
"NO until X is closed" into an unconditional "YES", a fresh re-audit
on the post-Wave-I-1 HEAD (`e30571b`) is required. That is Category 3.

### Category 3: Post-Wave-I-1 re-audit (TBD pre-tag)

The Codex v7 + Opus v7 audits will be re-run against HEAD `e30571b`
before the tag cut. Their NEW verdicts will land in `transcripts/`
under `wave-i-X__codex_v8__verdict.md` and `wave-i-X__opus_v8__verdict.md`
with the same prompt template. Expected outcome: both flip to
unconditional YES given the Wave-I-1 closures (mapped 1:1 in
`wave-i-1__closure_log.md`). If either reviewer surfaces a NEW blocker
on the post-fix HEAD, Wave I-1 reopens.

## Wave-I-1 closure log

`wave-i-1__closure_log.md` maps each finding from Codex v7 + Opus v7
to the Wave-I-1 commit that closes it. Auditable 1:1 mapping; any
remaining open finding is listed there as such.

## §5.1 status

- **Wave-H**: NOT SATISFIED (author-summaries)
- **Wave-I-1**: PARTIALLY SATISFIED — Category 2 transcripts are
  genuine independent passes, but their conditional verdicts depend
  on Wave-I-1 closures still being audited.
- **Pre-tag**: SATISFIED iff Category 3 re-audit yields 2-of-3 YES.

This file is updated each time a category gains content.
