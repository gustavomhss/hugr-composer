# Tool Contract

Every compose tool is a plugin against this contract. Uniformity is what makes 99 tools
maintainable and composition safe.

> **Status: TARGET STATE.** The per-tool directory layout (`<tool>/__init__.py` +
> `templates/`) and the shared `adapt/_base/` phases are the destination of the refactor
> (Work Packages in [`wp/`](wp/)). Current tools are flat modules with inline emitted
> code; the honesty rules and invariants below already apply.

## Signature
```python
def add_<tool>(inp: ToolInput) -> ToolResult: ...
```
- `ToolInput`: `project_dir`, `dry_run`, … (see `adapt/contracts`).
- `ToolResult`: `status` (`success`|`no_op`|`error`), `files_created`, `files_modified`,
  `notes`, `next_steps`, `warnings`, `execution_time_ms`.

## Phases (run in order, via `adapt/_base/`)
1. **`discover()`** — find the target domain models/routes via the shared AST discovery
   in `adapt/_base/discover.py`. Never reimplement discovery per tool. Honor the infra
   skip-set (`base`, `user`, `mixins`, `__init__`, `tenant`, …).
2. **`plan()`** — compute what will be written/patched. In `dry_run`, stop here and report.
3. **`write()`** — render emitted code from `templates/*.py.tmpl` (never inline strings)
   and copy primitives/adapters.
4. **`patch()`** — AST-patch existing files via `adapt/_base/patch.py`. Ensure imports for
   anything emitted (the missing-`CurrentUser` class of bug).
5. **`verify()`** — syntax-check every written file; **emit tests** asserting the behavior
   added; leave the emitted project's `pytest tests/` green.

## Honesty rules (non-negotiable)
- A tool that does not enforce something MUST lead its `warnings` with an unmistakable
  `⚠ … IS NOT ENFORCED` notice. Never imply a guarantee not delivered.
- `notes` must describe what the emitted code *actually does*, verifiable by reading it.
  No claim that is only true on one code path (e.g. "delete() overridden" when only a
  module re-export is patched and the CRUDBase instance is not).
- No dead/orphan code: every primitive/module shipped must be wired and reachable.

## Invariants
- Idempotent: a second run returns `no_op` without touching files.
- Import paths stable; emitted code parses; no behavior change outside the tool's scope.
- Composition-safe: composing this tool keeps the emitted suite green (GATE 1) and the
  added behavior is covered by emitted tests.
