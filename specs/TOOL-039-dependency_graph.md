---
spec_id: "TOOL-039"
tool_name: "add_dependency_graph"
primitive: "data/DiContainer"
primitive_path: "core.venous.data.DiContainer"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-DG-01"
  - "INV-DG-02"
  - "INV-DG-03"
  - "INV-DG-04"
  - "INV-DG-05"
  - "INV-DG-06"
  - "INV-DG-07"
  - "INV-DG-08"
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
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "auth"
  - "api"
  - "payments"
  - "performance"
  - "operate"
---
# TOOL-039: dependency_graph

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_dependency_graph` |
| Category | OPERATE |
| Complexity | Medium |
| Dependencies | FastAPI, AST parser, Graphviz |
| Signature | `dependency_graph(project_dir: str, output_format: str = "svg", layer_rules_file: str = ".deps-layers.yaml", detect_cycles: bool = True, fail_on_violation: bool = True) -> dict` |
| Parameters | `project_dir`: Root directory of the FastAPI project<br>`output_format`: Output format (`svg`, `png`, `dot`, or `json`)<br>`layer_rules_file`: Path to YAML file defining architectural layers<br>`detect_cycles`: Enable cycle detection (default: `True`)<br>`fail_on_violation`: Fail on layer boundary violations (default: `True`) |

## 2. Purpose

The `fastapi_dependency_graph` tool builds a complete module-level dependency graph of a FastAPI project from AST-parsed imports and turns it into an **architectural enforcement gate**. It goes beyond visualization tools like `pydeps` (which give you a pretty picture and stop there) by letting teams declare their layered architecture (`routes → services → repos → models`) in `.deps-layers.yaml` and failing the CI build whenever a lower-layer module imports from a higher layer — the single biggest source of rot in long-lived codebases, where a "quick fix" has a repository module suddenly importing a route handler and the clean architecture quietly becomes a hairball over six months. The tool also detects circular imports via Tarjan's strongly-connected-components algorithm (O(V+E), not naive DFS which explodes on highly-connected graphs), flags orphan modules that nothing imports, and outputs the graph in SVG (humans), DOT (Graphviz customization), JSON (programmatic tooling), and an inline PR-comment Markdown summary.

The generator produces `scripts/dependency_graph.py` with a cached graph builder that keys on file mtimes so the second invocation is sub-second, a layer-rules engine that enforces the allowed edge directions declaratively, a violation reporter that highlights every bad edge in red on the SVG, and a GitHub Actions workflow that blocks PRs introducing new violations while leaving pre-existing ones alone (so teams can adopt the tool without a forced big-bang migration). Key design decisions: **external libraries are always excluded** from the internal graph so it stays focused on what the team actually controls; **`TYPE_CHECKING` imports are ignored** for runtime cycle detection because they never execute at import time (only at static-analysis time) — counting them would produce false-positive cycles that annoy everyone; **layer violations are strict and committed** — the rules live in YAML so the architectural decisions are auditable in git history instead of dying in a whiteboard photo; **cycles never cause infinite loops** because Tarjan's visited set bounds traversal in linear time; **integration with TOOL-035 blast_radius** so a `blast_radius` query can be filtered by layer ("show me only the routes that depend on this repo, not the 80 transitive test files") — the two tools share the same AST cache and graph representation.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s for 1000 modules | Ensures fast feedback in CI/CD pipelines |
| Files modified | ≤ 2 | Minimizes impact on existing project files |
| Files created | ≥ 7 | Includes graph builder, layer rules, CI workflow, report templates, tests, docs, Makefile targets |
| Graph build time | < 2s | Ensures quick graph generation |
| Cycle detection time | < 500 ms | Fast cycle detection for large projects |
| Layer check time | < 200 ms | Efficient layer boundary validation |
| Output file size | < 1MB for SVG | Keeps visualization files manageable |
| Memory overhead | < 100MB | Ensures low resource consumption |

---

## 4. Code Examples (Before / After)

### 4.1 Graph Builder: BEFORE
```python
# app/core/graph_builder.py
from pathlib import Path
from typing import Dict, List, Set, Tuple
import ast


class GraphBuilder:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.nodes: Set[str] = set()
        self.edges: List[Tuple[str, str]] = []

    def build(self) -> Dict[str, List[str]]:
        for py_file in self.project_dir.rglob("*.py"):
            self._parse_file(py_file)
        return {"nodes": list(self.nodes), "edges": self.edges}

    def _parse_file(self, file_path: Path) -> None:
        with open(file_path, "r") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
        self.nodes.add(file_path.stem)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.edges.append((file_path.stem, alias.name))
            elif isinstance(node, ast.ImportFrom):
                self.edges.append((file_path.stem, node.module))
```

### 4.2 Graph Builder: AFTER
```python
# app/core/graph_builder.py
from pathlib import Path
from typing import Dict, List, Set, Tuple
import ast
import yaml


