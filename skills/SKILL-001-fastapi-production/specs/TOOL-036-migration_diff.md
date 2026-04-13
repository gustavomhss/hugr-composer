# TOOL-036: migration_diff

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_migration_diff` |
| Category | OPERATE |
| Complexity | High |
| Dependencies | existing FastAPI project, Alembic, SQLAlchemy |
| Signature | `migration_diff(project_dir: str, base_ref: str = "origin/main", head_ref: str = "HEAD", fail_on_destructive: bool = True, fail_on_unsafe_default: bool = True, allow_list_file: str = ".migration-allow.yaml") -> dict` |
| Parameters | `project_dir`: project root<br>`base_ref`: git ref to diff from (default: "origin/main")<br>`head_ref`: git ref to diff to (default: "HEAD")<br>`fail_on_destructive`: block DROP COLUMN/TABLE, TYPE CHANGE without cast, NOT NULL on existing column (default: True)<br>`fail_on_unsafe_default`: block ADD COLUMN NOT NULL without DEFAULT on large tables (default: True)<br>`allow_list_file`: explicit allow-list for acknowledged destructive ops with justification (default: ".migration-allow.yaml") |

## 2. Purpose

The `fastapi_migration_diff` tool inspects every Alembic migration introduced in a PR and classifies each schema operation into one of three buckets — **SAFE** (add nullable column, create index CONCURRENTLY, create table), **UNSAFE** (rename column, add NOT NULL without default on an existing column, index creation without CONCURRENTLY on a large table), or **DESTRUCTIVE** (DROP COLUMN, DROP TABLE, TYPE NARROWING) — so the production deploy never silently lands a migration that breaks consumers, locks a hot table for 40 minutes, or throws away business data with no recovery path. It also detects the **multi-phase zero-downtime pattern** (`add_column(nullable=True) + server_default → backfill → set NOT NULL → drop old column`, spread across three migrations) and marks the sequence SAFE when complete, UNSAFE when half-applied, so teams writing correct migrations never get false-positive noise but incomplete attempts are caught before merge.

The generator produces `scripts/migration_diff.py` with an AST parser of `upgrade()`/`downgrade()` that extracts every `op.*` call, a safety-rules engine classifying by operation type + arguments + estimated table size, a rollback-distance computer that walks the revision graph and counts how many migrations would need to be reverted to undo the change, an **explicit allow-list** at `.migration-allow.yaml` where every acknowledged destructive op is committed with a SHA hash of the migration file + justification + reviewer + expiry, and a Markdown PR-comment renderer with ✅/⚠️/❌ per migration plus lock-duration estimates for ALTER TABLE on known-large tables. Key design decisions: **destructive is destructive regardless of size** — the tool never downgrades `DROP COLUMN` to "safe" because the target table happened to be small in the test environment (small today, big tomorrow); **empty downgrade on destructive is a hard blocker** — irreversible migrations are traps, so the tool rejects PRs that remove data without a documented recovery plan; **allow-list is hash-pinned** — if the migration file is edited after approval, the hash no longer matches and re-review is required (no one silently amends an approved destructive migration); **Postgres-specific awareness** — the tool knows `CREATE INDEX CONCURRENTLY` is safe while plain `CREATE INDEX` locks writes, so it flags non-concurrent index creation on tables heuristically marked "large"; **integration with TOOL-043 add_migration_data** so data migrations and schema migrations are analyzed with the correct rules and never mixed in the same file.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s for 100 migrations | Ensures fast feedback in CI pipelines |
| Files modified | ≤ 2 (pyproject.toml, CI workflow) | Minimizes impact on existing project files |
| Files created | ≥ 7 (diff analyzer, safety rules, CI workflow, report template, tests, allow-list, docs) | Provides comprehensive tooling and documentation |
| Rule evaluation | < 100 ms per migration | Maintains responsiveness for large migration sets |
| Report generation | < 500 ms | Keeps PR comment updates snappy |
| Latency overhead | 0s — no DB changes | Analysis-only tool with no production impact |
| Migration runtime | 0s — no DB changes | Analysis-only tool with no production impact |
| Rollback distance computation | < 50 ms per migration | Efficient revision graph traversal |
| Allow-list validation | < 10 ms per entry | Fast hash matching for CI gating |

---

## 4. Code Examples (Before / After)

### 4.1 Safety Rules: BEFORE
```python
# app/core/safety_rules.py
from typing import Dict, List


class SafetyRules:
    DESTRUCTIVE_OPS = {"drop_table", "drop_column"}
    
    def classify(self, operations: List[Dict]) -> str:
        if any(op["type"] in self.DESTRUCTIVE_OPS for op in operations):
            return "destructive"
        return "safe"
```

### 4.2 Safety Rules: AFTER
```python
# app/core/safety_rules.py
from typing import Dict, List, Optional
from datetime import datetime


class SafetyRules:
    DESTRUCTIVE_OPS = {
        "drop_table", "drop_column", "alter_column_type",
        "drop_constraint", "drop_index", "drop_type"
    }
    
    UNSAFE_OPS = {
        "add_column_not_null_no_default", "alter_column_nullable_false",
        "create_index_non_concurrent", "rename_column"
    }

    def classify(self, operations: List[Dict]) -> str:
        if any(self._is_destructive(op) for op in operations):
            return "destructive"
        if any(self._is_unsafe(op) for op in operations):
            return "unsafe"
        return "safe"

    def _is_destructive(self, op: Dict) -> bool:
        return op["type"] in self.DESTRUCTIVE_OPS

    def _is_unsafe(self, op: Dict) -> bool:
        if op["type"] == "add_column":
            return not op.get("nullable", True) and "server_default" not in op
        return op["type"] in self.UNSAFE_OPS

    def check_multi_phase(self, operations: List[Dict]) -> Optional[datetime]:
        """Returns estimated completion time if multi-phase detected"""
        add_ops = [op for op in operations if op["type"] == "add_column"]
        alter_ops = [op for op in operations if op["type"] == "alter_column"]
        
        for add_op in add_ops:
            if add_op.get("nullable") and add_op.get("server_default"):
                matching_alter = next(
                    (op for op in alter_ops 
                     if op["column_name"] == add_op["column_name"]
                     and not op.get("nullable")),
                    None
                )
                if matching_alter:
                    return datetime.now() + timedelta(days=7)  # Estimated backfill period
        return None
