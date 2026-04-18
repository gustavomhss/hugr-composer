# Meta-Tools Specification

> Tools that build tools. Tools that test tools. Tools that audit tools.
> The factory that produces the factory.

---

## Why

Building 100 tools required:
- Manually briefing agents with 350-line MEGA_BRIEFING
- Manually auditing every delivery (patterns, _elapsed_ms, lazy imports)
- Manually wiring into 6 test infrastructure files
- Manually writing behavior scenarios
- Manually writing specs

With meta-tools, building the NEXT 100 tools becomes:
```python
# 1. Generate the tool from a description
fastapi_create_tool(
    name="add_webhook_retry",
    category="infrastructure",
    description="Exponential retry for failed outbound webhooks",
    generates=["app/webhooks/retry.py", "app/webhooks/config.py"],
    config_fields=["WEBHOOK_RETRY_MAX", "WEBHOOK_RETRY_BACKOFF"],
    sdk_deps=["httpx"],  # lazy import
)

# 2. Auto-generate tests
fastapi_create_tests(tool_path="adapt/extend/infrastructure/add_webhook_retry.py")

# 3. Validate everything
fastapi_audit_tool(tool_path="adapt/extend/infrastructure/add_webhook_retry.py")

# 4. Generate spec
fastapi_create_spec(tool_path="adapt/extend/infrastructure/add_webhook_retry.py")
```

---

## 7 Meta-Tools

### META-001: fastapi_create_tool

**What it does:** Generates a complete, pattern-compliant tool file from a structured description.

**Input:**
```python
ToolBlueprint(
    name="add_webhook_retry",
    tool_id="TOOL-125",
    category="infrastructure",       # → adapt/extend/infrastructure/
    description="Exponential retry for failed outbound webhooks",
    
    # What the tool generates
    files_to_create=[
        FileTemplate(
            path="app/webhooks/retry_engine.py",
            class_name="RetryEngine",
            methods=["schedule_retry", "execute_retry", "get_retry_status"],
            docstring="Exponential backoff retry engine for webhooks.",
        ),
        FileTemplate(
            path="app/webhooks/retry_config.py",
            class_name="RetryConfig",
            methods=["from_settings"],
        ),
        FileTemplate(
            path="app/api/routes/webhook_retry.py",
            endpoints=[
                Endpoint("GET", "/webhooks/retries", "list pending retries"),
                Endpoint("POST", "/webhooks/retries/{id}/retry-now", "force immediate retry"),
            ],
        ),
    ],
    
    # Config fields injected into Settings
    config_fields=[
        ConfigField("WEBHOOK_RETRY_MAX_ATTEMPTS", "int", "5"),
        ConfigField("WEBHOOK_RETRY_BACKOFF_BASE_S", "int", "30"),
        ConfigField("WEBHOOK_RETRY_BACKOFF_MAX_S", "int", "3600"),
    ],
    
    # Optional SDK dependencies (lazy import)
    sdk_deps=["httpx"],
    
    # Prerequisites
    prereqs=["CONFIG_SETTINGS", "REQUIREMENTS_TXT", "ROUTES_INIT"],
    
    # Idempotency fingerprint
    fingerprint_class="RetryEngine",
    fingerprint_file="app/webhooks/retry_engine.py",
    
    # Has migration?
    has_migration=False,
    
    # Patches main.py?
    patches_main=False,
)
```

**Output:** A complete `add_webhook_retry.py` with:
- `from __future__ import annotations` + `import ast`
- `MCP_TOOL` dict (auto-generated from name/description/category)
- `ensure_prerequisites()` with correct Prereqs
- Idempotency guard checking fingerprint
- `dry_run` branch
- All file writers with `textwrap.dedent`
- ast.parse validation loop
- `_elapsed_ms(start)` on ALL return paths
- Config patching with 4-space indent
- Lazy SDK imports in generated code

**Generated files:** `adapt/extend/{category}/add_{name}.py`

---

### META-002: fastapi_create_tests

**What it does:** Reads a tool file and auto-generates structural + behavior test files.

**Input:** Path to tool file

**Output:** Two files:
1. `test_add_{name}.py` — ≥22 structural tests covering all CCs
2. `test_add_{name}_behavior.py` — ≥8 behavior tests (ASGI transport boot, endpoint checks, quality verification)

**How it works:**
1. Parse the tool source with AST
2. Extract: MCP_TOOL name, entry function, config fields, files created, routes registered
3. Generate CC-01 through CC-N based on what the tool does:
   - Always: success, idempotent, dry_run, files_created, files_modified, all_py_parse, no_function_over_50_loc
   - If config fields: config_fields_patched
   - If models: models_init_patched
   - If routes: routes_registered
   - If requirements: requirements_patched
   - Always: execution_time, next_steps, idempotent_still_parses
   - Domain-specific: one test per created file checking key content
4. Generate behavior test:
   - Patch db.py to SQLite
   - Patch idempotency to stub
   - Boot via ASGI transport
   - Test /healthz → 200
   - Test domain endpoints
   - Verify lazy imports via AST
   - Verify max LOC ≤ 50
   - Verify ruff F401 clean

---

### META-003: fastapi_audit_tool

**What it does:** Runs ALL quality checks on a tool and returns a pass/fail report.

