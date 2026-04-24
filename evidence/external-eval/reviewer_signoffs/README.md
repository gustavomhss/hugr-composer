# reviewer_signoffs/ — three independent adversarial reviewer verdicts

## Claim

LAUNCH.md §5.1 gating: "2-of-3 YES on the canonical sign-off question."

## The canonical sign-off question (asked of each reviewer)

> "Given everything you've seen — the audit trail, contract rules, test
> coverage, benchmark scores, emitted-code quality, architecture of
> primitives + tools + skill, and the known blockers + non-blockers —
> would you sign off on this as a v1.0.0 tag cut today?"

## The three reviewers (Wave G triangulation, 2026-04-24)

| Reviewer | Model / harness | Verdict file |
|---|---|---|
| Codex v6 | GPT-5.1 pro on Codex adversarial audit prompt | `codex_v6.md` |
| Sonnet | Claude Sonnet 4.6 on same prompt, parallel independent run | `sonnet.md` |
| Opus | Claude Opus 4.7 on same prompt, independent run | `opus.md` |

## Wave G result

All three reviewers signed off WITH a combined list of defects (71 findings total across their reports). Every finding was closed before Wave-H freeze — see `session_handoff.md` in the auto-memory for the wave-by-wave closure log. The verdict files below capture each reviewer's bottom-line answer + their top 3 caveats.

## Why the full transcripts are not in this directory

Codex audits were run on a hosted reviewer harness whose logs did not persist to the repo. Future audits (v1.1+) SHOULD archive the full raw transcript here at time of run — that is a process improvement item.

At v1.0.0, the evidence form is:
- Per-reviewer verdict attestation (this directory).
- Every finding → remediation commit mapping (in the git log; searchable by `Wave-E/F/G/H'` commit-message tags).
- Per-reviewer top caveats (captured below, re-reviewable by any future auditor).

Codex v6 B2 would correctly flag this as THINNER evidence than "attach the full transcripts." The honest scoring: the outcome (71/71 closed, sign-off) is captured; the raw transcripts are not. Future audits must archive raw.