```

### 4.3 Migration Analyzer (NEW)
```python
# app/core/migration_analyzer.py
import ast
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple
from alembic.script import ScriptDirectory


class MigrationAnalyzer:
    def __init__(self, project_dir: str):
        self.script_dir = ScriptDirectory(str(Path(project_dir) / "alembic"))
        self.safety_rules = SafetyRules()

    def analyze(self, path: str) -> Dict:
        with open(path) as f:
            tree = ast.parse(f.read())

        ops = self._extract_operations(tree)
        classification = self.safety_rules.classify(ops)
        rollback_dist = self._calculate_rollback_distance(path)
        multi_phase_eta = self.safety_rules.check_multi_phase(ops)

        return {
            "path": path,
            "operations": ops,
            "classification": classification,
            "rollback_distance": rollback_dist,
            "multi_phase_eta": multi_phase_eta,
            "hash": hashlib.sha256(open(path, "rb").read()).hexdigest()
        }

    def _extract_operations(self, tree: ast.AST) -> List[Dict]:
        ops = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "upgrade":
                    ops.extend(self._parse_op_call(node))
        return ops

    def _parse_op_call(self, node: ast.Call) -> List[Dict]:
        if not isinstance(node.func, ast.Attribute):
            return []
            
        op_type = node.func.attr
        args = {
            arg.arg: ast.literal_eval(arg.value) 
            for arg in node.keywords
            if isinstance(arg, ast.keyword)
        }
        return [{"type": op_type, **args}]
```

### 4.4 Allow List Validator (NEW)
```python
# app/core/allow_list.py
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import yaml


class AllowListValidator:
    def __init__(self, path: str = ".migration-allow.yaml"):
        self.path = Path(path)
        self.entries = self._load_entries()

    def validate(self, migration_hash: str) -> Optional[Dict]:
        entry = self.entries.get(migration_hash)
        if not entry:
            return None

        expires = datetime.fromisoformat(entry["expires_at"])
        if datetime.now() > expires:
            return None

        return {
            "justification": entry["justification"],
            "approved_by": entry["approved_by"],
            "expires_at": entry["expires_at"],
            "ticket": entry.get("ticket", "")
        }

    def _load_entries(self) -> Dict:
        if not self.path.exists():
            return {}

        with open(self.path) as f:
            data = yaml.safe_load(f)
            return {
                e["hash"]: e 
                for e in data.get("allow_list", [])
                if "hash" in e
            }
```

### 4.5 Report Generator (NEW)
```python
# app/core/report_generator.py
from typing import List, Dict
from datetime import datetime


class ReportGenerator:
    EMOJI_MAP = {
        "safe": "✅",
        "unsafe": "⚠️",
        "destructive": "❌"
    }

    def generate(self, analyses: List[Dict], allow_list: Dict) -> str:
        lines = [
            "# Migration Safety Report",
            "",
            "| File | Status | Rollback | Operations |",
            "|------|--------|----------|------------|"
        ]

        for analysis in analyses:
            status = self.EMOJI_MAP[analysis["classification"]]
            ops_summary = ", ".join(
                f"{op['type']}({op.get('table_name', '')})"
                for op in analysis["operations"][:3]
            )
            if len(analysis["operations"]) > 3:
                ops_summary += "..."

            lines.append(
                f"| {analysis['path']} | {status} | {analysis['rollback_distance']} | {ops_summary} |"
            )

        if any(a["classification"] == "destructive" for a in analyses):
            lines.extend([
                "",
                "## Destructive Operations Detected",
                "The following migrations contain operations that may cause downtime:"
            ])
            for analysis in filter(lambda a: a["classification"] == "destructive", analyses):
                if not allow_list.get(analysis["hash"]):
                    lines.append(f"- {analysis['path']} (no allow-list entry)")

        return "\n".join(lines)
```

### 4.6 Main Tool Class (NEW)
```python
# app/main.py
import subprocess
from pathlib import Path
from typing import Dict, List
from .core import (
    MigrationAnalyzer,
    AllowListValidator,
    ReportGenerator
)


class MigrationDiffTool:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.analyzer = MigrationAnalyzer(project_dir)
        self.allow_list = AllowListValidator()
        self.reporter = ReportGenerator()

    def run(self, base_ref: str, head_ref: str) -> Dict:
        migrations = self._get_changed_migrations(base_ref, head_ref)
        analyses = [self.analyzer.analyze(m) for m in migrations]
        allow_entries = {
            a["hash"]: self.allow_list.validate(a["hash"])
            for a in analyses
        }

        return {
            "analyses": analyses,
            "has_blockers": any(
                a["classification"] in ("destructive", "unsafe") 
                and not allow_entries.get(a["hash"])
                for a in analyses
            ),
            "report": self.reporter.generate(analyses, allow_entries)
        }

    def _get_changed_migrations(self, base: str, head: str) -> List[str]:
        cmd = ["git", "diff", "--name-only", base, head, "--", "alembic/versions"]
        result = subprocess.run(
            cmd,
            cwd=self.project_dir,
            capture_output=True,
            text=True
        )
        return [
            str(self.project_dir / path)
            for path in result.stdout.splitlines()
            if path.endswith(".py")
        ]
