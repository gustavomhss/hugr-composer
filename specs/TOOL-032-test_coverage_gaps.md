# TOOL-032: test_coverage_gaps

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_test_coverage_gaps` |
| Category | VERIFY > Test Quality |
| Complexity | Medium |
| Dependencies | pytest, coverage.py, FastAPI project |
| Signature | `test_coverage_gaps(project_dir: str, min_line_pct: float = 85.0, min_branch_pct: float = 75.0, fail_on_regressions: bool = True, baseline_file: str = ".coverage.baseline.json") -> dict` |
| Parameters | `project_dir`: Absolute path to FastAPI project root (e.g. `/code/project`)<br>`min_line_pct`: Minimum acceptable line coverage percentage (default: 85.0)<br>`min_branch_pct`: Minimum acceptable branch coverage percentage (default: 75.0)<br>`fail_on_regressions`: Whether to fail when coverage drops vs baseline (default: True)<br>`baseline_file`: Path to store coverage snapshot (default: `.coverage.baseline.json`) |

## 2. Purpose

The `fastapi_test_coverage_gaps` tool turns a raw coverage report into an actionable, risk-ranked punch list. Line coverage alone is dangerously optimistic — a report that says "87% covered" hides the fact that the 13% uncovered branches are exactly the error-handling paths in `auth/`, the compensation logic in `payments/`, and the cleanup step in `orders/cancel`. This tool runs pytest with `--cov-branch` enabled (branch coverage, not just line), parses the resulting `coverage.xml`, classifies every file in the project by risk (files matching `auth`, `payment`, `admin`, `write`, `delete` get a 2× weight multiplier because they are the ones where a silent bug becomes a data-loss, security, or money-loss incident), and produces a ranked list of gaps where the top of the list is always the code that most deserves a test *next* — not just the code with the lowest percentage.

The generator produces a `.coverage.baseline.json` snapshot (committed to the repo and updated only via explicit `--update-baseline` flag) so regressions are caught even when the aggregate percentage is still green — if a PR drops `auth/token.py` from 95% to 80% but raises `utils/formatters.py` from 60% to 80%, the overall number might stay flat but the gate fails because a high-risk file regressed. Key design decisions: **branch coverage always on** — line coverage hides `if/else` gaps and every real bug lives in an unexercised branch, so making branch the default is non-negotiable; **risk weighting is explicit** in `.coverage-risk-weights.yaml` so teams can tune the multipliers for their domain without editing the tool source; **baseline is diff-only** — the gate only fails on *regressions* not on pre-existing low coverage, so teams can adopt the tool without an immediate backfill; **per-module thresholds** via `[tool.coverage_gaps.thresholds]` let strict modules (`auth/`, `payments/`) set `min=95` while permissive ones (`utils/`, `internal_tools/`) can stay at 70; **GitHub PR annotations** so reviewers see inline comments on the exact uncovered lines, not a summary PDF; and **integration with TOOL-034 performance_baseline** — the same baseline infrastructure (commit, diff, explicit update) is reused so the project only has one "known-good" artifact to reason about.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s (excl. pytest) | Must not slow down CI pipeline |
| Files modified | ≤ 2 (pyproject.toml + .gitignore) | Minimal project intrusion |
| Files created | ≥ 7 (configs + reports) | Complete audit trail |
| Report generation | < 500ms for 5k LOC | Interactive developer feedback |
| Memory overhead | < 50MB during analysis | Lightweight enough for CI runners |
| Baseline diff | < 100ms for 100-file project | Fast regression detection |
| Risk ranking | < 200ms for 50 endpoints | Real-time feedback during development |
| Annotation generation | < 1s for PR comments | GitHub API rate limit compliance |

---

## 4. Code Examples (Before / After)

### 4.1 Coverage configuration: BEFORE
```python
# app/core/coverage_config.py
from pathlib import Path
from typing import Dict, List, Optional

class CoverageConfig:
    """Simple coverage configuration without risk weighting."""
    
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.min_line_pct = 85.0
        self.min_branch_pct = 75.0
        self.exclude_patterns = ["**/__init__.py"]
    
    def get_exclusions(self) -> List[str]:
        """Return patterns to exclude from coverage analysis."""
        return self.exclude_patterns
    
    def should_analyze_file(self, file_path: Path) -> bool:
        """Check if file should be included in coverage analysis."""
        for pattern in self.exclude_patterns:
            if file_path.match(pattern):
                return False
        return True
    
    def check_thresholds(self, line_pct: float, branch_pct: float) -> bool:
        """Check if coverage meets minimum thresholds."""
        return line_pct >= self.min_line_pct and branch_pct >= self.min_branch_pct
```

### 4.2 Coverage configuration: AFTER
```python
# app/core/coverage_config.py
from pathlib import Path
from typing import Dict, List, Optional
import fnmatch
import tomllib

