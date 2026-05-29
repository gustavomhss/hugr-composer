# Contributing

> **Canonical contributor guide:** [`/CONTRIBUTING.md`](../CONTRIBUTING.md) at the
> repo root. This file is a pointer kept here so links from `docs/` and from
> `engine.docs.build` (which renders this page under `/contributing/`) keep
> resolving.

## Why root, not `docs/`?

- GitHub auto-surfaces root `CONTRIBUTING.md` in the PR template, the issue
  template, and the new-contributor banner. Moving it under `docs/` breaks
  every one of those automatic links and degrades the first-time contributor
  experience that `CONTRIBUTING.md` §0 specifically targets ("time-to-first-PR
  < 1 hour").
- The audit rule `B4.5` in `engine.audit.contract_check` (line ~2449) reads
  root `CONTRIBUTING.md` and asserts it covers the primitive + tool + recipe +
  dev-setup surfaces. The docs-site builder (`engine.docs.build`, line ~50)
  renders root `CONTRIBUTING.md` as the `/contributing/` page. Both treat root
  as canonical; keeping them aligned is the F-007 closure decision.
- `docs/repo-standard.md` §1 was updated alongside this file to explicitly
  exempt root convention docs (CONTRIBUTING / CHANGELOG / LICENSE / SECURITY /
  governance) from "narrative docs live in `docs/`" — those files have a
  GitHub-surface or repo-root convention reason to live at the top.

## Where to go

| You want | Read |
|---|---|
| Land a primitive / tool / recipe (the full guide) | [`/CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Enforced repo hygiene rules | [`./repo-standard.md`](./repo-standard.md) |
| Architecture overview | [`./architecture.md`](./architecture.md) |
| Tool contract (discover/plan/write/patch/verify) | [`./tool-contract.md`](./tool-contract.md) |
