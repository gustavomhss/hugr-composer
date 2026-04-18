# TOOL-110: add_sbom_guardian

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_sbom_guardian` |
| Category | EXTEND > Testing Tools |
| Complexity | High |
| Dependencies | stdlib only (`pip`, `urllib`, `hashlib`, `json`, `re`) |
| Signature | `add_sbom_guardian(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_sbom_guardian", "description": "Add a Software Bill of Materials (SBOM) generator and lockfile integrity verifier with OSV vulnerability scanning.", "tags": ["extend", "testing_tools"], "entry": "add_sbom_guardian"}` |
| Files created (typical) | 3 — `scripts/__init__.py`, `scripts/generate_sbom.py`, `scripts/verify_lockfile.py` |
| Files modified (typical) | 1 — `app/core/config.py` |

---

## 2. Purpose

The `fastapi_add_sbom_guardian` tool installs a production-grade Software Bill of Materials (SBOM) generation and dependency security verification system into a FastAPI project. PCI DSS 4.0 Requirement 6.3 mandates a maintained inventory of bespoke and custom software and third-party components; SOC 2 and NIST SSDF recommend SBOM as a supply-chain security control. Most teams either have no SBOM at all or rely on expensive SAST tools. This tool generates a complete CycloneDX 1.4 JSON SBOM from the live Python environment using `pip inspect --format=json` (stdlib-only, no SBOM library required) and provides a lockfile integrity verifier with dependency confusion detection and CVE scanning via the free OSV Vulnerability Database API.

The tool generates three files. First, `scripts/generate_sbom.py` which: invokes `pip inspect --format=json` to get all installed packages; builds a `component` dict per package with `type="library"`, `name`, `version`, `purl` (`pkg:pypi/name@version` format per PURL spec), and a `hashes` entry with `alg: SHA-256`; assembles a CycloneDX 1.4 JSON envelope (`specVersion: "1.4"`, `bomFormat: "CycloneDX"`, `metadata.timestamp`); computes a whole-SBOM SHA-256 hash (`compute_sbom_hash`); writes to `sbom.cdx.json`; optionally signs with PGP if `--sign` flag passed. Second, `scripts/verify_lockfile.py` which: `hash_lockfile(path)` computes the SHA-256 of the lockfile for tamper detection; `parse_requirements(content)` extracts `(name, version)` pairs via regex; `detect_confusion(packages)` checks each package name against `_INTERNAL_PREFIXES` (`myorg-`, `internal-`, `priv-`) to find dependency confusion risks; `query_osv(packages)` sends a batch POST to the OSV API at `https://api.osv.dev/v1/querybatch` using `urllib.request`; `find_critical_vulns(osv_response)` filters for `CRITICAL` or `HIGH` severity; `verify(lockfile_path)` orchestrates all steps. Third, `scripts/__init__.py` (empty package marker).

The tool patches `app/core/config.py` with `SBOM_FAIL_ON_CRITICAL: bool = True` and `SBOM_LOCKFILE_PATH: str = "requirements.txt"`. All top-level imports in generated scripts are stdlib only — no `pip install` required to run them. The idempotency fingerprint is `generate_sbom` in `scripts/generate_sbom.py`.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | CI budget; measured via `execution_time_ms` |
| Files created | ≥ 3 | SBOM generator, lockfile verifier, `__init__.py` |
| Files modified | ≥ 1 | Config at minimum |
| Max function LOC in generated code | ≤ 50 | Auditable; AST-checked |
| `generate_sbom` execution time | < 30 s | `pip inspect` subprocess |
| `verify_lockfile` execution time | < 60 s | OSV API batch query |
| SBOM hash computation | < 100 ms | SHA-256 of JSON string |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── core/
│   │   └── config.py        # No SBOM_* fields
├── requirements.txt          # No SBOM generated, no CVE scan
└── scripts/
    └── (no sbom or lockfile scripts)
```

The team has no visibility into which versions are deployed, whether any have known CVEs, or whether a dependency confusion attack has occurred.

### 4.2 SBOM generator: AFTER

```python
# scripts/generate_sbom.py
"""Generate a CycloneDX 1.4 SBOM from the current Python environment.

Usage::

    python scripts/generate_sbom.py
    python scripts/generate_sbom.py --sign   # PGP sign the output

Output: sbom.cdx.json (CycloneDX 1.4 JSON format)

PCI DSS 4.0 Req 6.3 compliance: maintain a complete inventory of
all third-party components with version and hash.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _pip_inspect() -> list[dict]:
    """Return installed package info via ``pip inspect --format=json``."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "inspect", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout).get("installed", [])


def build_component(pkg: dict) -> dict:
    """Build a CycloneDX component entry for *pkg*."""
    meta = pkg.get("metadata", {})
    name = meta.get("name", "unknown").lower()
    version = meta.get("version", "0.0.0")
    purl = f"pkg:pypi/{name}@{version}"
    return {
        "type": "library",
        "name": name,
        "version": version,
        "purl": purl,
    }


def compute_sbom_hash(sbom: dict) -> str:
    """Return the SHA-256 hex-digest of the serialised SBOM."""
    raw = json.dumps(sbom, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def generate_sbom(output_path: Path | None = None) -> Path:
    """Generate sbom.cdx.json and return the output path."""
    if output_path is None:
        output_path = Path("sbom.cdx.json")
    packages = _pip_inspect()
    components = [build_component(pkg) for pkg in packages]
    sbom: dict = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "components": components,
    }
    sbom["sbom_hash"] = compute_sbom_hash(sbom)
    output_path.write_text(json.dumps(sbom, indent=2))
    return output_path


def main() -> None:
    sign = "--sign" in sys.argv
    path = generate_sbom()
    print(f"SBOM written to {path}")
    if sign:
        print("PGP signing requested (configure GPG key to enable)")


if __name__ == "__main__":
    main()
```

### 4.3 Lockfile verifier: AFTER

```python
# scripts/verify_lockfile.py
"""Verify lockfile integrity and scan for known vulnerabilities.

Checks:
1. Lockfile SHA-256 hash (tamper detection)
2. Dependency confusion (internal package names on PyPI)
3. OSV vulnerability database scan (CRITICAL/HIGH CVEs)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

_INTERNAL_PREFIXES = ("myorg-", "internal-", "priv-")
_OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"


def hash_lockfile(path: Path) -> str:
    """Return SHA-256 hex-digest of the lockfile content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_requirements(content: str) -> list[tuple[str, str]]:
    """Extract (name, version) pairs from requirements.txt content."""
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)", re.MULTILINE)
    return [(m.group(1), m.group(2)) for m in pattern.finditer(content)]