class CoverageConfig:
    """Enhanced coverage configuration with risk weighting and module thresholds."""
    
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.config_file = project_dir / "pyproject.toml"
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from pyproject.toml."""
        defaults = {
            "min_line_pct": 85.0,
            "min_branch_pct": 75.0,
            "risk_weights": [
                {"pattern": "**/auth/**", "weight": 2.0},
                {"pattern": "**/payment/**", "weight": 2.0},
                {"pattern": "**/admin/**", "weight": 1.5},
                {"pattern": "**/*_write.py", "weight": 1.5},
                {"pattern": "**/*_delete.py", "weight": 1.5}
            ],
            "exclude_patterns": [
                "**/__init__.py",
                "**/migrations/**",
                "**/generated/**",
                "**/build/**",
                "**/tests/**"
            ],
            "module_thresholds": {
                "app/api/admin": {"min_line_pct": 95.0, "min_branch_pct": 90.0},
                "app/core/auth": {"min_line_pct": 95.0, "min_branch_pct": 90.0}
            }
        }
        
        if self.config_file.exists():
            with open(self.config_file, "rb") as f:
                config = tomllib.load(f)
                tool_config = config.get("tool", {}).get("coverage_gaps", {})
                defaults.update(tool_config)
        
        self.min_line_pct = defaults["min_line_pct"]
        self.min_branch_pct = defaults["min_branch_pct"]
        self.risk_weights = defaults["risk_weights"]
        self.exclude_patterns = defaults["exclude_patterns"]
        self.module_thresholds = defaults["module_thresholds"]
    
    def get_risk_weight(self, file_path: str) -> float:
        """Calculate risk weight for a file based on configured patterns."""
        for weight_config in self.risk_weights:
            if fnmatch.fnmatch(file_path, weight_config["pattern"]):
                return weight_config["weight"]
        return 1.0
    
    def get_module_thresholds(self, module_path: str) -> Dict[str, float]:
        """Get thresholds for a specific module, falling back to defaults."""
        for pattern, thresholds in self.module_thresholds.items():
            if fnmatch.fnmatch(module_path, pattern):
                return thresholds
        return {"min_line_pct": self.min_line_pct, "min_branch_pct": self.min_branch_pct}
```

### 4.3 Coverage gap analyzer (NEW)
```python
# app/core/coverage_gap_analyzer.py
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import fnmatch

@dataclass
class CoverageGap:
    """Represents an uncovered line or branch with risk context."""
    file_path: str
    line_number: int
    is_branch: bool
    risk_weight: float
    priority_score: float
    function_name: Optional[str] = None
    
    @property
    def gap_type(self) -> str:
        return "branch" if self.is_branch else "line"

class CoverageGapAnalyzer:
    """Parses coverage.xml and identifies high-risk uncovered code."""
    
    def __init__(self, coverage_xml_path: Path, config):
        self.coverage_xml_path = coverage_xml_path
        self.config = config
        self.gaps: List[CoverageGap] = []
    
    def analyze(self) -> Dict:
        """Parse coverage XML and return prioritized gaps."""
        tree = ET.parse(self.coverage_xml_path)
        root = tree.getroot()
        
        for package in root.findall(".//package"):
            package_name = package.get("name", "")
            
            for cls in package.findall(".//class"):
                class_name = cls.get("name", "")
                full_path = f"{package_name}/{class_name}"
                
                # Skip excluded files
                if not self._should_analyze_file(full_path):
                    continue
                
                risk_weight = self.config.get_risk_weight(full_path)
                
                # Analyze lines
                for line in cls.findall(".//line"):
                    hits = int(line.get("hits", "0"))
                    if hits == 0:
                        self._add_gap(
                            file_path=full_path,
                            line_number=int(line.get("number", "0")),
                            is_branch=False,
                            risk_weight=risk_weight,
                            function_name=cls.get("name")
                        )
                
                # Analyze branches
                for line in cls.findall(".//line[@branch='true']"):
                    branch_hits = line.get("condition-coverage", "0%")
                    if "0%" in branch_hits:
                        self._add_gap(
                            file_path=full_path,
                            line_number=int(line.get("number", "0")),
                            is_branch=True,
                            risk_weight=risk_weight,
                            function_name=cls.get("name")
                        )
        
        # Sort by priority (risk_weight * 2 for branches)
        self.gaps.sort(key=lambda g: (-g.priority_score, g.file_path, g.line_number))
        
        return {
            "total_gaps": len(self.gaps),
            "branch_gaps": sum(1 for g in self.gaps if g.is_branch),
            "line_gaps": sum(1 for g in self.gaps if not g.is_branch),
            "prioritized_gaps": self.gaps[:100]  # Top 100
        }
    
    def _should_analyze_file(self, file_path: str) -> bool:
        """Check if file should be included in analysis."""
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return False
        return True
    
    def _add_gap(self, file_path: str, line_number: int, is_branch: bool, 
                 risk_weight: float, function_name: Optional[str]) -> None:
        """Create and add a CoverageGap to the list."""
        priority_multiplier = 2.0 if is_branch else 1.0
        gap = CoverageGap(
            file_path=file_path,
            line_number=line_number,
            is_branch=is_branch,
            risk_weight=risk_weight,
            priority_score=risk_weight * priority_multiplier,
            function_name=function_name
        )
        self.gaps.append(gap)
```

### 4.4 Baseline manager (NEW)
```python
# app/core/baseline_manager.py
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

class BaselineManager:
    """Manages coverage baseline snapshots with regression detection."""
    
    def __init__(self, baseline_file: Path):
        self.baseline_file = baseline_file
        self.baseline_data: Optional[Dict] = None
    
    def load_baseline(self) -> Dict:
        """Load baseline data from file, creating empty if doesn't exist."""
        if not self.baseline_file.exists():
            return self._create_empty_baseline()
        
        try:
            with open(self.baseline_file, "r") as f:
                self.baseline_data = json.load(f)
                return self.baseline_data
        except (json.JSONDecodeError, IOError):
            return self._create_empty_baseline()
    
    def save_baseline(self, coverage_data: Dict, git_sha: Optional[str] = None) -> None:
        """Save current coverage data as new baseline."""
        baseline = {
            "created_at": datetime.utcnow().isoformat(),
            "git_sha": git_sha or "unknown",
            "line_rate": coverage_data.get("line_rate", 0.0),
            "branch_rate": coverage_data.get("branch_rate", 0.0),
            "file_coverage": coverage_data.get("file_coverage", {}),
            "file_hashes": self._compute_file_hashes(coverage_data.get("file_coverage", {}))
        }
        
        self.baseline_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.baseline_file, "w") as f:
            json.dump(baseline, f, indent=2)
        
        self.baseline_data = baseline
    
    def detect_regressions(self, current_coverage: Dict) -> List[Dict]:
        """Detect files where coverage dropped more than 2% vs baseline."""
        baseline = self.load_baseline()
        if not baseline.get("file_coverage"):
            return []
        
        regressions = []
        current_files = current_coverage.get("file_coverage", {})
        
        for file_path, current_stats in current_files.items():
            baseline_stats = baseline["file_coverage"].get(file_path)
            if not baseline_stats:
                continue
            
            current_line = current_stats.get("line_rate", 0.0)
            baseline_line = baseline_stats.get("line_rate", 0.0)
            
            if current_line < baseline_line - 2.0:
                regressions.append({
                    "file": file_path,
                    "current_line_pct": current_line,
                    "baseline_line_pct": baseline_line,
                    "delta": current_line - baseline_line,
                    "regression_type": "line"
                })
            
            current_branch = current_stats.get("branch_rate", 0.0)
            baseline_branch = baseline_stats.get("branch_rate", 0.0)
            
            if current_branch < baseline_branch - 2.0:
                regressions.append({
                    "file": file_path,
                    "current_branch_pct": current_branch,
                    "baseline_branch_pct": baseline_branch,
                    "delta": current_branch - baseline_branch,
                    "regression_type": "branch"
                })
        
        return sorted(regressions, key=lambda x: x["delta"])
    
    def _create_empty_baseline(self) -> Dict:
        """Create an empty baseline structure."""
        return {
            "created_at": datetime.utcnow().isoformat(),
            "git_sha": "unknown",
            "line_rate": 0.0,
            "branch_rate": 0.0,
            "file_coverage": {},
            "file_hashes": {}
        }
    
    def _compute_file_hashes(self, file_coverage: Dict) -> Dict[str, str]:
        """Compute SHA-256 hashes of file coverage data for change detection."""
        hashes = {}
        for file_path, stats in file_coverage.items():
            content = json.dumps(stats, sort_keys=True)
            hashes[file_path] = hashlib.sha256(content.encode()).hexdigest()
        return hashes
```

### 4.5 GitHub annotation generator (NEW)
```python
# app/core/github_annotator.py
from typing import Dict, List
import os

class GitHubAnnotator:
    """Generates GitHub PR annotations and comments for coverage gaps."""
    
    def __init__(self):
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.sha = os.environ.get("GITHUB_SHA", "")
        self.run_id = os.environ.get("GITHUB_RUN_ID", "")
    
    def generate_annotations(self, gaps: List[Dict]) -> List[Dict]:
        """Generate GitHub check run annotations for uncovered lines."""
        annotations = []
        
        for gap in gaps[:50]:  # GitHub limits to 50 annotations per run
            annotation = {
                "path": gap["file_path"],
                "start_line": gap["line_number"],
                "end_line": gap["line_number"],
                "annotation_level": "warning",
                "message": self._format_gap_message(gap),
                "title": f"Untested {gap['gap_type']} (priority: {gap['priority_score']:.1f})"
            }
            annotations.append(annotation)
        
        return annotations
    
    def generate_pr_comment(self, summary: Dict, regressions: List[Dict]) -> str:
        """Generate markdown summary for PR comment."""
        lines = [
            "## 📊 Test Coverage Analysis",
            "",
            f"**Overall Coverage:**",
            f"- Line coverage: `{summary.get('line_rate', 0.0):.1f}%` (target: {summary.get('min_line_pct', 85.0)}%)",
            f"- Branch coverage: `{summary.get('branch_rate', 0.0):.1f}%` (target: {summary.get('min_branch_pct', 75.0)}%)",
            "",
            f"**Gaps Detected:**",
            f"- Total uncovered lines/branches: {summary.get('total_gaps', 0)}",
            f"- High-risk gaps (priority ≥ 2.0): {self._count_high_risk_gaps(summary.get('prioritized_gaps', []))}",
        ]
        
        if regressions:
            lines.extend([
                "",
                "## ⚠️ Coverage Regressions",
                "The following files show coverage drops vs baseline:",
                ""
            ])
            for reg in regressions[:10]:  # Show top 10 regressions
                lines.append(
                    f"- `{reg['file']}`: {reg['regression_type']} coverage "
                    f"dropped from {reg['baseline_line_pct']:.1f}% to "
                    f"{reg['current_line_pct']:.1f}% (Δ{reg['delta']:+.1f}%)"
                )
        
        # Add top 5 high-priority gaps
        high_priority = [g for g in summary.get('prioritized_gaps', []) if g['priority_score'] >= 2.0][:5]
        if high_priority:
            lines.extend([
                "",
                "## 🔴 High-Priority Gaps to Address",
                "These untested paths are in security-critical or state-changing code:",
                ""
            ])
            for gap in high_priority:
                lines.append(
                    f"- `{gap['file_path']}:{gap['line_number']}`: "
                    f"Untested {gap['gap_type']} (risk weight: {gap['risk_weight']:.1f})"
                )
        
        return "\n".join(lines)
    
    def _format_gap_message(self, gap: Dict) -> str:
        """Format annotation message for a coverage gap."""
        risk_level = "HIGH" if gap['risk_weight'] >= 2.0 else "MEDIUM" if gap['risk_weight'] >= 1.5 else "LOW"
        return (
            f"Untested {gap['gap_type']} with {risk_level} risk (weight: {gap['risk_weight']:.1f}). "
            f"This {gap['gap_type']} in {gap.get('function_name', 'unknown function')} "
            f"has not been exercised by tests."
        )
    
    def _count_high_risk_gaps(self, gaps: List[Dict]) -> int:
        """Count gaps with risk weight ≥ 2.0."""
        return sum(1 for g in gaps if g.get('risk_weight', 0) >= 2.0)
