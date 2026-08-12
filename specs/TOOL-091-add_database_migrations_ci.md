---
spec_id: "TOOL-091"
tool_name: "add_database_migrations_ci"
generator: "generators/database/alembic_migration.py"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-MCI-01"
  - "INV-MCI-02"
  - "INV-MCI-03"
  - "INV-MCI-04"
  - "INV-MCI-05"
  - "INV-MCI-06"
  - "INV-MCI-07"
  - "INV-MCI-08"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-091: add_database_migrations_ci

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_database_migrations_ci` |
| Category | EXTEND > Testing Tools |
| Complexity | Medium |
| Dependencies | alembic (already required), stdlib `subprocess` — no new packages |
| Signature | `add_database_migrations_ci(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_database_migrations_ci", "description": "Add Alembic CI runner with rollback safety and schema diff to FastAPI.", "tags": ["extend", "testing_tools"], "entry": "add_database_migrations_ci"}` |
| Files created (typical) | 4 — `app/migrations/__init__.py`, `app/migrations/ci_runner.py`, `app/migrations/safety_checker.py`, `scripts/check_migrations.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_database_migrations_ci` tool adds Alembic CI tooling that catches three classes of migration problems before they reach production: (1) pending migrations (developer forgot to run `alembic upgrade head`), (2) unsafe rollback (the downgrade path is broken, preventing emergency rollbacks), and (3) destructive operations (DROP TABLE/COLUMN that will cause data loss without a human review gate).

Teams commonly discover pending migrations in production when a feature that depends on a new column silently fails, or discovers a broken downgrade path during a hotfix rollback at 2 am. The `MigrationCIRunner` wraps alembic CLI invocations with proper subprocess management (timeout=60s, `capture_output=True`, `FileNotFoundError` handled for environments where alembic is not installed). `SafetyChecker` scans migration files with regex patterns for `op.drop_table`, `op.drop_column`, `op.drop_constraint`, `op.drop_index`, and `TRUNCATE`, producing a structured findings report that CI can fail on.

The `scripts/check_migrations.py` CLI integrates directly with GitHub Actions, GitLab CI, and Makefile targets via `--pending`, `--rollback`, `--diff`, and `--safety` flags. Running all checks is the default when no flag is provided. Exit codes follow POSIX conventions (0 = pass, 1 = fail) so CI pipelines fail correctly.

No new pip dependencies are required — alembic is already a dependency of any FastAPI project with migrations.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI step budget |
| Files created | ≥ 4 | migrations init, ci_runner, safety_checker, check script |
| Files modified | ≥ 1 | `config.py` at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable functions |
| `alembic current` subprocess timeout | 60 s | Bounded; returns error dict on timeout |
| Safety checker scan | < 1 s for 100 migration files | Regex scan, no subprocess |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── alembic/
│   └── versions/
│       └── 0001_initial.py
├── app/
│   └── core/
│       └── config.py        # No MIGRATION_CI_* fields
└── requirements.txt         # alembic present
```

CI runs no migration checks. A PR can introduce a pending migration, a broken downgrade, or a DROP TABLE that no reviewer noticed.

### 4.2 MigrationCIRunner: AFTER

```python
# app/migrations/ci_runner.py
class MigrationCIRunner:
    """Alembic CI runner for migration checks in CI pipelines."""

    def check_pending(self) -> dict[str, Any]:
        """Check for unapplied migrations (alembic current vs heads)."""
        current = self._run_alembic(["current"])
        heads = self._run_alembic(["heads"])
        # Returns: pending_count, current, heads, is_up_to_date

    def verify_rollback(self) -> dict[str, Any]:
        """Dry-run downgrade -1 to verify rollback is safe."""
        result = self._run_alembic(["downgrade", "-1", "--sql"])
        # Returns: rollback_safe, sql, error

    def schema_diff(self) -> dict[str, Any]:
        """alembic check — detect schema drift between models and DB."""
        result = self._run_alembic(["check"])
        # Returns: in_sync, output, error
```

### 4.3 SafetyChecker: AFTER

```python
# app/migrations/safety_checker.py
_DESTRUCTIVE_PATTERNS = [
    ("DROP TABLE", re.compile(r"drop_table|op\.drop_table", re.IGNORECASE)),
    ("DROP COLUMN", re.compile(r"drop_column|op\.drop_column", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"truncate|op\.execute.*TRUNCATE", re.IGNORECASE)),
    ("DROP CONSTRAINT", re.compile(r"drop_constraint|op\.drop_constraint", re.IGNORECASE)),
    ("DROP INDEX", re.compile(r"drop_index|op\.drop_index", re.IGNORECASE)),
]

class SafetyChecker:
    def detect_destructive(self) -> dict[str, Any]:
        """Scan all migration files for destructive operations."""
        # Returns: destructive_found, findings, files_scanned
```

### 4.4 CLI script: AFTER

```bash
# CI pipeline usage
python scripts/check_migrations.py --pending   # exit 1 if unapplied migrations
python scripts/check_migrations.py --rollback  # exit 1 if downgrade breaks
python scripts/check_migrations.py --diff      # exit 1 if schema drifts
python scripts/check_migrations.py --safety    # exit 1 if DROP TABLE/COLUMN found
python scripts/check_migrations.py            # all checks (default)
```

### 4.5 Config patch: AFTER

```python
# app/core/config.py  (diff, 4-space indented inside class Settings)
    # --- Migration CI (added by add_database_migrations_ci tool) ---
    MIGRATION_CI_FAIL_ON_DESTRUCTIVE: bool = True
    MIGRATION_CI_REQUIRE_ROLLBACK: bool = True
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"MigrationCIRunner" in ci_runner_file.read_text()` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` loop over `files_created` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk asserts |
| QS-5 | **No new pip dependencies** | alembic already required; no new packages added to `requirements.txt` |
| QS-6 | **subprocess calls are bounded** | `timeout=60` in `_run_alembic`; `FileNotFoundError` and `TimeoutExpired` handled |
| QS-7 | **Safety checker scans versioned migrations only** | Skips `__init__.py` files |
| QS-8 | **CLI exits with POSIX codes** | Exit code 0 = all pass, 1 = any failure; combined with bitwise OR |
| QS-9 | **`MIGRATION_CI_*` fields 4-space indented inside `class Settings`** | `_patch_config` enforces indent |
| QS-10 | **`execution_time_ms` set on every return path** | `_elapsed_ms(start)` on all branches |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_database_migrations_ci.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC | AST walk, `loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `MIGRATION_CI_FAIL_ON_DESTRUCTIVE`, `MIGRATION_CI_REQUIRE_ROLLBACK` in `config.py` with 4-space indent | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `app/migrations/__init__.py` created, exports `MigrationCIRunner` | File exists + `"MigrationCIRunner" in src` | `test_migrations_init_created` |
| CC-10 | `app/migrations/ci_runner.py` with `class MigrationCIRunner` | File exists + class present | `test_ci_runner_file_created` |
| CC-11 | `check_pending()` method present | `"def check_pending" in src` | `test_check_pending_method` |
| CC-12 | `verify_rollback()` method present | `"def verify_rollback" in src` | `test_verify_rollback_method` |
| CC-13 | `schema_diff()` method present | `"def schema_diff" in src` | `test_schema_diff_method` |
| CC-14 | `app/migrations/safety_checker.py` with `class SafetyChecker` | File exists + class present | `test_safety_checker_file_created` |
| CC-15 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-16 | `next_steps` non-empty and mention CI or migration | `"ci" in combined or "migration" in combined` | `test_next_steps_present` |

---

## 7. Definition of Done (DoD)

- [ ] All 16 Completeness Criteria verified by `test_add_database_migrations_ci.py`
- [ ] `add_database_migrations_ci.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] Fingerprint check `"MigrationCIRunner" in ci_runner.py` returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `_run_alembic` handles `FileNotFoundError` and `TimeoutExpired` gracefully
- [ ] `SafetyChecker` detects DROP TABLE, DROP COLUMN, TRUNCATE, DROP CONSTRAINT, DROP INDEX
- [ ] `scripts/check_migrations.py` exits with code 0 (pass) or 1 (fail)
- [ ] CLI supports `--pending`, `--rollback`, `--diff`, `--safety` flags
- [ ] No new packages added to `requirements.txt`
- [ ] `MIGRATION_CI_*` fields inserted with 4-space indent inside `class Settings` body
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-MCI-01 | Tool is ALWAYS idempotent on second invocation | `"MigrationCIRunner" in ci_runner_file.read_text()` → `status="no_op"` | `test_idempotent` |
| INV-MCI-02 | `dry_run=True` NEVER writes to disk | Early return before any write | `test_dry_run` |
| INV-MCI-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop | `test_all_py_parse` |
| INV-MCI-04 | Subprocess calls MUST be bounded by a 60-second timeout | `timeout=60` in `subprocess.run` | structural |
| INV-MCI-05 | MUST handle `FileNotFoundError` when alembic not installed | `except FileNotFoundError` block | structural |
| INV-MCI-06 | MUST NOT add new pip dependencies | `requirements.txt` unchanged | `test_no_new_deps_required` |
| INV-MCI-07 | `MIGRATION_CI_*` fields MUST be 4-space indented inside `class Settings` | `_patch_config` enforces indent | `test_config_fields_patched` |
| INV-MCI-08 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` on all branches | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Catch pending migrations in CI**
- **As a** CI pipeline
- **I want** to fail the build when there are unapplied migrations
- **So that** production deployments always run `alembic upgrade head`
- **Given:** `add_database_migrations_ci` applied
- **When:** `python scripts/check_migrations.py --pending`
- **Then:** Exit code 1 if pending; 0 if up to date

**US-02: Verify rollback path before merging**
- **As a** platform engineer requiring rollback safety
- **I want** to test the downgrade path without actually downgrading
- **Given:** `add_database_migrations_ci` applied
- **When:** `python scripts/check_migrations.py --rollback`
- **Then:** Exit code 1 if alembic downgrade SQL generation fails; 0 otherwise

**US-03: Block destructive migrations for human review**
- **As a** database administrator
- **I want** CI to flag DROP TABLE and DROP COLUMN for mandatory review
- **Given:** A migration file containing `op.drop_column("users", "email")`
- **When:** `python scripts/check_migrations.py --safety`
- **Then:** Exit code 1 with structured findings report

**US-04: Preview changes without writing files**
- **Given:** Fresh project
- **When:** `add_database_migrations_ci(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Returns `status="success"` with notes, zero files written

**US-05: Re-run safely on already-configured project**
- **Given:** `app/migrations/ci_runner.py` already contains `MigrationCIRunner`
- **When:** `add_database_migrations_ci(...)` invoked again
- **Then:** Returns `status="no_op"`, no files written

---

## 10. Edge Cases

| Edge Case | Handling |
|-----------|----------|
| alembic CLI not installed | `_run_alembic` catches `FileNotFoundError`, returns `{"returncode": 1, "stderr": "alembic not found"}` |
| Subprocess times out (60 s) | `_run_alembic` catches `TimeoutExpired`, returns `{"returncode": 1, "stderr": "timeout"}` |
| `alembic/versions/` directory does not exist | `SafetyChecker.detect_destructive` returns `destructive_found=False, files_scanned=0` with warning log |
| Migration file has UTF-8 encoding error | `_scan_file` catches `OSError`, logs warning, returns empty findings |
| `alembic check` not available (alembic < 1.9) | `schema_diff` returns `in_sync=False` with error from stderr |
| Multiple migration heads | `_parse_heads` returns list of all heads; `is_up_to_date` only when current is in heads |

---

## 11. Dependencies and Prerequisites

| Dependency | Version | Role | Install? |
|------------|---------|------|---------|
| alembic | any | `alembic current`, `heads`, `check`, `downgrade` CLI | Already present |
| stdlib `subprocess` | 3.10+ | Run alembic CLI | Always available |
| stdlib `re` | 3.10+ | Pattern matching in SafetyChecker | Always available |

**Prerequisites** (checked by `ensure_prerequisites`):
- `Prereq.CONFIG_SETTINGS` — `app/core/config.py` with `class Settings`
- `Prereq.REQUIREMENTS_TXT` — `requirements.txt` exists
- `Prereq.ALEMBIC_VERSIONS` — `alembic/versions/` directory exists

---

## 12. File Map

```
project/
├── app/
│   ├── migrations/
│   │   ├── __init__.py              [CREATED] Exports MigrationCIRunner, SafetyChecker
│   │   ├── ci_runner.py             [CREATED] MigrationCIRunner
│   │   └── safety_checker.py        [CREATED] SafetyChecker
│   └── core/
│       └── config.py                [MODIFIED] MIGRATION_CI_* fields added
├── scripts/
│   └── check_migrations.py          [CREATED] CLI with --pending/--rollback/--diff/--safety
└── alembic/
    └── versions/                    [REQUIRED] Must exist (auto-created if missing)
```

---

## 13. Rollback

To remove migration CI tooling:

1. Delete `app/migrations/ci_runner.py`, `app/migrations/safety_checker.py`, `app/migrations/__init__.py`
2. Delete `scripts/check_migrations.py`
3. Remove `MIGRATION_CI_*` fields from `app/core/config.py`
4. Remove migration CI step from CI configuration files

---

## 14. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Subprocess injection via `project_dir` | `project_dir` is validated by `validate_project_dir` before use; passed as `cwd` to `subprocess.run`, not interpolated into shell string |
| `--safety` blocking legitimate DROP operations | Tool reports findings; the CI gate decision (fail or warn) is controlled by `MIGRATION_CI_FAIL_ON_DESTRUCTIVE` env var |
| Schema diff exposing database credentials | `alembic check` reads `DATABASE_URL` from environment; no credentials logged by the tool |

---

## 15. Observability

| Signal | Where | Content |
|--------|-------|---------|
| `logger.info` | `MigrationCIRunner.check_pending` | `"Migration check: current=%s heads=%s pending=%d"` |
| `logger.warning` | `MigrationCIRunner._run_alembic` | alembic not found or timeout |
| `logger.warning` | `SafetyChecker.detect_destructive` | Versions dir not found; destructive findings count |
| `ToolResult.notes` | Success return | Migration CI tooling summary |
| `ToolResult.next_steps` | Success return | CI pipeline integration commands |
| `ToolResult.execution_time_ms` | All branches | Wall-clock milliseconds |

---

## 16. Test Coverage Map

| Test | CC | Description |
|------|----|-------------|
| `test_success_status` | CC-01 | Returns `status="success"` on fresh project |
| `test_idempotent` | CC-02 | Second run returns `no_op` |
| `test_dry_run` | CC-03 | `dry_run=True` writes nothing |
| `test_files_created_count` | CC-04 | At least 4 files created |
| `test_files_modified_count` | CC-05 | At least 1 file modified |
| `test_all_py_parse` | CC-06 | All `.py` parse cleanly |
| `test_no_function_over_50_loc` | CC-07 | No function > 50 LOC |
| `test_config_fields_patched` | CC-08 | `MIGRATION_CI_*` with 4-space indent |
| `test_migrations_init_created` | CC-09 | `__init__.py` exports `MigrationCIRunner` |
| `test_ci_runner_file_created` | CC-10 | `ci_runner.py` with `class MigrationCIRunner` |
| `test_check_pending_method` | CC-11 | `check_pending()` present |
| `test_verify_rollback_method` | CC-12 | `verify_rollback()` present |
| `test_schema_diff_method` | CC-13 | `schema_diff()` present |
| `test_safety_checker_file_created` | CC-14 | `safety_checker.py` with `class SafetyChecker` |
| `test_safety_checker_detects_drop_table` | INV-MCI-05 | DROP TABLE detection |
| `test_safety_checker_detects_drop_column` | INV-MCI-05 | DROP COLUMN detection |
| `test_check_migrations_script_created` | CC-04 | `scripts/check_migrations.py` exists |
| `test_check_script_has_pending_flag` | CC-04 | `--pending` flag in CLI |
| `test_check_script_has_rollback_flag` | CC-04 | `--rollback` flag in CLI |
| `test_check_script_has_diff_flag` | CC-04 | `--diff` flag in CLI |
| `test_no_new_deps_required` | INV-MCI-06 | `requirements.txt` unchanged |
| `test_next_steps_present` | CC-16 | Non-empty `next_steps` |
| `test_execution_time_recorded` | CC-15 | `execution_time_ms > 0` |
| `test_idempotent_project_still_parses` | INV-MCI-01/03 | After two runs all `.py` parseable |
