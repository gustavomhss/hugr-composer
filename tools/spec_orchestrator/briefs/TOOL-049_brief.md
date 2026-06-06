## Tool: `generate_docs`

### Overview parameters
- Tool name: `fastapi_generate_docs`
- Category: EVOLVE
- Complexity: Medium
- Dependencies: existing FastAPI project, MkDocs Material, mkdocstrings, OpenAPI
- Signature: `generate_docs(project_dir: str, output_dir: str = "docs/generated", include_sections: list[str] | None = None, deploy_target: str = "none", theme: str = "material") -> dict`
- Parameters:
  - `project_dir`: project root
  - `output_dir`: where generated docs are written
  - `include_sections`: subset of `["api","models","schemas","deployment","architecture"]`; default all
  - `deploy_target`: `none`, `github_pages`, `s3`, `netlify`
  - `theme`: MkDocs theme (`material`, `readthedocs`, custom)

### Purpose
Auto-generate comprehensive project documentation from code + metadata. Sections: API reference (OpenAPI rendered via Redoc), model schemas (Pydantic docs via mkdocstrings), architecture diagrams (Mermaid from module imports), deployment guide (parsed from Dockerfile + docker-compose), and a "getting started" tutorial (scaffolded). Writes a MkDocs project with navigation, search, and versioning. Optionally publishes to GitHub Pages. Keeps documentation in sync with code — regenerated on every release. Eliminates the "docs are always wrong" problem.

### Performance SLOs
- Tool execution time < 15s (full generation for 100 routes)
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 12 (mkdocs.yml, section pages, plugins config, navigation, theme overrides, CI workflow, tests, publish script, docs, Makefile targets, index, README)
- Build time (mkdocs build) < 20s
- Redoc render < 3s
- Mermaid diagram gen < 2s

### Key technical decisions
1. **MkDocs Material:** primary, mature, themeable
2. **mkdocstrings:** auto-extract docstrings for Python modules
3. **Redoc integration:** embedded via iframe or plugin
4. **Mermaid diagrams:** generated from dependency graph tool
5. **Versioning:** `mike` plugin for multi-version docs
6. **Navigation:** auto-generated from section tree + YAML override
7. **Search:** built-in Lunr search with pre-built index
8. **Deploy targets:** GitHub Actions publishing to `gh-pages` branch
9. **Incremental build:** only regenerate changed sections
10. **Diagram validation:** Mermaid syntax checked before publish

### Key invariants
1. Documentation is ALWAYS generated from source, never hand-edited in the output dir.
2. API reference is ALWAYS regenerated on schema change.
3. Versioning is ALWAYS aligned with Git tags.
4. Publishing NEVER happens without explicit flag.
5. Navigation is DETERMINISTIC (sorted by section order).
6. Build failures BLOCK the publish step.
7. Dead links are ALWAYS detected via `mkdocs build --strict`.

### User story themes
- 9.1 Basic docs (US-01..05): API ref, models, schemas, deployment, architecture
- 9.2 Build (US-06..10): clean, incremental, strict mode, dead links, local preview
- 9.3 Versioning (US-11..15): tag-aligned, multi-version nav, switcher, default
- 9.4 Publishing (US-16..20): GitHub Pages, S3, Netlify, dry-run, rollback
- 9.5 Edge cases (US-21..25): missing section, tool idempotency, broken diagram

### Test plan categories
- 10.1 Generation (T-01..06): sections, nav, search, theme, strict
- 10.2 Content (T-07..12): API ref, models, diagrams, tutorial
- 10.3 Versioning (T-13..18): mike setup, tag, switcher, multi-version
- 10.4 Publishing (T-19..24): GH pages, S3, dry-run
- 10.5 Edge cases (T-25..30): missing section, tool idempotency, strict mode

### Edge cases (15)
1. Module without docstring → warning in build log
2. Broken Mermaid syntax → build fails with clear error
3. Section excluded → navigation adjusted automatically
4. Git tag without corresponding version → skipped with warning
5. `mike` plugin not installed → feature disabled gracefully
6. MkDocs strict mode off → warnings surface as normal
7. MkDocs strict mode on → any warning = build failure
8. Very large OpenAPI schema → paginated rendering
9. Deploy target `none` → no publish step
10. Tool re-run idempotent
11. Theme override → CSS applied
12. Schema changed mid-build → rebuild triggered
13. Language setting (pt-br, en-us) → i18n supported
14. Dead link to `/api/orders` route not in schema → build fails
15. Non-ASCII characters in docstrings → rendered correctly

### Anti-patterns
- DO NOT hand-edit the output dir (gets overwritten)
- DO NOT skip strict mode in CI (dead links accumulate)
- DO NOT publish without dry-run first
- DO NOT forget versioning (users need it)
- DO NOT hardcode the deploy target (configurable)
