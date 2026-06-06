## Tool: `dependency_graph`

### Overview parameters
- Tool name: `fastapi_dependency_graph`
- Category: OPERATE
- Complexity: Medium
- Dependencies: existing FastAPI project, AST parser, optional Graphviz
- Signature: `dependency_graph(project_dir: str, output_format: str = "svg", layer_rules_file: str = ".deps-layers.yaml", detect_cycles: bool = True, fail_on_violation: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root
  - `output_format`: `svg`, `png`, `dot`, or `json`
  - `layer_rules_file`: YAML defining layers and allowed cross-layer edges
  - `detect_cycles`: fail if import cycles exist
  - `fail_on_violation`: fail if layer boundaries crossed in the wrong direction

### Purpose
Generate a visual and machine-readable dependency graph of the project's internal modules. Goes beyond "pydeps" by supporting **architectural layering** (routes → services → repos → models) and failing the build when a lower layer imports from a higher layer (the canonical sin of rotted architectures). Detects circular imports, module clusters, and dead branches of the graph. Outputs SVG for humans, DOT for Graphviz customization, and JSON for programmatic consumption. Essential for maintaining a clean layered architecture over time.

### Performance SLOs
- Tool execution time < 3s for 1000 modules
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 7 (graph builder, layer rules, CI workflow, report templates, tests, docs, Makefile targets)
- Graph build < 2s
- Cycle detection < 500 ms
- Layer check < 200 ms

### Key technical decisions
1. **AST import walker:** parses all `.py` files, extracts `import`/`from ... import`
2. **Module-level granularity:** aggregates imports to module, not symbol
3. **Layer rules (YAML):**
   ```yaml
   layers:
     - name: routes
       path: "src/routes/**"
     - name: services
       path: "src/services/**"
   allowed:
     - from: routes
       to: [services]
     - from: services
       to: [repos, models]
   ```
4. **Cycle detection:** Tarjan's SCC algorithm
5. **Violation classification:** layer-cross (wrong direction), cycle (SCC > 1), orphan (no inbound)
6. **Visualization:** SVG via Graphviz `dot` command, DOT for manual styling
7. **JSON schema:** nodes (modules), edges (imports), metadata (layer, loc, fan-in/out)
8. **CI integration:** blocks PR that introduces new cycle or layer violation
9. **Incremental mode:** `--since=HEAD~1` only shows new edges
10. **Report:** Markdown summary + inline SVG + violation list

### Key invariants
1. Layer rules are ALWAYS enforced — no silent exceptions.
2. Cycle detection is ALWAYS O(V+E) via Tarjan (not naive DFS).
3. Layer violation direction is ALWAYS "lower → higher" = forbidden.
4. Orphan modules are ALWAYS flagged, but optional to fail.
5. Re-running produces IDENTICAL graph (deterministic sort).
6. External libraries NEVER included in the internal graph.
7. `__init__.py` re-exports ALWAYS traced to final symbol.

### User story themes
- 9.1 Basic graph (US-01..05): build, render SVG, JSON output, DOT output, empty project
- 9.2 Layer rules (US-06..10): config loaded, violation detected, allowed path, multi-hop, fail
- 9.3 Cycle detection (US-11..15): simple 2-cycle, 3-cycle, self-loop, SCC, pass when clean
- 9.4 CI integration (US-16..20): PR comment, block on new violation, delta report
- 9.5 Edge cases (US-21..25): external imports, __init__ chains, tool idempotency, rename

### Test plan categories
- 10.1 Graph building (T-01..06): imports, package, submodules, __init__, external
- 10.2 Layer rules (T-07..12): allowed, violation, multi-hop, glob, no-match
- 10.3 Cycles (T-13..18): 2-cycle, 3-cycle, self, SCC, Tarjan correctness
- 10.4 Output (T-19..24): SVG, DOT, JSON, Markdown
- 10.5 Edge cases (T-25..30): empty, large graph, tool idempotency

### Edge cases (15)
1. Empty project → empty graph, passes
2. Single module → node with no edges
3. 2-cycle (A↔B) → detected via SCC
4. 3-cycle (A→B→C→A) → detected via SCC
5. Self-loop (`import module from module`) → flagged
6. External library (`import requests`) → excluded from internal graph
7. Star import (`from x import *`) → traced to actual symbols via `__all__`
8. Dynamic import (`importlib.import_module`) → flagged with low confidence
9. `__init__.py` re-export → traced to final module
10. Circular via type hint only (`TYPE_CHECKING`) → not counted as runtime cycle
11. 1000+ modules → still < 3s
12. Glob pattern no match → warning
13. Rename detection (Git) → preserved in graph
14. Tool re-run idempotent
15. Multi-package monorepo → cross-package edges tracked

### Anti-patterns
- DO NOT include external libraries (noise)
- DO NOT use naive DFS for cycle detection (exponential)
- DO NOT silently allow layer violations
- DO NOT generate graphs without layer semantics (just a blob)
- DO NOT forget `TYPE_CHECKING` exclusion (false cycles)
