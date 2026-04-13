## Tool: `blast_radius`

### Overview parameters
- Tool name: `fastapi_blast_radius`
- Category: OPERATE
- Complexity: High
- Dependencies: existing FastAPI project, git, AST introspection
- Signature: `blast_radius(project_dir: str, target: str, diff_ref: str | None = None, depth: int = 3, include_tests: bool = True, output_format: str = "markdown") -> dict`
- Parameters:
  - `project_dir`: project root
  - `target`: file path, function name, or git diff range (e.g., `src/models.py::User`, `origin/main...HEAD`)
  - `diff_ref`: compare-against ref for diff mode
  - `depth`: transitive dependency depth
  - `include_tests`: include test files in the impacted set
  - `output_format`: `markdown`, `json`, or `dot` (for Graphviz)

### Purpose
Answer "if I change this function/model/route, what else will break?" by building a reverse-dependency graph of the codebase (callers, importers, tests that touch it, routes that depend on it) and walking it transitively up to `depth` levels. Essential for code review: reviewers can instantly see whether a one-line change is actually a one-line change or touches 40 files. Uses AST imports + call graph + FastAPI route introspection + optional DB foreign-key traversal for model changes.

### Performance SLOs
- Tool execution time < 5s for 50k LOC project
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 7 (graph builder, CLI wrapper, CI workflow, report templates, tests, docs, Makefile targets)
- Graph construction < 3s
- Query < 500 ms
- Incremental cache < 100 ms for subsequent queries

### Key technical decisions
1. **AST-based call graph:** `ast` module walks all `.py` files, indexes `Call`, `Import`, `ImportFrom`, `ClassDef`, `FunctionDef`
2. **Route awareness:** FastAPI `app.routes` parsed to link URL → handler → callees
3. **Test linkage:** tests importing a symbol are included as affected tests
4. **Model FK traversal:** SQLAlchemy FK detection for model changes
5. **Depth limit:** default 3 levels, configurable, prevents explosion in highly connected code
6. **Cache:** graph cached in `.blast_radius_cache.json` with mtime validation
7. **Report formats:** Markdown summary + JSON for programs + DOT for visualization
8. **Diff mode:** parses `git diff` to find changed symbols, walks reverse deps for each
9. **Classification:** "direct callers" (1 hop) vs "transitive" (2+ hops)
10. **Severity:** flags routes, migrations, and test-critical paths

### Key invariants
1. Graph is ALWAYS built from AST, never from grep heuristics.
2. Depth limit is ALWAYS enforced to prevent runaway traversal.
3. Cache is INVALIDATED when any source file mtime changes.
4. Test files are ALWAYS classified separately from production code.
5. Route mapping ALWAYS includes the full handler chain.
6. Cycles in the graph NEVER cause infinite loops (visited set).
7. Report is DETERMINISTIC (sorted by path) for reproducibility.

### User story themes
- 9.1 Direct impact (US-01..05): rename function, change signature, delete method, change model field
- 9.2 Transitive (US-06..10): 2-hop, 3-hop, depth-limited, test cascade
- 9.3 Diff mode (US-11..15): PR diff, stash, staged changes, specific commit
- 9.4 Reporting (US-16..20): Markdown summary, DOT graph, JSON for bots, PR comment
- 9.5 Edge cases (US-21..25): cycles, dynamic imports, duplicates, tool idempotency

### Test plan categories
- 10.1 Graph building (T-01..06): imports, calls, classes, routes, FK, cache
- 10.2 Traversal (T-07..12): 1-hop, n-hop, depth limit, cycles
- 10.3 Diff mode (T-13..18): git diff, stash, staged
- 10.4 Output (T-19..24): Markdown, JSON, DOT
- 10.5 Edge cases (T-25..30): dynamic imports, tool idempotency

### Edge cases (15)
1. Function not found → tool errors with fuzzy match suggestions
2. Dynamic import (`importlib.import_module`) → flagged as "likely caller" with low confidence
3. `getattr` reflection → not detected, warning at top of report
4. Cyclic imports → visited set prevents infinite loop
5. Same symbol name in multiple modules → disambiguation via full path
6. Empty diff → empty report, exit 0
7. Depth 0 → only the target itself returned
8. Depth 100 → still fast (visited set bounds work)
9. Project with no routes → route linkage skipped gracefully
10. File deleted in diff → reverse deps reported as "now-orphaned"
11. New file in diff → forward deps reported
12. Private helper (`_foo`) → included if imported
13. `__all__` export changed → all consumers flagged
14. Tool re-run idempotent
15. Graph cache stale → mtime check triggers rebuild

### Anti-patterns
- DO NOT rely on grep (misses dynamic dispatch, catches strings)
- DO NOT ignore tests (test coverage is part of impact)
- DO NOT traverse without depth limit (blows up on monolith)
- DO NOT forget to invalidate cache on file change
- DO NOT mix direct and transitive results (reviewer confusion)