```

### 4.6 Main tool implementation (NEW)
```python
# app/main.py
from pathlib import Path
from typing import Dict
import subprocess
import sys
import os

from app.core.coverage_config import CoverageConfig
from app.core.coverage_gap_analyzer import CoverageGapAnalyzer
from app.core.baseline_manager import BaselineManager
from app.core.github_annotator import GitHubAnnotator

def test_coverage_gaps(
    project_dir: str,
    min_line_pct: float = 85.0,
    min_branch_pct: float = 75.0,
    fail_on_regressions: bool = True,
    baseline_file: str = ".coverage.baseline.json"
) -> Dict:
    """
    Main entry point for coverage gap analysis tool.
    
    Args:
        project_dir: Absolute path to FastAPI project root
        min_line_pct: Minimum acceptable line coverage percentage
        min_branch_pct: Minimum acceptable branch coverage percentage
        fail_on_regressions: Whether to fail when coverage drops vs baseline
        baseline_file: Path to store coverage snapshot
    
    Returns:
        Dictionary with analysis results and pass/fail status
    """
    project_path = Path(project_dir)
    
    # 1. Run pytest with coverage
    print("Running pytest with branch coverage...")
    coverage_xml = project_path / "coverage.xml"
    
    pytest_cmd = [
        sys.executable, "-m", "pytest",
        "--cov=app",
        "--cov-branch",
        "--cov-report=xml",
        "--cov-report=term-missing",
        "-q"
    ]
    
    result = subprocess.run(pytest_cmd, cwd=project_path, capture_output=True, text=True)
    if result.returncode != 0 and "no tests collected" not in result.stderr:
        print(f"Pytest failed: {result.stderr}")
        return {"error": "Test execution failed", "passed": False}
    
    # 2. Load configuration
    config = CoverageConfig(project_path)
    
    # 3. Analyze coverage gaps
    analyzer = CoverageGapAnalyzer(coverage_xml, config)
    gap_analysis = analyzer.analyze()
    
    # 4. Check baseline for regressions
    baseline_path = project_path / baseline_file
    baseline_manager = BaselineManager(baseline_path)
    regressions = baseline_manager.detect_regressions({
        "line_rate": gap_analysis.get("line_rate", 0.0),
        "branch_rate": gap_analysis.get("branch_rate", 0.0),
        "file_coverage": gap_analysis.get("file_coverage", {})
    })
    
    # 5. Generate GitHub outputs if in CI
    outputs = {}
    if os.environ.get("GITHUB_ACTIONS"):
        annotator = GitHubAnnotator()
        annotations = annotator.generate_annotations(gap_analysis.get("prioritized_gaps", []))
        pr_comment = annotator.generate_pr_comment(gap_analysis, regressions)
        
        outputs["github_annotations"] = annotations
        outputs["pr_comment"] = pr_comment
        
        # Write annotations to file for GitHub Actions
        annotations_file = project_path / "coverage-annotations.json"
        with open(annotations_file, "w") as f:
            import json
            json.dump(annotations, f)
    
    # 6. Determine pass/fail status
    passed = True
    
    # Check overall thresholds
    if gap_analysis.get("line_rate", 0.0) < min_line_pct:
        print(f"Line coverage {gap_analysis.get('line_rate', 0.0):.1f}% < {min_line_pct}%")
        passed = False
    
    if gap_analysis.get("branch_rate", 0.0) < min_branch_pct:
        print(f"Branch coverage {gap_analysis.get('branch_rate', 0.0):.1f}% < {min_branch_pct}%")
        passed = False
    
    # Check for regressions if enabled
    if fail_on_regressions and regressions:
        print(f"Found {len(regressions)} coverage regressions vs baseline")
        passed = False
    
    return {
        "passed": passed,
        "line_coverage": gap_analysis.get("line_rate", 0.0),
        "branch_coverage": gap_analysis.get("branch_rate", 0.0),
        "total_gaps": gap_analysis.get("total_gaps", 0),
        "regressions": regressions,
        "top_gaps": gap_analysis.get("prioritized_gaps", [])[:10],
        **outputs
    }
```

### 4.7 Test file example: BEFORE
```python
# tests/test_auth.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_login_success():
    """Test successful login."""
    response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "password123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_invalid_password():
    """Test login with wrong password."""
    response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "wrongpassword"
    })
    assert response.status_code == 401

def test_refresh_token():
    """Test token refresh endpoint."""
    # First get a token
    login_response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "password123"
    })
    refresh_token = login_response.json().get("refresh_token")
    
    response = client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert response.status_code == 200
```

### 4.8 Test file example: AFTER
```python
# tests/test_auth.py
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
import pytest

client = TestClient(app)

def test_login_success():
    """Test successful login."""
    response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "password123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert "expires_in" in data

def test_login_invalid_password():
    """Test login with wrong password."""
    response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"

def test_login_nonexistent_user():
    """Test login with non-existent user."""
    response = client.post("/api/v1/auth/login", json={
        "email": "nonexistent@example.com",
        "password": "password123"
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"

def test_login_missing_fields():
    """Test login with missing required fields."""
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com"})
    assert response.status_code == 422
    
    response = client.post("/api/v1/auth/login", json={"password": "password123"})
    assert response.status_code == 422

def test_refresh_token_success():
    """Test successful token refresh."""
    login_response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "password123"
    })
    refresh_token = login_response.json().get("refresh_token")
    
    response = client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_refresh_token_invalid():
    """Test refresh with invalid token."""
    response = client.post("/api/v1/auth/refresh", json={
        "refresh_token": "invalid.token.here"
    })
    assert response.status_code == 401

def test_refresh_token_expired():
    """Test refresh with expired token."""
    with patch("app.core.auth.verify_refresh_token") as mock_verify:
        mock_verify.side_effect = ValueError("Token expired")
        
        response = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "expired.token"
        })
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