**Checks (automated, not trust-based):**
1. `import ast` present
2. `MCP_TOOL` dict with 4 keys, entry matches function
3. `ensure_prerequisites()` called
4. `validate_project_dir` error return has `_elapsed_ms`
5. Idempotency guard → `no_op` (fingerprint exists in generated code)
6. `dry_run` returns before any `write_text()`
7. `_elapsed_ms(start)` on ALL return paths (counted via AST, not grep)
8. `ast.parse` validation loop before success return
9. `textwrap.dedent` on all template strings
10. Every generated function ≤ 50 LOC (actually generates project + checks)
11. Optional SDK imports lazy (AST walk on generated code)
12. No dead imports (ruff F401 on generated code)
13. Config fields 4-space indent
14. All created `.py` files parse
15. Tests exist and pass

**Output:**
```json
{
  "tool": "add_webhook_retry",
  "verdict": "PASS",
  "checks": 15,
  "passed": 15,
  "failed": 0,
  "details": [
    {"check": "import_ast", "passed": true},
    {"check": "mcp_tool_entry", "passed": true},
    ...
  ]
}
```

---

### META-004: fastapi_validate_tool

**What it does:** Goes beyond audit — generates a REAL project, applies the tool, and verifies the generated code works at runtime.

**Steps:**
1. Generate fixture project
2. Apply tool
3. Patch db.py to SQLite
4. Boot via ASGI transport
5. Hit every generated endpoint
6. Verify response shapes
7. Check generated classes have expected methods
8. Verify lazy imports via AST walk
9. Run ruff on generated code
10. Report pass/fail with evidence

**This is `verify_tool()` from `delivery_contract_v3.py` packaged as an MCP tool.**

---

### META-005: fastapi_create_spec

**What it does:** Reads a tool file + test file and generates the 16-section formal specification.

**Input:** Tool path + test path

**Output:** `specs/TOOL-{NNN}-add_{name}.md` with:
1. Overview (auto-generated from MCP_TOOL dict)
2. Purpose (from tool docstring)
3. Performance SLOs (from config fields + file counts)
4. Code Examples (extracted from tool templates via AST)
5. Quality Standards (standard template)
6. Completeness Criteria (auto-mapped from test function names)
7. DoD (generated from checks)
8. Invariants (standard + tool-specific)
9. User Stories (5 generated from description)
10. Test Plan (auto-mapped from test file)
11. Interaction Matrix (from config fields + file paths)
12. Rollback (from files created/modified)
13. Edge Cases (generated from type analysis)
14. Acceptance Criteria (from CCs)
15. Implementation Checklist (from tool structure)
16. Documentation Output (from next_steps)

---

### META-006: fastapi_wire_tool

**What it does:** Adds a tool to ALL test infrastructure files automatically.

**Modifies:**
- `tests/test_boot.py` — add entry to EXTEND_TOOLS
- `tests/test_boot_chains.py` — add to ALL_TOOLS_FORWARD
- `tests/test_stress.py` — add to _ALL_TOOLS
- `tests/property_tests.py` — add to _TOOL_REGISTRY
- `tests/test_cross_composition.py` — add to ALL_EXTEND + _CONFIG_PATCHERS
- `ci.sh` — update count labels

**Input:** Tool name + module path
**Output:** All 6 files modified, counts updated

---

### META-007: fastapi_test_tool

**What it does:** Runs ALL tests for a specific tool and returns results.

**Runs:**
1. Structural tests (`pytest test_add_{name}.py`)
2. Behavior tests (`pytest test_add_{name}_behavior.py`)
3. Pattern audit (META-003)
4. Runtime validation (META-004)
5. Boot test (generate + apply + boot)
6. Property tests (idempotency, dry_run, parse, contract)

**Output:**
```json
{
  "tool": "add_webhook_retry",
  "structural": {"total": 22, "passed": 22, "failed": 0},
  "behavior": {"total": 8, "passed": 8, "failed": 0},
  "audit": {"checks": 15, "passed": 15},
  "validation": {"boot": true, "endpoints": 3, "all_200": true},
  "properties": {"idempotent": true, "dry_run_pure": true, "parses": true},
  "verdict": "PASS"
}
```

---

## The Pipeline

With these 7 meta-tools, building a new tool becomes:

```bash
# Step 1: Create the tool from a blueprint
fastapi_create_tool(blueprint)

# Step 2: Auto-generate tests  
fastapi_create_tests(tool_path)

# Step 3: Audit patterns
fastapi_audit_tool(tool_path)  # fix if fails

# Step 4: Validate runtime
fastapi_validate_tool(tool_path)  # fix if fails

# Step 5: Wire into test infra
fastapi_wire_tool(name, module)

# Step 6: Run full test suite
fastapi_test_tool(tool_path)  # must be all green

# Step 7: Generate spec
fastapi_create_spec(tool_path, test_path)
```

**From description to fully tested + documented tool in 7 commands.**
No agent briefing. No manual audit. No wiring. No spec writing.

---

## Implementation Priority

1. **META-003 (audit)** — highest value, replaces manual pattern checking
2. **META-006 (wire)** — eliminates the most tedious manual step
3. **META-002 (create_tests)** — auto-generates from tool structure
4. **META-001 (create_tool)** — the big one, generates tools from blueprints
5. **META-005 (create_spec)** — auto-generates documentation
6. **META-004 (validate)** — runtime verification
7. **META-007 (test_tool)** — orchestrates everything
