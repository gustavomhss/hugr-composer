## Tool: `migration_diff`

### Overview parameters
- Tool name: `fastapi_migration_diff`
- Category: OPERATE
- Complexity: High
- Dependencies: existing FastAPI project, Alembic, SQLAlchemy
- Signature: `migration_diff(project_dir: str, base_ref: str = "origin/main", head_ref: str = "HEAD", fail_on_destructive: bool = True, fail_on_unsafe_default: bool = True, allow_list_file: str = ".migration-allow.yaml") -> dict`
- Parameters:
  - `project_dir`: project root
  - `base_ref` / `head_ref`: git refs to diff migrations between
  - `fail_on_destructive`: block DROP COLUMN/TABLE, TYPE CHANGE without cast, NOT NULL on existing column
  - `fail_on_unsafe_default`: block ADD COLUMN NOT NULL without DEFAULT on large tables
  - `allow_list_file`: explicit allow-list for acknowledged destructive ops with justification

### Purpose
Inspect Alembic migrations added in a PR and classify each operation as SAFE, UNSAFE, or DESTRUCTIVE. Computes the "rollback distance" (how many migrations would need to be reverted to undo a change), estimates lock duration for ALTER TABLE on large tables, and flags operations that require downtime or a multi-phase rollout (add column → backfill → set NOT NULL → drop old). Essential for zero-downtime deployments. Produces a Markdown report suitable for PR comment with a traffic-light classification per migration file.

### Performance SLOs
- Tool execution time < 3s for 100 migrations
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 7 (diff analyzer, safety rules, CI workflow, report template, tests, allow-list, docs)
- Rule evaluation < 100 ms per migration
- Report generation < 500 ms
- Zero production impact

### Key technical decisions
1. **AST parse of `upgrade()`/`downgrade()`** — extract each `op.*` call
2. **Rule engine:** classify by op type + args (DROP = destructive, ADD nullable = safe)
3. **Lock duration estimate:** heuristic based on table row count hint (Postgres ALTER TABLE locks)
4. **Multi-phase pattern detection:** `add_column(nullable=True) + server_default` is SAFE for zero-downtime
5. **Reversibility check:** `downgrade()` must be non-empty for destructive ops
6. **Rollback distance:** walk `down_revision` chain to count reversions needed
7. **Allow-list:** YAML file with migration hash + justification + expiry date
8. **Postgres-specific checks:** CONCURRENTLY required for INDEX on large tables
9. **Report format:** Markdown with ✅/⚠️/❌ per migration, JSON for bots
10. **CI integration:** blocks PR merge on destructive without allow-list entry

### Key invariants
1. Every destructive op is ALWAYS classified regardless of table size.
2. Allow-list entries ALWAYS require justification + expiry.
3. Rollback distance is ALWAYS computed from the revision graph, not assumed.
4. `downgrade()` is ALWAYS parsed; empty downgrade on destructive op is a blocker.
5. Multi-phase patterns (add+default) are DETECTED automatically.
6. Report is DETERMINISTIC (same diff → same output).
7. CI gate NEVER bypassed without explicit allow-list hash match.

### User story themes
- 9.1 Destructive detection (US-01..05): DROP COLUMN, DROP TABLE, TYPE CHANGE, NOT NULL, allow-list
- 9.2 Safe changes (US-06..10): ADD COLUMN nullable, CREATE INDEX CONCURRENTLY, RENAME, CREATE TABLE
- 9.3 Multi-phase (US-11..15): detect 2-phase pattern, detect 3-phase, warn on incomplete
- 9.4 CI integration (US-16..20): PR comment, block on destructive, allow-list hash
- 9.5 Edge cases (US-21..25): empty diff, revision graph hole, tool idempotency

### Test plan categories
- 10.1 Classification (T-01..06): destructive, unsafe, safe, multi-phase
- 10.2 Rollback distance (T-07..12): 1, 5, 20 revisions, hole, branch
- 10.3 Allow-list (T-13..18): valid, expired, wrong hash, bypass attempt
- 10.4 Reporting (T-19..24): Markdown, JSON, PR comment
- 10.5 Edge cases (T-25..30): tool idempotency, no migrations, multiple branches

### Edge cases (15)
1. Migration with no ops → SAFE, passes
2. DROP COLUMN on tiny table → still DESTRUCTIVE (size irrelevant)
3. RENAME COLUMN → always UNSAFE (consumers break)
4. CREATE INDEX without CONCURRENTLY → UNSAFE for large tables
5. ADD COLUMN NOT NULL without default → UNSAFE (fails on existing rows)
6. ADD COLUMN NOT NULL with server_default → SAFE (Postgres 11+)
7. Empty `downgrade()` on destructive → blocker, even with allow-list
8. Migration chain hole (missing down_revision) → error with clear message
9. Multiple heads → multi-branch diff supported
10. Auto-generated migration with bad type inference → flagged for manual review
11. Data migration mixed with schema → flagged as "data in schema migration"
12. Allow-list entry expired → blocks, suggests renewal
13. Allow-list hash mismatch → blocks (file changed, re-approval needed)
14. Tool re-run idempotent
15. Postgres ENUM TYPE modification → flagged as unsafe (blocking)

### Anti-patterns
- DO NOT rely on table size for classification (DROP is always destructive)
- DO NOT skip downgrade parsing (irreversible migrations are traps)
- DO NOT allow bypass without justification + expiry
- DO NOT assume ALTER TABLE is cheap (Postgres locks)
- DO NOT mix data and schema migrations silently