def detect_confusion(packages: list[tuple[str, str]]) -> list[str]:
    """Return package names that match internal prefixes (confusion risk)."""
    return [
        name
        for name, _ in packages
        if any(name.lower().startswith(p) for p in _INTERNAL_PREFIXES)
    ]


def query_osv(packages: list[tuple[str, str]]) -> dict:
    """Send a batch query to OSV and return the JSON response."""
    queries = [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in packages]
    payload = json.dumps({"queries": queries}).encode()
    req = urllib.request.Request(
        _OSV_BATCH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return {}


def find_critical_vulns(osv_response: dict) -> list[str]:
    """Return vulnerability IDs with CRITICAL or HIGH severity."""
    critical = []
    for result in osv_response.get("results", []):
        for vuln in result.get("vulns", []):
            vid = vuln.get("id", "")
            severity = vuln.get("database_specific", {}).get("severity", "")
            if severity in ("CRITICAL", "HIGH"):
                critical.append(vid)
    return critical


def verify(lockfile_path: Path) -> bool:
    """Run full lockfile verification pipeline."""
    content = lockfile_path.read_text()
    lockfile_hash = hash_lockfile(lockfile_path)
    print(f"Lockfile hash (SHA-256): {lockfile_hash}")
    packages = parse_requirements(content)
    confused = detect_confusion(packages)
    if confused:
        print(f"WARNING: possible dependency confusion: {confused}")
    osv_data = query_osv(packages)
    critical = find_critical_vulns(osv_data)
    if critical:
        print(f"CRITICAL vulnerabilities found: {critical}")
        return False
    return True


def main() -> None:
    lockfile = Path("requirements.txt")
    if not lockfile.exists():
        print(f"Lockfile not found: {lockfile}")
        sys.exit(1)
    ok = verify(lockfile)
    if not ok:
        sys.exit(1)
    print("Lockfile OK")


if __name__ == "__main__":
    main()
```

### 4.4 Config patch (inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- SBOM guardian settings — added by add_sbom_guardian tool ---
    SBOM_FAIL_ON_CRITICAL: bool = True
    SBOM_LOCKFILE_PATH: str = "requirements.txt"
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `"generate_sbom" in scripts/generate_sbom.py` → `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return before any write |
| QS-3 | **Every generated `.py` AST-parses** | `ast.parse` on each created `.py` |
| QS-4 | **No generated function exceeds 50 LOC** | AST walk; all functions kept short |
| QS-5 | **Top-level imports are stdlib only** | No third-party imports at module level in generated scripts |
| QS-6 | **SBOM format is CycloneDX 1.4** | `specVersion: "1.4"`, `bomFormat: "CycloneDX"` |
| QS-7 | **PURL format is `pkg:pypi/name@version`** | `purl` field in every component |
| QS-8 | **Lockfile hashed with SHA-256** | `hashlib.sha256` in `verify_lockfile.py` |
| QS-9 | **OSV batch API used for CVE scanning** | `urllib.request` POST to OSV endpoint |
| QS-10 | **Dependency confusion detection present** | `detect_confusion` with `_INTERNAL_PREFIXES` |
| QS-11 | **`SBOM_FAIL_ON_CRITICAL` defaults to `True`** | Default value `True` in config |
| QS-12 | **`SBOM_*` inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` |
| QS-13 | **`execution_time_ms` is positive** | `_elapsed_ms(start)` on all return paths |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `adapt/extend/testing_tools/test_add_sbom_guardian.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | `test_success_status` |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | `test_idempotent` |
| CC-03 | `dry_run=True` writes zero bytes to filesystem | `before == after` over all `.py` | `test_dry_run` |
| CC-04 | Tool creates at least 3 new files | `len(files_created) >= 3` | `test_files_created_count` |
| CC-05 | Tool modifies at least 1 existing file | `len(files_modified) >= 1` | `test_files_modified_count` |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` | `test_all_py_parse` |
| CC-07 | No generated function exceeds 50 LOC | AST walk, `max_loc <= 50` | `test_no_function_over_50_loc` |
| CC-08 | `SBOM_FAIL_ON_CRITICAL` defaults to `True` inside `class Settings` | String scan + indent check | `test_config_fields_patched` |
| CC-09 | `scripts/generate_sbom.py` exists and contains `generate_sbom` function | File exists + name present | `test_generate_sbom_script_created` |
| CC-10 | SBOM output uses CycloneDX 1.4 format (`specVersion`) | `"1.4"` and `"CycloneDX"` in script | `test_cyclonedx_format` |
| CC-11 | `scripts/verify_lockfile.py` exists with dependency confusion detection | File exists + `detect_confusion` | `test_verify_lockfile_script_created` |
| CC-12 | OSV vulnerability scanning present in `verify_lockfile.py` | `query_osv` + `find_critical_vulns` | `test_osv_scanning` |
| CC-13 | Top-level imports in generated scripts are stdlib only | No third-party at module level | `test_stdlib_only_imports` |
| CC-14 | SHA-256 hash used in `generate_sbom.py` | `"sha256"` or `"SHA-256"` in script | `test_sha256_in_sbom` |
| CC-15 | `next_steps` mentions `sbom`, `python`, or `ci` | Token in lowercased join | `test_next_steps_present` |
| CC-16 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | `test_execution_time_recorded` |
| CC-17 | Two runs leave the project AST-parseable | `ast.parse` after two runs | `test_idempotent_project_still_parses` |
| CC-18 | `SBOM_FAIL_ON_CRITICAL` defaults to `True` | Default is `True` not `False` | `test_sbom_fail_on_critical_default` |
| CC-19 | `purl` field in SBOM component format | `"purl"` in `generate_sbom.py` | `test_purl_field_present` |
| CC-20 | SHA-256 hash function present in SBOM generator | `compute_sbom_hash` or `hashlib.sha256` | `test_hash_function_present` |
| CC-21 | Error raised for invalid `project_dir` | `status="error"` or exception | `test_error_on_invalid_project_dir` |
| CC-22 | `MCP_TOOL["entry"]` matches function name | `MCP_TOOL["entry"] == "add_sbom_guardian"` | `test_mcp_tool_entry_matches_function` |

---

## 7. Definition of Done (DoD)

- [ ] All 22 Completeness Criteria verified by `test_add_sbom_guardian.py`
- [ ] `add_sbom_guardian.py` runs `ast.parse` on every created `.py` before returning success
- [ ] Fingerprint `"generate_sbom" in scripts/generate_sbom.py` triggers `status="no_op"`
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `generate_sbom.py` outputs valid CycloneDX 1.4 JSON with `specVersion: "1.4"` and `purl` per component
- [ ] `compute_sbom_hash` uses `hashlib.sha256`
- [ ] `verify_lockfile.py` uses `urllib.request` for OSV batch API (no `httpx`/`requests`)
- [ ] `detect_confusion` checks `_INTERNAL_PREFIXES`
- [ ] All top-level imports are stdlib
- [ ] `SBOM_FAIL_ON_CRITICAL: bool = True` in config (default True, not False)
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] `execution_time_ms` set on every return path
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SBOM-01 | Tool is ALWAYS idempotent | `"generate_sbom" in generate_sbom.py` → `no_op` | `test_idempotent` |
| INV-SBOM-02 | `dry_run=True` NEVER writes to disk | Early return before write | `test_dry_run` |
| INV-SBOM-03 | Every generated `.py` MUST parse | `ast.parse` loop | `test_all_py_parse` |
| INV-SBOM-04 | SBOM format MUST be CycloneDX 1.4 | `specVersion: "1.4"` in output | `test_cyclonedx_format` |
| INV-SBOM-05 | Every component MUST have a `purl` | `pkg:pypi/name@version` format | `test_purl_field_present` |
| INV-SBOM-06 | SBOM hash MUST use SHA-256 | `hashlib.sha256` in `generate_sbom.py` | `test_sha256_in_sbom` |
| INV-SBOM-07 | Top-level imports MUST be stdlib only | No third-party at module level | `test_stdlib_only_imports` |
| INV-SBOM-08 | `SBOM_FAIL_ON_CRITICAL` MUST default to `True` | Default value check | `test_sbom_fail_on_critical_default` |
| INV-SBOM-09 | `SBOM_*` settings MUST be inside `class Settings` | `_patch_config` anchor | `test_config_fields_patched` |
| INV-SBOM-10 | `ToolResult.execution_time_ms` MUST be positive | `_elapsed_ms(start)` | `test_execution_time_recorded` |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install SBOM guardian into a clean FastAPI project**
- **As a** compliance engineer
- **I want** one tool call to add SBOM generation and CVE scanning
- **So that** the team meets PCI DSS 4.0 Req 6.3
- **Given:** A FastAPI project with `app/core/config.py`
- **When:** `add_sbom_guardian(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (CC-01)
  - ≥ 3 files created (CC-04)
  - Verified by `test_success_status`, `test_files_created_count`

**US-02: Re-run safely**
- **As a** CI job
- **I want** `status="no_op"` on second run
- **Given:** `generate_sbom` already in `scripts/generate_sbom.py`
- **When:** Tool invoked again
- **Then:** `r2.status == "no_op"` — verified by `test_idempotent`

**US-03: Dry-run preview**
- **Given:** Fresh project
- **When:** `add_sbom_guardian(ToolInput(project_dir=..., dry_run=True))`
- **Then:** Zero filesystem changes — verified by `test_dry_run`

**US-04: Config defaults are safe**
- **As a** security-conscious engineer
- **I want** `SBOM_FAIL_ON_CRITICAL` to default to `True`
- **Given:** Config patched
- **When:** Tool runs
- **Then:** `SBOM_FAIL_ON_CRITICAL: bool = True` — verified by CC-18

**US-05: Generated code is auditable**
- **As a** code reviewer
- **I want** all functions ≤ 50 LOC
- **Given:** Tool emitted `generate_sbom.py`, `verify_lockfile.py`
- **When:** AST walk
- **Then:** `max_loc <= 50` — verified by `test_no_function_over_50_loc`

### 9.2 SBOM generation (US-06 .. US-10)

**US-06: Generate CycloneDX 1.4 SBOM**
- **As a** developer
- **I want** `python scripts/generate_sbom.py` to output `sbom.cdx.json`
- **Given:** Python environment with installed packages
- **When:** Script runs
- **Then:** Valid CycloneDX 1.4 JSON with `specVersion: "1.4"` and PURL per component

**US-07: Each component has a PURL**
- **As a** supply chain auditor
- **I want** each dependency identified by a PURL
- **Given:** `fastapi==0.111.0` installed
- **When:** SBOM generated
- **Then:** Component has `purl: "pkg:pypi/fastapi@0.111.0"` — verified by CC-19

**US-08: SBOM has a SHA-256 hash for tamper detection**
- **As a** ops engineer deploying signed artifacts
- **I want** the SBOM itself to have a hash
- **Given:** `compute_sbom_hash(sbom)` present
- **When:** `generate_sbom()` runs
- **Then:** `sbom["sbom_hash"]` is a 64-char hex string — verified by CC-14, CC-20

**US-09: Detect dependency confusion attacks**
- **As a** security engineer
- **I want** packages named `myorg-private-lib` flagged
- **Given:** `detect_confusion` with `_INTERNAL_PREFIXES`
- **When:** `parse_requirements(content)` finds `myorg-lib==1.0`
- **Then:** `detect_confusion([("myorg-lib", "1.0")])` returns `["myorg-lib"]`

**US-10: Flag critical CVEs and fail CI**
- **As a** CI pipeline
- **I want** the lockfile check to exit 1 on CRITICAL CVEs
- **Given:** `SBOM_FAIL_ON_CRITICAL=true` (default)
- **When:** `verify()` finds CRITICAL vulnerabilities via OSV
- **Then:** `verify()` returns `False`; `main()` calls `sys.exit(1)`

### 9.3 Integration (US-11 .. US-13)

**US-11: Use stdlib only**
- **As a** developer in a restricted environment
- **I want** SBOM scripts to run without additional pip installs
- **Given:** Generated scripts have only stdlib imports at module level
- **When:** `python scripts/generate_sbom.py` in fresh venv
- **Then:** Runs without import errors — verified by CC-13

**US-12: Project parseable after two runs**
- **Given:** Tool applied twice
- **When:** `ast.parse` over all `.py`
- **Then:** Zero errors — verified by CC-17

**US-13: Error on invalid project_dir**
- **As a** developer
- **I want** a clear error when `project_dir` doesn't exist
- **Given:** Non-existent path
- **When:** `add_sbom_guardian(ToolInput(project_dir="/nonexistent"))`
- **Then:** `result.status == "error"` — verified by CC-21

---

## 10. Error Handling

| Scenario | Behaviour | Status |
|----------|-----------|--------|
| `project_dir` does not exist | Returns `status="error"`, `error` set | `"error"` |
| `app/core/config.py` absent | `ensure_prerequisites` raises | `"error"` |
| `pip inspect` subprocess fails | `generate_sbom` raises; caller handles | Propagated |
| OSV API unreachable | `query_osv` catches exception, returns `{}` | Silent degradation |
| Lockfile not found | `main()` prints message + `sys.exit(1)` | CLI exit |

---

## 11. Dependencies

| Package | Why needed |
|---------|------------|
| `hashlib` (stdlib) | SHA-256 SBOM hash + lockfile hash |
| `json` (stdlib) | JSON serialisation/deserialisation |
| `subprocess` (stdlib) | `pip inspect --format=json` |
| `urllib.request` (stdlib) | OSV batch API POST |
| `re` (stdlib) | `parse_requirements` regex |
| `pathlib.Path` (stdlib) | File I/O |

No new packages added to `requirements.txt`.

---

## 12. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Dependency confusion attack | `detect_confusion` flags internal-prefixed packages on PyPI |
| Outdated dependencies with CVEs | `query_osv` + `find_critical_vulns` with CRITICAL/HIGH filter |
| SBOM tampering | `compute_sbom_hash` (SHA-256) embedded in SBOM file |
| Subprocess injection | `pip inspect` called with fixed arguments; no user input |

---

## 13. Observability

| Signal | Where |
|--------|-------|
| `execution_time_ms` | `ToolResult.execution_time_ms` |
| Lockfile hash | Printed by `verify_lockfile.py main()` |
| Dependency confusion warnings | `print(f"WARNING: possible dependency confusion: {confused}")` |
| Critical CVE list | `print(f"CRITICAL vulnerabilities found: {critical}")` |
| SBOM output path | `print(f"SBOM written to {path}")` |

---

## 14. Configuration Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SBOM_FAIL_ON_CRITICAL` | `bool` | `True` | When `True`, CI exits 1 on CRITICAL/HIGH CVEs |
| `SBOM_LOCKFILE_PATH` | `str` | `"requirements.txt"` | Path to the lockfile for hash/confusion checks |

---

## 15. Migration / Rollback

**Rollback is mechanical:**
- Delete `scripts/generate_sbom.py` and `scripts/verify_lockfile.py`
- Delete `scripts/__init__.py` if empty
- Remove `SBOM_*` lines from `app/core/config.py`
- Delete `sbom.cdx.json` if generated

No database migrations. No new tables.

---

## 16. Test File Reference

**Location:** `adapt/extend/testing_tools/test_add_sbom_guardian.py`

**Test runner:**
```bash
PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_sbom_guardian.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_sbom_guardian.py
```

**Full test inventory:**

| Test function | CC ID | What it asserts |
|---------------|-------|-----------------|
| `test_success_status` | CC-01 | `result.status == "success"` on fresh project |
| `test_idempotent` | CC-02 | Second run → `status="no_op"`, no file ops |
| `test_dry_run` | CC-03 | `dry_run=True` → zero filesystem changes |
| `test_files_created_count` | CC-04 | `len(files_created) >= 3`, all paths exist |
| `test_files_modified_count` | CC-05 | `len(files_modified) >= 1`, all paths exist |
| `test_all_py_parse` | CC-06 | All generated `.py` pass `ast.parse` |
| `test_no_function_over_50_loc` | CC-07 | No function exceeds 50 LOC |
| `test_config_fields_patched` | CC-08 | `SBOM_FAIL_ON_CRITICAL` inside `class Settings` |
| `test_generate_sbom_script_created` | CC-09 | `generate_sbom.py` exists + `generate_sbom` present |
| `test_cyclonedx_format` | CC-10 | `"1.4"` + `"CycloneDX"` in `generate_sbom.py` |
| `test_verify_lockfile_script_created` | CC-11 | `verify_lockfile.py` + `detect_confusion` present |
| `test_osv_scanning` | CC-12 | `query_osv` + `find_critical_vulns` in file |
| `test_stdlib_only_imports` | CC-13 | No third-party at module level |
| `test_sha256_in_sbom` | CC-14 | `sha256` or `SHA-256` in `generate_sbom.py` |
| `test_next_steps_present` | CC-15 | `next_steps` mentions `sbom`/`python`/`ci` |
| `test_execution_time_recorded` | CC-16 | `execution_time_ms > 0` |
| `test_idempotent_project_still_parses` | CC-17 | Two runs → all `.py` still parse |
| `test_sbom_fail_on_critical_default` | CC-18 | `SBOM_FAIL_ON_CRITICAL` defaults to `True` |
| `test_purl_field_present` | CC-19 | `"purl"` in `generate_sbom.py` |
| `test_hash_function_present` | CC-20 | `compute_sbom_hash` or `hashlib.sha256` in script |
| `test_error_on_invalid_project_dir` | CC-21 | `status="error"` on non-existent project dir |
| `test_mcp_tool_entry_matches_function` | CC-22 | `MCP_TOOL["entry"] == "add_sbom_guardian"` |