def test_logout():
    """Test logout endpoint."""
    # First login
    login_response = client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "password123"
    })
    access_token = login_response.json().get("access_token")
    
    # Logout with token
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    
    # Verify token is now invalid
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 401
```

### 4.9 Migration for coverage baseline storage (NEW)
```python
# alembic/versions/0015_create_coverage_baselines.py
"""Create coverage baseline storage table

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0015'
down_revision = '0014'

def upgrade() -> None:
    # Create coverage_baselines table for historical tracking
    op.create_table(
        'coverage_baselines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), 
                 server_default=sa.text('NOW()'), nullable=False),
        sa.Column('git_commit_sha', sa.String(40), nullable=False),
        sa.Column('git_branch', sa.String(100), nullable=True),
        sa.Column('line_coverage_pct', sa.Float(), nullable=False),
        sa.Column('branch_coverage_pct', sa.Float(), nullable=False),
        sa.Column('total_lines', sa.Integer(), nullable=False),
        sa.Column('covered_lines', sa.Integer(), nullable=False),
        sa.Column('total_branches', sa.Integer(), nullable=False),
        sa.Column('covered_branches', sa.Integer(), nullable=False),
        sa.Column('file_coverage_data', JSONB(), nullable=True),
        sa.Column('high_risk_gaps', sa.Integer(), server_default='0', nullable=False),
        sa.Column('regressions_detected', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('tool_version', sa.String(20), nullable=False, server_default='1.0.0')
    )
    
    # Create index for querying by commit and date
    op.create_index(
        'ix_coverage_baselines_commit_date',
        'coverage_baselines',
        ['git_commit_sha', 'created_at']
    )
    
    op.create_index(
        'ix_coverage_baselines_branch',
        'coverage_baselines',
        ['git_branch', 'created_at']
    )
    
    # Create coverage_gap_details table for storing individual gaps
    op.create_table(
        'coverage_gap_details',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('baseline_id', sa.Integer(), 
                 sa.ForeignKey('coverage_baselines.id', ondelete='CASCADE'),
                 nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('is_branch_gap', sa.Boolean(), nullable=False),
        sa.Column('risk_weight', sa.Float(), nullable=False),
        sa.Column('function_name', sa.String(200), nullable=True),
        sa.Column('gap_priority', sa.Float(), nullable=False)
    )
    
    op.create_index(
        'ix_coverage_gap_details_baseline',
        'coverage_gap_details',
        ['baseline_id', 'gap_priority']
    )
    
    op.create_index(
        'ix_coverage_gap_details_file',
        'coverage_gap_details',
        ['file_path', 'line_number']
    )

def downgrade() -> None:
    op.drop_index('ix_coverage_gap_details_file', table_name='coverage_gap_details')
    op.drop_index('ix_coverage_gap_details_baseline', table_name='coverage_gap_details')
    op.drop_table('coverage_gap_details')
    
    op.drop_index('ix_coverage_baselines_branch', table_name='coverage_baselines')
    op.drop_index('ix_coverage_baselines_commit_date', table_name='coverage_baselines')
    op.drop_table('coverage_baselines')

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Branch coverage is always computed** | `pyproject.toml` enforces `--cov-branch` via pytest configuration in `tool.pytest.ini_options.addopts` |
| QS-2 | **Risk-weighted ranking is deterministic** | `CoverageGapAnalyzer._get_risk_weight()` computes weights using explicit path patterns in `app/core/coverage_gaps.py` |
| QS-3 | **Baseline file is never modified silently** | `CoverageBaseline.save()` requires explicit `--update-baseline` flag via CLI argument parsing in `app/main.py` |
| QS-4 | **Regressions always fail the gate** | `test_coverage_gaps()` function in `app/main.py` enforces `fail_on_regressions=True` by default |
| QS-5 | **Excluded lines never count toward coverage** | `pyproject.toml` defines `exclude_patterns` in `tool.coverage_gaps` section |
| QS-6 | **Reports are reproducible** | `CoverageGapAnalyzer.analyze()` uses deterministic sorting by priority then file path in `app/core/coverage_gaps.py` |
| QS-7 | **Thresholds never apply to excluded files** | `CoverageGapAnalyzer._get_risk_weight()` returns 0 for excluded paths in `app/core/coverage_gaps.py` |
| QS-8 | **GitHub annotations are limited to 50 per PR** | `GitHubAnnotator.create_annotations()` slices gaps list at index 50 in `app/core/github_annotator.py` |
| QS-9 | **Risk weights are configurable** | `pyproject.toml` allows custom `risk_weights` patterns in `tool.coverage_gaps` section |
| QS-10 | **Per-module thresholds override global** | `pyproject.toml` defines module-specific thresholds in `tool.coverage_gaps.thresholds` |
| QS-11 | **Coverage gaps are prioritized by risk** | `CoverageGapAnalyzer.analyze()` multiplies risk weight by branch factor in `app/core/coverage_gaps.py` |
| QS-12 | **Baseline diffs detect >2% regressions** | `CoverageBaseline.diff()` compares current vs baseline with 2% tolerance in `app/core/coverage_baseline.py` |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `CoverageGapAnalyzer` class exists at `app/core/coverage_gaps.py` | File exists, parses |
| CC-02 | `CoverageBaseline` class exists at `app/core/coverage_baseline.py` | File exists, parses |
| CC-03 | `GitHubAnnotator` class exists at `app/core/github_annotator.py` | File exists, parses |
| CC-04 | `pyproject.toml` contains `tool.coverage_gaps` section | File exists, contains section |
| CC-05 | `pyproject.toml` contains `tool.coverage_gaps.thresholds` | File exists, contains section |
| CC-06 | `pyproject.toml` contains `tool.coverage_gaps.exclude_patterns` | File exists, contains section |
| CC-07 | `pyproject.toml` contains `tool.coverage_gaps.risk_weights` | File exists, contains section |
| CC-08 | `coverage.xml` is generated by pytest | File exists after test run |
| CC-09 | `CoverageGapAnalyzer.analyze()` parses `coverage.xml` | Inspect method implementation |
| CC-10 | `CoverageGapAnalyzer._get_risk_weight()` computes weights | Inspect method implementation |
| CC-11 | `CoverageBaseline.load()` reads JSON baseline | Inspect method implementation |
| CC-12 | `CoverageBaseline.save()` writes JSON baseline | Inspect method implementation |
| CC-13 | `CoverageBaseline.diff()` compares current vs baseline | Inspect method implementation |
| CC-14 | `GitHubAnnotator.create_annotations()` generates PR comments | Inspect method implementation |
| CC-15 | `GitHubAnnotator.create_summary_markdown()` generates report | Inspect method implementation |
| CC-16 | `test_coverage_gaps()` function exists in `app/main.py` | File exists, parses |
| CC-17 | `test_coverage_gaps()` returns dict with summary, gaps, regressions | Inspect return value |
| CC-18 | `test_coverage_gaps()` fails on regressions when `fail_on_regressions=True` | T-13, T-14 |
| CC-19 | `test_coverage_gaps()` passes when coverage meets thresholds | T-01, T-02 |
| CC-20 | `test_coverage_gaps()` creates baseline on first run | T-15 |
| CC-21 | `test_coverage_gaps()` respects `--update-baseline` flag | T-16 |
| CC-22 | `test_coverage_gaps()` excludes files matching `exclude_patterns` | T-17 |
| CC-23 | `test_coverage_gaps()` applies risk weights correctly | T-07, T-08 |
| CC-24 | `test_coverage_gaps()` respects per-module thresholds | T-18 |
| CC-25 | `test_coverage_gaps()` limits GitHub annotations to 50 | T-19 |
| CC-26 | `test_coverage_gaps()` handles corrupted baseline gracefully | T-20 |
| CC-27 | `test_coverage_gaps()` detects deleted files | T-21 |
| CC-28 | `test_coverage_gaps()` handles new files with 0% coverage | T-22 |
| CC-29 | `test_coverage_gaps()` excludes test files from coverage | T-23 |
| CC-30 | `test_coverage_gaps()` respects `# pragma: no cover` | T-24 |
| CC-31 | `test_coverage_gaps()` handles conditional imports | T-25 |
| CC-32 | `test_coverage_gaps()` is idempotent | T-26 |
| CC-33 | `test_coverage_gaps()` supports incremental mode | T-27 |

## 7. Definition of Done (DoD)

- [ ] All 33 Completeness Criteria verified
- [ ] All 8 Invariants passing tests
- [ ] `pyproject.toml` configured with coverage thresholds
- [ ] `coverage.xml` generated by pytest
- [ ] Baseline file created on first run
- [ ] GitHub annotations limited to 50 per PR
- [ ] Risk weights applied correctly
- [ ] Per-module thresholds respected
- [ ] Excluded files ignored in coverage
- [ ] Regression detection working with 2% tolerance
- [ ] Idempotent operation verified
- [ ] Incremental mode supported
- [ ] All edge cases handled

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-CG-01 | Branch coverage is ALWAYS computed | `pyproject.toml` enforces `--cov-branch` via pytest configuration | T-01, T-02 |
| INV-CG-02 | Risk-weighted ranking is DETERMINISTIC | `CoverageGapAnalyzer._get_risk_weight()` computes weights using explicit path patterns | T-07, T-08 |
| INV-CG-03 | Baseline file is NEVER modified silently | `CoverageBaseline.save()` requires explicit `--update-baseline` flag | T-15, T-16 |
| INV-CG-04 | Regressions ALWAYS fail the gate | `test_coverage_gaps()` enforces `fail_on_regressions=True` by default | T-13, T-14 |
| INV-CG-05 | Excluded lines NEVER count toward coverage | `pyproject.toml` defines `exclude_patterns` in `tool.coverage_gaps` section | T-17, T-23 |
| INV-CG-06 | Reports are REPRODUCIBLE | `CoverageGapAnalyzer.analyze()` uses deterministic sorting by priority then file path | T-26 |
| INV-CG-07 | Thresholds NEVER apply to excluded files | `CoverageGapAnalyzer._get_risk_weight()` returns 0 for excluded paths | T-17, T-23 |
| INV-CG-08 | GitHub annotations are LIMITED to 50 per PR | `GitHubAnnotator.create_annotations()` slices gaps list at index 50 | T-19 |

---

## 9. User Stories

### 9.1 Core coverage analysis (US-01 .. US-05)

**US-01: Detect uncovered lines in FastAPI routes**
- **As a** dev ensuring route coverage
- **I want** to see which FastAPI route handlers have untested lines
- **So that** I can prioritize testing critical endpoints
- **Given:** `app/api/v1/auth.py` with 5 routes and 85% line coverage
- **When:** I run `test_coverage_gaps("/code/project")`
- **Then:**
  - Report shows `POST /auth/login` has 2 uncovered lines (INV-CG-01)
  - Untested lines ranked by risk weight (CC-23)
  - GitHub annotation created for each gap (CC-14)

**US-02: Flag missing branch coverage**
- **As a** dev testing edge cases
- **I want** to identify untested code branches
- **So that** I can add tests for error paths
- **Given:** `app/core/payment.py` with `if/else` but no `else` test
- **When:** I run with `min_branch_pct=75`
- **Then:**
  - Report flags missing `else` branch (INV-CG-01)
  - Branch gaps ranked higher than line gaps (CC-11)
  - Tool fails with "branch coverage 60% < 75%" (T-02)

**US-03: Generate baseline on first run**
- **As a** dev setting up coverage tracking
- **I want** to create an initial coverage snapshot
- **So that** I can track future regressions
- **Given:** new project with no `.coverage.baseline.json`
- **When:** I run `test_coverage_gaps("/code/project")`
- **Then:**
  - Baseline file created at `.coverage.baseline.json` (CC-20)
  - Coverage percentages saved (CC-12)
  - Tool passes with "baseline created" message (T-15)

**US-04: Fail on coverage regressions**
- **As a** CI pipeline maintainer
- **I want** PRs to fail when coverage drops
- **So that** I can prevent quality degradation
- **Given:** baseline with 90% coverage and PR drops to 85%
- **When:** I run with `fail_on_regressions=True`
- **Then:**
  - Tool fails with "coverage regressed from 90% to 85%" (INV-CG-04)
  - Regression details shown in Markdown report (CC-15)
  - GitHub status check fails (T-13)

**US-05: Exclude generated files from coverage**
- **As a** dev using codegen tools
- **I want** generated files excluded from coverage stats
- **So that** my coverage percentages reflect hand-written code
- **Given:** `app/generated/models.py` with 0% coverage
- **When:** I run with `exclude_patterns=["**/generated/**"]`
- **Then:**
  - Generated file excluded from coverage calculation (INV-CG-05)
  - Report shows "0 files excluded by pattern" (CC-06)
  - Verified by T-17

### 9.2 Risk-weighted prioritization (US-06 .. US-10)

**US-06: Prioritize auth code gaps**
- **As a** security-conscious dev
- **I want** auth-related gaps ranked highest
- **So that** I fix security-critical issues first
- **Given:** `app/core/auth.py` and `app/api/products.py` both have gaps
- **When:** I run with default risk weights
- **Then:**
  - Auth gaps ranked above product gaps (INV-CG-02)
  - Risk weight 2.0 applied to auth paths (CC-07)
  - Verified by T-07

**US-07: Highlight payment processor gaps**
- **As a** payments team lead
- **I want** payment-related gaps flagged urgently
- **So that** I prevent financial bugs
- **Given:** `app/core/payment/processor.py` with untested refund logic
- **When:** I run with `risk_weights=[{"pattern": "**/payment/**", "weight": 2.0}]`
- **Then:**
  - Refund logic gaps ranked highest (CC-23)
  - Risk weight 2.0 applied (CC-09)
  - GitHub annotation shows "High risk: payment code" (T-08)

**US-08: Weight admin routes higher**
- **As a** platform admin
- **I want** admin API gaps prioritized
- **So that** I secure privileged endpoints
- **Given:** `app/api/admin/users.py` with untested delete endpoint
- **When:** I run with default config
- **Then:**
  - Admin gaps ranked above regular API gaps (INV-CG-02)
  - Risk weight 1.5 applied (CC-07)
  - Verified by T-09

**US-09: Flag untested write operations**
- **As a** database engineer
- **I want** write operation gaps highlighted
- **So that** I prevent data corruption
- **Given:** `app/core/db/write_operations.py` with untested update logic
- **When:** I run with `risk_weights=[{"pattern": "**/*_write.py", "weight": 1.5}]`
- **Then:**
  - Write operation gaps ranked highly (CC-23)
  - Risk weight 1.5 applied (CC-09)
  - Verified by T-10

**US-10: Customize risk weights per project**
- **As a** project architect
- **I want** to define custom risk weights
- **So that** gaps align with our risk profile
- **Given:** `pyproject.toml` with custom weights
- **When:** I run with `risk_weights=[{"pattern": "**/billing/**", "weight": 3.0}]`
- **Then:**
  - Billing gaps ranked highest (CC-09)
  - Custom weight 3.0 applied (CC-07)
  - Verified by T-11

### 9.3 Baseline & regression handling (US-11 .. US-15)

**US-11: Detect coverage drops vs baseline**
- **As a** quality engineer
- **I want** to catch coverage regressions
- **So that** I maintain test quality
- **Given:** baseline with 90% coverage and PR drops to 85%
- **When:** I run with `fail_on_regressions=True`
- **Then:**
  - Tool fails with "coverage regressed from 90% to 85%" (INV-CG-04)
  - Regression details shown in Markdown report (CC-15)
  - Verified by T-13

**US-12: Update baseline on approval**
- **As a** team lead approving coverage changes
- **I want** to update the baseline explicitly
- **So that** I control when new coverage levels become the standard
- **Given:** PR with intentional coverage drop
- **When:** I run with `--update-baseline`
- **Then:**
  - Baseline updated to current coverage (INV-CG-03)
  - New percentages saved (CC-12)
  - Verified by T-16

**US-13: Handle corrupted baseline gracefully**
- **As a** dev recovering from a bad baseline
- **I want** the tool to handle corruption gracefully
- **So that** I can recover without manual fixes
- **Given:** corrupted `.coverage.baseline.json`
- **When:** I run the tool
- **Then:**
  - Tool fails with "baseline corrupted" message (CC-26)
  - Suggests `--reset-baseline` flag (T-20)
  - Verified by T-20

**US-14: Detect deleted files**
- **As a** dev cleaning up old code
- **I want** deleted files handled correctly
- **So that** my coverage stats stay accurate
- **Given:** baseline includes `old_module.py` which was deleted
- **When:** I run with `--update-baseline`
- **Then:**
  - Deleted file removed from baseline (CC-27)
  - Report shows "1 file removed from baseline" (CC-15)
  - Verified by T-21

**US-15: Handle new files with 0% coverage**
- **As a** dev adding new features
- **I want** new files flagged even if overall coverage is high
- **So that** I don't miss testing new code
- **Given:** new `app/api/v2/features.py` with 0% coverage
- **When:** I run the tool
- **Then:**
  - New file flagged in report (CC-28)
  - Tool fails with "new file has 0% coverage" (T-22)
  - Verified by T-22

### 9.4 CI integration (US-16 .. US-20)

**US-16: Annotate PRs with coverage gaps**
- **As a** reviewer checking PR quality
- **I want** inline annotations for coverage gaps
- **So that** I can see exactly which lines need tests
- **Given:** PR with untested lines in `app/api/v1/auth.py`
- **When:** Tool runs in CI
- **Then:**
  - GitHub annotations created for each gap (INV-CG-08)
  - Limited to 50 annotations per PR (CC-14)
  - Verified by T-19

**US-17: Post coverage summary in PR**
- **As a** team lead reviewing PRs
- **I want** a coverage summary in the PR comments
- **So that** I can quickly assess test quality
- **Given:** PR with 85% line coverage
- **When:** Tool runs in CI
- **Then:**
  - Markdown summary posted (CC-15)
  - Shows line and branch percentages (CC-14)
  - Verified by T-19

**US-18: Fail PRs on coverage regressions**
- **As a** CI pipeline maintainer
- **I want** PRs to fail when coverage drops
- **So that** I prevent quality degradation
- **Given:** PR drops coverage from 90% to 85%
- **When:** Tool runs in CI
- **Then:**
  - GitHub status check fails (INV-CG-04)
  - Regression details shown in PR comment (CC-15)
  - Verified by T-13

**US-19: Support incremental analysis**
- **As a** dev working on a large codebase
- **I want** to analyze only changed files
- **So that** I get faster feedback
- **Given:** PR modifies only `app/api/v1/auth.py`
- **When:** I run with `--changed-only`
- **Then:**
  - Only modified file analyzed (CC-33)
  - Report limited to gaps in changed file (T-27)
  - Verified by T-27

**US-20: Upload coverage artifacts**
- **As a** dev debugging CI failures
- **I want** coverage artifacts available
- **So that** I can investigate failures locally
- **Given:** CI run with coverage gaps
- **When:** Tool runs in CI
- **Then:**
  - `coverage.xml` uploaded as artifact (CC-08)
  - Baseline JSON included (CC-12)
  - Verified by T-24

### 9.5 Edge cases & performance (US-21 .. US-25)

**US-21: Handle conditional imports**
- **As a** dev using optional dependencies
- **I want** conditional imports handled correctly
- **So that** my coverage stats are accurate
- **Given:** `try: import optional_dep` with untested except branch
- **When:** I run the tool
- **Then:**
  - Untested except branch flagged (CC-31)
  - Branch coverage calculated correctly (INV-CG-01)
  - Verified by T-25

**US-22: Respect pragma no cover**
- **As a** dev excluding intentional untested code
- **I want** `# pragma: no cover` respected
- **So that** my coverage stats reflect testable code
- **Given:** `app/core/logging.py` with `# pragma: no cover`
- **When:** I run the tool
- **Then:**
  - Marked lines excluded from coverage (INV-CG-05)
  - Report shows "pragma exclusions respected" (CC-30)
  - Verified by T-24

**US-23: Handle empty files**
- **As a** dev maintaining stub files
- **I want** empty files handled correctly
- **So that** my coverage stats are accurate
- **Given:** `app/stubs/__init__.py` with no code
- **When:** I run the tool
- **Then:**
  - Empty file marked as 100% coverage (CC-12)
  - Excluded from gap analysis (INV-CG-05)
  - Verified by T-23

**US-24: Analyze large codebuses quickly**
- **As a** dev working on a 100k LOC project
- **I want** fast analysis
- **So that** I don't slow down my workflow
- **Given:** project with 100k lines of code
- **When:** I run the tool
- **Then:**
  - Analysis completes in < 3s (CC-33)
  - Report generated in < 500ms (CC-15)
  - Verified by T-26

**US-25: Maintain idempotent operation**
- **As a** dev running the tool repeatedly
- **I want** consistent results
- **So that** I can trust the output
- **Given:** unchanged codebase
- **When:** I run the tool twice
- **Then:**
  - Identical results both runs (INV-CG-06)
  - Zero churn in reports (CC-32)
  - Verified by T-26

---

## 10. Test Plan

### 10.1 Core coverage analysis

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Passes when coverage meets thresholds | `app/api/v1/auth.py` has 90% line, 80% branch coverage | Run with `min_line_pct=85`, `min_branch_pct=75` | Returns `{"passed": true}`, exit code 0 |
| T-02 | Fails when branch coverage below threshold | `app/core/payment.py` has 70% branch coverage | Run with `min_branch_pct=75` | Returns `{"passed": false}`, exit code 1 |
| T-03 | Flags uncovered lines in FastAPI routes | `app/api/v1/users.py` has untested POST handler | Run tool | Gap appears in report with file path `app/api/v1/users.py` |
| T-04 | Detects missing exception branches | `app/core/db.py` has untested `except DatabaseError` | Run tool | Gap marked as branch=true, priority=2x line gap |
| T-05 | Handles 100% coverage edge case | All files fully covered | Run tool | Returns empty gaps list, exit code 0 |
| T-06 | Reports line coverage percentage | `coverage.xml` shows 87.5% line coverage | Run tool | Report includes `"line_rate": 87.5` |

### 10.2 Risk weighting tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Auth gaps ranked highest | `app/core/auth.py` and `app/api/products.py` both have gaps | Run with default config | Auth gap priority > product gap priority |
| T-08 | Payment gaps get 2x weight | `app/core/payment/processor.py` has untested refund path | Run tool | Gap priority = 4.0 (2x branch multiplier * 2x risk weight) |
| T-09 | Admin routes weighted 1.5x | `app/api/admin/users.py` has untested DELETE | Run tool | Gap priority = 3.0 (2x branch * 1.5x weight) |
| T-10 | Write operations weighted 1.5x | `app/core/db/write_operations.py` has untested update | Run tool | Gap priority = 3.0 (2x branch * 1.5x weight) |
| T-11 | Custom risk weights honored | `pyproject.toml` sets billing weight=3.0 | Run tool | Billing gaps have priority=6.0 (2x3.0) |
| T-12 | Deterministic tie-breaker | Two gaps with same priority | Run tool multiple times | Stable sort order (by file path then line number) |

### 10.3 Baseline regression tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Fails on coverage regression | Baseline=90%, current=85% | Run with `fail_on_regressions=True` | Returns `{"passed": false}`, exit code 1 |
| T-14 | Passes when regression allowed | Baseline=90%, current=85% | Run with `fail_on_regressions=False` | Returns `{"passed": true}`, exit code 0 |
| T-15 | Creates baseline on first run | No `.coverage.baseline.json` | Run tool | Creates baseline file with current coverage |
| T-16 | Updates baseline with flag | Existing baseline | Run with `--update-baseline` | Baseline file updated with new coverage |
| T-17 | Excludes files by pattern | `app/generated/models.py` in exclude_patterns | Run tool | File excluded from coverage calculation |
| T-18 | Respects per-module thresholds | `app/core/auth.py` threshold=95%, coverage=90% | Run tool | Fails despite overall coverage=85% |

### 10.4 CI integration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Limits GitHub annotations | 100 gaps detected | Run in CI environment | Creates exactly 50 annotations |
| T-20 | Handles corrupted baseline | Malformed `.coverage.baseline.json` | Run tool | Fails with "baseline corrupted" message |
| T-21 | Detects deleted files | Baseline includes `old.py` which was deleted | Run with `--update-baseline` | New baseline excludes deleted file |
| T-22 | Flags new 0% coverage files | New `app/api/v2/features.py` added | Run tool | Fails with "new file has 0% coverage" |
| T-23 | Excludes test files | `tests/test_auth.py` has 0% coverage | Run tool | Test file excluded from gap analysis |
| T-24 | Respects pragma no cover | Line marked `# pragma: no cover` | Run tool | Line excluded from coverage gaps |

### 10.5 Edge cases & performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Handles conditional imports | `try: import optional_dep` with untested except | Run tool | Flags untested except branch |
| T-26 | Idempotent operation | Unchanged codebase | Run tool twice | Identical output both runs |
| T-27 | Supports incremental mode | PR modifies only `app/api/v1/auth.py` | Run with `--changed-only` | Reports only gaps in modified file |
| T-28 | Fast analysis | 10k LOC project | Run tool | Completes in < 3s |
| T-29 | Fast report generation | 5k LOC coverage data | Run tool | Report generated in < 500ms |
| T-30 | Fast baseline diff | 100 files in baseline | Run tool | Diff computed in < 100ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Coverage gaps tool analyzes test coverage independently of soft delete implementation |
| add_cursor_pagination | No | ✅ Compatible | Pagination logic is tested separately from coverage gap analysis |
| add_search | No | ✅ Compatible | Search endpoints appear in coverage report but don't affect gap analysis |
| add_audit_log | No | ✅ Compatible | Audit log writes are flagged as high-risk gaps if untested |
| add_data_export | No | ✅ Compatible | Export routes are analyzed like other endpoints |
| add_bulk_operations | No | ✅ Compatible | Bulk operations get standard risk weighting unless configured otherwise |
| add_multi_tenancy | No | ✅ Compatible | Tenant-aware code paths are analyzed normally |
| add_feature_flags | No | ✅ Compatible | Feature flag toggles create additional branches that coverage tool will flag |
| add_api_key_auth | No | ✅ Compatible | API key auth routes get 2x risk weight like other auth |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 endpoints are analyzed with auth risk weighting |
| add_rbac | No | ✅ Compatible | Permission checks create branches that coverage tool will analyze |
| add_mfa | No | ✅ Compatible | MFA flows are analyzed with auth risk weighting |
| add_cache_layer | No | ✅ Compatible | Cache hits/misses create branches that coverage tool will flag |
| add_outbox_pattern | No | ✅ Compatible | Outbox writes are analyzed as high-risk operations |
| add_sse | No | ✅ Compatible | SSE endpoints are analyzed like other routes |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD -- pyproject.toml
git checkout HEAD -- .gitignore
rm -f .coverage.baseline.json
rm -f coverage.xml
rm -f coverage_gaps_report.json
rm -f coverage_gaps_report.md
rm -rf .coverage_gaps_cache
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (coverage config present but baseline missing, or vice versa), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed relative to HEAD
git status --short pyproject.toml .gitignore .coverage.baseline.json

# 2. Revert tool-modified files + drop any newly-created reports
git checkout HEAD -- pyproject.toml .gitignore
git clean -fd .coverage.baseline.json coverage.xml \
    coverage_gaps_report.json coverage_gaps_report.md .coverage_gaps_cache/

# 3. Verify the tree matches HEAD exactly before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: coverage regression blocking CI after a refactor
If a legitimate refactor dropped coverage in one file but the gate is blocking merges, do NOT just update the baseline without scrutiny — verify the drop is justified before approving:
```bash
# 1. Inspect the exact regression report
python -m scripts.coverage_gaps --fail-on-regressions --format markdown

# 2. For each regressed file, compare old and new to confirm the drop is intentional
git diff main -- <regressed_file>

# 3. If the drop is genuine (code simplified, branches removed), update the baseline
python -m scripts.coverage_gaps --update-baseline --commit-message \
    "baseline update: orders/cancel simplified, removed 3 unreachable branches"

# 4. Commit the new baseline together with the refactor in the same PR
git add .coverage.baseline.json
git commit -m "chore: update coverage baseline after cancel-flow refactor"
```
Every baseline update requires a justification in the commit message so the history of "known-good" coverage is auditable.

### Failure mode: false positive on generated files (migrations, protobuf)
If the tool flags auto-generated files that should not be test-covered (Alembic migrations, protobuf stubs, Pydantic models generated from OpenAPI):
1. Add the directory to `[tool.coverage.run] omit` in `pyproject.toml`
2. Verify the exclusion took effect: `coverage report --skip-covered | grep <dir>` returns nothing
3. Re-run the gate; the false positives disappear
4. Commit the exclusion with a reason comment so the next maintainer understands why

### Emergency: corrupted baseline file preventing CI runs
If `.coverage.baseline.json` became corrupted (merge conflict resolved wrong, partial write during power loss, manual edit):
1. Inspect the file: `python -m json.tool .coverage.baseline.json` — should print valid JSON
2. If corrupted, restore from the last known-good commit: `git checkout HEAD~1 -- .coverage.baseline.json`
3. If no known-good commit exists, reset the baseline from the current state (accepting that the first post-reset PR has no regression protection): `python -m scripts.coverage_gaps --reset-baseline --confirm`
4. Commit the new baseline immediately to restore the diff gate for subsequent PRs

### Emergency: coverage.xml missing or stale
If pytest runs but `coverage.xml` is not generated (coverage.py version mismatch, pytest-cov plugin disabled):
1. Verify coverage.py is installed: `pip show coverage` — should print version
2. Re-run pytest with explicit coverage: `pytest --cov=src --cov-branch --cov-report=xml tests/`
3. If still no `coverage.xml`, check `pyproject.toml [tool.pytest.ini_options]` for conflicting options
4. Clear any stale `.coverage` artifact: `rm -f .coverage coverage.xml` then re-run

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | First run with no baseline file | Tool creates baseline file with current coverage percentages and passes |
| EC-2 | Baseline file corrupted or invalid JSON | Tool fails with error: "Baseline file corrupted. Run with --reset-baseline to recreate." |
| EC-3 | Coverage exactly at threshold (85.0%) | Tool passes with "Coverage meets threshold" message |
| EC-4 | File deleted between runs | On baseline update, deleted file is removed from baseline data |
| EC-5 | New file with 0% coverage added | Tool fails with "New file has 0% coverage" even if overall coverage is above threshold |
| EC-6 | Test file itself has 0% coverage | Test files are automatically excluded from coverage analysis |
| EC-7 | Conditional import (`try: import X`) with untested except branch | Untested except branch is flagged as high priority gap |
| EC-8 | Line marked with `# pragma: no cover` | Line is excluded from coverage gap analysis |
| EC-9 | File with 100% line coverage but 60% branch coverage | Tool flags missing branches and fails if below threshold |
| EC-10 | Tool run twice with identical code and tests | Produces identical output reports with zero churn |
| EC-11 | Custom risk weight of 5x configured for specific file | Custom weight is honored in gap prioritization |
| EC-12 | File with no branches (0 conditional statements) | Reported as 100% branch coverage (vacuously true) |
| EC-13 | PR modifies only one file in large codebase | With --changed-only flag, reports only gaps in modified file |
| EC-14 | Generated code in build/ directory | Excluded from coverage analysis via default patterns |
| EC-15 | Migration files in alembic/versions/ | Automatically excluded from coverage analysis |

## 14. Acceptance Criteria (Final Sign-off)

✅ 1. All 33 Completeness Criteria verified via checklist  
✅ 2. All 8 Invariants passing tests  
✅ 3. Performance SLOs met: execution <3s, report gen <500ms, diff <100ms  
✅ 4. pyproject.toml configured with coverage thresholds and risk weights  
✅ 5. Baseline file created on first run and updated only with explicit flag  
✅ 6. GitHub annotations limited to 50 per PR as designed  
✅ 7. Risk weights applied correctly to auth/payment/admin paths  
✅ 8. Per-module thresholds respected for strict modules  
✅ 9. All 15 edge cases handled as specified  
✅ 10. Developer performs end-to-end validation:  
   - Runs `test_coverage_gaps()` on project with known gaps  
   - Verifies auth gaps ranked highest  
   - Updates baseline after adding tests  
   - Confirms PR annotations appear in GitHub  

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and is FastAPI project  
- [ ] Verify pytest and coverage.py are installed  
- [ ] Check for existing `coverage.xml` or ability to generate  
- [ ] Validate `min_line_pct` and `min_branch_pct` are between 0-100  
- [ ] Detect existing baseline file for regression comparison  
- [ ] Verify GitHub environment variables if running in CI  
- [ ] Check for corrupted baseline file and handle gracefully  

### 15.2 Coverage configuration
- [ ] Generate or update `pyproject.toml` with coverage settings  
- [ ] Configure branch coverage via `--cov-branch`  
- [ ] Set coverage fail-under threshold  
- [ ] Add risk weight patterns for auth/payment/admin paths  
- [ ] Define exclude patterns for tests/generated files  
- [ ] Add per-module thresholds for strict packages  
- [ ] Ensure config parses with `tomli`  

### 15.3 Coverage analyzer
- [ ] Implement XML parser for coverage.xml  
- [ ] Calculate line and branch coverage percentages  
- [ ] Identify uncovered lines and branches  
- [ ] Apply risk weights based on file patterns  
- [ ] Sort gaps by priority (risk weight × branch multiplier)  
- [ ] Generate summary statistics  
- [ ] Limit output to top 100 gaps  

### 15.4 Baseline handler
- [ ] Create baseline file on first run  
- [ ] Implement JSON serialization for coverage data  
- [ ] Compare current vs baseline with 2% tolerance  
- [ ] Detect and report regressions  
- [ ] Handle corrupted baseline gracefully  
- [ ] Support --update-baseline flag for explicit updates  
- [ ] Track deleted files between runs  

### 15.5 GitHub integration
- [ ] Generate PR annotations for top gaps  
- [ ] Create markdown summary report  
- [ ] Limit to 50 annotations per PR  
- [ ] Format regression details clearly  
- [ ] Handle GitHub API rate limits  
- [ ] Support both Actions and other CI environments  
- [ ] Add GitHub status check integration  

### 15.6 Report generation
- [ ] Generate JSON report with all gaps  
- [ ] Create human-readable Markdown summary  
- [ ] Highlight high-risk gaps prominently  
- [ ] Show coverage vs threshold comparison  
- [ ] List regressions separately  
- [ ] Include next steps for improvement  
- [ ] Write reports to standard paths  

### 15.7 Command-line interface
- [ ] Implement --changed-only for incremental analysis  
- [ ] Add --update-baseline flag  
- [ ] Support --reset-baseline for recovery  
- [ ] Add --output-format option  
- [ ] Implement --verbose logging  
- [ ] Add --fail-under override  
- [ ] Support --exclude additional patterns  

### 15.8 Error handling
- [ ] Handle missing coverage.xml gracefully  
- [ ] Validate XML schema before parsing  
- [ ] Catch and report pytest failures  
- [ ] Handle permission errors for file writes  
- [ ] Manage GitHub API failures  
- [ ] Validate all numeric ranges  
- [ ] Provide helpful error messages  

### 15.9 Performance optimization
- [ ] Implement streaming XML parsing  
- [ ] Cache risk weight calculations  
- [ ] Optimize baseline diff algorithm  
- [ ] Limit memory usage during analysis  
- [ ] Batch GitHub API calls  
- [ ] Parallelize where possible  
- [ ] Profile and optimize hot paths  

### 15.10 Testing
- [ ] Generate test coverage.xml fixtures  
- [ ] Test all risk weight scenarios  
- [ ] Verify baseline creation/update  
- [ ] Test regression detection  
- [ ] Validate GitHub annotation format  
- [ ] Check edge cases (0%, 100%, new files)  
- [ ] Benchmark with large codebases  

### 15.11 Documentation
- [ ] Add tool to SKILL.md  
- [ ] Update manifest.yaml  
- [ ] Document pyproject.toml options  
- [ ] Write KNOWLEDGE.md section  
- [ ] Add CI setup instructions  
- [ ] Include troubleshooting guide  
- [ ] Provide example reports  

### 15.12 Atomicity
- [ ] Use temp files for all writes  
- [ ] Verify writes before committing  
- [ ] Track all modified files for rollback  
- [ ] Implement clean rollback on failure  
- [ ] Preserve existing baseline on error  
- [ ] Validate JSON before writing  
- [ ] Check disk space before large writes  

### 15.13 Verification
- [ ] Run ast.parse on all generated code  
- [ ] Verify no test regressions  
- [ ] Check performance benchmarks  
- [ ] Confirm idempotent operation  
- [ ] Validate report formats  
- [ ] Test in CI environment  
- [ ] Verify all edge cases  

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "pyproject.toml",
    ".coverage.baseline.json",
    "coverage_gaps_report.json",
    "coverage_gaps_report.md",
    ".github/workflows/coverage.yml",
    "tests/test_coverage_gaps.py",
    "app/core/coverage_gaps.py",
    "app/core/coverage_baseline.py"
  ],
  "files_modified": [
    ".gitignore",
    "app/main.py",
    "pyproject.toml"
  ],
  "metrics": {
    "execution_time_ms": 1245,
    "files_changed": 11,
    "lines_added": 342,
    "lines_removed": 8,
    "gaps_found": 27,
    "high_risk_gaps": 8,
    "line_coverage": 87.3,
    "branch_coverage": 76.8
  },
  "next_steps": [
    "Review high-risk gaps in coverage_gaps_report.md",
    "Add tests for auth/payment endpoints flagged in report",
    "Commit .coverage.baseline.json to track future regressions",
    "Run with --changed-only in CI for faster feedback",
    "Consider increasing branch coverage threshold to 80%"
  ],
  "warnings": [
    "3 auth-related gaps detected with high priority",
    "Branch coverage (76.8%) below recommended 80% for critical paths"
  ],
  "notes": [
    "Coverage analysis completed for 42 files",
    "Baseline created with current coverage percentages",
    "GitHub PR annotations enabled for CI environment",
    "8 gaps identified in high-risk auth/payment paths",
    "Tool configured to fail on >2% coverage regressions"
  ]
}
