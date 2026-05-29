# Repo Standard

The simple, enforced rules that keep HuGR Arsenal organized, hygienic, and
trustworthy. Small on purpose — every rule has teeth (a check) and a reason.

## 1. Structure
```
/                 root: configs only (pyproject, .pre-commit, .gitignore, Makefile, README)
/docs/            ALL narrative docs: architecture, contributing, adr/, guides/, wp/
/skills/…/        the kit (code); each package has at most one thin README.md
/hugr_auth/       the gate (license + MCP)
/deploy/          Dockerfiles + compose
/scripts/         verify.sh + checks/
/_staging/        relocated extraction graveyard (outside the import path)
```
**Rule:** no narrative markdown outside `docs/` — only `README.md` (a pointer) inside code packages. *(enforced: `scripts/checks/md_location.py`)*

## 2. Hygiene
- Never track virtualenvs, `site-packages`, emitted projects, `*.db`, `__pycache__`. *(enforced: `scripts/checks/no_committed_venv.py` + `.gitignore`)*
- No blobs > 500 KB. *(enforced: `check-added-large-files`)*
- No secrets / private keys. *(enforced: `detect-private-key`)*

## 3. Code size
- Logic `.py`: sweet spot ≤ 300 LOC, **hard cap 500**. No per-function cap.
- Emitted-code templates (`templates/*.py.tmpl`) are data — exempt.
- Over the cap usually means embedded templates → externalize them. *(enforced: `scripts/checks/file_size.py`)*

## 4. Tests & "done"
- **Composition gates are the must-run**, not the full unit suite — this kit's bugs live in tool *composition*. Use `scripts/verify.sh` (tiered: tier-0 touched tools / tier-1 composition / tier-2 full).
- A change is *done* only when its tier gates are green (`make verify`).
- Unit suite runs parallel: `pytest -n auto` (~4 min, not 15).
- Two permanent regression gates (`tests/test_p0_regression_gates.py`): composition keeps the emitted suite green; no raw-SQL interpolation in emitted code.

## 5. Tools (the compose plugins)
- One contract: `discover() → plan() → write() → patch() → verify()` over `ToolInput`/`ToolResult` (`docs/tool-contract.md`).
- A tool that does not enforce something MUST say so in `warnings` — never imply success it didn't deliver.
- Emitted code lives in `templates/`, never in Python string literals.

## 6. Git & review
- Conventional commits (`fix(...)`, `refactor(...)`, `test(...)`, `docs(...)`, `chore(...)`); commit messages end with the `Co-Authored-By` trailer.
- Branch names: `wp/<id>-<slug>`, `fix/<slug>`, `chore/<slug>`.
- PRs use the template (What/Why/How/Testing + Definition of Done). CODEOWNERS review required.
- Squash-merge; the PR title becomes the main commit (so it must be conventional).

## 7. Decisions & documentation
- Significant architectural choices → an ADR in `docs/adr/NNNN-title.md` (template: `0000-template.md`).
- Work is parceled as Work Package contracts in `docs/wp/` (template: `WP-CONTRACT-TEMPLATE.md`).
- Docs live with the code in `docs/`, never scattered as `AGENT_SESSION.md` / `brief.md` / `KNOWLEDGE.md` in the tree.

## How it's enforced
| Layer | Tool |
|---|---|
| Local, every commit | `.pre-commit-config.yaml` (ruff + standard hooks + the 3 local checks) |
| Local, pre-merge | `scripts/verify.sh` (tiered composition gates) |
| CI | lint → verify → regression gates → `contract_check` |
| Review | CODEOWNERS + PR template DoD + branch protection |

Install locally once: `pre-commit install`.
