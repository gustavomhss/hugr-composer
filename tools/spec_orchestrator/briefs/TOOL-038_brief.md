## Tool: `api_changelog`

### Overview parameters
- Tool name: `fastapi_api_changelog`
- Category: OPERATE
- Complexity: Medium
- Dependencies: existing FastAPI project, git, committed OpenAPI snapshot
- Signature: `api_changelog(project_dir: str, from_ref: str = "v1.0.0", to_ref: str = "HEAD", output_file: str = "CHANGELOG.md", format: str = "keepachangelog", include_breaking_prefix: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root
  - `from_ref` / `to_ref`: git refs to diff OpenAPI snapshots between (tag, commit, branch)
  - `output_file`: changelog path to write (markdown)
  - `format`: `keepachangelog`, `semver`, or `plain`
  - `include_breaking_prefix`: prefix BREAKING: entries (Conventional Commits style)

### Purpose
Generate a human-readable changelog from OpenAPI diffs between two refs. Extracts added/removed/changed endpoints, classifies each change (breaking/non-breaking/metadata), groups them by tag (Users, Orders, etc.), writes a `CHANGELOG.md` entry in Keep a Changelog format, and suggests the next semver version (major if any breaking, minor if any added, patch for metadata-only). Eliminates the "we forgot to document this endpoint change" failure mode. Integrated into release pipelines to auto-populate release notes.

### Performance SLOs
- Tool execution time < 3s (schema gen + diff + render for 200 routes)
- Files modified ≤ 2 (CHANGELOG.md, pyproject.toml)
- Files created ≥ 6 (diff renderer, CI workflow, template, tests, docs, Makefile targets)
- Diff computation < 500 ms
- Rendering < 300 ms
- Zero runtime impact

### Key technical decisions
1. **Snapshot retrieval:** `git show <ref>:openapi.json` for each ref
2. **Diff algorithm:** same core as `api_spec_compliance` tool — structural comparison
3. **Grouping:** by `tag` (Users, Orders) for readability; fallback to path prefix
4. **Classification:** BREAKING, ADDED, CHANGED, REMOVED, DEPRECATED, METADATA
5. **Semver inference:** any BREAKING → major, else any ADDED/CHANGED → minor, else patch
6. **Keep-a-Changelog format:** `### Added`, `### Changed`, `### Removed`, `### BREAKING`
7. **Idempotency:** re-running for same ref range produces identical output
8. **Release note mode:** `--for-release` writes only the new section, to be prepended
9. **PR mode:** `--unreleased` accumulates changes under `## Unreleased` heading
10. **Emoji tagging:** optional `🔴` for breaking, `🟢` for additions (configurable)

### Key invariants
1. Snapshot retrieval is ALWAYS done via `git show`, never from filesystem HEAD.
2. Semver inference ALWAYS prioritizes breaking changes.
3. Grouping is DETERMINISTIC (tags sorted alphabetically).
4. Changelog format is VALID Keep a Changelog (parseable by tools).
5. Re-running with same refs produces IDENTICAL output (idempotent).
6. Unreleased section is NEVER duplicated.
7. Breaking changes ALWAYS appear first in their group.

### User story themes
- 9.1 Basic diff (US-01..05): added route, removed route, changed response, param added, first changelog
- 9.2 Classification (US-06..10): BREAKING detected, ADDED detected, metadata-only, deprecated path
- 9.3 Semver inference (US-11..15): major on breaking, minor on added, patch on metadata, override
- 9.4 Output formats (US-16..20): Keep a Changelog, plain, semver, release mode, unreleased mode
- 9.5 Edge cases (US-21..25): empty diff, tag without routes, idempotency, git ref not found

### Test plan categories
- 10.1 Diff (T-01..06): added, removed, changed, param added, param removed, type change
- 10.2 Classification (T-07..12): breaking, non-breaking, metadata, semver
- 10.3 Grouping (T-13..18): by tag, by prefix, sorted, ties
- 10.4 Output (T-19..24): Keep a Changelog, plain, semver, release mode
- 10.5 Edge cases (T-25..30): idempotency, missing ref, empty snapshot

### Edge cases (15)
1. Empty diff → entry with "No API changes"
2. `from_ref` is ancestor of `to_ref` → normal flow
3. `from_ref` not found → clear error
4. Snapshot missing in one ref → error with `api_spec_compliance` hint
5. New tag added → grouped under its own section
6. Tag removed (no routes left) → section appears with removal note
7. Route moved to different tag → classified as metadata change
8. Path param renamed → BREAKING
9. Unreleased section already present → merged, not duplicated
10. Operation ID change → ignored (noise)
11. Server URL change → ignored
12. Tool re-run idempotent
13. Multi-version support (v1, v2 paths) → grouped separately
14. Emoji mode → correctly prefixes each entry
15. Output to stdout (no file) → writes to stdout with exit 0

### Anti-patterns
- DO NOT edit the changelog by hand for auto-generated sections
- DO NOT drop breaking changes under a generic "Changed" header
- DO NOT guess semver — compute from diff
- DO NOT skip grouping (unreadable for large APIs)
- DO NOT forget idempotency (re-runs must be safe)
