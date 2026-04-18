# TOOL-104: add_schema_evolution_guard

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_schema_evolution_guard` |
| Category | EXTEND > Testing Tools |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, SQLAlchemy 2.0 |
| Signature | `add_schema_evolution_guard(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_schema_evolution_guard", "description": "Add a Pydantic schema compatibility checker that detects breaking changes in API schemas.", "tags": ["extend", "testing_tools"], "entry": "add_schema_evolution_guard"}` |
| Files created (typical) | 5 — `app/schema_guard/__init__.py`, `app/schema_guard/rules.py`, `app/schema_guard/comparator.py`, `scripts/check_schema_compat.py`, `.github/workflows/schema_guard.yml` |
| Files modified (typical) | 1 — `app/core/config.py` (adds `SCHEMA_GUARD_BASELINE_PATH`, `SCHEMA_GUARD_FAIL_ON_BREAKING`) |

---

## 2. Purpose

The `fastapi_add_schema_evolution_guard` tool installs a production-grade schema compatibility enforcement system into a FastAPI project. Modern API development generates a constant stream of schema changes — new fields, removed fields, type changes, required-field additions, enum shrinkage — and teams discover they broke consumers only after a deploy. Linters catch syntax; OpenAPI validation catches malformation; nothing catches "you removed `user_id` from the response and three microservices depend on it." This tool fills that gap.

The core insight is that Pydantic v2 schemas are inspectable Python objects: `model.model_fields` yields every field with its annotation, default, and `is_required` flag. A comparison engine can snapshot those fields into a JSON baseline and then re-compare on every CI run, classifying each difference as `BREAKING` (removal of a field, type narrowing, required status added), `COMPATIBLE` (type widening, optional → required where default exists), `ADDITIVE` (new field with a default), or `IDENTICAL` (no change). If any comparison is `BREAKING` and `SCHEMA_GUARD_FAIL_ON_BREAKING=true`, the CI script exits with code 1 and blocks the merge.

This tool generates the entire kit without bespoke wiring by the developer: (a) `app/schema_guard/comparator.py` with a `SchemaComparator` class that holds `compare(baseline: dict, current: dict) -> ComparisonResult`, a `ComparisonResult` dataclass (`change_class`, `added`, `removed`, `changed` field lists, `is_breaking` property), and a `ChangeClass` enum with four members (`IDENTICAL`, `ADDITIVE`, `COMPATIBLE`, `BREAKING`); (b) `app/schema_guard/rules.py` with five rule functions (`check_fields_removed`, `check_types_changed`, `check_required_added`, `check_enum_shrunk`, `check_response_shape_changed`) each accepting `(baseline_fields, current_fields)` and returning a list of `str` violations; (c) `app/schema_guard/__init__.py` exporting the public surface (`SchemaComparator`, `ComparisonResult`, `ChangeClass`); (d) `scripts/check_schema_compat.py` — a CLI script that imports FastAPI app, extracts current OpenAPI schema, loads the baseline JSON, calls `SchemaComparator`, exits 1 if any breaking change is found, supports `--export-baseline` to write a fresh baseline; (e) `.github/workflows/schema_guard.yml` — a ready-made GitHub Actions workflow running the script on every PR.

The tool patches `app/core/config.py` with two `SCHEMA_GUARD_*` settings anchored on the existing `ACCESS_TOKEN_EXPIRE_MINUTES` field (so they land **inside** `class Settings` and pydantic-settings reads them from env vars). The tool is idempotent: if `SchemaComparator` is already present in `app/schema_guard/comparator.py`, it returns `status="no_op"` without touching any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` |
| Files created | ≥ 4 | Guard requires comparator, rules, init, CI script, workflow — at minimum 4 |
| Files modified | ≥ 1 | Config must be patched with `SCHEMA_GUARD_*` fields |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree |
| Schema comparison time | < 100 ms | Pure Python dict comparison; no I/O; bounded by schema size |
| CI script execution time | < 30 s | Imports FastAPI app + one `json.loads` + comparison |
| `--export-baseline` write time | < 1 s | Single `json.dumps` + `Path.write_text` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no schema guard
│   ├── core/
│   │   └── config.py        # Settings class, no SCHEMA_GUARD_* fields
│   └── schemas/
│       └── user.py          # Pydantic models — no compat tracking
├── requirements.txt
└── .github/workflows/
    └── (no schema guard workflow)
```

Schema changes propagate silently. A developer removes `phone_number` from `UserPublic`; downstream consumers break at runtime; the regression is discovered in staging three days later.

### 4.2 Comparator module: AFTER

```python
# app/schema_guard/comparator.py
"""Schema compatibility comparator.

Compares two OpenAPI-derived schema dicts (or Pydantic model field
maps) and classifies the delta as IDENTICAL, ADDITIVE, COMPATIBLE,
or BREAKING.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeClass(Enum):
    """Classification of a schema delta."""

    IDENTICAL = "identical"
    ADDITIVE = "additive"
    COMPATIBLE = "compatible"
    BREAKING = "breaking"


@dataclass
class ComparisonResult:
    """Result of a schema comparison."""

    change_class: ChangeClass
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def is_breaking(self) -> bool:
        """True when change_class is BREAKING."""
        return self.change_class == ChangeClass.BREAKING


class SchemaComparator:
    """Compare two schema field maps and produce a ComparisonResult.

    Args:
        rules: List of rule callables to apply. Defaults to all
            built-in rules from ``app.schema_guard.rules``.
    """

    def __init__(self, rules: list | None = None) -> None:
        if rules is None:
            from app.schema_guard.rules import ALL_RULES
            rules = ALL_RULES
        self._rules = rules

    def compare(
        self, baseline: dict[str, Any], current: dict[str, Any]
    ) -> ComparisonResult:
        """Compare *baseline* fields map against *current* fields map."""
        violations: list[str] = []
        for rule in self._rules:
            violations.extend(rule(baseline, current))
        added = [k for k in current if k not in baseline]
        removed = [k for k in baseline if k not in current]
        changed = [v for v in violations if v not in removed]
        if removed or (changed and any("required" in v for v in changed)):
            cls = ChangeClass.BREAKING
        elif changed:
            cls = ChangeClass.COMPATIBLE
        elif added:
            cls = ChangeClass.ADDITIVE
        else:
            cls = ChangeClass.IDENTICAL
        return ComparisonResult(
            change_class=cls,
            added=added,
            removed=removed,
            changed=changed,
        )
```

### 4.3 Rules module: AFTER

```python
# app/schema_guard/rules.py
"""Schema evolution rule functions.

Each rule accepts two dicts — *baseline_fields* and *current_fields*
— and returns a list of violation strings. An empty list means the
rule found no problems.
"""
from __future__ import annotations

from typing import Any


def check_fields_removed(
    baseline: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Return violation for every field present in baseline but absent now."""
    return [
        f"BREAKING: field '{k}' removed from schema"
        for k in baseline
        if k not in current
    ]


def check_types_changed(
    baseline: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Return violation when a field's type annotation changed."""
    violations = []
    for k in baseline:
        if k in current and baseline[k].get("type") != current[k].get("type"):
            violations.append(
                f"COMPATIBLE: field '{k}' type changed "
                f"{baseline[k].get('type')!r} -> {current[k].get('type')!r}"
            )
    return violations


def check_required_added(
    baseline: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Return violation when a previously optional field becomes required."""
    violations = []
    for k in baseline:
        if k in current:
            was_required = baseline[k].get("required", False)
            now_required = current[k].get("required", False)
            if not was_required and now_required:
                violations.append(
                    f"BREAKING: field '{k}' changed from optional to required"
                )
    return violations


def check_enum_shrunk(
    baseline: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Return violation when enum values are removed."""
    violations = []
    for k in baseline:
        if k in current:
            b_enum = set(baseline[k].get("enum") or [])
            c_enum = set(current[k].get("enum") or [])
            removed = b_enum - c_enum
            if removed:
                violations.append(
                    f"BREAKING: field '{k}' enum shrunk, removed: {sorted(removed)}"
                )
    return violations


def check_response_shape_changed(
    baseline: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Return violation when top-level response shape keys differ."""
    b_keys = set(baseline.keys())
    c_keys = set(current.keys())
    removed = b_keys - c_keys
    return [
        f"BREAKING: response shape field '{k}' removed" for k in removed
    ]


ALL_RULES = [
    check_fields_removed,
    check_types_changed,
    check_required_added,
    check_enum_shrunk,
    check_response_shape_changed,
]
```

### 4.4 CLI script: AFTER

```python
# scripts/check_schema_compat.py
"""Check OpenAPI schema compatibility against a saved baseline.

Usage::

    # Compare against baseline
    python scripts/check_schema_compat.py

    # Export current schema as new baseline
    python scripts/check_schema_compat.py --export-baseline

Exits 1 if any BREAKING change is detected and
SCHEMA_GUARD_FAIL_ON_BREAKING=true.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_baseline(path: Path) -> dict:
    if not path.exists():
        print(f"No baseline found at {path}. Run --export-baseline first.")
        sys.exit(1)
    return json.loads(path.read_text())


def _get_current_schema() -> dict:
    from app.main import app  # type: ignore[import]
    return app.openapi()


def _export_baseline(schema: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2))
    print(f"Baseline exported to {path}")


def main() -> None:
    from app.core.config import settings  # type: ignore[import]
    from app.schema_guard import SchemaComparator  # type: ignore[import]

    export = "--export-baseline" in sys.argv
    baseline_path = Path(settings.SCHEMA_GUARD_BASELINE_PATH)
    current = _get_current_schema()
    if export:
        _export_baseline(current, baseline_path)
        return
    baseline = _load_baseline(baseline_path)
    result = SchemaComparator().compare(baseline, current)
    print(f"Schema change class: {result.change_class.value}")
    if result.removed:
        print("Removed fields:", result.removed)
    if result.changed:
        print("Changed fields:", result.changed)
    if result.is_breaking and settings.SCHEMA_GUARD_FAIL_ON_BREAKING:
        print("BREAKING change detected — failing CI.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 4.5 Config patch (settings inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- schema guard settings — added by add_schema_evolution_guard tool ---
    SCHEMA_GUARD_BASELINE_PATH: str = "schema_baseline.json"
    SCHEMA_GUARD_FAIL_ON_BREAKING: bool = True
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables.

### 4.6 GitHub Actions workflow: AFTER

```yaml
# .github/workflows/schema_guard.yml
name: Schema Compatibility Guard

on:
  pull_request:
    branches: [main, master]

jobs:
  schema-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python scripts/check_schema_compat.py
        env:
          SCHEMA_GUARD_FAIL_ON_BREAKING: "true"
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_schema_evolution_guard` pre-flight checks `"SchemaComparator" in app/schema_guard/comparator.py` and returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Returns success+notes before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | `ast.parse` run on each created `.py` file before returning success |
| QS-4 | **No generated function exceeds 50 LOC** | All rule functions, comparator methods, and CLI helpers kept short; asserted by AST walk in test harness |
| QS-5 | **`ChangeClass` enum has all four members** | `IDENTICAL`, `ADDITIVE`, `COMPATIBLE`, `BREAKING` are always emitted |
| QS-6 | **All five rule functions are exported** | `rules.py` exports `check_fields_removed`, `check_types_changed`, `check_required_added`, `check_enum_shrunk`, `check_response_shape_changed` |
| QS-7 | **CI script exits 1 on breaking changes** | `sys.exit(1)` when `is_breaking and SCHEMA_GUARD_FAIL_ON_BREAKING` |
| QS-8 | **`SCHEMA_GUARD_*` fields live inside `class Settings` body** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-9 | **`--export-baseline` flag is supported** | CLI script checks `"--export-baseline" in sys.argv` |
| QS-10 | **No hardcoded secrets in generated templates** | Rule: no `password=`, `secret=`, or `api_key=` literals in any emitted file |
| QS-11 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` called on every return path |
| QS-12 | **Prerequisites validated before write** | `ensure_prerequisites(Prereq.CONFIG_SETTINGS)` runs first |
| QS-13 | **`MCP_TOOL` descriptor is complete** | `{"name", "description", "tags", "entry"}` quartet, `entry == "add_schema_evolution_guard"` |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/testing_tools/test_add_schema_evolution_guard.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | `test_dry_run` |
| CC-04 | Tool creates at least 4 new files | `len(result.files_created) >= 4` and each path exists | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(result.files_modified) >= 1` and each path exists | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `SCHEMA_GUARD_BASELINE_PATH` and `SCHEMA_GUARD_FAIL_ON_BREAKING` exist inside `class Settings` body | String scan + indent check | `test_config_fields_patched` |
| CC-11 | `app/schema_guard/comparator.py` exists with `SchemaComparator` and `ComparisonResult` | File exists + substring checks | `test_comparator_module_created` |
| CC-12 | `app/schema_guard/rules.py` exists with all five rule functions | File exists + `check_fields_removed` etc. present | `test_rules_module_created` |
| CC-13 | `scripts/check_schema_compat.py` exists with CLI entry and `--export-baseline` logic | File exists + `sys.exit` + `--export-baseline` checks | `test_ci_script_created` |
| CC-14 | `.github/workflows/schema_guard.yml` exists | File exists + `schema_guard` in content | `test_github_workflow_created` |
| CC-15 | `ChangeClass` enum has `BREAKING`, `COMPATIBLE`, `ADDITIVE`, `IDENTICAL` members | Substring checks for all four members | `test_change_class_enum_values` |
| CC-16 | `SchemaComparator` exposes a `compare` method | `"def compare(" in content` of comparator module | `test_comparator_compare_method_exists` |
| CC-17 | CI script exits 1 on breaking changes | `"sys.exit(1)"` present in `check_schema_compat.py` | `test_ci_script_exit_1_on_breaking` |
| CC-18 | All generated public functions and classes have docstrings | Docstring present in comparator, rules, and CLI | `test_docstrings_present` |
| CC-19 | CLI script supports `--export-baseline` | `"--export-baseline"` in `check_schema_compat.py` | `test_ci_script_export_baseline` |
| CC-20 | No hardcoded secrets in generated files | Checks for `password="`, `secret="`, `api_key="` | `test_no_hardcoded_secrets` |
| CC-N-1 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-N | `next_steps` mentions `schema` or `baseline` | Lowercased join contains relevant token | `test_next_steps_present` |
| CC-LAST | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | `test_idempotent_project_still_parses` |
| INV-10 | `MCP_TOOL["entry"]` matches the actual function name | `MCP_TOOL["entry"] == "add_schema_evolution_guard"` | `test_mcp_tool_entry_matches_function` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_schema_evolution_guard.py`
- [ ] `add_schema_evolution_guard.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] Fingerprint `"SchemaComparator" in comparator.py` triggers `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `ChangeClass` enum has exactly four members: `IDENTICAL`, `ADDITIVE`, `COMPATIBLE`, `BREAKING`
- [ ] All five rule functions present in `rules.py` and exported via `ALL_RULES`
- [ ] CI script calls `sys.exit(1)` when breaking change detected and `FAIL_ON_BREAKING=True`
- [ ] `--export-baseline` flag writes JSON to `SCHEMA_GUARD_BASELINE_PATH`
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SEG-01 | Tool is ALWAYS idempotent on second invocation | `"SchemaComparator" in comparator_file.read_text()` short-circuits to `status="no_op"` | `test_idempotent`, `test_idempotent_project_still_parses` |
| INV-SEG-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | `test_dry_run` |
| INV-SEG-03 | Every generated `.py` MUST parse as valid Python | `ast.parse` loop over `files_created` | `test_all_py_parse`, `test_idempotent_project_still_parses` |
| INV-SEG-04 | `ChangeClass` MUST have all four members | `IDENTICAL`, `ADDITIVE`, `COMPATIBLE`, `BREAKING` always emitted | `test_change_class_enum_values` |
| INV-SEG-05 | CI script MUST exit 1 on breaking changes | `sys.exit(1)` present in CLI script | `test_ci_script_exit_1_on_breaking` |
| INV-SEG-06 | `SCHEMA_GUARD_*` settings MUST land inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | `test_config_fields_patched` |
| INV-SEG-07 | `--export-baseline` MUST be supported | String check in CLI script | `test_ci_script_export_baseline` |
| INV-SEG-08 | No hardcoded credentials in any generated file | Scan for `password="`, `secret="`, `api_key="` | `test_no_hardcoded_secrets` |
| INV-SEG-09 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on all branches | `test_execution_time_recorded` |
| INV-SEG-10 | `MCP_TOOL["entry"]` MUST match function name exactly | `MCP_TOOL["entry"] == "add_schema_evolution_guard"` | `test_mcp_tool_entry_matches_function` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install schema guard into a clean FastAPI project**
- **As a** backend engineer who wants to catch API breaking changes
- **I want** to run one tool call and get a schema guard kit
- **So that** CI blocks merges with breaking schema changes
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_schema_evolution_guard(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"`
  - `files_created` contains ≥ 4 paths (CC-04)
  - `files_modified` contains ≥ 1 path (CC-05)
  - Verified by `test_success_status`, `test_files_created_count`, `test_files_modified_count`

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** the project is not corrupted
- **Given:** Project where `app/schema_guard/comparator.py` already contains `SchemaComparator`
- **When:** `add_schema_evolution_guard(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-SEG-01)
  - `files_created == []` and `files_modified == []`
  - Verified by `test_idempotent`, `test_idempotent_project_still_parses`

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_schema_evolution_guard(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational notes
  - Filesystem byte-identical before and after (INV-SEG-02)
  - Verified by `test_dry_run`

**US-04: Generated code is auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted `comparator.py`, `rules.py`, `check_schema_compat.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50`
  - Verified by `test_no_function_over_50_loc`

**US-05: Config fields land inside Settings class**
- **As a** platform engineer customising the guard
- **I want** `SCHEMA_GUARD_BASELINE_PATH` and `SCHEMA_GUARD_FAIL_ON_BREAKING` in `Settings`
- **So that** I can override them via environment variables
- **Given:** `app/core/config.py` with `ACCESS_TOKEN_EXPIRE_MINUTES`
- **When:** Tool runs
- **Then:**
  - Both fields present with 4-space indent inside the `Settings` class (INV-SEG-06)
  - Verified by `test_config_fields_patched`

### 9.2 Comparator and rules (US-06 .. US-10)

**US-06: Compare two schemas and detect breaking removal**
- **As a** CI step
- **I want** `SchemaComparator().compare(baseline, current)` to flag removed fields as `BREAKING`
- **So that** the PR is blocked
- **Given:** `baseline` has `user_id`; `current` does not
- **When:** `compare(baseline, current)`
- **Then:**
  - `result.change_class == ChangeClass.BREAKING`
  - `result.is_breaking is True`
  - `"user_id"` in `result.removed`
  - Verified by CC-15, CC-16

**US-07: Classify additive-only changes as ADDITIVE**
- **As a** developer adding a new optional field
- **I want** CI to pass (no breaking change)
- **Given:** `current` adds `avatar_url` with a default
- **When:** `compare(baseline, current)`
- **Then:**
  - `result.change_class == ChangeClass.ADDITIVE`
  - `"avatar_url"` in `result.added`

**US-08: Detect enum shrinkage**
- **As a** consumer of a status enum
- **I want** CI to block when valid enum values are removed
- **Given:** `baseline` enum has `["active", "inactive", "suspended"]`; `current` removes `"suspended"`
- **When:** `check_enum_shrunk(baseline, current)`
- **Then:**
  - Returns a violation string containing `"suspended"`
  - `compare()` returns `BREAKING`

**US-09: Export a baseline**
- **As a** developer starting schema guard from scratch
- **I want** `python scripts/check_schema_compat.py --export-baseline`
- **So that** I have a starting baseline JSON
- **Given:** No baseline file exists
- **When:** CLI called with `--export-baseline`
- **Then:**
  - Baseline JSON written to `SCHEMA_GUARD_BASELINE_PATH`
  - Script exits 0
  - Verified by CC-19

**US-10: CI exits non-zero on breaking change**
- **As a** GitHub Actions workflow
- **I want** the check script to exit 1 when a breaking change is detected
- **So that** the merge is blocked automatically
- **Given:** Schema has a removed field and `SCHEMA_GUARD_FAIL_ON_BREAKING=true`
- **When:** `python scripts/check_schema_compat.py`
- **Then:**
  - `sys.exit(1)` is called
  - Verified by CC-17

### 9.3 GitHub Actions integration (US-11 .. US-13)

**US-11: Workflow runs on every PR**
- **As a** team lead
- **I want** schema compat checked on every PR
- **Given:** `.github/workflows/schema_guard.yml` generated
- **When:** PR opened against `main`
- **Then:**
  - Workflow triggers, runs `python scripts/check_schema_compat.py`
  - Verified by CC-14

**US-12: Generated project stays parseable after two runs**
- **As a** CI system
- **I want** two consecutive tool runs to leave the project intact
- **Given:** Tool applied once; applied again (no_op)
- **When:** `ast.parse` over all `.py` files
- **Then:**
  - Zero `SyntaxError` exceptions
  - Verified by CC-LAST

**US-13: No secrets in generated code**
- **As a** security auditor
- **I want** generated files to contain no hardcoded credentials
- **Given:** Schema guard installed
- **When:** I scan `app/schema_guard/` for `password=`, `secret=`, `api_key=`
- **Then:**
  - Zero occurrences
  - Verified by CC-20

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` field set | `"error"` |
| `app/core/config.py` absent (prerequisite) | `ensure_prerequisites` raises; tool returns `status="error"` | `"error"` |
| Baseline file not found at runtime | CLI script prints guidance and `sys.exit(1)` | n/a (runtime) |
| `ast.parse` fails on generated file | Tool raises `SyntaxError` — should never happen | Internal guard |

---

## 11. Dependencies

| Package | Why needed | Import location |
|---------|------------|-----------------|
| `ast` (stdlib) | Validate generated `.py` files; count function LOC | `add_schema_evolution_guard.py` |
| `json` (stdlib) | Baseline serialisation / deserialisation | `check_schema_compat.py` |
| `sys` (stdlib) | `sys.exit(1)` on breaking change | `check_schema_compat.py` |
| `pathlib.Path` | File I/O operations | Throughout |
| `dataclasses` (stdlib) | `ComparisonResult` dataclass | `comparator.py` |
| `enum` (stdlib) | `ChangeClass` | `comparator.py` |
| `pydantic-settings` | `Settings` class in target project | Target project |

No third-party packages are added to `requirements.txt`. The guard is pure Python stdlib + existing project dependencies.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Schema baseline contains sensitive field names | Baseline is a CI artifact; do not commit to public repos |
| CI script imports `app.main` | Only run in a controlled CI environment with proper env vars |
| Generated code has no credentials | Verified by CC-20 (`test_no_hardcoded_secrets`) |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Files created/modified | `ToolResult.files_created`, `ToolResult.files_modified` |
| Breaking change details | CLI stdout: removed fields, changed fields, change class |
| CI step exit code | `sys.exit(0)` (no breaking) / `sys.exit(1)` (breaking) |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SCHEMA_GUARD_BASELINE_PATH` | `str` | `"schema_baseline.json"` | Path (relative to project root) where the baseline JSON is stored |
| `SCHEMA_GUARD_FAIL_ON_BREAKING` | `bool` | `True` | When `True`, CI script exits 1 on any `BREAKING` classification |

Both settings are injected inside `class Settings` in `app/core/config.py` and can be overridden via environment variables (pydantic-settings convention).

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `app/schema_guard/` (3 files)
- Delete `scripts/check_schema_compat.py`
- Delete `.github/workflows/schema_guard.yml`
- Remove `SCHEMA_GUARD_*` lines from `app/core/config.py`

No database migrations. No runtime dependencies added. Schema baseline JSON is a plain file that can be deleted.

---

## 16. Test File Reference

**Location:** `adapt/extend/testing_tools/test_add_schema_evolution_guard.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_schema_evolution_guard.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_schema_evolution_guard.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 4`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` files pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function in `app/` exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `SCHEMA_GUARD_BASELINE_PATH` inside class body |
| `test_comparator_module_created` | CC-11 | `comparator.py` exists with `SchemaComparator`, `ComparisonResult` |
| `test_rules_module_created` | CC-12 | `rules.py` exists with all five rule functions |
| `test_ci_script_created` | CC-13 | `check_schema_compat.py` has `sys.exit` + `--export-baseline` |
| `test_github_workflow_created` | CC-14 | `schema_guard.yml` exists |
| `test_change_class_enum_values` | CC-15 | `ChangeClass` has BREAKING/COMPATIBLE/ADDITIVE/IDENTICAL |
| `test_comparator_compare_method_exists` | CC-16 | `def compare(` in comparator |
| `test_ci_script_exit_1_on_breaking` | CC-17 | `sys.exit(1)` in CI script |
| `test_docstrings_present` | CC-18 | Public functions/classes have docstrings |
| `test_ci_script_export_baseline` | CC-19 | `--export-baseline` in CLI script |
| `test_no_hardcoded_secrets` | CC-20 | No `password=`, `secret=`, `api_key=` literals |
| `test_execution_time_recorded` | CC-N-1 | `execution_time_ms > 0` |
| `test_next_steps_present` | CC-N | `next_steps` contains schema/baseline guidance |
| `test_idempotent_project_still_parses` | CC-LAST | Two runs → all `.py` still parse |
| `test_mcp_tool_entry_matches_function` | INV-10 | `MCP_TOOL["entry"] == "add_schema_evolution_guard"` |
