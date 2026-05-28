# Work Package Contract — `WP-<id>`

> **This is a binding contract, not a suggestion.** An agent executing a WP MUST
> satisfy every section below. A WP is *done* only when every acceptance gate is
> green and every Definition-of-Done box is checked, with proof pasted. Anything
> less is "in progress", never "done". Copy this file to `docs/wp/WP-<id>.md` and
> fill every `<…>`.

---

## 0. Identity
| Field | Value |
|---|---|
| **WP id** | `WP-<id>` |
| **Title** | `<one imperative line>` |
| **Wave** | `<0 \| 1 \| 2>` |
| **Depends on** | `<WP ids that must merge first, or "none">` |
| **Blocks** | `<WP ids that wait on this, or "none">` |
| **Branch** | `wp/<id>-<slug>` (off the post-dependency main) |
| **Isolation** | dedicated git worktree |
| **Model** | `<opus for security/cross-cutting · sonnet for mechanical>` |

## 1. Context bundle (the ONLY context the agent gets)
The agent must operate with exactly this set — nothing wider.
- **Owned files (exclusive write surface):**
  ```
  <exact paths this WP may create/modify — and NOTHING outside this set>
  ```
- **Golden reference (read-only, copy the pattern):** `<path to the already-migrated pilot tool>`
- **Shared base/contract to import (read-only):** `adapt/_base/` + `adapt/contracts/`
- **Spec to follow:** `docs/tool-contract.md`, `docs/architecture.md`

## 2. Forbidden surface (collision guard)
The agent MUST NOT create, modify, move, or delete anything outside §1 owned files.
Explicitly off-limits: `<files owned by sibling WPs>`, any shared registry/catalog,
`pyproject.toml`, CI config. If the task seems to require touching a forbidden file,
**stop and report** — do not edit it.

## 3. Transformation (exact before → after)
- **Goal:** `<what this WP changes, in one paragraph>`
- **Before:** `<current state, with file:line evidence>`
- **After:** `<target state — concrete, e.g. "templates externalized to templates/*.py.tmpl, __init__.py is orchestration only">`
- **Out of scope:** `<explicitly what NOT to change>`

## 4. Invariants (must hold — verified, not asserted)
- [ ] **Zero behavior change** unless explicitly specified in §3. Proven by gates, not by claim.
- [ ] **Import paths stable** — public module paths (`adapt.extend.<cat>.<tool>`) resolve identically before and after.
- [ ] **Templates externalized** — no emitted code lives in a Python string literal; it lives in `templates/*.py.tmpl`.
- [ ] **File size** — every logic `.py` ≤ 300 LOC (hard cap 500); template files exempt.
- [ ] **No dead code** — no unused helpers, no `get_multi_active`-style orphan functions, no commented-out blocks.
- [ ] **Docstrings honest** — a tool that does not enforce something MUST say so in its `warnings`, never imply success it didn't deliver.
- [ ] **No new dependencies** without an ADR.

## 5. Acceptance gates (deterministic — copy/paste, must be GREEN)
Run from the kit dir with the shared interpreter; paste each result in §7.
```bash
PY=.venv/bin/python ; export PYTHONPATH=. SECRET_KEY=ci-test-secret-key-must-be-32-chars-long!!! RATE_LIMITING_ENABLED=false ENVIRONMENT=local
# tier-0: this WP's own tests, parallel
$PY -m pytest <owned test paths> -q -p no:cacheprovider -n auto
# class gates — run ALL FOUR. None is optional. If one is structurally N/A for
# this WP, you must still run it (it must stay green) AND justify the N/A in §7.
$PY tests/property_tests.py            # 8/8 × N
$PY tests/test_p0_regression_gates.py  # GATE 1 + GATE 2 PASS
$PY tests/test_boot_chains.py          # 5/5 (run ALONE — contention-sensitive)
$PY -m engine.audit.contract_check     # 37/37
```
A WP that changes a contract-changing tool MUST also show the EMITTED project's
`pytest tests/` green after composing it (GATE 1 covers this class).

## 6. Quality bar (SOTA — non-negotiable)
- Match the surrounding code's idiom, naming, comment density. No drive-by reformatting outside owned files.
- Every new module has a module docstring stating its single responsibility.
- Commits are conventional (`fix(...)`, `refactor(...)`, `test(...)`), end with the `Co-Authored-By` trailer.
- No `print` debugging, no `TODO`/`FIXME` left behind, no skipped tests.
- If you discover a bug outside your scope, **report it** — do not fix it (that's another WP).

## 7. Proof of completion (paste real output — no summaries)
```
<paste the verbatim tail of every §5 gate, showing PASS/✓ counts>
```

## 8. Definition of Done (every box, or it's not done)
- [ ] All §5 acceptance gates green, output pasted in §7
- [ ] All §4 invariants verified
- [ ] §6 quality bar met
- [ ] Branch `wp/<id>-<slug>` pushed; PR opened with this contract linked
- [ ] No file outside §1 touched (`git diff --name-only` proves it)
- [ ] Self-review done: re-read your own diff as an adversarial reviewer

## 9. Anti-patterns (instant reject)
- Reporting "done" with a failing or unrun gate.
- "Fixing" a test by weakening its assertion to make it pass.
- Touching a forbidden file "just a little".
- Leaving emitted code as inline strings "for now".
- Claiming a tool enforces something it doesn't.