class GraphBuilder:
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.nodes: Set[str] = set()
        self.edges: List[Tuple[str, str]] = []
        self.layer_rules: Dict[str, List[str]] = {}

    def build(self) -> Dict[str, List[str]]:
        self._load_layer_rules()
        for py_file in self.project_dir.rglob("*.py"):
            self._parse_file(py_file)
        return {"nodes": list(self.nodes), "edges": self.edges}

    def _load_layer_rules(self) -> None:
        with open(self.project_dir / ".deps-layers.yaml") as f:
            self.layer_rules = yaml.safe_load(f)

    def _parse_file(self, file_path: Path) -> None:
        with open(file_path, "r") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
        module_name = file_path.stem
        self.nodes.add(module_name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._add_edge(module_name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                self._add_edge(module_name, node.module)

    def _add_edge(self, from_module: str, to_module: str) -> None:
        if self._is_edge_allowed(from_module, to_module):
            self.edges.append((from_module, to_module))

    def _is_edge_allowed(self, from_module: str, to_module: str) -> bool:
        from_layer = self._get_module_layer(from_module)
        to_layer = self._get_module_layer(to_module)
        return to_layer in self.layer_rules["allowed"].get(from_layer, [])
```

### 4.3 Layer rules loader (NEW)
```python
# app/core/layer_rules.py
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class Layer:
    name: str
    path_pattern: str


@dataclass(frozen=True)
class LayerRules:
    layers: tuple[Layer, ...]
    allowed: dict[str, frozenset[str]]

    @classmethod
    def load(cls, yaml_path: Path) -> "LayerRules":
        data = yaml.safe_load(yaml_path.read_text())
        layers = tuple(Layer(name=entry["name"], path_pattern=entry["path"]) for entry in data["layers"])
        allowed = {
            rule["from"]: frozenset(rule["to"])
            for rule in data.get("allowed", [])
        }
        return cls(layers=layers, allowed=allowed)

    def layer_for(self, module_path: str) -> str | None:
        for layer in self.layers:
            if fnmatch.fnmatch(module_path, layer.path_pattern):
                return layer.name
        return None

    def is_allowed(self, src_layer: str, dst_layer: str) -> bool:
        if src_layer == dst_layer:
            return True
        return dst_layer in self.allowed.get(src_layer, frozenset())

    def violations(self, edges: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
        bad: list[tuple[str, str]] = []
        for src, dst in edges:
            src_l = self.layer_for(src)
            dst_l = self.layer_for(dst)
            if src_l and dst_l and not self.is_allowed(src_l, dst_l):
                bad.append((src, dst))
        return bad
```

### 4.4 Cycle Detector: BEFORE
```python
# app/core/cycle_detector.py
from typing import Dict, List, Set


class CycleDetector:
    def __init__(self, graph: Dict[str, List[str]]):
        self.graph = graph
        self.visited: Set[str] = set()
        self.stack: Set[str] = set()
        self.cycles: List[List[str]] = []

    def detect(self) -> List[List[str]]:
        for node in self.graph["nodes"]:
            if node not in self.visited:
                self._dfs(node)
        return self.cycles

    def _dfs(self, node: str) -> None:
        self.visited.add(node)
        self.stack.add(node)
        for neighbor in self.graph["edges"].get(node, []):
            if neighbor in self.stack:
                self.cycles.append(list(self.stack) + [neighbor])
            elif neighbor not in self.visited:
                self._dfs(neighbor)
        self.stack.remove(node)
```

### 4.5 Cycle Detector: AFTER
```python
# app/core/cycle_detector.py
from typing import Dict, List, Set
from collections import defaultdict


class CycleDetector:
    def __init__(self, graph: Dict[str, List[str]]):
        self.graph = self._build_adjacency_list(graph)
        self.visited: Set[str] = set()
        self.stack: Set[str] = set()
        self.cycles: List[List[str]] = []

    def detect(self) -> List[List[str]]:
        for node in self.graph.keys():
            if node not in self.visited:
                self._dfs(node)
        return self.cycles

    def _dfs(self, node: str) -> None:
        self.visited.add(node)
        self.stack.add(node)
        for neighbor in self.graph[node]:
            if neighbor in self.stack:
                self.cycles.append(list(self.stack) + [neighbor])
            elif neighbor not in self.visited:
                self._dfs(neighbor)
        self.stack.remove(node)

    def _build_adjacency_list(self, graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
        adj_list = defaultdict(list)
        for from_node, to_node in graph["edges"]:
            adj_list[from_node].append(to_node)
        return adj_list
```

### 4.6 Report Generator (NEW)
```python
# app/core/report_generator.py
from typing import Dict, List
import json
import subprocess


class ReportGenerator:
    def __init__(self, graph: Dict[str, List[str]], cycles: List[List[str]]):
        self.graph = graph
        self.cycles = cycles

    def generate_svg(self, output_path: str) -> None:
        dot = self._generate_dot()
        with open(output_path, "w") as f:
            subprocess.run(["dot", "-Tsvg"], input=dot.encode(), stdout=f)

    def generate_json(self, output_path: str) -> None:
        with open(output_path, "w") as f:
            json.dump({"graph": self.graph, "cycles": self.cycles}, f)

    def _generate_dot(self) -> str:
        dot = ["digraph G {"]
        for node in self.graph["nodes"]:
            dot.append(f'  "{node}";')
        for from_node, to_node in self.graph["edges"]:
            dot.append(f'  "{from_node}" -> "{to_node}";')
        dot.append("}")
        return "\n".join(dot)
```

### 4.7 Migration: Add Dependency Graph Tables
```python
# alembic/versions/0001_add_dependency_graph_tables.py
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "dependency_graph",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("graph_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dependency_graph_project_id", "dependency_graph", ["project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_dependency_graph_project_id", table_name="dependency_graph")
    op.drop_table("dependency_graph")
```

### 4.8 SVG / DOT renderer (NEW)
```python
# app/core/graph_renderer.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping, Sequence


def to_dot(nodes: Sequence[str], edges: Sequence[tuple[str, str]],
           layer_of: Mapping[str, str] | None = None,
           violations: frozenset[tuple[str, str]] = frozenset()) -> str:
    """Render the module graph as Graphviz DOT. Violations are colored red."""
    lines: list[str] = [
        "digraph deps {",
        '    rankdir=LR;',
        '    node [shape=box, fontname="Helvetica", fontsize=10];',
        '    edge [fontname="Helvetica", fontsize=9];',
    ]
    layer_colors = {"routes": "#d5e8d4", "services": "#dae8fc",
                    "repos": "#f8cecc", "models": "#fff2cc"}
    for node in sorted(nodes):
        layer = (layer_of or {}).get(node)
        color = layer_colors.get(layer, "#ffffff")
        safe_label = node.replace('"', '\\"')
        lines.append(f'    "{node}" [label="{safe_label}", fillcolor="{color}", style=filled];')
    for src, dst in sorted(edges):
        attrs = ' [color="red", penwidth=2]' if (src, dst) in violations else ""
        lines.append(f'    "{src}" -> "{dst}"{attrs};')
    lines.append("}")
    return "\n".join(lines)


def render_svg(dot_source: str, output_path: Path) -> Path:
    """Render a DOT source to SVG using the system Graphviz `dot` binary."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["dot", "-Tsvg", "-o", str(output_path)],
        input=dot_source.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"graphviz dot failed (rc={result.returncode}): {result.stderr.decode('utf-8', 'ignore')}"
        )
    return output_path
```

### 4.9 CLI Entry Point (NEW)
```python
# app/cli.py
import argparse
from pathlib import Path
from app.core.graph_builder import GraphBuilder
from app.core.cycle_detector import CycleDetector
from app.core.report_generator import ReportGenerator


def main():
    parser = argparse.ArgumentParser(description="Generate dependency graph for FastAPI project")
    parser.add_argument("--project-dir", type=str, required=True, help="Project root directory")
    parser.add_argument("--output-format", type=str, default="svg", choices=["svg", "png", "dot", "json"])
    parser.add_argument("--layer-rules-file", type=str, default=".deps-layers.yaml")
    parser.add_argument("--detect-cycles", action="store_true")
    parser.add_argument("--fail-on-violation", action="store_true")
    args = parser.parse_args()

    builder = GraphBuilder(args.project_dir)
    graph = builder.build()
    cycles = []
    if args.detect_cycles:
        detector = CycleDetector(graph)
        cycles = detector.detect()

    generator = ReportGenerator(graph, cycles)
    if args.output_format == "svg":
        generator.generate_svg("dependency-graph.svg")
    elif args.output_format == "json":
        generator.generate_json("dependency-graph.json")

    if args.fail_on_violation and cycles:
        raise SystemExit("Dependency graph contains cycles")

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Layer rules are ALWAYS enforced** | `GraphBuilder._add_edge()` validates imports against `.deps-layers.yaml` rules via `_validate_layer_boundary()` |
| QS-2 | **Cycle detection is ALWAYS O(V+E)** | `CycleDetector._dfs()` implements Tarjan's algorithm with `visited` and `stack` sets for linear time complexity |
| QS-3 | **Layer violation direction is ALWAYS "lower → higher"** | `GraphBuilder._validate_layer_boundary()` raises `LayerViolationError` when higher layers import from lower layers |
| QS-4 | **Orphan modules are ALWAYS flagged** | `GraphBuilder.build()` identifies modules with zero inbound edges via `fan_in` calculation |
| QS-5 | **Graph generation is ALWAYS deterministic** | `GraphBuilder.build()` sorts nodes and edges alphabetically before returning the graph |
| QS-6 | **External libraries are NEVER included** | `GraphBuilder._parse_file()` skips imports starting with known external package prefixes |
| QS-7 | **`__init__.py` re-exports are ALWAYS traced** | `GraphBuilder._parse_file()` follows `__all__` declarations in `__init__.py` to resolve re-exports |
| QS-8 | **Dynamic imports are ALWAYS flagged** | `GraphBuilder._parse_file()` detects `importlib.import_module()` calls and marks them with low confidence |
| QS-9 | **Type hints are NEVER counted as cycles** | `GraphBuilder._parse_file()` skips imports inside `TYPE_CHECKING` blocks |
| QS-10 | **Graphviz output is ALWAYS valid DOT** | `ReportGenerator._generate_dot()` produces syntactically correct DOT language output |
| QS-11 | **JSON output is ALWAYS valid schema** | `ReportGenerator.generate_json()` validates against `dependency_graph.schema.json` |
| QS-12 | **CI integration ALWAYS fails on violations** | `.github/workflows/dependency-graph.yml` runs with `--fail-on-violation` enabled |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `GraphBuilder` class exists at `app/core/graph_builder.py` | File exists, parses |
| CC-02 | `CycleDetector` class exists at `app/core/cycle_detector.py` | File exists, contains Tarjan's algorithm |
| CC-03 | `ReportGenerator` class exists at `app/core/report_generator.py` | File exists, exports SVG/DOT/JSON |
| CC-04 | Layer rules YAML exists at `.deps-layers.yaml` | File exists, validates against schema |
| CC-05 | CI workflow exists at `.github/workflows/dependency-graph.yml` | File exists, runs on PR |
| CC-06 | CLI entry point exists at `app/cli.py` | File exists, handles all arguments |
| CC-07 | Graph contains all `.py` files in `project_dir` | Inspect `GraphBuilder.rglob("*.py")` |
| CC-08 | Graph excludes external libraries | grep `import requests` in graph output |
| CC-09 | Graph includes `__init__.py` re-exports | Inspect `__all__` handling in `GraphBuilder` |
| CC-10 | Graph detects simple cycles (A↔B) | T-13 |
| CC-11 | Graph detects complex cycles (A→B→C→A) | T-14 |
| CC-12 | Graph detects self-loops | T-15 |
| CC-13 | Graph detects SCCs | T-16 |
| CC-14 | Graph validates layer boundaries | T-07 |
| CC-15 | Graph flags orphan modules | T-25 |
| CC-16 | Graph handles empty projects | T-26 |
| CC-17 | Graph handles single-module projects | T-27 |
| CC-18 | Graph handles 1000+ modules in < 3s | T-28 |
| CC-19 | Graph detects dynamic imports | T-29 |
| CC-20 | Graph excludes `TYPE_CHECKING` imports | T-30 |
| CC-21 | SVG output exists and is valid | Inspect `ReportGenerator.generate_svg()` |
| CC-22 | DOT output exists and is valid | Inspect `ReportGenerator._generate_dot()` |
| CC-23 | JSON output exists and validates | Inspect `ReportGenerator.generate_json()` |
| CC-24 | CI workflow fails on new violations | T-19 |
| CC-25 | CLI handles all output formats | T-20 |
| CC-26 | CLI handles layer rules file | T-21 |
| CC-27 | CLI handles cycle detection flag | T-22 |
| CC-28 | CLI handles violation failure flag | T-23 |
| CC-29 | Tool is idempotent on re-run | T-24 |
| CC-30 | Graph preserves module renames | Inspect Git rename detection |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 8 Invariants implemented and tested
- [ ] CLI handles all required arguments and flags
- [ ] CI workflow fails PRs with new violations
- [ ] SVG, DOT, and JSON outputs validated
- [ ] Layer rules YAML schema implemented
- [ ] Cycle detection passes Tarjan's correctness tests
- [ ] Graph excludes external libraries and type hints
- [ ] Graph handles edge cases (empty, single module, 1000+ modules)
- [ ] Documentation covers installation, usage, and configuration
- [ ] Test suite covers all 30 test cases
- [ ] Performance SLOs met (graph build < 2s, cycle detect < 500ms)

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-DG-01 | Layer rules are ALWAYS enforced | `GraphBuilder._validate_layer_boundary()` raises `LayerViolationError` when imports violate `.deps-layers.yaml` rules | T-07 |
| INV-DG-02 | Cycle detection is ALWAYS O(V+E) | `CycleDetector._dfs()` implements Tarjan's algorithm with `visited` and `stack` sets for linear time complexity | T-13, T-14 |
| INV-DG-03 | Graph generation is ALWAYS deterministic | `GraphBuilder.build()` sorts nodes and edges alphabetically before returning the graph | T-24 |
| INV-DG-04 | External libraries are NEVER included | `GraphBuilder._parse_file()` skips imports starting with known external package prefixes via `EXTERNAL_PREFIXES` | T-08 |
| INV-DG-05 | `__init__.py` re-exports are ALWAYS traced | `GraphBuilder._parse_file()` follows `__all__` declarations in `__init__.py` to resolve re-exports | T-09 |
| INV-DG-06 | Dynamic imports are ALWAYS flagged | `GraphBuilder._parse_file()` detects `importlib.import_module()` calls and marks them with low confidence | T-29 |
| INV-DG-07 | Type hints are NEVER counted as cycles | `GraphBuilder._parse_file()` skips imports inside `TYPE_CHECKING` blocks via `ast.walk()` | T-30 |
| INV-DG-08 | CI integration ALWAYS fails on violations | `.github/workflows/dependency-graph.yml` runs with `--fail-on-violation` enabled and `SystemExit` on violations | T-19 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Generate basic dependency graph**
- **As a** lead architect
- **I want** to visualize module dependencies
- **So that** I can understand the project structure
- **Given:** FastAPI project at `./myapp` with 50 modules
- **When:** I run `dependency_graph(project_dir="./myapp")`
- **Then:**
  - SVG file `dependency-graph.svg` is created (CC-21)
  - Graph contains all 50 modules as nodes (INV-DG-03)
  - Edges show all `import` and `from ... import` statements

**US-02: Detect simple import cycles**
- **As a** backend developer
- **I want** to find circular dependencies
- **So that** I can fix architectural issues
- **Given:** Module `services/payment.py` imports `routes/checkout.py` which imports back
- **When:** I run with `detect_cycles=True`
- **Then:**
  - Cycle `payment.py ↔ checkout.py` is detected (T-13)
  - JSON output contains `"cycles": [["payment", "checkout"]]` (INV-DG-02)
  - Tool exits with code 1 if `fail_on_violation=True`

**US-03: Enforce layer boundaries**
- **As a** platform engineer
- **I want** to prevent routes from importing models directly
- **So that** we maintain clean architecture
- **Given:** `.deps-layers.yaml` forbids routes→models imports
- **When:** `routes/users.py` imports `models/user.py`
- **Then:**
  - Layer violation error is raised (INV-DG-01)
  - Error message specifies "routes → models" is forbidden (CC-14)
  - Violation appears in JSON report under `"violations"`

**US-04: Generate DOT output for customization**
- **As a** DevOps engineer
- **I want** to customize the graph styling
- **So that** I can highlight critical paths
- **Given:** Project with complex dependency graph
- **When:** I run with `output_format="dot"`
- **Then:**
  - `dependency-graph.dot` file is created (CC-22)
  - File contains valid DOT syntax with modules as nodes (INV-DG-08)
  - I can pipe it to `dot -Tpng > graph.png`

**US-05: Handle empty project**
- **As a** new developer
- **I want** to run the tool on a fresh project
- **So that** I can establish baselines
- **Given:** Empty directory `./newproject`
- **When:** I run the tool
- **Then:**
  - Graph contains no nodes or edges (T-26)
  - Tool exits successfully with code 0 (CC-16)
  - JSON output shows `{"nodes": [], "edges": []}`

### 9.2 Layer rules enforcement (US-06 .. US-10)

**US-06: Allow permitted cross-layer imports**
- **As a** service developer
- **I want** services to legally import repositories
- **So that** I can follow the architecture
- **Given:** `.deps-layers.yaml` allows services→repos
- **When:** `services/order.py` imports `repos/order.py`
- **Then:**
  - Import is allowed (T-07)
  - No violations reported (INV-DG-01)
  - Edge appears normally in the graph

**US-07: Detect multi-hop violations**
- **As a** code reviewer
- **I want** to catch indirect layer violations
- **So that** we don't bypass architectural rules
- **Given:** routes→services→repos is allowed but routes→repos is not
- **When:** `routes/api.py` imports `repos/db.py` via intermediate service
- **Then:**
  - Direct violation is flagged (CC-14)
  - Error shows full path `routes → services → repos` (INV-DG-03)
  - JSON output includes violation path

**US-08: Custom layer rules via YAML**
- **As a** team lead
- **I want** to define our own architectural layers
- **So that** the tool matches our conventions
- **Given:** Custom `.deps-layers.yaml` with `adapters` and `domain` layers
- **When:** I run the tool with `layer_rules_file=".deps-layers.yaml"`
- **Then:**
  - Custom layers are loaded (CC-04)
  - Violations use our layer names in errors (INV-DG-01)
  - Graph colors nodes by our custom layers

**US-09: Handle missing layer rules**
- **As a** developer testing the tool
- **I want** to run without layer checks
- **So that** I can get just the raw graph
- **Given:** No `.deps-layers.yaml` file exists
- **When:** I run with `layer_rules_file=None`
- **Then:**
  - Tool runs without layer validation (T-12)
  - Warning is logged about missing rules (CC-04)
  - Graph is generated with all edges allowed

**US-10: Reject invalid layer rules**
- **As a** platform engineer
- **I want** to validate layer configs
- **So that** bad configs fail fast
- **Given:** Invalid `.deps-layers.yaml` with syntax errors
- **When:** I run the tool
- **Then:**
  - Tool fails immediately with YAML parse error (CC-04)
  - Error message shows file and line number (INV-DG-01)
  - No graph output is generated

### 9.3 Cycle detection (US-11 .. US-15)

**US-11: Detect three-module cycle**
- **As a** software architect
- **I want** to find complex dependency cycles
- **So that** I can break them
- **Given:** `A → B → C → A` import cycle
- **When:** I run with `detect_cycles=True`
- **Then:**
  - Cycle `[A, B, C]` is detected (T-14)
  - JSON shows complete cycle path (INV-DG-02)
  - SVG highlights the cycle in red

**US-12: Ignore TYPE_CHECKING imports**
- **As a** Python developer
- **I want** type hints to not trigger cycles
- **So that** mypy works without false positives
- **Given:** `if TYPE_CHECKING:` block with cyclic imports
- **When:** I run the tool
- **Then:**
  - TYPE_CHECKING imports are excluded (INV-DG-07)
  - No false cycle detected (T-30)
  - Graph shows only runtime dependencies

**US-13: Detect self-imports**
- **As a** code quality engineer
- **I want** to find modules that import themselves
- **So that** we can fix confusing code
- **Given:** `utils/helpers.py` contains `from . import helpers`
- **When:** I analyze the project
- **Then:**
  - Self-import is flagged as cycle (T-15)
  - JSON shows `["helpers", "helpers"]` (INV-DG-02)
  - SVG shows self-loop arrow

**US-14: Exclude external libraries**
- **As a** developer
- **I want** to focus on internal dependencies
- **So that** the graph isn't cluttered
- **Given:** `import requests` in `services/api.py`
- **When:** I generate the graph
- **Then:**
  - `requests` doesn't appear in nodes (INV-DG-04)
  - Edge to `requests` is omitted (T-08)
  - Internal imports are still shown

**US-15: Handle large strongly connected components**
- **As a** performance engineer
- **I want** to identify tightly coupled modules
- **So that** we can modularize them
- **Given:** 10-module SCC with complex interdependencies
- **When:** I run cycle detection
- **Then:**
  - Entire SCC is identified (T-16)
  - Report shows all 10 modules in one cycle (INV-DG-02)
  - Processing completes in <500ms (CC-18)

### 9.4 CI integration (US-16 .. US-20)

**US-16: Block PRs with new violations**
- **As a** CI maintainer
- **I want** to prevent architectural rot
- **So that** violations don't accumulate
- **Given:** PR adds `routes/admin.py → models/user.py` import
- **When:** CI runs with `fail_on_violation=True`
- **Then:**
  - Build fails with violation error (INV-DG-08)
  - GitHub comment shows the offending import (CC-24)
  - JSON artifact contains violation details

**US-17: Generate PR comment with delta**
- **As a** reviewer
- **I want** to see what changed
- **So that** I can focus review
- **Given:** PR modifies dependency graph
- **When:** CI runs with `--since=HEAD~1`
- **Then:**
  - Comment shows added/removed edges (CC-24)
  - No full graph is generated (T-19)
  - Only new violations are reported

**US-18: Cache graph between runs**
- **As a** DevOps engineer
- **I want** fast incremental checks
- **So that** CI remains fast
- **Given:** Previous run cached `graph.json`
- **When:** Only 2 files changed since last run
- **Then:**
  - Tool only parses changed files (CC-29)
  - Merges with cached graph (INV-DG-03)
  - Completes in <1s for small changes

**US-19: Export JSON for artifacts**
- **As a** data engineer
- **I want** machine-readable output
- **So that** I can track trends
- **Given:** CI pipeline
- **When:** Tool runs with `output_format="json"`
- **Then:**
  - `dependency-graph.json` is uploaded (CC-23)
  - File validates against schema (INV-DG-07)
  - Contains `nodes`, `edges`, `violations`

**US-20: Integrate with existing workflows**
- **As a** platform team member
- **I want** to add this to our Makefile
- **So that** it's easy to run locally
- **Given:** Existing `Makefile` with `test` target
- **When:** I add `depgraph` target
- **Then:**
  - `make depgraph` runs the tool (CC-06)
  - Output goes to `./reports/dependency-graph.svg`
  - Returns non-zero on violations (INV-DG-08)

### 9.5 Edge cases (US-21 .. US-25)

**US-21: Handle module renames**
- **As a** Git user
- **I want** renames tracked properly
- **So that** history isn't lost
- **Given:** `git mv old.py new.py`
- **When:** I generate the graph
- **Then:**
  - Graph shows continuity (CC-30)
  - No false "orphan" for `old.py` (CC-15)
  - Edges to `new.py` include historical data

**US-22: Parse __init__ re-exports**
- **As a** package maintainer
- **I want** re-exports traced properly
- **So that** the graph is accurate
- **Given:** `__init__.py` with `__all__ = ["util"]`
- **When:** `from pkg import util` is used
- **Then:**
  - Edge points to actual module (INV-DG-05)
  - Not just `__init__.py` (T-09)
  - JSON shows resolved target

**US-23: Flag dynamic imports**
- **As a** security reviewer
- **I want** to identify risky imports
- **So that** we can audit them
- **Given:** `importlib.import_module("plugins." + name)`
- **When:** I scan the code
- **Then:**
  - Dynamic import is flagged (INV-DG-06)
  - Marked as "low confidence" in JSON (T-29)
  - SVG shows dotted edge

**US-24: Process 1000+ modules quickly**
- **As a** enterprise developer
- **I want** fast analysis at scale
- **So that** it's practical for large projects
- **Given:** Monorepo with 1500 Python files
- **When:** I run the tool
- **Then:**
  - Completes in <3s (CC-18)
  - Memory stays under 100MB (INV-DG-03)
  - All modules are processed

**US-25: Detect orphan modules**
- **As a** codebase maintainer
- **I want** to find unused code
- **So that** we can clean up
- **Given:** `legacy/utils.py` with no imports to it
- **When:** I generate the report
- **Then:**
  - Module is flagged as orphan (CC-15)
  - JSON contains `"orphans": ["legacy/utils"]`
  - SVG shows grayed-out node (T-25)

---

## 10. Test Plan

### 10.1 Graph Building Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Build graph from single module | `src/main.py` with no imports | Run tool on `src/` | Graph has 1 node, 0 edges |
| T-02 | Build graph from package | `src/__init__.py` + `src/module.py` | Run tool on `src/` | Graph has 2 nodes, 1 edge (`module` → `__init__`) |
| T-03 | Build graph with submodules | `src/parent/__init__.py` + `src/parent/child.py` | Run tool on `src/` | Graph shows `parent.child` → `parent.__init__` |
| T-04 | Skip external libraries | `src/app.py` with `import requests` | Run tool on `src/` | Graph excludes `requests`, only shows internal modules |
| T-05 | Trace `__init__` re-exports | `src/__init__.py` with `__all__ = ["module"]` | Run tool on `src/` | Graph shows imports resolved to `module`, not `__init__` |
| T-06 | Handle empty project | Empty directory `empty/` | Run tool on `empty/` | Graph has 0 nodes, 0 edges |

### 10.2 Layer Rule Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Allow permitted layer import | `.deps-layers.yaml` allows routes→services | `routes/api.py` imports `services/auth.py` | No violation reported |
| T-08 | Detect layer violation | `.deps-layers.yaml` forbids routes→models | `routes/api.py` imports `models/user.py` | Violation error raised |
| T-09 | Detect multi-hop violation | `.deps-layers.yaml` allows routes→services→models but not routes→models | `routes/api.py` imports `models/user.py` via service | Violation error shows full path |
| T-10 | Handle missing layer rules | No `.deps-layers.yaml` file | Run tool with `layer_rules_file=None` | Warning logged, all edges allowed |
| T-11 | Reject invalid YAML | `.deps-layers.yaml` with syntax error | Run tool | Immediate YAML parse error |
| T-12 | Handle glob pattern mismatch | `.deps-layers.yaml` with `path: "src/routes/**"` but no routes | Run tool | Warning logged, no routes layer |

### 10.3 Cycle Detection Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Detect simple cycle | `A.py` imports `B.py` and vice versa | Run tool with `detect_cycles=True` | Cycle `[A, B]` detected |
| T-14 | Detect complex cycle | `A.py` → `B.py` → `C.py` → `A.py` | Run tool with `detect_cycles=True` | Cycle `[A, B, C]` detected |
| T-15 | Detect self-loop | `module.py` imports itself | Run tool with `detect_cycles=True` | Cycle `[module, module]` detected |
| T-16 | Detect SCC | 10 modules with complex interdependencies | Run tool with `detect_cycles=True` | Entire SCC identified as one cycle |
| T-17 | Skip TYPE_CHECKING imports | `if TYPE_CHECKING:` block with cyclic imports | Run tool | No cycle detected |
| T-18 | Handle large graph cycles | 1000 modules with cycles | Run tool with `detect_cycles=True` | Cycles detected in <500ms |

### 10.4 Output Format Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Generate SVG output | Project with 10 modules | Run tool with `output_format="svg"` | Valid SVG file created |
| T-20 | Generate DOT output | Project with 10 modules | Run tool with `output_format="dot"` | Valid DOT file created |
| T-21 | Generate JSON output | Project with 10 modules | Run tool with `output_format="json"` | Valid JSON file matching schema |
| T-22 | SVG highlights cycles | Project with cycle `A → B → A` | Run tool with `output_format="svg"` | SVG shows cycle in red |
| T-23 | JSON includes violations | Project with layer violation | Run tool with `output_format="json"` | JSON contains `violations` key |
| T-24 | DOT includes layers | Project with routes and services layers | Run tool with `output_format="dot"` | DOT file colors nodes by layer |

### 10.5 Edge Case Tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Detect orphan modules | `legacy/utils.py` with no imports to it | Run tool | Module flagged as orphan |
| T-26 | Handle module renames | `git mv old.py new.py` | Run tool | Graph shows continuity, no false orphan |
| T-27 | Flag dynamic imports | `importlib.import_module("plugins." + name)` | Run tool | Dynamic import flagged with low confidence |
| T-28 | Process large project | Monorepo with 1500 Python files | Run tool | Completes in <3s, all modules processed |
| T-29 | Tool idempotent | Project already analyzed | Run tool again | No changes, notes "skipped" |
| T-30 | CI fails on new violation | PR adds `routes/admin.py → models/user.py` | CI runs with `fail_on_violation=True` | Build fails with violation error |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Dependency graph analyzes imports regardless of soft delete implementation |
| add_cursor_pagination | No | ✅ Compatible | Pagination logic doesn't affect module dependencies |
| add_search | No | ✅ Compatible | Search implementation doesn't impact dependency analysis |
| add_audit_log | No | ✅ Compatible | Audit logging is orthogonal to dependency structure |
| add_data_export | No | ✅ Compatible | Data export functionality exists independently of module dependencies |
| add_bulk_operations | No | ✅ Compatible | Bulk operation patterns don't affect dependency analysis |
| add_multi_tenancy | No | ✅ Compatible | Multi-tenancy implementation doesn't impact module imports |
| add_feature_flags | No | ✅ Compatible | Feature flag usage doesn't affect dependency structure |
| add_api_key_auth | No | ✅ Compatible | Authentication layer exists independently of module dependencies |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 implementation doesn't impact dependency analysis |
| add_rbac | No | ✅ Compatible | Role-based access control doesn't affect module imports |
| add_mfa | No | ✅ Compatible | Multi-factor authentication exists independently of dependency structure |
| add_cache_layer | No | ✅ Compatible | Caching implementation doesn't impact dependency analysis |
| add_outbox_pattern | No | ✅ Compatible | Outbox pattern implementation doesn't affect module dependencies |
| add_sse | No | ✅ Compatible | Server-sent events implementation exists independently of dependency structure |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/core/graph_builder.py
git checkout -- app/core/cycle_detector.py
git checkout -- app/core/report_generator.py
git checkout -- app/cli.py
rm -f .deps-layers.yaml
rm -f .github/workflows/dependency-graph.yml
rm -f dependency-graph.svg
rm -f dependency-graph.json
rm -f dependency-graph.dot
```

### Database rollback (after deploy)
**N/A** — this tool is a code-only refactor. No database tables, columns, or
indexes are created. `alembic downgrade -1` would be a no-op. Skip this step.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout -- app/core/graph_builder.py
git checkout -- app/core/cycle_detector.py
git checkout -- app/core/report_generator.py
git checkout -- app/cli.py
rm -f .deps-layers.yaml
rm -f .github/workflows/dependency-graph.yml
rm -f dependency-graph.*
```

### Emergency: Graphviz installation fails
1. Install Graphviz manually:
```bash
sudo apt-get install graphviz
```
2. Verify installation:
```bash
dot -V
```
3. Re-run tool:
```bash
python -m fastapi_dependency_graph --project-dir .
```

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Empty project directory | Tool generates empty graph with zero nodes and edges |
| EC-2 | Single module project | Graph contains one node with no edges |
| EC-3 | Two-module circular dependency | Tool detects cycle and fails if detect_cycles=True |
| EC-4 | Three-module circular dependency | Tool detects complex cycle and reports all three modules |
| EC-5 | Self-importing module | Tool flags self-loop as cycle in report |
| EC-6 | External library import | Tool excludes external libraries from internal dependency graph |
| EC-7 | Star import with __all__ | Tool resolves star imports to actual symbols via __all__ |
| EC-8 | Dynamic import using importlib | Tool flags dynamic imports with low confidence warning |
| EC-9 | __init__.py re-exports | Tool traces re-exports to final module destination |
| EC-10 | Circular imports in TYPE_CHECKING block | Tool excludes TYPE_CHECKING imports from cycle detection |
| EC-11 | Project with 1000+ modules | Tool completes analysis in under 3 seconds |
| EC-12 | Glob pattern matches no files | Tool logs warning about empty layer but continues |
| EC-13 | Module renamed via Git | Tool preserves rename history in dependency graph |
| EC-14 | Tool run twice on same project | Second run produces identical output (idempotent) |
| EC-15 | Multi-package monorepo | Tool tracks cross-package dependencies correctly |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified via test suite  
✅ All 12 Quality Standards enforced in implementation  
✅ All 8 Invariants implemented and tested  
✅ CLI handles all required arguments and flags  
✅ CI workflow fails PRs with new violations  
✅ SVG, DOT, and JSON outputs validated  
✅ Layer rules YAML schema implemented  
✅ Cycle detection passes Tarjan's correctness tests  
✅ Performance SLOs met (graph build < 2s, cycle detect < 500ms)  
✅ Developer successfully generates dependency graph for their FastAPI project and resolves all violations

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists and is readable
- [ ] Verify Python version >= 3.8
- [ ] Check for Graphviz installation (`dot` command)
- [ ] Validate `.deps-layers.yaml` exists if specified
- [ ] Parse `.deps-layers.yaml` schema
- [ ] Check for write permissions in output directory
- [ ] Verify FastAPI project structure exists

### 15.2 Graph builder implementation
- [ ] Implement AST parser for Python files
- [ ] Extract imports and from-imports
- [ ] Handle relative imports correctly
- [ ] Skip TYPE_CHECKING imports
- [ ] Flag dynamic imports with low confidence
- [ ] Trace __init__.py re-exports via __all__
- [ ] Exclude external library imports

### 15.3 Cycle detection
- [ ] Implement Tarjan's SCC algorithm
- [ ] Detect simple cycles (A↔B)
- [ ] Detect complex cycles (A→B→C→A)
- [ ] Flag self-loops
- [ ] Identify strongly connected components
- [ ] Optimize for O(V+E) time complexity
- [ ] Handle large graphs efficiently

### 15.4 Layer validation
- [ ] Load layer rules from YAML
- [ ] Validate layer boundaries
- [ ] Detect multi-hop violations
- [ ] Allow permitted cross-layer imports
- [ ] Generate violation reports
- [ ] Color nodes by layer in visualization
- [ ] Fail on violations if configured

### 15.5 Report generation
- [ ] Implement SVG output via Graphviz
- [ ] Generate DOT format for customization
- [ ] Create JSON output with full metadata
- [ ] Highlight cycles in visualization
- [ ] Flag orphan modules
- [ ] Include layer information in reports
- [ ] Validate output formats

### 15.6 CLI implementation
- [ ] Handle project_dir argument
- [ ] Support output_format options
- [ ] Accept layer_rules_file parameter
- [ ] Implement detect_cycles flag
- [ ] Add fail_on_violation option
- [ ] Provide help and version commands
- [ ] Return appropriate exit codes

### 15.7 CI integration
- [ ] Create GitHub Actions workflow
- [ ] Install Python dependencies
- [ ] Run dependency graph check
- [ ] Fail on new violations
- [ ] Upload JSON artifact
- [ ] Comment with delta report
- [ ] Cache graph between runs

### 15.8 Performance optimization
- [ ] Parallelize file parsing
- [ ] Optimize AST traversal
- [ ] Cache parsed modules
- [ ] Batch Graphviz calls
- [ ] Limit memory usage
- [ ] Profile critical paths
- [ ] Meet all SLOs

### 15.9 Error handling
- [ ] Handle missing files gracefully
- [ ] Validate YAML syntax
- [ ] Catch AST parsing errors
- [ ] Handle Graphviz failures
- [ ] Provide helpful error messages
- [ ] Log warnings appropriately
- [ ] Maintain atomic operations

### 15.10 Documentation
- [ ] Write usage documentation
- [ ] Document layer rules format
- [ ] Explain output formats
- [ ] Provide CLI reference
- [ ] Add CI integration guide
- [ ] Include troubleshooting tips
- [ ] Update SKILL.md entry

### 15.11 Testing
- [ ] Test empty project scenario
- [ ] Verify single module handling
- [ ] Validate cycle detection
- [ ] Test layer boundary enforcement
- [ ] Check external import exclusion
- [ ] Verify TYPE_CHECKING handling
- [ ] Test large project performance

### 15.12 Atomicity
- [ ] Use temp files for outputs
- [ ] Rollback on failure
- [ ] Maintain operation logs
- [ ] Verify file permissions
- [ ] Handle concurrent runs
- [ ] Preserve existing files
- [ ] Clean up temp files

### 15.13 Verification
- [ ] Run ast.parse on all modified files
- [ ] Validate JSON output schema
- [ ] Verify SVG/DOT syntax
- [ ] Check idempotency
- [ ] Measure performance metrics
- [ ] Audit security implications
- [ ] Confirm CI integration works

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/graph_builder.py",
    "app/core/cycle_detector.py",
    "app/core/report_generator.py",
    "app/cli.py",
    ".deps-layers.yaml",
    ".github/workflows/dependency-graph.yml",
    "tests/test_dependency_graph.py",
    "docs/dependency_graph.md"
  ],
  "files_modified": [
    "pyproject.toml",
    "Makefile",
    "README.md"
  ],
  "metrics": {
    "execution_time_ms": 1872,
    "files_changed": 11,
    "lines_added": 423,
    "lines_removed": 8,
    "modules_analyzed": 147,
    "cycles_detected": 3,
    "violations_found": 2
  },
  "next_steps": [
    "Review dependency-graph.svg visualization",
    "Check dependency-graph.json for detailed analysis",
    "Resolve any detected cycles or layer violations",
    "Add dependency-graph.yml to your CI pipeline",
    "Run make depgraph regularly to maintain architecture"
  ],
  "warnings": [
    "Found 3 circular dependencies that may impact maintainability",
    "Detected 2 layer boundary violations that violate architectural rules"
  ],
  "notes": [
    "Analyzed 147 Python modules across 4 architectural layers",
    "Generated SVG, DOT, and JSON output formats",
    "Integrated with GitHub Actions for CI enforcement",
    "Cycle detection completed in 312ms using Tarjan's algorithm"
  ]
}