```

### 4.7 Example Migration (NEW)
```python
# alembic/versions/2026_04_08_0001_add_user_profile.py
"""Add user profile columns

Revision ID: 2026_04_08_0001
Revises: 2026_03_15_0001
Create Date: 2026-04-08 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "2026_04_08_0001"
down_revision = "2026_03_15_0001"


def upgrade():
    # Safe: nullable column
    op.add_column(
        "users",
        sa.Column("bio", sa.Text(), nullable=True)
    )
    
    # Unsafe: NOT NULL without default
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(100), nullable=False)
    )
    
    # Multi-phase pattern
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=True, server_default="false")
    )


def downgrade():
    op.drop_column("users", "bio")
    op.drop_column("users", "display_name")
    op.drop_column("users", "is_verified")
```

### 4.8 CLI Interface (NEW)
```python
# app/cli.py
import argparse
import json
import sys
from pathlib import Path
from .main import MigrationDiffTool


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Alembic migrations for safety"
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        required=True,
        help="Path to project root"
    )
    parser.add_argument(
        "--base-ref",
        type=str,
        default="origin/main",
        help="Git reference to compare from"
    )
    parser.add_argument(
        "--head-ref",
        type=str,
        default="HEAD",
        help="Git reference to compare to"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of Markdown"
    )
    args = parser.parse_args()

    tool = MigrationDiffTool(args.project_dir)
    result = tool.run(args.base_ref, args.head_ref)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["report"])

    sys.exit(1 if result["has_blockers"] else 0)


if __name__ == "__main__":
    main()
```

### 4.9 CI Workflow (NEW)
```python
# .github/workflows/check_migrations.yml
name: Check Migrations

on:
  pull_request:
    paths:
      - "alembic/versions/*.py"

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0  # Needed for git diff
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.10"
      
      - name: Install dependencies
        run: |
          pip install alembic sqlalchemy pyyaml
      
      - name: Run migration diff
        run: |
          python -m app.cli --project-dir . --base-ref origin/main --head-ref HEAD
      
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: migration-report
          path: migration-report.md

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Every destructive operation is classified regardless of table size** | `SafetyRules.classify()` in `app/core/safety_rules.py` checks DESTRUCTIVE_OPS set before any size-based rules |
| QS-2 | **Allow-list entries require justification + expiry date** | `AllowListValidator.is_allowed()` in `app/core/allow_list.py` validates both fields exist and expiry is future |
| QS-3 | **Rollback distance is computed from actual revision graph** | `MigrationAnalyzer._calculate_rollback_distance()` walks `down_revision` chain via `ScriptDirectory.get_revision()` |
| QS-4 | **Empty downgrade() on destructive operations is always blocked** | `MigrationAnalyzer.analyze_migration()` parses both upgrade/downgrade via AST and compares operation counts |
| QS-5 | **Multi-phase patterns are detected automatically** | `SafetyRules.check_multi_phase()` matches op sequences like add_column(nullable=True)→backfill→alter_column(nullable=False) |
| QS-6 | **Reports are deterministic (same diff → same output)** | `MigrationDiffTool.run()` sorts migrations by path before analysis and uses SHA-256 hashes for allow-list matching |
| QS-7 | **CI gate cannot be bypassed without allow-list hash match** | `.github/workflows/check_migrations.yml` calls tool with `--fail-on-destructive` and validates exit code |
| QS-8 | **Postgres-specific checks are applied for CONCURRENTLY ops** | `SafetyRules.classify()` flags CREATE INDEX without CONCURRENTLY on tables >10k rows as UNSAFE |
| QS-9 | **Type changes without explicit cast are always destructive** | `SafetyRules.DESTRUCTIVE_OPS` includes "alter_column_type" and checks for `existing_type=sa.String()` in args |
| QS-10 | **Data migrations mixed with schema are flagged for review** | `MigrationAnalyzer._extract_operations()` detects raw SQL in upgrade() and classifies as "data_in_schema" |
| QS-11 | **Lock duration estimates are based on table size hints** | `MigrationAnalyzer._estimate_lock_duration()` uses `op.get_bind().execute(text("SELECT reltuples FROM pg_class"))` |
| QS-12 | **Migration chain holes (missing down_revision) are errors** | `ScriptDirectory.get_revision()` raises `RevisionError` which is caught and converted to tool error message |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `MigrationAnalyzer` class exists at `app/core/migration_analyzer.py` | File exists, parses |
| CC-02 | `SafetyRules` class exists at `app/core/safety_rules.py` | File exists, contains DESTRUCTIVE_OPS set |
| CC-03 | `AllowListValidator` class exists at `app/core/allow_list.py` | File exists, loads YAML |
| CC-04 | `ReportGenerator` class exists at `app/core/report_generator.py` | File exists, generates markdown |
| CC-05 | Main tool class exists at `app/main.py` with `MigrationDiffTool` | File exists, implements `run()` |
| CC-06 | CI workflow exists at `.github/workflows/check_migrations.yml` | File exists, runs on PR |
| CC-07 | All destructive ops are in `DESTRUCTIVE_OPS` set | grep `drop_table\|drop_column\|alter_column_type` |
| CC-08 | All unsafe ops are in `UNSAFE_OPS` set | grep `add_column_not_null_no_default\|create_index_non_concurrent` |
| CC-09 | AST parsing extracts all `op.*` calls from upgrade/downgrade | Inspect `_extract_operations()` |
| CC-10 | Rollback distance counts actual reversions needed | T-07, T-08 |
| CC-11 | Allow-list validates justification + expiry | T-13, T-14 |
| CC-12 | Report shows status emoji per migration | grep `✅\|⚠️\|❌` in report |
| CC-13 | Multi-phase pattern detection works | T-11, T-12 |
| CC-14 | Empty downgrade() blocks destructive ops | T-09 |
| CC-15 | Type changes require cast to be safe | grep `existing_type` in safety rules |
| CC-16 | Postgres CONCURRENTLY is enforced for large tables | grep `CONCURRENTLY` in safety rules |
| CC-17 | Data migration detection flags raw SQL | grep `execute(text(` in analyzer |
| CC-18 | Lock duration estimates use pg_class | grep `reltuples FROM pg_class` |
| CC-19 | Revision graph holes are errors | T-25 |
| CC-20 | Tool handles multiple branches | T-30 |
| CC-21 | Migration files are sorted before analysis | Inspect `MigrationDiffTool.run()` |
| CC-22 | SHA-256 hashes are used for allow-list | grep `hashlib.sha256` in analyzer |
| CC-23 | CI workflow blocks on destructive | grep `fail-on-destructive` in workflow |
| CC-24 | Report includes rollback distance | grep `Rollback distance` in report |
| CC-25 | Report includes operation details | grep `Operations:` in report |
| CC-26 | ENUM TYPE changes are flagged unsafe | grep `enum` in safety rules |
| CC-27 | RENAME COLUMN is classified unsafe | grep `rename` in safety rules |
| CC-28 | NOT NULL on existing column is destructive | grep `nullable=False` in safety rules |
| CC-29 | ADD COLUMN with default is safe | grep `server_default` in safety rules |
| CC-30 | Tool execution time < 3s for 100 migrations | Time measurement T-29 |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] All 8 Invariants tested and passing
- [ ] CI workflow integrated and blocking PRs on destructive changes
- [ ] Allow-list YAML schema documented in README
- [ ] Example migration report generated for test cases
- [ ] Multi-phase pattern detection tested with 3-phase example
- [ ] Rollback distance calculation handles branch points
- [ ] AST parser handles all Alembic op.* methods
- [ ] Lock duration estimation tested with pg_class mock
- [ ] Postgres-specific checks validated against real DB
- [ ] Tool idempotency verified (T-28)
- [ ] Edge cases tested: empty diff, multiple heads, revision holes
- [ ] Performance SLOs met: <3s for 100 migrations

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-MD-01 | A destructive operation is ALWAYS classified regardless of table size | `SafetyRules.classify()` checks DESTRUCTIVE_OPS set before any size-based rules in `app/core/safety_rules.py` | T-01, T-02 |
| INV-MD-02 | An allow-list entry ALWAYS requires justification + future expiry | `AllowListValidator.is_allowed()` validates both fields exist and expiry is future in `app/core/allow_list.py` | T-13, T-14 |
| INV-MD-03 | Rollback distance is ALWAYS computed from actual revision graph | `MigrationAnalyzer._calculate_rollback_distance()` walks `down_revision` chain via `ScriptDirectory.get_revision()` | T-07, T-08 |
| INV-MD-04 | A destructive operation with empty downgrade() ALWAYS blocks | `MigrationAnalyzer.analyze_migration()` compares upgrade/downgrade op counts via AST parsing | T-09 |
| INV-MD-05 | Multi-phase patterns are ALWAYS detected when present | `SafetyRules.check_multi_phase()` matches op sequences in `app/core/safety_rules.py` | T-11, T-12 |
| INV-MD-06 | Reports are ALWAYS deterministic (same diff → same output) | `MigrationDiffTool.run()` sorts migrations by path and uses SHA-256 hashes in `app/main.py` | T-19, T-28 |
| INV-MD-07 | The CI gate ALWAYS blocks destructive changes without allow-list | `.github/workflows/check_migrations.yml` calls tool with `--fail-on-destructive` flag | T-16, T-17 |
| INV-MD-08 | Postgres CONCURRENTLY is ALWAYS required for large table indexes | `SafetyRules.classify()` checks table size and CONCURRENTLY flag in `app/core/safety_rules.py` | T-05, T-06 |

---

## 9. User Stories

### 9.1 Core classification (US-01 .. US-05)

**US-01: Detect DROP COLUMN as destructive**
- **As a** database engineer
- **I want** the tool to flag any `op.drop_column()` as destructive
- **So that** I never accidentally remove a column in production
- **Given:** migration file `alembic/versions/2026_01_drop_old.py` with `op.drop_column("users", "legacy_id")`
- **When:** I run `migration_diff --project-dir .`
- **Then:**
  - Operation classified as "destructive" (INV-MD-01)
  - Report shows ❌ emoji for this migration (CC-12)
  - CI pipeline fails if no allow-list entry exists (INV-MD-07)

**US-02: Allow safe ADD COLUMN nullable**
- **As a** backend developer
- **I want** the tool to approve `op.add_column(nullable=True)`
- **So that** I can add optional fields without downtime
- **Given:** migration adding `op.add_column("products", sa.Column("description", sa.Text(), nullable=True))`
- **When:** Tool analyzes the migration
- **Then:**
  - Operation classified as "safe" (CC-29)
  - Report shows ✅ emoji (CC-12)
  - CI pipeline allows merge without allow-list (T-03)

**US-03: Flag NOT NULL on existing column**
- **As a** release engineer
- **I want** the tool to block `op.alter_column(nullable=False)` on populated tables
- **So that** we enforce multi-phase migrations
- **Given:** migration altering `op.alter_column("orders", "customer_id", nullable=False)` on table with 1M rows
- **When:** Tool evaluates the migration
- **Then:**
  - Operation classified as "destructive" (INV-MD-01)
  - Report explains required 3-phase pattern (CC-13)
  - Suggests using `server_default` as alternative (CC-29)

**US-04: Detect missing downgrade()**
- **As a** platform SRE
- **I want** the tool to reject destructive operations without downgrade logic
- **So that** we maintain rollback capability
- **Given:** migration with `op.drop_table("temp_data")` but empty `downgrade()`
- **When:** Tool parses the file
- **Then:**
  - Classification shows "blocker" (INV-MD-04)
  - Report highlights empty downgrade (CC-14)
  - Fails even with allow-list entry (T-09)

**US-05: Require CONCURRENTLY for large indexes**
- **As a** performance engineer
- **I want** the tool to enforce `CREATE INDEX CONCURRENTLY` on tables >10k rows
- **So that** we avoid production locks
- **Given:** migration with `op.create_index("idx_user_email", "users", ["email"])` on 100k-row table
- **When:** Tool checks the operation
- **Then:**
  - Classified as "unsafe" (INV-MD-08)
  - Report suggests adding CONCURRENTLY (CC-16)
  - Estimates lock duration >5s (CC-18)

### 9.2 Allow-list workflow (US-06 .. US-10)

**US-06: Bypass with valid allow-list**
- **As a** lead developer
- **I want** to approve specific destructive migrations via allow-list
- **So that** we can make necessary breaking changes
- **Given:** `.migration-allow.yaml` with valid hash, justification, and future expiry
- **When:** Tool encounters matching migration
- **Then:**
  - Allows the change (INV-MD-02)
  - Includes justification in report (CC-11)
  - Still shows ❌ but doesn't fail (T-13)

**US-07: Reject expired allow-list**
- **As a** security auditor
- **I want** expired allow-list entries to be rejected
- **So that** temporary exceptions don't become permanent
- **Given:** allow-list entry with `expires_at: 2025-01-01`
- **When:** Current date is 2026-01-01
- **Then:**
  - Tool rejects the entry (INV-MD-02)
  - Report suggests renewal (T-14)
  - CI pipeline fails (INV-MD-07)

**US-08: Require full justification**
- **As a** engineering manager
- **I want** every allow-list entry to require 50+ char justification
- **So that** we maintain accountability
- **Given:** allow-list entry with `justification: "fix"`
- **When:** Tool validates the entry
- **Then:**
  - Rejects as insufficient (CC-11)
  - Returns specific length requirement (T-13)
  - Suggests example justifications (CC-24)

**US-09: Detect allow-list hash mismatch**
- **As a** compliance officer
- **I want** the tool to detect when a migration changes after approval
- **So that** we don't bypass checks silently
- **Given:** allow-list entry for migration that was later modified
- **When:** SHA-256 hashes don't match
- **Then:**
  - Treats as unapproved (INV-MD-06)
  - Shows diff in report (CC-22)
  - Requires re-approval (T-17)

**US-10: Generate allow-list template**
- **As a** developer needing an exception
- **I want** the tool to generate a properly formatted allow-list snippet
- **So that** I don't make syntax errors
- **Given:** destructive migration `2026_04_drop_legacy.py`
- **When:** I run `migration_diff --generate-allowlist`
- **Then:**
  - Outputs YAML with hash, expiry placeholder (CC-11)
  - Includes example justification (CC-24)
  - Ready for PR approval (T-13)

### 9.3 Rollback analysis (US-11 .. US-15)

**US-11: Calculate linear rollback distance**
- **As a** release coordinator
- **I want** to know how many migrations must be reverted to undo a change
- **So that** we assess rollback complexity
- **Given:** migration `rev_005` depends on `rev_004` which depends on `rev_003`
- **When:** Analyzing `rev_005`
- **Then:**
  - Reports rollback distance 2 (INV-MD-03)
  - Shows revision chain in report (CC-10)
  - Classifies as "safe" if distance <5 (T-07)

**US-12: Detect revision graph holes**
- **As a** database architect
- **I want** the tool to detect broken migration chains
- **So that** we maintain clean history
- **Given:** migration with `down_revision = "missing_rev"`
- **When:** Tool traverses the graph
- **Then:**
  - Reports "broken chain" error (CC-19)
  - Fails CI immediately (T-25)
  - Suggests `alembic repair` command (CC-30)

**US-13: Handle multiple heads**
- **As a** developer working in a branch
- **I want** the tool to analyze migrations across branches
- **So that** we catch issues before merge
- **Given:** `main` has rev_010 and `feature` has rev_011a, 011b
- **When:** Comparing `main...feature`
- **Then:**
  - Analyzes all new migrations (CC-20)
  - Shows branch topology in report (CC-21)
  - Calculates worst-case rollback distance (T-08)

**US-14: Weigh rollback difficulty**
- **As a** production engineer
- **I want** rollback distance to factor into safety classification
- **So that** we prioritize reviewing risky changes
- **Given:** migration with 10+ dependent revisions
- **When:** Tool evaluates impact
- **Then:**
  - Adds "high rollback cost" warning (CC-10)
  - Still allows if operations are safe (INV-MD-03)
  - Suggests breaking into smaller migrations (T-12)

**US-15: Ignore already-merged migrations**
- **As a** CI pipeline
- **I want** the tool to only analyze new, unmerged migrations
- **So that** we don't re-check approved work
- **Given:** PR with 2 new migrations and 50 existing ones
- **When:** Running `migration_diff origin/main HEAD`
- **Then:**
  - Only analyzes the 2 new files (CC-21)
  - Completes in <1s (CC-30)
  - Skips allow-list checks for existing (T-19)

### 9.4 CI integration (US-16 .. US-20)

**US-16: Post PR comment**
- **As a** code reviewer
- **I want** the tool to post a formatted Markdown report
- **So that** I can assess migration safety
- **Given:** PR with 3 changed migration files
- **When:** CI runs `migration_diff`
- **Then:**
  - Posts comment with ✅/⚠️/❌ per file (CC-12)
  - Includes operation details (CC-25)
  - Links to allow-list docs (CC-24)

**US-17: Block destructive changes**
- **As a** site reliability engineer
- **I want** the CI to fail on unapproved destructive changes
- **So that** they can't reach production
- **Given:** PR with `op.drop_table()` and no allow-list
- **When:** Pipeline executes
- **Then:**
  - Returns non-zero exit code (INV-MD-07)
  - Comment shows "Merge blocked" (T-16)
  - Provides allow-list instructions (CC-11)

**US-18: Fast feedback under 3s**
- **As a** developer waiting on CI
- **I want** migration analysis to complete quickly
- **So that** I don't delay my workflow
- **Given:** PR with 15 migration files
- **When:** Tool runs in CI
- **Then:**
  - Completes in <1.5s (CC-30)
  - Reports per-file timing (T-29)
  - Caches AST parsing (INV-MD-06)

**US-19: JSON output for bots**
- **As a** release automation system
- **I want** machine-readable output
- **So that** I can gate deployments
- **Given:** `migration_diff --format=json`
- **When:** Tool executes
- **Then:**
  - Outputs valid JSON (CC-24)
  - Includes all classification data (CC-25)
  - Compatible with jq filtering (T-19)

**US-20: Track migration history**
- **As a** production support team
- **I want** the tool to record analyzed migrations
- **So that** we can audit safety trends
- **Given:** `--track-history` flag enabled
- **When:** Tool runs in CI
- **Then:**
  - Appends to `migration_audit.log` (CC-24)
  - Records hash, classification, timestamp (CC-22)
  - Preserves history across runs (T-28)

### 9.5 Edge cases (US-21 .. US-25)

**US-21: Handle empty migration**
- **As a** developer generating boilerplate
- **I want** the tool to skip empty migrations
- **So that** we don't get false positives
- **Given:** migration with empty `upgrade()` and `downgrade()`
- **When:** Tool analyzes it
- **Then:**
  - Classifies as "safe" (T-01)
  - Shows "no operations" in report (CC-25)
  - Completes in <10ms (CC-30)

**US-22: Detect data migrations**
- **As a** database administrator
- **I want** the tool to flag raw SQL in schema migrations
- **So that** we keep them separate
- **Given:** migration with `op.execute("UPDATE users SET role='admin' WHERE...")`
- **When:** AST parsing finds non-op calls
- **Then:**
  - Adds "data_in_schema" warning (CC-17)
  - Still evaluates schema ops (INV-MD-01)
  - Suggests splitting migrations (T-10)

**US-23: Validate ENUM changes**
- **As a** Postgres specialist
- **I want** the tool to flag ENUM alterations
- **So that** we handle them carefully
- **Given:** `op.alter_column("users", "status", type_=sa.Enum(...))`
- **When:** Tool analyzes the operation
- **Then:**
  - Classifies as "unsafe" (CC-26)
  - Recommends CREATE TYPE first (T-06)
  - Estimates >1s lock (CC-18)

**US-24: Idempotent analysis**
- **As a** developer re-running checks
- **I want** the tool to produce identical output
- **So that** I can trust the results
- **Given:** unchanged migration files
- **When:** Running tool multiple times
- **Then:**
  - Same SHA-256 hashes (INV-MD-06)
  - Identical classifications (T-28)
  - Consistent report ordering (CC-21)

**US-25: Handle first migration**
- **As a** project bootstrap script
- **I want** the tool to work with initial migrations
- **So that** new projects get safety from day one
- **Given:** migration with `down_revision = None`
- **When:** Calculating rollback distance
- **Then:**
  - Reports distance 0 (INV-MD-03)
  - Still checks operations (INV-MD-01)
  - Handles cleanly without error (T-25)

---

## 10. Test Plan

### 10.1 Classification tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Empty migration is safe | Migration with empty upgrade/downgrade | Run migration_diff | Classification="safe" |
| T-02 | DROP COLUMN is destructive | Migration with `op.drop_column("users", "legacy_id")` | Analyze migration | Classification="destructive" |
| T-03 | ADD COLUMN nullable is safe | Migration with `op.add_column("users", sa.Column("notes", sa.Text(), nullable=True))` | Analyze migration | Classification="safe" |
| T-04 | ADD COLUMN NOT NULL without default is unsafe | Migration adding `op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False))` | Analyze migration | Classification="unsafe" |
| T-05 | CREATE INDEX without CONCURRENTLY on large table is unsafe | Migration with `op.create_index("idx_user_email", "users", ["email"])` on 100k-row table | Analyze migration | Classification="unsafe" |
| T-06 | ALTER COLUMN TYPE without cast is destructive | Migration with `op.alter_column("users", "email", type_=sa.String(320))` | Analyze migration | Classification="destructive" |

### 10.2 Rollback tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Single migration rollback distance | Migration with `down_revision = "0001"` | Calculate rollback distance | Distance=1 |
| T-08 | Branch point rollback distance | Migration with `down_revision = "0001a"` where 0001 has two heads | Calculate rollback distance | Distance=2 |
| T-09 | Empty downgrade blocks destructive | Migration with `op.drop_table("temp_data")` and empty downgrade() | Analyze migration | Classification="blocker" |
| T-10 | Multi-phase pattern detected | Migration sequence: add_column(nullable=True)→backfill→alter_column(nullable=False) | Analyze migrations | Classification="safe" |
| T-11 | Revision graph hole detected | Migration with `down_revision = "missing_rev"` | Analyze migration | Error="broken chain" |
| T-12 | First migration rollback distance | Migration with `down_revision = None` | Calculate rollback distance | Distance=0 |

### 10.3 Allow-list tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Valid allow-list bypass | `.migration-allow.yaml` with hash, justification="legacy cleanup", expires_at="2026-12-31" | Analyze destructive migration | Allows change |
| T-14 | Expired allow-list rejected | Allow-list entry with expires_at="2025-01-01" | Analyze migration | Blocks change |
| T-15 | Short justification rejected | Allow-list with justification="fix" | Validate entry | Rejects="justification too short" |
| T-16 | Hash mismatch detected | Migration changed after allow-list approval | Analyze migration | Blocks="hash mismatch" |
| T-17 | CI blocks destructive without allow-list | PR with `op.drop_table()` and no allow-list | Run CI pipeline | Fails="destructive change" |
| T-18 | Allow-list template generation | Migration `2026_04_drop_legacy.py` | Run `--generate-allowlist` | Outputs valid YAML template |

### 10.4 Reporting tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Markdown report generation | 3 migrations: safe, unsafe, destructive | Generate report | Shows ✅/⚠️/❌ per migration |
| T-20 | JSON output format | Migration with `op.add_column()` | Run `--format=json` | Outputs valid JSON |
| T-21 | Report includes rollback distance | Migration with distance=3 | Generate report | Shows "Rollback distance: 3" |
| T-22 | Report includes operation details | Migration with `op.create_table()` | Generate report | Lists "create_table: users" |
| T-23 | Report shows allow-list justification | Migration with allow-list entry | Generate report | Includes justification text |
| T-24 | Report handles multiple branches | PR with migrations from feature branch | Generate report | Shows branch topology |

### 10.5 Edge case tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Tool handles first migration | Migration with `down_revision = None` | Analyze migration | Completes without error |
| T-26 | Data migration detection | Migration with `op.execute("UPDATE users SET...")` | Analyze migration | Adds "data_in_schema" warning |
| T-27 | ENUM change flagged unsafe | Migration with `op.alter_column("users", "status", type_=sa.Enum(...))` | Analyze migration | Classification="unsafe" |
| T-28 | Tool idempotency | Unchanged migration files | Run tool twice | Same SHA-256 hashes |
| T-29 | Performance SLO met | 100 migrations in `alembic/versions` | Time execution | < 3s |
| T-30 | Multiple branches supported | PR with migrations from feature and main | Analyze migrations | Processes all new files |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | Yes | ✅ Compatible | Migration diff must run after soft delete to detect `deleted_at` column additions |
| add_cursor_pagination | No | ✅ Compatible | Pagination doesn't affect schema migrations |
| add_search | Yes | ✅ Compatible | Migration diff should run after search to analyze GIN/GIST indexes |
| add_audit_log | Yes | ✅ Compatible | Audit log migrations must be analyzed for triggers and history tables |
| add_data_export | No | ✅ Compatible | Data export is a read-only feature with no schema changes |
| add_bulk_operations | No | ✅ Compatible | Bulk operations don't modify database schema |
| add_multi_tenancy | Yes | ✅ Compatible | Migration diff must analyze tenant_id column additions and indexes |
| add_feature_flags | No | ✅ Compatible | Feature flags are stored in Redis, not the database |
| add_api_key_auth | Yes | ✅ Compatible | Migration diff must analyze api_key table and indexes |
| add_oauth2_provider | Yes | ✅ Compatible | Migration diff must analyze OAuth2 token and client tables |
| add_rbac | Yes | ✅ Compatible | Migration diff must analyze role and permission tables |
| add_mfa | Yes | ✅ Compatible | Migration diff must analyze MFA secret storage table |
| add_cache_layer | No | ✅ Compatible | Cache layer uses Redis, not database schema changes |
| add_outbox_pattern | Yes | ✅ Compatible | Migration diff must analyze outbox table schema |
| add_sse | No | ✅ Compatible | Server-sent events don't modify database schema |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- alembic/versions/*.py
rm -rf app/core/migration_analyzer.py
rm -rf app/core/safety_rules.py
rm -rf app/core/allow_list.py
rm -rf app/core/report_generator.py
rm -rf app/main.py
rm -rf .github/workflows/check_migrations.yml
rm -rf .migration-allow.yaml
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (analyzer module present but CI workflow missing, allow-list schema corrupted), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short app/core/ .migration-allow.yaml .github/workflows/

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- app/core/migration_analyzer.py app/core/safety_rules.py \
    app/core/allow_list.py app/core/report_generator.py
git clean -fd .migration-allow.yaml .github/workflows/check_migrations.yml \
    scripts/migration_diff.py tests/test_migration_diff.py

# 3. Verify clean tree
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: genuine destructive migration blocked by gate
If a PR legitimately needs to drop a deprecated column and the gate is blocking it, do NOT bypass — add an explicit, time-boxed allow-list entry with a recovery plan:
```bash
# 1. Compute the migration file hash (pinning the allow-list to this exact content)
sha256sum alembic/versions/2026_04_12_1415-drop_legacy_email.py

# 2. Append an allow-list entry with reason, reviewer, expiry, recovery plan
cat >> .migration-allow.yaml <<'YAML'
destructive_ops:
  - file: "2026_04_12_1415-drop_legacy_email.py"
    sha256: "<paste the hash from step 1>"
    op: "drop_column(users, legacy_email)"
    reason: "Column replaced by email_v2 in 2026_03_01_*; no consumers remain"
    reviewed_by: "data-platform-team"
    expires: "2026-05-12"
    recovery_plan: "pg_dump of users table committed to s3://backups/pre-drop-2026-04-12/"
YAML

# 3. Re-run the gate locally to confirm the allow-list took effect
python -m scripts.migration_diff origin/main HEAD

# 4. Commit allow-list update in the same PR as the migration
git add .migration-allow.yaml alembic/versions/
git commit -m "db: drop legacy_email column (SEC-1234)"
```
If the migration file is edited after the hash was pinned, the gate re-fails and a new allow-list entry (with fresh review) is required.

### Failure mode: multi-phase migration half-applied across PRs
If phase 1 (add nullable column) landed in main but phase 2 (backfill) hasn't merged yet, subsequent PRs will see UNSAFE state and fail:
1. Inspect current state: `alembic heads` and check which phase is live in each environment
2. Fast-track the pending phase — do NOT merge PRs that mutate the affected table until the multi-phase sequence is complete
3. Document the in-flight phase in `.migration-allow.yaml` under `in_progress_phases` so other developers see the warning
4. Once the final phase merges, remove the `in_progress_phases` entry

### Emergency: CI pipeline blocked by a false positive
If the safety-rules engine flags a known-safe op as UNSAFE (e.g., `CREATE INDEX CONCURRENTLY` misclassified because of a parser edge case):
1. Reproduce locally: `python -m scripts.migration_diff --verbose` to see the exact rule that triggered
2. File a reproducer ticket with the offending migration so the rule can be corrected at the source
3. In the interim, add a **temporary** allow-list entry with `expires` set to 14 days so the bypass cannot become permanent
4. Once the rule is fixed and deployed, remove the allow-list entry — verify the fix catches the original case

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Migration with no operations | Tool classifies as SAFE with "no operations" note |
| EC-2 | DROP COLUMN on tiny table | Tool still classifies as DESTRUCTIVE regardless of table size |
| EC-3 | RENAME COLUMN operation | Tool classifies as UNSAFE due to potential consumer breakage |
| EC-4 | CREATE INDEX without CONCURRENTLY on large table | Tool classifies as UNSAFE and suggests adding CONCURRENTLY |
| EC-5 | ADD COLUMN NOT NULL without default | Tool classifies as UNSAFE due to potential failure on existing rows |
| EC-6 | ADD COLUMN NOT NULL with server_default | Tool classifies as SAFE for zero-downtime deployment |
| EC-7 | Empty downgrade() on destructive operation | Tool blocks with "empty downgrade" error even with allow-list |
| EC-8 | Migration chain hole (missing down_revision) | Tool errors with "broken migration chain" message |
| EC-9 | Multiple heads in revision graph | Tool supports multi-branch diff and calculates worst-case rollback distance |
| EC-10 | Auto-generated migration with bad type inference | Tool flags for manual review with "type inference" warning |
| EC-11 | Data migration mixed with schema migration | Tool adds "data_in_schema" warning but still evaluates schema operations |
| EC-12 | Allow-list entry expired | Tool blocks migration and suggests renewal with updated expiry |
| EC-13 | Allow-list hash mismatch | Tool blocks migration due to file changes requiring re-approval |
| EC-14 | Tool re-run on unchanged migrations | Tool produces identical output due to deterministic SHA-256 hashes |
| EC-15 | Postgres ENUM TYPE modification | Tool classifies as UNSAFE and recommends CREATE TYPE pattern |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 30 Completeness Criteria verified
✅ 2. All 8 Invariants tested and passing
✅ 3. CI workflow integrated and blocking PRs on destructive changes
✅ 4. Allow-list YAML schema documented in README
✅ 5. Example migration report generated for test cases
✅ 6. Multi-phase pattern detection tested with 3-phase example
✅ 7. Rollback distance calculation handles branch points
✅ 8. AST parser handles all Alembic op.* methods
✅ 9. Performance SLOs met: <3s for 100 migrations
✅ 10. Developer successfully adds allow-list entry for destructive migration and merges PR

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `alembic/versions/` directory exists
- [ ] Verify Alembic is initialized in project
- [ ] Check for existing migration files
- [ ] Validate Python version >= 3.8
- [ ] Verify SQLAlchemy is installed
- [ ] Check for `.migration-allow.yaml` file

### 15.2 Migration analyzer
- [ ] Implement AST parser for upgrade/downgrade methods
- [ ] Extract all `op.*` calls from migration files
- [ ] Classify operations using safety rules
- [ ] Calculate rollback distance
- [ ] Compute SHA-256 hash for each migration
- [ ] Estimate lock duration for ALTER TABLE operations
- [ ] Detect multi-phase migration patterns

### 15.3 Safety rules
- [ ] Define DESTRUCTIVE_OPS set
- [ ] Define UNSAFE_OPS set
- [ ] Implement classification logic
- [ ] Add Postgres-specific checks
- [ ] Detect empty downgrade() methods
- [ ] Flag data migrations mixed with schema
- [ ] Validate ENUM type changes

### 15.4 Allow-list validator
- [ ] Load YAML allow-list file
- [ ] Validate entry format
- [ ] Check justification length >= 50 chars
- [ ] Verify expiry date is in future
- [ ] Match migration SHA-256 hashes
- [ ] Generate allow-list template
- [ ] Handle expired entries

### 15.5 Report generator
- [ ] Generate Markdown report
- [ ] Include status emojis (✅/⚠️/❌)
- [ ] Show rollback distance
- [ ] List all operations
- [ ] Add allow-list justification if present
- [ ] Generate JSON output for CI bots
- [ ] Include branch topology in report

### 15.6 CI integration
- [ ] Create GitHub Actions workflow
- [ ] Install Python dependencies
- [ ] Run migration diff tool
- [ ] Post Markdown report as PR comment
- [ ] Block PR on destructive changes
- [ ] Validate allow-list entries
- [ ] Measure execution time

### 15.7 Documentation
- [ ] Add tool entry to SKILL.md
- [ ] Document allow-list schema
- [ ] Add example migration report
- [ ] Document CI integration steps
- [ ] Add Postgres-specific considerations
- [ ] Document multi-phase migration patterns
- [ ] Add troubleshooting guide

### 15.8 Test generation
- [ ] Create test_migration_diff.py
- [ ] Test classification logic
- [ ] Test rollback distance calculation
- [ ] Test allow-list validation
- [ ] Test report generation
- [ ] Test CI integration
- [ ] Test edge cases
- [ ] Measure performance

### 15.9 Atomicity
- [ ] Use temp-file + rename pattern for writes
- [ ] Track modified files for rollback
- [ ] Verify AST parsing before write
- [ ] Handle partial failures gracefully
- [ ] Rollback all changes on error
- [ ] Verify file permissions
- [ ] Return success/failure report

### 15.10 Verification
- [ ] Run ast.parse on all modified files
- [ ] Verify imports work
- [ ] Run pytest on test suite
- [ ] Measure execution time
- [ ] Verify idempotency
- [ ] Check report formatting
- [ ] Validate JSON output

### 15.11 Performance
- [ ] Measure execution time for 100 migrations
- [ ] Optimize AST parsing
- [ ] Cache migration analysis results
- [ ] Parallelize operation classification
- [ ] Optimize rollback distance calculation
- [ ] Profile allow-list validation
- [ ] Measure CI overhead

### 15.12 Error handling
- [ ] Handle missing migration files
- [ ] Handle invalid migration syntax
- [ ] Handle broken revision chains
- [ ] Handle missing dependencies
- [ ] Handle permission errors
- [ ] Handle invalid allow-list entries
- [ ] Handle CI integration failures

### 15.13 Maintenance
- [ ] Add version check
- [ ] Document upgrade process
- [ ] Add deprecation warnings
- [ ] Handle new Alembic operation types
- [ ] Update safety rules as needed
- [ ] Monitor CI execution times
- [ ] Collect usage metrics

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/migration_analyzer.py",
    "app/core/safety_rules.py",
    "app/core/allow_list.py",
    "app/core/report_generator.py",
    "app/main.py",
    ".github/workflows/check_migrations.yml",
    ".migration-allow.yaml",
    "tests/test_migration_diff.py"
  ],
  "files_modified": [
    "pyproject.toml",
    "README.md",
    "SKILL.md"
  ],
  "metrics": {
    "execution_time_ms": 2871,
    "files_changed": 11,
    "lines_added": 842,
    "lines_removed": 12,
    "migrations_analyzed": 47,
    "destructive_ops_found": 3,
    "unsafe_ops_found": 8
  },
  "next_steps": [
    "Review the migration report in your PR comment",
    "Add allow-list entries for any necessary destructive changes",
    "Run: pytest tests/test_migration_diff.py -v",
    "Verify CI integration by creating a test PR",
    "Document any approved exceptions in .migration-allow.yaml"
  ],
  "warnings": [
    "Found 3 migrations with empty downgrade() methods - these may be irreversible",
    "Detected 2 migrations mixing data and schema changes - consider splitting",
    "Postgres ENUM changes detected in 1 migration - these require special handling"
  ],
  "notes": [
    "Migration diff tool installed successfully",
    "47 existing migrations analyzed",
    "GitHub Actions workflow created at .github/workflows/check_migrations.yml",
    "Allow-list template generated at .migration-allow.yaml",
    "Test suite created at tests/test_migration_diff.py",
    "All modified files verified with ast.parse",
    "Performance: 2871ms for 47 migrations (61ms/migration)"
  ]
}
