# Post-release — rollback runbook + first-72h monitoring

> **Purpose:** what to watch after the v1.0.0 tag ships, and how to
> recover if a release-blocker shows up within 72 hours.
>
> **Owner:** Gustavo (primary), on-call coverage TBD.

---

## 1. First-72h monitoring checklist

| Window | Signal | Action threshold | Remedy |
|---|---|---|---|
| 0-1h  | GitHub release published + tag visible | Tag missing → retry push | `git push origin v1.0.0` |
| 0-2h  | `install.sh` Docker nightly run — first post-tag run | Non-zero exit | Read workflow log; if spurious, rerun; if real, open hotfix branch |
| 0-6h  | First user reports of `fastapi_meta_*` tool-not-found | ≥ 1 legitimate report | Verify catalog.json has expected names; check Forge version mismatch |
| 0-12h | Benchmark nightly (both plan + code) | < 95 on any spec | Investigate regression; gate next commit behind root cause |
| 0-24h | `SECURITY.md` email inbox | Any message | Acknowledge per SLA in `SECURITY.md` §Response SLA |
| 0-48h | Install.sh on fresh Docker | Fail 2 nights in a row | Treat as hotfix-blocker |
| 0-72h | Contract drift — any CI failure on `main` | Any `34/34 ALL GREEN` regression | Revert the offending commit immediately |
| 0-72h | User-reported scaffold errors (generated projects don't compile) | ≥ 3 reports of the same root cause | Hotfix-blocker |

**Every morning during the 72h window:**

```bash
# from repo root
cd skills/SKILL-001-fastapi-production
PYTHONPATH=. .venv/bin/python -m engine.audit.contract_check   # must be 34/34
PYTHONPATH=. .venv/bin/python -m engine.index.manifest verify   # stable_hash unchanged
PYTHONPATH=. .venv/bin/python -m engine.promotion.classify      # ledger sane
```

If any of those three diverges from the frozen state, treat as
critical.

---

## 2. Rollback protocol

If a critical bug surfaces in v1.0.0, we do NOT `git tag --force` or
rewrite history. We ship a remediation tag.

### 2a. Hotfix — small, surgical fix

1. Branch from the freeze commit:
   ```
   git checkout -b hotfix/v1.0.1 v1.0.0
   ```
2. Fix the bug with minimum surface area. Contract MUST stay 34/34.
3. Update:
   - `VERSION` (skill dir) + `VERSION` (repo root) → `1.0.1`.
   - `CHANGELOG.md`: add `[1.0.1]` block under `### Fixed` with CVE
     reference if security-related.
   - `stable_hash` cited in the new CHANGELOG block.
4. Open a PR against `main`; run full `GOLIVE.md §3` test pass.
5. Tag `v1.0.1` on the merge commit:
   ```
   git tag -s v1.0.1 -m "SKILL-001 v1.0.1: <one-line summary>"
   git push origin main v1.0.1
   ```
6. GitHub release: mark v1.0.1 as "Latest"; update v1.0.0 release notes
   with a "**Superseded by v1.0.1** (link)" banner.

### 2b. Yank — v1.0.0 is unusable, no fix ready

If a v1.0.0 consumer cannot run the skill at all (e.g. import-error
at boot), we yank publicly while fixing:

1. On the GitHub release page, mark v1.0.0 "pre-release" + add a
   "**Do not install**" banner with a link to the tracking issue.
2. Do NOT delete the tag — consumers may be pinned to it and silent
   deletion breaks their reproducibility worse than a warning banner.
3. While the fix is in flight, `install.sh` should refuse to install
   v1.0.0 (temporary patch to the installer that will itself ship as
   v1.0.1).
4. When the fix lands, publish v1.0.1 and remove the v1.0.0 banner.

### 2c. Emergency revert

If the freeze commit itself introduced the regression and rewriting
history isn't an option, revert-merge:

```
git checkout main
git revert --no-edit v1.0.0
# (this creates a revert commit on main that undoes the freeze)
# Tag this commit v1.0.1 with the revert message
```

Not preferred — leaves an ugly diff-vs-tag relationship — but
acceptable in emergencies.

---

## 3. Who decides "critical"?

Severity ladder (from `SECURITY.md`):

- **Critical** — any scaffold emits code with auth-bypass, SQL
  injection, shell-injection, secrets-leak.
- **High** — scaffold emits code with known-bad crypto defaults.
- **Medium** — generator bug affecting edge-case prompts.
- **Low** — docs / cosmetic.

Critical and High = hotfix the same or next business day. Gustavo
makes the final call; in emergencies the on-call engineer may cut the
tag and Gustavo reviews post-hoc.

---

## 4. Communications

- **External users on early-access list:** notify via email within 24h
  of any critical finding with a planned ETA.
- **Forge team:** notify if a skill regression affects Forge's skill
  loader contract (INTERFACES.md §3). Fix path may require
  coordinated Forge patch.
- **Maestro team:** notify if a tool name or schema changed in a
  hotfix (shouldn't — PATCH releases don't rename — but monitor).
- **Internal:** CHANGELOG.md + git tag message are the canonical
  announcement; everything else references them.

---

## 5. First-week follow-ups (beyond 72h)

- Day 5: summarise incident rate + benchmark stability in a brief
  email; archive under `/docs/releases/v1.0.0-day5.md`.
- Day 7: if no incidents, declare v1.0.0 "stable"; update
  `GOLIVE.md §6.4` check to ✅.
- Day 14: retro — what surprised us? Log lessons into a new ADR if
  the retro yields process changes.

---

## 6. Archive pre-v1.0 state

After v1.0.1 or day-14 "stable" signal, whichever later:

- Move `SESSION_STATE.md` + transient HANDOFF.md files into
  `/docs/releases/v1.0.0/archive/` so the root stays lean.
- Leave CHANGELOG + MIGRATION + FREEZE + GOLIVE + POST_RELEASE in
  root as permanent references.

This runbook is itself a living document; update it after each
release cycle with lessons from the last one.
