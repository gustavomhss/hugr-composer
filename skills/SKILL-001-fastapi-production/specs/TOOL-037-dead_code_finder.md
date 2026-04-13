# TOOL-037: dead_code_finder

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_dead_code_finder` |
| Category | OPERATE > Code Quality |
| Complexity | Medium |
| Dependencies | FastAPI, vulture, PyYAML |
| Signature | `dead_code_finder(project_dir: str, confidence_threshold: int = 80, include_routes: bool = True, exclude_patterns: list[str] \| None = None, allow_list_file: str = ".deadcode-allow.yaml") -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/app/project`)<br>`confidence_threshold`: Minimum 0-100 score to report (default: 80)<br>`include_routes`: Scan for orphan FastAPI routes (default: True)<br>`exclude_patterns`: Path globs to skip (e.g. `["tests/*", "migrations/*"]`)<br>`allow_list_file`: Path to YAML exceptions file (default: project root) |

## 2. Purpose

The `fastapi_dead_code_finder` identifies unused code — functions, classes, variables, imports, and unreachable FastAPI routes — in production codebases and lets teams prune with confidence instead of leaving the tech debt to rot. Plain `vulture` catches most of it but generates false positives on every Python web framework: a handler that is referenced only via `@app.get("/items")` looks "unused" to vulture because no other code calls it, same for a SQLAlchemy model referenced only via `relationship("Order")` as a string, a Pydantic schema used only as `response_model=UserOut`, an Alembic migration `upgrade()`/`downgrade()` pair, or a pytest fixture discovered by decorator. This tool extends the vulture AST walker with **framework-awareness plugins** that understand FastAPI decorators, SQLAlchemy event listeners and relationships, Pydantic response models and validators, pytest collection, and CLI entry points in `pyproject.toml` — so real dead code stands out and the framework's legitimate usages never generate noise.

The generator produces a `scripts/dead_code_finder.py` CLI with per-framework plugin hooks, a `.deadcode-allow.yaml` schema where every intentional dead entry (plugin hooks, public API surface, planned-deprecation code) carries a justification + reviewer + expiry, confidence scoring so teams can tackle the 100-confidence findings first before auditing the 60-confidence ones, an incremental `--changed-only` mode that runs on PRs and only flags NEW dead code (never pre-existing — adoption is painless), and a CI workflow that posts an inline PR comment with the delta. Key design decisions: **framework-aware from day one** — the tool ships with FastAPI, SQLAlchemy, Pydantic, pytest, and Alembic plugins enabled by default so the first run surfaces real findings instead of hundreds of framework false positives; **confidence-threshold gate** — only CRITICAL (100-confidence: unreachable-after-return) and HIGH (90-confidence: unused import/function in internal module) findings block the PR by default, MEDIUM and LOW are reports-only so noise never kills trust in the gate; **allowlist is explicit and expiry-bound** — every suppression has a reason, a reviewer, and a date so it cannot silently cover rotted code forever; **dynamic dispatch is flagged low-confidence** — `getattr(module, name)` patterns are impossible for AST to resolve, so the tool reports them as "likely used, verify manually" rather than either false-positive dead or silently ignoring; **integration with TOOL-035 blast_radius** so reviewers can instantly query "is this actually reachable from any route?" before deleting a flagged symbol.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s for 50k LOC | Must run in pre-commit hooks without developer friction |
| Files modified | ≤ 2 (pyproject.toml + CI config) | Minimize side effects during installation |
| Files created | ≥ 7 (scanner, plugin, workflow, etc.) | Complete solution requires multiple artifacts |
| AST walk time | < 2s | Core analysis must be faster than full test suite |
| Confidence scoring | < 500ms | Secondary scoring shouldn't dominate runtime |
| Report generation | < 200ms | Fast feedback for CI annotations |
| Migration runtime | 0s — no DB changes | Pure static analysis tool |
| False positive rate | < 5% for confidence ≥80 | Balance between noise and missed detections |
| Route detection accuracy | 100% for decorated endpoints | Critical for FastAPI integration safety |

---

## 4. Code Examples (Before / After)

### 4.1 Core scanner: BEFORE
```python
# app/dead_code/scanner.py
import ast
from pathlib import Path
from typing import Dict, List, Set

class CodeScanner:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.used_symbols: Set[str] = set()
        self.dead_code: List[Dict] = []

    def scan_file(self, file_path: Path) -> None:
        with open(file_path) as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.used_symbols.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.used_symbols.add(node.module)

    def scan_project(self) -> None:
        for py_file in self.project_dir.rglob("*.py"):
            if py_file.name.startswith("test_"):
                continue
            self.scan_file(py_file)
```

### 4.2 Core scanner: AFTER
```python
# app/dead_code/scanner.py
import ast
from pathlib import Path
from typing import Dict, List, Set, Optional
from collections import defaultdict

class CodeScanner:
    def __init__(self, project_dir: str, confidence_threshold: int = 80):
        self.project_dir = Path(project_dir)
        self.used_symbols: Set[str] = set()
        self.dead_code: List[Dict] = []
        self.confidence_threshold = confidence_threshold
        self.import_graph = defaultdict(set)
        self.plugins = [FastAPIPlugin(), SQLAlchemyPlugin()]

    def scan_file(self, file_path: Path) -> None:
        with open(file_path) as f:
            tree = ast.parse(f.read())

        self._scan_imports(tree)
        self._scan_fastapi_routes(tree, file_path)
        self._scan_orm_relationships(tree)

        for plugin in self.plugins:
            plugin.visit(tree)
            self.used_symbols.update(plugin.get_used_symbols())

    def _scan_fastapi_routes(self, tree: ast.AST, file_path: Path) -> None:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and 
                isinstance(node.func, ast.Attribute) and
                node.func.attr in {'get', 'post', 'put', 'delete', 'patch'}):
                self._mark_route_usage(node, file_path)

    def _mark_route_usage(self, node: ast.Call, file_path: Path) -> None:
        for kw in node.keywords:
            if kw.arg == 'response_model':
                if isinstance(kw.value, ast.Name):
                    self.used_symbols.add(kw.value.id)
            elif kw.arg == 'dependencies':
                self._scan_dependencies(kw.value)
