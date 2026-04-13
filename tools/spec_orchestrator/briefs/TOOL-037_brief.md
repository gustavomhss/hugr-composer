## Tool: `dead_code_finder`

### Overview parameters
- Tool name: `fastapi_dead_code_finder`
- Category: OPERATE
- Complexity: Medium
- Dependencies: existing FastAPI project, vulture or custom AST walker
- Signature: `dead_code_finder(project_dir: str, confidence_threshold: int = 80, include_routes: bool = True, exclude_patterns: list[str] | None = None, allow_list_file: str = ".deadcode-allow.yaml") -> dict`
- Parameters:
  - `project_dir`: project root
  - `confidence_threshold`: minimum confidence percentage (0-100) to report (vulture convention)
  - `include_routes`: also flag unreachable/orphan FastAPI routes
  - `exclude_patterns`: glob patterns to skip (e.g., `migrations/*`, `tests/fixtures/*`)
  - `allow_list_file`: YAML with intentional dead code (plugin hooks, public API) + justification

### Purpose
Find unused functions, classes, variables, imports, and routes in the codebase. Goes beyond plain vulture by understanding FastAPI: a function referenced only via `@app.get` is not dead, a model referenced only via Alembic is not dead, a schema used in `response_model=` is not dead. Generates a report ranked by confidence (so maintainers tackle the obvious wins first) and integrates with CI to prevent new dead code from accumulating. Supports an allow-list for intentional dead code (plugin entry points, public API surface).

### Performance SLOs
- Tool execution time < 4s for 50k LOC
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 7 (scanner, FastAPI plugin, CI workflow, report template, tests, allow-list, docs)
- AST walk < 2s
- Confidence scoring < 500 ms
- Report < 200 ms

### Key technical decisions
1. **Vulture core + FastAPI extensions:** reuse vulture's AST walker, add route/model/schema detection
2. **Confidence scoring:** 100 for unreachable-after-return, 90 for unused import, 60 for unused private function
3. **FastAPI awareness:** decorators `@app.*`, `Depends()`, `response_model=` all count as "used"
4. **SQLAlchemy awareness:** models referenced in `relationship()` or ForeignKey string count as used
5. **Pydantic awareness:** schemas referenced in type hints count as used
6. **Dynamic dispatch:** `getattr`/`setattr`/`globals()` flagged with low confidence
7. **Allow-list:** YAML with fully-qualified names + justification
8. **CI integration:** blocks PR that introduces new dead code (delta > 0)
9. **Incremental mode:** `--changed-only` analyzes only files in git diff
10. **Report:** Markdown + JSON + per-file count

### Key invariants
1. Confidence threshold is ALWAYS respected (low-confidence never forced to fail).
2. FastAPI/SQLAlchemy/Pydantic references ALWAYS count as usage.
3. Allow-list requires justification for EVERY entry.
4. Imports are ALWAYS analyzed separately from function calls.
5. Dynamic dispatch findings are ALWAYS marked low confidence.
6. Report is DETERMINISTIC (sorted by confidence desc, path asc).
7. `__init__.py` re-exports ALWAYS count as usage.

### User story themes
- 9.1 Basic detection (US-01..05): unused import, function, class, variable, confidence
- 9.2 FastAPI awareness (US-06..10): route kept, Depends kept, response_model kept, model kept, schema kept
- 9.3 Allow-list (US-11..15): plugin hook allowed, public API allowed, expired, bypass attempt
- 9.4 CI integration (US-16..20): PR comment, block on new dead code, delta report, artifact
- 9.5 Edge cases (US-21..25): dynamic dispatch, __all__, tool idempotency, cycles

### Test plan categories
- 10.1 Core detection (T-01..06): import, function, class, variable, threshold
- 10.2 FastAPI (T-07..12): route, Depends, response_model, SQLAlchemy relationship
- 10.3 Allow-list (T-13..18): valid, expired, hash mismatch
- 10.4 CI (T-19..24): delta, block, annotations
- 10.5 Edge cases (T-25..30): dynamic dispatch, idempotency

### Edge cases (15)
1. Function referenced only via `getattr` → low confidence (60)
2. Class used as type hint only → counted as used
3. Variable assigned but never read → flagged
4. Function decorator with auto-registration → needs plugin or allow-list
5. SQLAlchemy event listener → auto-detected via `@event.listens_for`
6. Pytest fixture → detected via decorator, not flagged
7. CLI entry point → detected via `pyproject.toml` scripts
8. Deprecated public API → allow-list with expiry
9. `__all__` export → counted even if not referenced in file
10. Cyclic usage (A calls B calls A, neither called externally) → flagged with cycle notation
11. Re-exported in `__init__.py` → counted as used
12. Tool re-run idempotent
13. New dead code in PR → fails gate
14. Same amount of dead code pre/post PR → passes (no regression)
15. All files excluded → warning, no findings

### Anti-patterns
- DO NOT ignore FastAPI/ORM framework usage (false positives)
- DO NOT fail on low-confidence findings (noise kills trust)
- DO NOT require re-approval of allow-list on every run (high friction)
- DO NOT conflate unused imports with unused functions (different remedies)
- DO NOT skip `__init__.py` re-exports