```

### 4.3 FastAPI plugin (NEW)
```python
# app/dead_code/plugins/fastapi.py
from typing import Set
import ast

class FastAPIPlugin:
    def __init__(self):
        self.used_models: Set[str] = set()
        self.used_schemas: Set[str] = set()
        self.used_dependencies: Set[str] = set()

    def visit(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and 
                isinstance(node.func, ast.Attribute) and
                node.func.attr in {'get', 'post', 'put', 'delete', 'patch'}):
                self.visit_route_decorator(node)

    def visit_route_decorator(self, node: ast.Call) -> None:
        for kw in node.keywords:
            if kw.arg == 'response_model':
                self._extract_schema_name(kw.value)
            elif kw.arg == 'dependencies':
                self._scan_dependencies(kw.value)

    def _extract_schema_name(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self.used_schemas.add(node.id)
        elif isinstance(node, ast.Subscript):
            self._extract_schema_name(node.value)

    def get_used_symbols(self) -> Set[str]:
        return self.used_schemas | self.used_dependencies
```

### 4.4 SQLAlchemy plugin (NEW)
```python
# app/dead_code/plugins/sqlalchemy.py
from typing import Set
import ast

class SQLAlchemyPlugin:
    def __init__(self):
        self.used_models: Set[str] = set()

    def visit(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self._check_relationship(node)
                self._check_foreign_key(node)

    def _check_relationship(self, node: ast.Call) -> None:
        if (isinstance(node.func, ast.Name) and 
            node.func.id == 'relationship' and 
            len(node.args) > 0):
            arg = node.args[0]
            if isinstance(arg, ast.Str):
                self.used_models.add(arg.s.split('.')[0])

    def _check_foreign_key(self, node: ast.Call) -> None:
        if (isinstance(node.func, ast.Name) and 
            node.func.id == 'ForeignKey' and 
            len(node.args) > 0):
            arg = node.args[0]
            if isinstance(arg, ast.Str):
                self.used_models.add(arg.s.split('.')[0])

    def get_used_symbols(self) -> Set[str]:
        return self.used_models
```

### 4.5 Allow-list handler (NEW)
```python
# app/dead_code/allowlist.py
from pathlib import Path
import yaml
from typing import Dict, List, Set
from datetime import datetime

class AllowList:
    def __init__(self, file_path: str = ".deadcode-allow.yaml"):
        self.file_path = Path(file_path)
        self.entries: Dict[str, Dict] = {}
        self.load()

    def load(self) -> None:
        if not self.file_path.exists():
            return

        with open(self.file_path) as f:
            data = yaml.safe_load(f) or {}
            for entry in data.get('allow', []):
                if 'name' in entry:
                    if not self._is_expired(entry):
                        self.entries[entry['name']] = entry

    def _is_expired(self, entry: Dict) -> bool:
        if 'expires' not in entry:
            return False
        return datetime.now() > datetime.fromisoformat(entry['expires'])

    def is_allowed(self, symbol_name: str) -> bool:
        return symbol_name in self.entries

    def get_justification(self, symbol_name: str) -> str:
        return self.entries.get(symbol_name, {}).get('reason', '')
```

### 4.6 Report generator (NEW)
```python
# app/dead_code/reporter.py
from typing import List, Dict
from pathlib import Path
import json
import csv

class ReportGenerator:
    def __init__(self, output_dir: str = "dead_code_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def generate(self, findings: List[Dict], format: str = "markdown") -> Path:
        if format == "markdown":
            return self._generate_markdown(findings)
        elif format == "json":
            return self._generate_json(findings)
        elif format == "csv":
            return self._generate_csv(findings)
        raise ValueError(f"Unknown format: {format}")

    def _generate_markdown(self, findings: List[Dict]) -> Path:
        output_file = self.output_dir / "dead_code.md"
        with open(output_file, "w") as f:
            f.write("# Dead Code Report\n\n")
            f.write("| Confidence | File | Symbol | Type |\n")
            f.write("|------------|------|--------|------|\n")
            for finding in sorted(findings, key=lambda x: (-x['confidence'], x['file'])):
                f.write(
                    f"| {finding['confidence']}% | {finding['file']} | "
                    f"{finding['symbol']} | {finding['type']} |\n"
                )
        return output_file
```

### 4.7 CI integration (NEW)
```python
# app/dead_code/ci.py
from typing import Optional, Dict
import subprocess
from pathlib import Path
import json
import os

class CIIntegration:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.base_ref: Optional[str] = os.getenv("GITHUB_BASE_REF")
        self.head_ref: Optional[str] = os.getenv("GITHUB_HEAD_REF")

    def run_analysis(self) -> Dict:
        cmd = [
            "python", "-m", "app.dead_code.main",
            "--project-dir", str(self.project_dir),
            "--output-format", "json",
            "--confidence-threshold", "80"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.project_dir)
        return json.loads(result.stdout)

    def annotate_pr(self, findings: Dict) -> None:
        for finding in findings.get("findings", []):
            print(f"::warning file={finding['file']},line=1::"
                  f"Dead code detected: {finding['symbol']} "
                  f"(confidence: {finding['confidence']}%)")

    def should_block_pr(self, findings: Dict) -> bool:
        return any(f['confidence'] >= 90 for f in findings.get("findings", []))
```

### 4.8 Migration for results storage
```python
# alembic/versions/0001_create_dead_code_tables.py
"""Create tables for dead code tracking

Revision ID: 0001
Revises: 
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None

def upgrade() -> None:
    op.create_table(
        "dead_code_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("symbol", sa.String(256), nullable=False),
        sa.Column("symbol_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("first_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.Index("ix_dead_code_run_id", "run_id"),
        sa.Index("ix_dead_code_file_path", "file_path"),
    )

    op.create_table(
        "dead_code_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("total_findings", sa.Integer(), nullable=False),
        sa.Column("new_findings", sa.Integer(), nullable=False),
        sa.Column("resolved_findings", sa.Integer(), nullable=False),
        sa.Column("commit_hash", sa.String(40), nullable=True),
    )

def downgrade() -> None:
    op.drop_table("dead_code_findings")
    op.drop_table("dead_code_runs")
```

### 4.9 Main entry point (NEW)
```python
# app/dead_code/main.py
import argparse
from pathlib import Path
from typing import List, Dict
from .scanner import CodeScanner
from .reporter import ReportGenerator
from .allowlist import AllowList

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--confidence-threshold", type=int, default=80)
    parser.add_argument("--output-format", choices=["markdown", "json", "csv"], default="markdown")
    args = parser.parse_args()

    scanner = CodeScanner(
        project_dir=args.project_dir,
        confidence_threshold=args.confidence_threshold
    )
    scanner.scan_project()
    
    allowlist = AllowList()
    findings = [
        f for f in scanner.dead_code 
        if f['confidence'] >= args.confidence_threshold 
        and not allowlist.is_allowed(f['symbol'])
    ]

    reporter = ReportGenerator()
    report_path = reporter.generate(findings, args.output_format)
    print(f"Report generated at: {report_path}")

if __name__ == "__main__":
    main()

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Dead code detection respects confidence threshold** | `CodeScanner` in `app/dead_code/scanner.py` filters findings below `confidence_threshold` before report generation |
| QS-2 | **FastAPI route decorators count as usage** | `FastAPIPlugin` in `app/dead_code/plugins/fastapi.py` visits `@app.*` decorators and marks referenced symbols as used |
| QS-3 | **SQLAlchemy relationships count as usage** | `CodeScanner._scan_orm_relationships()` parses `relationship()` and `ForeignKey` strings in `app/dead_code/scanner.py` |
| QS-4 | **Pydantic schemas in type hints count as usage** | `FastAPIPlugin._extract_schema_name()` in `app/dead_code/plugins/fastapi.py` handles `response_model=` and `Depends()` |
| QS-5 | **Allow-list entries require justification** | `AllowList` class in `app/dead_code/allowlist.py` validates YAML entries contain both `name` and `reason` fields |
| QS-6 | **Dynamic dispatch findings are low confidence** | `CodeScanner` assigns confidence=60 to symbols referenced via `getattr`/`setattr`/`globals()` in `app/dead_code/scanner.py` |
| QS-7 | **Report is deterministic and sorted** | `ReportGenerator._generate_markdown()` sorts findings by confidence descending, file path ascending in `app/dead_code/reporter.py` |
| QS-8 | **CI integration blocks new dead code** | `CIIntegration.check_for_new_dead_code()` compares `base_ref` and `head_ref` reports in `app/dead_code/ci.py` |
| QS-9 | **Tool execution time scales linearly** | `CodeScanner.scan_project()` uses `Path.rglob()` with `exclude_patterns` filtering in `app/dead_code/scanner.py` |
| QS-10 | **Migration tables track historical findings** | `0001_create_dead_code_tables.py` creates `dead_code_findings` and `dead_code_runs` tables with timestamps |
| QS-11 | **Allow-list file is optional but validated** | `AllowList.load()` skips silently if `.deadcode-allow.yaml` missing but validates schema when present |
| QS-12 | **Report formats include Markdown and JSON** | `ReportGenerator.generate()` implements both formats with consistent content in `app/dead_code/reporter.py` |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `CodeScanner` exists at `app/dead_code/scanner.py` | File exists, parses |
| CC-02 | `FastAPIPlugin` exists at `app/dead_code/plugins/fastapi.py` | File exists, contains route decorator visitor |
| CC-03 | `AllowList` exists at `app/dead_code/allowlist.py` | File exists, validates YAML schema |
| CC-04 | `ReportGenerator` exists at `app/dead_code/reporter.py` | File exists, implements markdown + json |
| CC-05 | `CIIntegration` exists at `app/dead_code/ci.py` | File exists, implements git diff analysis |
| CC-06 | Migration creates dead code tracking tables | Inspect `0001_create_dead_code_tables.py` |
| CC-07 | `CodeScanner` respects `confidence_threshold` | grep `self.confidence_threshold` in scanner.py |
| CC-08 | `FastAPIPlugin` handles `response_model=` | grep `response_model` in fastapi.py |
| CC-09 | `FastAPIPlugin` handles `Depends()` | grep `Depends` in fastapi.py |
| CC-10 | `CodeScanner` handles SQLAlchemy relationships | grep `relationship` in scanner.py |
| CC-11 | `CodeScanner` handles dynamic dispatch | grep `getattr` in scanner.py |
| CC-12 | `AllowList` validates YAML schema | grep `allow` in allowlist.py |
| CC-13 | `ReportGenerator` implements markdown format | grep `_generate_markdown` in reporter.py |
| CC-14 | `ReportGenerator` implements json format | grep `_generate_json` in reporter.py |
| CC-15 | `CIIntegration` compares git refs | grep `base_ref` in ci.py |
| CC-16 | Migration tables have proper indexes | Inspect `dead_code_findings` table |
| CC-17 | `CodeScanner` handles `exclude_patterns` | grep `exclude_patterns` in scanner.py |
| CC-18 | `AllowList` skips missing file | grep `exists()` in allowlist.py |
| CC-19 | Existing test suite passes | pytest 0 failures |
| CC-20 | New file `tests/test_dead_code.py` created | File exists |
| CC-21 | All target files verified with `ast.parse` | Tool internal step |
| CC-22 | Tool execution time < 4s | Time measurement |
| CC-23 | AST walk time < 2s | Benchmark T-29 |
| CC-24 | Confidence scoring < 500ms | Benchmark T-28 |
| CC-25 | Report generation < 200ms | Benchmark T-27 |
| CC-26 | Idempotent: re-run leaves same findings | T-26 |
| CC-27 | `__init__.py` re-exports counted as used | grep `__all__` in scanner.py |
| CC-28 | Cyclic dependencies detected | T-25 |
| CC-29 | Dynamic dispatch marked low confidence | T-24 |
| CC-30 | CI integration blocks new dead code | T-19 |
| CC-31 | Allow-list justification required | grep `reason` in allowlist.py |
| CC-32 | Report sorted by confidence desc, path asc | Inspect reporter.py |
| CC-33 | Migration uses proper FK constraints | Inspect `0001_create_dead_code_tables.py` |

## 7. Definition of Done (DoD)

- [ ] All 33 Completeness Criteria verified
- [ ] Test suite passes with 0 failures
- [ ] Performance benchmarks meet SLOs
- [ ] CI integration blocks new dead code
- [ ] Markdown and JSON reports generated
- [ ] Allow-list validation implemented
- [ ] FastAPI route detection implemented
- [ ] SQLAlchemy relationship detection implemented
- [ ] Pydantic schema detection implemented
- [ ] Dynamic dispatch marked low confidence
- [ ] Cyclic dependencies detected
- [ ] `__init__.py` re-exports counted as used
- [ ] Migration tables created and indexed

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DC-01 | Confidence threshold is ALWAYS respected | `CodeScanner` filters findings below `confidence_threshold` before report generation in `app/dead_code/scanner.py` | T-01, T-02 |
| INV-DC-02 | FastAPI route decorators ALWAYS count as usage | `FastAPIPlugin.visit_route_decorator()` marks symbols referenced in `@app.*` decorators as used in `app/dead_code/plugins/fastapi.py` | T-07, T-08 |
| INV-DC-03 | SQLAlchemy relationships ALWAYS count as usage | `CodeScanner._scan_orm_relationships()` parses `relationship()` and `ForeignKey` strings in `app/dead_code/scanner.py` | T-09, T-10 |
| INV-DC-04 | Pydantic schemas in type hints ALWAYS count as usage | `FastAPIPlugin._extract_schema_name()` handles `response_model=` and `Depends()` in `app/dead_code/plugins/fastapi.py` | T-11, T-12 |
| INV-DC-05 | Allow-list entries ALWAYS require justification | `AllowList` validates YAML entries contain both `name` and `reason` fields in `app/dead_code/allowlist.py` | T-13, T-14 |
| INV-DC-06 | Dynamic dispatch findings are ALWAYS low confidence | `CodeScanner` assigns confidence=60 to symbols referenced via `getattr`/`setattr`/`globals()` in `app/dead_code/scanner.py` | T-24, T-25 |
| INV-DC-07 | Report is ALWAYS deterministic and sorted | `ReportGenerator._generate_markdown()` sorts findings by confidence descending, file path ascending in `app/dead_code/reporter.py` | T-26, T-27 |
| INV-DC-08 | CI integration ALWAYS blocks new dead code | `CIIntegration.check_for_new_dead_code()` compares `base_ref` and `head_ref` reports in `app/dead_code/ci.py` | T-19, T-20 |

---

## 9. User Stories

### 9.1 Core detection (US-01 .. US-05)

**US-01: Detect unused imports**
- **As a** developer cleaning up dependencies
- **I want** unused imports flagged
- **So that** I can remove unnecessary dependencies
- **Given:** `app/utils.py` with unused `import datetime`
- **When:** Run `dead_code_finder("/app", confidence_threshold=80)`
- **Then:**
  - Report includes `datetime` import with confidence=90 (INV-DC-01)
  - File path shows `/app/utils.py` (CC-01)
  - Type shows `unused-import`

**US-02: Flag unused functions**
- **As a** codebase maintainer
- **I want** private functions never called to be flagged
- **So that** I can remove dead code
- **Given:** `app/services.py` with `def _helper()` never called
- **When:** Run tool with `confidence_threshold=60`
- **Then:**
  - Report includes `_helper` with confidence=60 (INV-DC-06)
  - File path shows `/app/services.py`
  - Type shows `unused-function`

**US-03: Detect unused classes**
- **As a** team lead reducing tech debt
- **I want** unused classes flagged
- **So that** I can remove unnecessary abstractions
- **Given:** `app/models.py` with unused `class OldModel`
- **When:** Run tool with default threshold
- **Then:**
  - Report includes `OldModel` with confidence=100 (CC-07)
  - File path shows `/app/models.py`
  - Type shows `unused-class`

**US-04: Identify unused variables**
- **As a** developer optimizing memory usage
- **I want** unused variables flagged
- **So that** I can reduce memory overhead
- **Given:** `app/config.py` with `DEBUG = False` never read
- **When:** Run tool with `confidence_threshold=80`
- **Then:**
  - Report includes `DEBUG` with confidence=90
  - File path shows `/app/config.py`
  - Type shows `unused-variable`

**US-05: Respect confidence threshold**
- **As a** developer tuning the tool
- **I want** low-confidence findings filtered out
- **So that** I avoid false positives
- **Given:** Tool run with `confidence_threshold=90`
- **When:** Finding has confidence=85
- **Then:**
  - Finding is excluded from report (INV-DC-01)
  - Log shows `Skipping low-confidence finding`
  - Final report count decreases

### 9.2 FastAPI awareness (US-06 .. US-10)

**US-06: Keep routes referenced via decorators**
- **As a** FastAPI developer
- **I want** routes referenced via `@app.get` to be kept
- **So that** my API endpoints aren't flagged as dead
- **Given:** `app/api.py` with `@app.get("/items")`
- **When:** Run tool with `include_routes=True`
- **Then:**
  - Route handler is marked as used (INV-DC-02)
  - File path shows `/app/api.py`
  - Type shows `route-handler`

**US-07: Preserve models used in response_model**
- **As a** API designer
- **I want** models referenced in `response_model=` to be kept
- **So that** my response schemas aren't flagged as dead
- **Given:** `app/schemas.py` with `ItemSchema` used in `response_model=ItemSchema`
- **When:** Run tool with default settings
- **Then:**
  - `ItemSchema` is marked as used (INV-DC-04)
  - File path shows `/app/schemas.py`
  - Type shows `pydantic-model`

**US-08: Keep dependencies referenced in Depends**
- **As a** FastAPI developer
- **I want** dependencies referenced via `Depends()` to be kept
- **So that** my dependency injection works
- **Given:** `app/dependencies.py` with `get_db` used in `Depends(get_db)`
- **When:** Run tool with default settings
- **Then:**
  - `get_db` is marked as used (CC-09)
  - File path shows `/app/dependencies.py`
  - Type shows `dependency`

**US-09: Preserve SQLAlchemy relationships**
- **As a** database engineer
- **I want** models referenced in `relationship()` to be kept
- **So that** my ORM mappings work
- **Given:** `app/models.py` with `User.orders = relationship("Order")`
- **When:** Run tool with default settings
- **Then:**
  - `Order` model is marked as used (INV-DC-03)
  - File path shows `/app/models.py`
  - Type shows `orm-model`

**US-10: Keep Pydantic schemas used in type hints**
- **As a** API developer
- **I want** schemas referenced in type hints to be kept
- **So that** my type checking works
- **Given:** `app/schemas.py` with `ItemSchema` used in `def create(item: ItemSchema)`
- **When:** Run tool with default settings
- **Then:**
  - `ItemSchema` is marked as used (CC-08)
  - File path shows `/app/schemas.py`
  - Type shows `pydantic-schema`

### 9.3 Allow-list handling (US-11 .. US-15)

**US-11: Allow intentional dead code via YAML**
- **As a** plugin developer
- **I want** to mark plugin hooks as allowed dead code
- **So that** they aren't flagged as unused
- **Given:** `.deadcode-allow.yaml` with `name: plugin_hook`
- **When:** Run tool with default settings
- **Then:**
  - `plugin_hook` is excluded from report (INV-DC-05)
  - Log shows `Allowing plugin_hook per allow-list`
  - Report count decreases

**US-12: Require justification for allow-list entries**
- **As a** code reviewer
- **I want** all allow-list entries to have a reason
- **So that** I can audit intentional dead code
- **Given:** `.deadcode-allow.yaml` missing `reason` field
- **When:** Run tool with default settings
- **Then:**
  - Validation fails with `Missing reason` (CC-12)
  - Exit code is 1
  - Report not generated

**US-13: Handle missing allow-list file**
- **As a** developer running the tool for first time
- **I want** the tool to handle missing allow-list gracefully
- **So that** I don't need to create empty files
- **Given:** No `.deadcode-allow.yaml` exists
- **When:** Run tool with default settings
- **Then:**
  - Tool runs successfully (CC-18)
  - Log shows `No allow-list found`
  - Report generated normally

**US-14: Expire allow-list entries**
- **As a** codebase maintainer
- **I want** to set expiration dates for allow-list entries
- **So that** temporary exceptions don't become permanent
- **Given:** `.deadcode-allow.yaml` with `expires: 2026-01-01`
- **When:** Current date is 2026-01-02
- **Then:**
  - Entry is flagged as expired (CC-12)
  - Report includes expired entry
  - Log shows `Allow-list entry expired`

**US-15: Validate allow-list schema**
- **As a** DevOps engineer
- **I want** the allow-list YAML validated
- **So that** invalid configurations fail fast
- **Given:** `.deadcode-allow.yaml` with invalid YAML
- **When:** Run tool with default settings
- **Then:**
  - Validation fails with `Invalid YAML` (CC-12)
  - Exit code is 1
  - Report not generated

### 9.4 CI integration (US-16 .. US-20)

**US-16: Block PRs with new dead code**
- **As a** CI/CD engineer
- **I want** PRs with new dead code to fail
- **So that** we prevent tech debt accumulation
- **Given:** PR adds unused `def helper()` in `app/utils.py`
- **When:** CI runs `dead_code_finder`
- **Then:**
  - CI job fails (INV-DC-08)
  - Comment shows `New dead code detected`
  - Exit code is 1

**US-17: Generate delta report for PRs**
- **As a** code reviewer
- **I want** to see only new dead code in PRs
- **So that** I can focus on relevant changes
- **Given:** PR modifies `app/services.py`
- **When:** CI runs `dead_code_finder --changed-only`
- **Then:**
  - Report shows only findings in changed files (CC-17)
  - Comment links to delta report
  - Exit code reflects new findings

**US-18: Annotate code with findings**
- **As a** developer reviewing PRs
- **I want** findings annotated in the code
- **So that** I can see exactly where issues are
- **Given:** PR with unused import in `app/utils.py`
- **When:** CI runs `dead_code_finder`
- **Then:**
  - GitHub annotation shows `Unused import` (CC-24)
  - Line number is correct
  - Confidence score shown

**US-19: Handle unchanged dead code**
- **As a** developer making unrelated changes
- **I want** existing dead code not to fail CI
- **So that** I can make safe changes
- **Given:** PR modifies README.md
- **When:** CI runs `dead_code_finder`
- **Then:**
  - CI job passes (CC-26)
  - Log shows `No new dead code`
  - Exit code is 0

**US-20: Generate JSON artifact**
- **As a** CI/CD engineer
- **I want** JSON report artifact
- **So that** I can integrate with other tools
- **Given:** CI pipeline with `dead_code_finder`
- **When:** Run with `--output-format=json`
- **Then:**
  - `dead_code.json` artifact created (CC-14)
  - File contains valid JSON
  - Findings array present

### 9.5 Edge cases (US-21 .. US-25)

**US-21: Handle dynamic dispatch**
- **As a** developer using metaprogramming
- **I want** dynamic dispatch marked low confidence
- **So that** I can review manually
- **Given:** `app/utils.py` with `getattr(obj, method)`
- **When:** Run tool with default settings
- **Then:**
  - Finding marked confidence=60 (INV-DC-06)
  - File path shows `/app/utils.py`
  - Type shows `dynamic-dispatch`

**US-22: Preserve __all__ exports**
- **As a** package maintainer
- **I want** `__all__` exports counted as used
- **So that** my public API isn't flagged
- **Given:** `app/__init__.py` with `__all__ = ["helper"]`
- **When:** Run tool with default settings
- **Then:**
  - `helper` marked as used (CC-27)
  - File path shows `/app/__init__.py`
  - Type shows `__all__-export`

**US-23: Detect cyclic dependencies**
- **As a** architect reviewing imports
- **I want** cyclic dependencies flagged
- **So that** I can break cycles
- **Given:** `app/a.py` imports `app/b.py` which imports `app/a.py`
- **When:** Run tool with default settings
- **Then:**
  - Cycle detected (CC-28)
  - Report shows `a.py <-> b.py`
  - Confidence=100

**US-24: Handle excluded patterns**
- **As a** developer ignoring test files
- **I want** to exclude patterns from analysis
- **So that** test code isn't flagged
- **Given:** `exclude_patterns=["tests/*"]`
- **When:** Run tool with `tests/test_utils.py` present
- **Then:**
  - Test files skipped (CC-17)
  - Log shows `Skipping tests/test_utils.py`
  - Report excludes test findings

**US-25: Ensure tool idempotency**
- **As a** developer running the tool repeatedly
- **I want** identical runs to produce identical results
- **So that** I can trust the output
- **Given:** Unchanged codebase
- **When:** Run tool twice
- **Then:**
  - Reports identical (CC-26)
  - Exit codes match
  - Findings count unchanged

---

## 10. Test Plan

### 10.1 Core detection tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Respect confidence threshold | `app/utils.py` with unused `import datetime` | Run with `confidence_threshold=90` | `datetime` import (confidence=90) included |
| T-02 | Filter low confidence | `app/services.py` with unused `def _helper()` | Run with `confidence_threshold=80` | `_helper` (confidence=60) excluded |
| T-03 | Detect unused imports | `app/config.py` with unused `import os` | Run with default settings | Report includes `os` import with confidence=90 |
| T-04 | Flag unused functions | `app/logic.py` with unused `def calculate()` | Run with default settings | Report includes `calculate` with confidence=100 |
| T-05 | Identify unused classes | `app/models.py` with unused `class LegacyModel` | Run with default settings | Report includes `LegacyModel` with confidence=100 |
| T-06 | Find unused variables | `app/constants.py` with unused `TIMEOUT = 30` | Run with default settings | Report includes `TIMEOUT` with confidence=90 |

### 10.2 FastAPI integration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Preserve route handlers | `app/api.py` with `@app.get("/items")` | Run with `include_routes=True` | Route handler marked as used (INV-DC-02) |
| T-08 | Keep response_model schemas | `app/schemas.py` with `ItemSchema` used in `response_model=` | Run with default settings | `ItemSchema` marked as used (INV-DC-04) |
| T-09 | Preserve SQLAlchemy relationships | `app/models.py` with `User.orders = relationship("Order")` | Run with default settings | `Order` model marked as used (INV-DC-03) |
| T-10 | Keep ForeignKey references | `app/models.py` with `ForeignKey("user.id")` | Run with default settings | `User` model marked as used |
| T-11 | Preserve Depends() functions | `app/deps.py` with `get_db` used in `Depends(get_db)` | Run with default settings | `get_db` marked as used (INV-DC-04) |
| T-12 | Keep Pydantic type hints | `app/schemas.py` with `def create(item: ItemSchema)` | Run with default settings | `ItemSchema` marked as used |

### 10.3 Allow-list handling tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Validate allow-list entries | `.deadcode-allow.yaml` missing `reason` field | Run with default settings | Validation fails with `Missing reason` (INV-DC-05) |
| T-14 | Skip missing allow-list | No `.deadcode-allow.yaml` present | Run with default settings | Tool runs successfully with warning |
| T-15 | Honor allow-list entries | `.deadcode-allow.yaml` with `plugin_hook` allowed | Run with default settings | `plugin_hook` excluded from report |
| T-16 | Reject expired entries | `.deadcode-allow.yaml` with `expires: 2025-01-01` | Current date 2026-01-01 | Entry flagged as expired |
| T-17 | Validate YAML schema | `.deadcode-allow.yaml` with invalid YAML | Run with default settings | Validation fails with `Invalid YAML` |
| T-18 | Require justification | `.deadcode-allow.yaml` with empty `reason` | Run with default settings | Validation fails with `Empty reason` |

### 10.4 CI integration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Block new dead code in PR | PR adds unused `def helper()` | CI runs `dead_code_finder` | CI fails with `New dead code detected` (INV-DC-08) |
| T-20 | Pass with unchanged dead code | PR modifies README.md | CI runs `dead_code_finder` | CI passes with `No new dead code` |
| T-21 | Generate delta report | PR modifies `app/services.py` | CI runs with `--changed-only` | Report shows only findings in changed files |
| T-22 | Create JSON artifact | CI pipeline | Run with `--output-format=json` | `dead_code.json` created with valid findings |
| T-23 | Annotate code in PR | PR with unused import | CI runs `dead_code_finder` | GitHub annotation shows `Unused import` |
| T-24 | Handle dynamic dispatch | `app/utils.py` with `getattr(obj, method)` | Run with default settings | Finding marked confidence=60 (INV-DC-06) |

### 10.5 Edge case tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Detect cyclic dependencies | `app/a.py` imports `app/b.py` imports `app/a.py` | Run with default settings | Cycle detected with confidence=100 |
| T-26 | Ensure idempotency | Unchanged codebase | Run tool twice | Reports identical (INV-DC-07) |
| T-27 | Preserve __all__ exports | `app/__init__.py` with `__all__ = ["util"]` | Run with default settings | `util` marked as used |
| T-28 | Respect exclude_patterns | `exclude_patterns=["tests/*"]` | Run with `tests/test_utils.py` present | Test files skipped |
| T-29 | Benchmark AST walk | Project with 50k LOC | Measure execution time | AST walk < 2s |
| T-30 | Verify report sorting | Multiple findings | Generate report | Findings sorted by confidence desc, path asc (INV-DC-07) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Dead code finder ignores SQLAlchemy soft delete mixins as they're framework-level patterns |
| add_cursor_pagination | No | ✅ Compatible | Pagination utilities are detected as used when referenced in FastAPI route decorators |
| add_search | No | ✅ Compatible | Search index builders are marked as used when called from background tasks |
| add_audit_log | No | ✅ Compatible | Audit log hooks are detected via SQLAlchemy event listeners |
| add_data_export | No | ✅ Compatible | Export formatters are preserved when referenced in route response models |
| add_bulk_operations | No | ✅ Compatible | Bulk operation handlers are detected via FastAPI route decorators |
| add_multi_tenancy | No | ✅ Compatible | Tenant-scoped models are preserved when referenced in relationships |
| add_feature_flags | No | ⚠️ Caveat | Feature flag checks must be allow-listed if they appear unused in static analysis |
| add_api_key_auth | No | ✅ Compatible | Auth middleware is detected as used via FastAPI dependency injection |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 token handlers are preserved when referenced in security schemes |
| add_rbac | No | ✅ Compatible | Permission checks are detected via route dependencies |
| add_mfa | No | ✅ Compatible | MFA verification steps are preserved when referenced in auth flows |
| add_cache_layer | No | ⚠️ Caveat | Cache key builders using dynamic strings must be allow-listed |
| add_outbox_pattern | No | ✅ Compatible | Outbox processors are detected as used when registered as event handlers |
| add_sse | No | ✅ Compatible | SSE endpoint handlers are preserved when referenced in router |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/dead_code/scanner.py
git checkout -- app/dead_code/plugins/fastapi.py
git checkout -- app/dead_code/allowlist.py
git checkout -- app/dead_code/reporter.py
git checkout -- app/dead_code/ci.py
git checkout -- tests/test_dead_code.py
rm -rf app/dead_code/
rm -f .deadcode-allow.yaml
rm -rf dead_code_reports/
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (plugins half-installed, allowlist schema wrong, CI workflow missing), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short app/dead_code/ .deadcode-allow.yaml .github/workflows/

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- .github/workflows/dead-code.yml 2>/dev/null || true
git clean -fd app/dead_code/ .deadcode-allow.yaml \
    tests/test_dead_code.py dead_code_reports/ scripts/dead_code_finder.py

# 3. Verify clean tree
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: massive false-positive sweep from framework blindspot
If the first run reports hundreds of "dead" findings on a framework/library you use that the plugins don't know about (Typer CLI, Celery tasks, custom DI container), do NOT blindly delete — first teach the tool about the framework:
```bash
# 1. Spot-check one finding manually
grep -rn "my_framework.route" src/

# 2. If it's a framework usage the plugin missed, extend the plugin registry
#    Example: add Celery @task awareness
cat >> app/dead_code/plugins/celery.py <<'PY'
from ast import Call, Name, Attribute
def detects_usage(node) -> bool:
    return (isinstance(node, Call)
            and isinstance(node.func, Attribute)
            and node.func.attr in {"task", "shared_task"})
PY

# 3. Re-run the scanner; the false positives should be gone
python -m scripts.dead_code_finder scan src/
```

### Failure mode: dynamic-dispatch heavy codebase causing noise
If the codebase uses `getattr(module, name)` or `importlib.import_module()` pervasively (plugin architectures, feature flags, strategy pattern), the scanner floods the report with "likely dead" entries that are actually reached at runtime:
1. Raise `confidence_threshold` to 90 so only the near-certain findings show up: `--confidence-threshold 90`
2. For each legitimately dynamic pattern, add a module-level `__all__` export OR add the entries to `.deadcode-allow.yaml` with `reason: "reached via dynamic dispatch from plugin_loader.py:42"`
3. Review the allowlist quarterly and remove entries that are no longer needed

### Emergency: tool crashes mid-execution leaving temp files
```bash
find . -name "*.deadcode.bak" -o -name "*.tmp" 2>/dev/null | xargs rm -f
find . -name "*.deadcode.*" -delete
git clean -fd
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Function referenced only via `getattr` | Tool reports with confidence=60 and type=dynamic-dispatch |
| EC-2 | Class used only as type hint | Tool marks as used with confidence=100 via type analysis |
| EC-3 | Variable assigned but never read | Tool flags with confidence=90 and type=unused-variable |
| EC-4 | Function decorator with auto-registration | Requires allow-list entry with justification for plugin system |
| EC-5 | SQLAlchemy event listener | Detected as used via `@event.listens_for` decorator |
| EC-6 | Pytest fixture in test files | Skipped when file matches exclude_patterns=["tests/*"] |
| EC-7 | CLI entry point in pyproject.toml | Must be allow-listed as tool doesn't parse TOML |
| EC-8 | Deprecated public API in __all__ | Counted as used but flagged with warning about deprecation |
| EC-9 | Cyclic imports between files | Detected and reported with confidence=100 and type=cyclic-import |
| EC-10 | Re-export in __init__.py | Counted as used when symbol appears in __all__ |
| EC-11 | All files excluded via patterns | Tool exits with warning: "No files scanned - check exclude_patterns" |
| EC-12 | Empty allow-list file | Tool runs normally with zero allowed exceptions |
| EC-13 | Invalid confidence threshold (e.g. 110) | Tool errors: "confidence_threshold must be 0-100" |
| EC-14 | Non-Python file scanned | Skipped silently with debug log message |
| EC-15 | Syntax error in source file | Tool skips file with warning: "Skipping unparseable file" |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 33 Completeness Criteria verified via checklist  
✅ 2. Test suite passes with 0 failures (pytest tests/test_dead_code.py)  
✅ 3. Performance benchmarks meet SLOs (AST walk <2s, total <4s)  
✅ 4. CI integration blocks PRs with new dead code  
✅ 5. Markdown and JSON reports generated with identical findings  
✅ 6. Allow-list validation rejects entries without justification  
✅ 7. FastAPI route detection preserves decorated endpoints  
✅ 8. SQLAlchemy relationship detection preserves referenced models  
✅ 9. Dynamic dispatch marked with confidence=60  
✅ 10. Developer runs tool on their feature branch, fixes all findings with confidence ≥80, and verifies CI passes  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and is directory  
- [ ] Validate `confidence_threshold` is 0-100  
- [ ] Check for existing `.deadcode-allow.yaml`  
- [ ] Parse `exclude_patterns` into compiled regex objects  
- [ ] Verify Python version ≥3.8 (AST features)  
- [ ] Check for required dependencies (vulture, PyYAML)  
- [ ] Validate FastAPI project structure (app/main.py exists)  

### 15.2 Core scanner setup  
- [ ] Create `app/dead_code/scanner.py` with base `CodeScanner`  
- [ ] Implement AST walker for imports/classes/functions  
- [ ] Add confidence scoring for different detection types  
- [ ] Implement FastAPI route decorator detection  
- [ ] Add SQLAlchemy relationship parser  
- [ ] Handle dynamic dispatch with confidence=60  
- [ ] Add exclude_patterns filtering  

### 15.3 FastAPI plugin  
- [ ] Create `app/dead_code/plugins/fastapi.py`  
- [ ] Implement `response_model` extraction  
- [ ] Handle `Depends()` dependency tracking  
- [ ] Parse route decorators (`@app.get` etc)  
- [ ] Detect Pydantic schemas in type hints  
- [ ] Mark middleware classes as used  
- [ ] Preserve exception handlers registered via `app.add_exception_handler`  

### 15.4 Allow-list handler  
- [ ] Create `app/dead_code/allowlist.py`  
- [ ] Implement YAML schema validation  
- [ ] Add required `name` and `reason` fields  
- [ ] Support optional `expires` date field  
- [ ] Handle missing file gracefully  
- [ ] Add justification lookup method  
- [ ] Implement entry expiration checking  

### 15.5 Report generator  
- [ ] Create `app/dead_code/reporter.py`  
- [ ] Implement Markdown table output  
- [ ] Add JSON serialization  
- [ ] Sort findings by confidence desc, path asc  
- [ ] Generate summary statistics  
- [ ] Colorize confidence levels in terminal  
- [ ] Add timestamp to report metadata  
- [ ] Support output directory creation  

### 15.6 CI integration  
- [ ] Create `app/dead_code/ci.py`  
- [ ] Implement git ref comparison  
- [ ] Add delta reporting for PRs  
- [ ] Support GitHub annotations  
- [ ] Handle CI environment detection  
- [ ] Add exit code based on findings  
- [ ] Implement changed-only mode  

### 15.7 Test generation  
- [ ] Create `tests/test_dead_code.py`  
- [ ] Add core detection tests (T-01..T-06)  
- [ ] Implement FastAPI integration tests (T-07..T-12)  
- [ ] Add allow-list validation tests (T-13..T-18)  
- [ ] Include CI simulation tests (T-19..T-24)  
- [ ] Cover edge cases (T-25..T-30)  
- [ ] Benchmark AST walk performance  
- [ ] Verify idempotency  

### 15.8 Documentation  
- [ ] Add section to `core/KNOWLEDGE.md`  
- [ ] Update `manifest.yaml` with tool entry  
- [ ] Add to `SKILL.md` tools table  
- [ ] Document allow-list format  
- [ ] Explain confidence scoring  
- [ ] Provide CI integration guide  
- [ ] List common false positives  

### 15.9 Atomic operations  
- [ ] Use temp files for all writes  
- [ ] Track modified files for rollback  
- [ ] Verify file parses before commit  
- [ ] Implement clean rollback on error  
- [ ] Preserve file permissions  
- [ ] Handle symlinks correctly  
- [ ] Verify disk space before large operations  

### 15.10 Performance tuning  
- [ ] Benchmark AST walk time  
- [ ] Optimize hot paths with cProfile  
- [ ] Cache parsed ASTs for unchanged files  
- [ ] Parallelize file scanning  
- [ ] Implement early termination  
- [ ] Limit memory usage for large projects  
- [ ] Add progress reporting  

### 15.11 Error handling  
- [ ] Catch and report syntax errors  
- [ ] Handle permission denied cases  
- [ ] Validate YAML schema strictly  
- [ ] Provide helpful error messages  
- [ ] Log warnings for edge cases  
- [ ] Add debug mode for troubleshooting  
- [ ] Implement graceful Ctrl+C handling  

### 15.12 Verification  
- [ ] Run `ast.parse` on all modified files  
- [ ] Verify no new dead code introduced  
- [ ] Check test coverage ≥90%  
- [ ] Validate report formats  
- [ ] Confirm CI blocking works  
- [ ] Test allow-list expiration  
- [ ] Verify cross-platform behavior  

### 15.13 Finalization  
- [ ] Update pyproject.toml dependencies  
- [ ] Add pre-commit hook example  
- [ ] Generate example CI workflow  
- [ ] Create sample allow-list file  
- [ ] Document upgrade path  
- [ ] Add version compatibility matrix  
- [ ] Set up logging configuration  

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/dead_code/scanner.py",
    "app/dead_code/plugins/fastapi.py",
    "app/dead_code/allowlist.py",
    "app/dead_code/reporter.py",
    "app/dead_code/ci.py",
    "tests/test_dead_code.py",
    ".deadcode-allow.yaml.example",
    "docs/dead_code_finder.md"
  ],
  "files_modified": [
    "pyproject.toml",
    ".github/workflows/dead_code_check.yml",
    "app/main.py"
  ],
  "metrics": {
    "execution_time_ms": 3821,
    "files_changed": 11,
    "lines_added": 874,
    "lines_removed": 12,
    "findings_detected": 23,
    "confidence_threshold": 80
  },
  "next_steps": [
    "Review dead_code.md report in dead_code_reports/",
    "Add intentional dead code to .deadcode-allow.yaml with justifications",
    "Install pre-commit hook: echo 'dead_code_finder .' > .git/hooks/pre-commit",
    "Verify CI integration by pushing test branch",
    "Address high-confidence findings (confidence ≥90) first"
  ],
  "warnings": [
    "Dynamic dispatch findings (confidence=60) may require manual review",
    "Allow-list entries without expiration dates may become technical debt"
  ],
  "notes": [
    "Tool installed with confidence threshold 80 (medium strictness)",
    "FastAPI route detection enabled - 14 endpoints marked as used",
    "SQLAlchemy relationship parsing preserved 9 model references",
    "Existing test suite passes: 47/47 tests successful",
    "AST walk completed in 1.8s (meets SLO <2s)",
    "Total execution time 3.8s (meets SLO <4s)"
  ]
}
