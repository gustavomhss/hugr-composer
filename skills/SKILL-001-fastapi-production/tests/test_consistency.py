"""test_consistency.py — BRUTAL hardening round 4C.

Cross-tool consistency tests: import cycles, model sanity, schema hygiene,
route conflicts, migration chain integrity, and config coverage.

Run standalone:
    PYTHONPATH=. python3 tests/test_consistency.py

Run via pytest:
    PYTHONPATH=. pytest tests/test_consistency.py -v

Exit code 0  → all 6 test groups pass
Exit code 1  → one or more groups failed (details printed)
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
import tempfile
import traceback
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root & path setup
# ---------------------------------------------------------------------------

_SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_ROOT))

from adapt.contracts import ToolInput  # noqa: E402
from tests.common.fixture_factory import create_fixture_project  # noqa: E402

# ---------------------------------------------------------------------------
# 10-tool fixture
# ---------------------------------------------------------------------------

TOOLS_10: list[tuple[str, str, str]] = [
    ("add_soft_delete",      "adapt.extend.crud_data.add_soft_delete",      "add_soft_delete"),
    ("add_multi_tenancy",    "adapt.extend.auth_access.add_multi_tenancy",  "add_multi_tenancy"),
    ("add_rbac",             "adapt.extend.auth_access.add_rbac",           "add_rbac"),
    ("add_mfa",              "adapt.extend.auth_access.add_mfa",            "add_mfa"),
    ("add_api_key_auth",     "adapt.extend.auth_access.add_api_key_auth",   "add_api_key_auth"),
    ("add_audit_log",        "adapt.extend.crud_data.add_audit_log",        "add_audit_log"),
    ("add_cache_layer",      "adapt.extend.infrastructure.add_cache_layer", "add_cache_layer"),
    ("add_sse",              "adapt.extend.realtime.add_sse",               "add_sse"),
    ("add_webhook_receiver", "adapt.extend.realtime.add_webhook_receiver",  "add_webhook_receiver"),
    ("add_search",           "adapt.extend.crud_data.add_search",           "add_search"),
]


def _build_10_tool_project(tmp_dir: Path) -> Path:
    """Generate base project and apply all 10 tools.

    Returns:
        Path to the generated project root.
    """
    project_dir = create_fixture_project(name="consistency_test", tmp_dir=tmp_dir)
    for _name, mod_path, fn_name in TOOLS_10:
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, fn_name)
        result = fn(ToolInput(project_dir=str(project_dir)))
        if result.status == "error":
            raise RuntimeError(f"Tool {_name} failed: {result.error}")
    return project_dir


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _parse_file(path: Path) -> ast.Module:
    """Parse a Python file to AST, raising SyntaxError with path context."""
    source = path.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise SyntaxError(f"SyntaxError in {path}: {exc}") from exc


def _collect_py_files(directory: Path, *, exclude_dirs: set[str] | None = None) -> list[Path]:
    """Return all .py files under directory, excluding given subdirectory names."""
    excludes = exclude_dirs or set()
    return [
        p for p in sorted(directory.rglob("*.py"))
        if not any(part in excludes for part in p.parts)
    ]


def _module_key(py_file: Path, root: Path) -> str:
    """Convert a file path to a dotted module key relative to root."""
    rel = py_file.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Test 1 — Import cycle detection (Tarjan SCC)
# ---------------------------------------------------------------------------

def _build_import_graph(app_dir: Path) -> dict[str, set[str]]:
    """Build an intra-app import graph from AST.

    Returns:
        Adjacency dict {module_key: set of imported module_keys}.
        Only edges within app/ are recorded (no stdlib/third-party).
    """
    py_files = _collect_py_files(app_dir, exclude_dirs={"__pycache__"})
    all_modules = {_module_key(f, app_dir.parent): f for f in py_files}
    graph: dict[str, set[str]] = {m: set() for m in all_modules}

    for mod_key, py_file in all_modules.items():
        try:
            tree = _parse_file(py_file)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name
                    if target in graph:
                        graph[mod_key].add(target)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                # Handle relative imports
                if node.level and node.level > 0:
                    parts = mod_key.split(".")
                    base_parts = parts[: max(0, len(parts) - node.level)]
                    if node.module:
                        abs_module = ".".join(base_parts + node.module.split("."))
                    else:
                        abs_module = ".".join(base_parts)
                else:
                    abs_module = node.module

                if abs_module in graph:
                    graph[mod_key].add(abs_module)
                else:
                    # from app.models import Base → abs_module = "app.models"
                    for known in graph:
                        if known == abs_module or known.startswith(abs_module + "."):
                            graph[mod_key].add(known)

    return graph


def _tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's algorithm for strongly connected components.

    Returns:
        List of SCCs with more than one node (= cycles).
    """
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for v in list(graph.keys()):
        if v not in index:
            strongconnect(v)

    return [scc for scc in sccs if len(scc) > 1]


def test_1_no_import_cycles(project_dir: Path) -> tuple[bool, str]:
    """Test 1: Zero circular imports inside app/.

    Returns:
        (passed, message)
    """
    app_dir = project_dir / "app"
    graph = _build_import_graph(app_dir)
    cycles = _tarjan_scc(graph)

    if cycles:
        cycle_details = "\n".join(
            f"  Cycle {i + 1}: {' <-> '.join(sorted(c))}"
            for i, c in enumerate(cycles)
        )
        return False, f"Found {len(cycles)} import cycle(s):\n{cycle_details}"

    node_count = len(graph)
    edge_count = sum(len(v) for v in graph.values())
    return True, f"No import cycles detected ({node_count} modules, {edge_count} edges)"


# ---------------------------------------------------------------------------
# Test 2 — SQLAlchemy model consistency
# ---------------------------------------------------------------------------

def _collect_sa_models(app_dir: Path) -> dict[str, dict]:
    """Collect all SQLAlchemy models (classes inheriting Base) via AST.

    Also collects mixin classes so we can detect what base classes are
    SQLAlchemy-related (even through mixin intermediate classes).

    Returns:
        Dict {ClassName: {"file": Path, "tablename": str|None,
                          "columns": [str], "fk_refs": [(col, ref_table)],
                          "has_metadata_field": bool}}
    """
    # First pass: collect ALL class definitions to build inheritance map
    all_classes: dict[str, dict] = {}
    py_files = _collect_py_files(app_dir / "models", exclude_dirs={"__pycache__"})

    for py_file in py_files:
        try:
            tree = _parse_file(py_file)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = _get_base_names(node)
            tablename: str | None = None
            columns: list[str] = []
            fk_refs: list[tuple[str, str]] = []
            has_metadata_field = False

            for item in node.body:
                # __tablename__ = "..."
                if isinstance(item, ast.Assign):
                    for tgt in item.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                            if isinstance(item.value, ast.Constant):
                                tablename = item.value.value
                        if isinstance(tgt, ast.Name) and tgt.id == "metadata":
                            has_metadata_field = True

                # __tablename__: str = "..." (annotated)
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id == "__tablename__" and item.value:
                        if isinstance(item.value, ast.Constant):
                            tablename = item.value.value
                    col_name = item.target.id
                    if col_name not in ("__tablename__",):
                        columns.append(col_name)
                    if col_name == "metadata":
                        has_metadata_field = True
                    # Check for ForeignKey inside mapped_column(...)
                    if item.value:
                        for subnode in ast.walk(item.value):
                            if isinstance(subnode, ast.Call):
                                fname = _call_name(subnode.func)
                                if fname == "ForeignKey":
                                    for arg in subnode.args:
                                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                            ref_table = arg.value.split(".")[0]
                                            fk_refs.append((col_name, ref_table))

            all_classes[node.name] = {
                "file": py_file,
                "tablename": tablename,
                "columns": columns,
                "fk_refs": fk_refs,
                "has_metadata_field": has_metadata_field,
                "base_names": base_names,
            }

    # Second pass: identify which classes are ORM models (inherit from Base,
    # directly or transitively through mixins)
    def _inherits_base(class_name: str, visited: set[str] | None = None) -> bool:
        if visited is None:
            visited = set()
        if class_name in visited:
            return False
        visited.add(class_name)
        info = all_classes.get(class_name)
        if info is None:
            return class_name == "Base"
        for bn in info["base_names"]:
            if bn == "Base":
                return True
            if _inherits_base(bn, visited):
                return True
        return False

    models: dict[str, dict] = {}
    for name, info in all_classes.items():
        if "Mixin" in name:
            continue
        if _inherits_base(name):
            models[name] = info

    return models


def _get_base_names(node: ast.ClassDef) -> list[str]:
    """Extract simple base class names from a ClassDef node."""
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _call_name(func_node: ast.expr) -> str:
    """Extract the function name from a Call's func node."""
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return ""


def test_2_model_consistency(project_dir: Path) -> tuple[bool, str]:
    """Test 2: SQLAlchemy model sanity checks.

    Returns:
        (passed, message with all failures)
    """
    app_dir = project_dir / "app"
    models = _collect_sa_models(app_dir)
    failures: list[str] = []

    # Build tablename → model map for FK validation
    tablename_to_model: dict[str, str] = {}
    for name, info in models.items():
        if info["tablename"]:
            tablename_to_model[info["tablename"]] = name

    seen_names: dict[str, Path] = {}
    for name, info in models.items():
        rel = info["file"].relative_to(project_dir)

        # (a) No duplicate model names
        if name in seen_names:
            failures.append(
                f"Duplicate model name '{name}' in {rel} and {seen_names[name]}"
            )
        seen_names[name] = info["file"]

        # (b) Every model must have __tablename__
        if info["tablename"] is None:
            failures.append(f"{name} ({rel}): missing __tablename__")

        # (c) Every FK must reference a table that exists
        for col_name, ref_table in info["fk_refs"]:
            if ref_table not in tablename_to_model:
                failures.append(
                    f"{name}.{col_name} ({rel}): FK references table "
                    f"'{ref_table}' which has no corresponding model"
                )

        # (d) No field named 'metadata' (reserved by SQLAlchemy DeclarativeBase)
        if info["has_metadata_field"]:
            failures.append(
                f"{name} ({rel}): field named 'metadata' conflicts with "
                "SQLAlchemy's reserved DeclarativeBase attribute"
            )

    if failures:
        detail = "\n  ".join(failures)
        return False, f"Model consistency failures ({len(failures)}):\n  {detail}"

    return True, (
        f"All {len(models)} models consistent "
        f"(tablenames OK, FKs OK, no 'metadata' field)"
    )


# ---------------------------------------------------------------------------
# Test 3 — Pydantic schema consistency
# ---------------------------------------------------------------------------

def _collect_pydantic_schemas(app_dir: Path) -> dict[str, dict]:
    """Collect all FastAPI-compatible response model classes via AST.

    Searches all of app/ (not just app/schemas/) because tools like
    add_audit_log generate @dataclass response types in app/core/.

    Covers:
    - Direct/indirect BaseModel subclasses (Pydantic v2)
    - @dataclass classes (FastAPI supports them natively via dataclasses module)
    - TypedDict / NamedTuple subclasses

    Returns:
        Dict {ClassName: {"file": Path, "fields": [str], "base_names": [str],
                          "is_dataclass": bool}}
    """
    raw_classes: dict[str, dict] = {}
    py_files = _collect_py_files(app_dir, exclude_dirs={"__pycache__"})

    for py_file in py_files:
        try:
            tree = _parse_file(py_file)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = _get_base_names(node)
            fields: list[str] = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.append(item.target.id)
            # Detect @dataclass decorator in one pass
            is_dc = any(
                (isinstance(d, ast.Name) and d.id == "dataclass")
                or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
                for d in node.decorator_list
            )
            raw_classes[node.name] = {
                "file": py_file,
                "fields": fields,
                "base_names": base_names,
                "is_dataclass": is_dc,
            }

    def _is_response_model_compatible(class_name: str, visited: set[str] | None = None) -> bool:
        """Return True if class_name can be used as a FastAPI response_model."""
        if visited is None:
            visited = set()
        if class_name in visited:
            return False
        visited.add(class_name)
        if class_name in {"BaseModel", "BaseSettings", "RootModel", "TypedDict", "NamedTuple"}:
            return True
        info = raw_classes.get(class_name)
        if info is None:
            return False
        if info.get("is_dataclass"):
            return True
        return any(_is_response_model_compatible(bn, visited) for bn in info["base_names"])

    return {
        name: info
        for name, info in raw_classes.items()
        if _is_response_model_compatible(name)
    }


# Sensitive field patterns — "Public" schemas MUST NOT expose these
_SENSITIVE_FIELD_PATTERNS = re.compile(
    r"^(password|hashed_password|password_hash|hash|secret|encrypted|"
    r"secret_key|token|private_key|api_secret)$",
    re.IGNORECASE,
)


def _collect_response_model_names(app_dir: Path) -> list[tuple[str, str, Path]]:
    """Find all response_model=<Name> usages in route files.

    Handles: response_model=Name, response_model=list[Name],
    response_model=Optional[Name], response_model=dict (builtins).

    Returns:
        List of (schema_name, route_function_name, file_path).
    """
    results: list[tuple[str, str, Path]] = []
    route_dirs = [app_dir / "api" / "routes", app_dir / "routes"]

    for route_dir in route_dirs:
        if not route_dir.exists():
            continue
        for py_file in _collect_py_files(route_dir, exclude_dirs={"__pycache__"}):
            try:
                tree = _parse_file(py_file)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    for kw in decorator.keywords:
                        if kw.arg != "response_model":
                            continue
                        for name in _extract_type_names(kw.value):
                            results.append((name, node.name, py_file))
    return results


def _extract_type_names(node: ast.expr) -> list[str]:
    """Recursively extract simple Name nodes from a type expression."""
    names: list[str] = []
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, ast.Attribute):
        names.append(node.attr)
    elif isinstance(node, ast.Subscript):
        # list[X], Optional[X], dict[str, X], etc.
        names.extend(_extract_type_names(node.slice))
        # Also check the container itself (e.g., "list" is a builtin — skip)
    elif isinstance(node, ast.Tuple):
        for elt in node.elts:
            names.extend(_extract_type_names(elt))
    return names


def test_3_schema_consistency(project_dir: Path) -> tuple[bool, str]:
    """Test 3: Pydantic schema hygiene.

    Returns:
        (passed, message)
    """
    app_dir = project_dir / "app"
    schemas = _collect_pydantic_schemas(app_dir)
    failures: list[str] = []

    schemas_dir = app_dir / "schemas"

    # (a) No duplicate schema names within app/schemas/ files
    seen: dict[str, Path] = {}
    for name, info in schemas.items():
        # Only check within app/schemas/ for duplicates
        try:
            info["file"].relative_to(schemas_dir)
        except ValueError:
            continue
        if name in seen:
            failures.append(
                f"Duplicate schema '{name}' in {info['file'].name} and {seen[name].name}"
            )
        seen[name] = info["file"]

    # (b) 'Public' schemas (in app/schemas/) must not expose sensitive fields
    for name, info in schemas.items():
        if not name.endswith("Public"):
            continue
        # Only check classes defined in app/schemas/ — other 'Public' classes
        # (e.g. dataclasses in app/core/) are not API response schemas.
        try:
            info["file"].relative_to(schemas_dir)
        except ValueError:
            continue
        for field in info["fields"]:
            if _SENSITIVE_FIELD_PATTERNS.match(field):
                rel = info["file"].relative_to(project_dir)
                failures.append(
                    f"{name} ({rel}): 'Public' schema exposes sensitive field '{field}'"
                )

    # (c) Every schema used as response_model= must exist in the known schema set
    response_model_usages = _collect_response_model_names(app_dir)
    all_known_schemas = set(schemas.keys())
    # Builtins and well-known non-schema names that can appear in response_model
    _ALLOWED_NON_SCHEMA = {
        "dict", "list", "None", "Any", "bool", "str", "int",
        "float", "bytes", "set", "tuple",
    }
    for schema_name, fn_name, route_file in response_model_usages:
        if schema_name in _ALLOWED_NON_SCHEMA:
            continue
        if schema_name not in all_known_schemas:
            rel = route_file.relative_to(project_dir)
            failures.append(
                f"{fn_name} ({rel}): response_model={schema_name!r} not found "
                "in app/schemas/"
            )

    if failures:
        detail = "\n  ".join(failures)
        return False, f"Schema consistency failures ({len(failures)}):\n  {detail}"

    return True, (
        f"All {len(schemas)} schemas consistent; "
        f"{len(response_model_usages)} response_model references verified; "
        "no sensitive fields in Public schemas"
    )


# ---------------------------------------------------------------------------
# Test 4 — Route consistency
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Type-alias names for injected dependencies — these count as Depends() for
# our purposes (they are Annotated[T, Depends(...)] at module level).
_DEPENDS_ALIAS_PATTERNS = re.compile(
    r"^(CurrentUser|CurrentSuperuser|CurrentAuditor|SessionDep|"
    r"AsyncSessionDep|get_async_session|DBSession|"
    r"Current[A-Z][A-Za-z]+|[A-Z][A-Za-z]+Dep)$"
)


def _collect_routes(app_dir: Path) -> list[dict]:
    """Collect all route handlers via AST, including router prefix.

    Returns:
        List of dicts: method, path, full_path, fn_name, is_async,
        has_depends, file.
    """
    routes: list[dict] = []
    route_dirs = [app_dir / "api" / "routes", app_dir / "routes"]

    for route_dir in route_dirs:
        if not route_dir.exists():
            continue
        for py_file in _collect_py_files(route_dir, exclude_dirs={"__pycache__"}):
            try:
                tree = _parse_file(py_file)
            except SyntaxError:
                continue

            # Extract router prefix from APIRouter(prefix="...")
            router_prefix = _extract_router_prefix(tree)

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    func = decorator.func
                    if not isinstance(func, ast.Attribute):
                        continue
                    method = func.attr.lower()
                    if method not in _HTTP_METHODS:
                        continue
                    # Extract path (first positional arg)
                    path: str | None = None
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        path = decorator.args[0].value
                    if path is None:
                        continue

                    # Build fully-qualified path for duplicate detection
                    full_path = (router_prefix.rstrip("/") + "/" + path.lstrip("/")).rstrip("/") or "/"

                    # Check for Depends in function params (direct or via alias)
                    has_depends = _fn_has_depends_param(node)

                    # Check decorator-level dependencies=[Depends(...)]
                    has_dec_depends = _decorator_has_depends(decorator)

                    routes.append({
                        "method": method,
                        "path": path,
                        "full_path": full_path,
                        "fn_name": node.name,
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "has_depends": has_depends or has_dec_depends,
                        "file": py_file,
                    })

    return routes


def _extract_router_prefix(tree: ast.Module) -> str:
    """Extract the prefix= string from APIRouter(prefix=...) calls."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = _call_name(node.func)
        if func_name != "APIRouter":
            continue
        for kw in node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return ""


def _fn_has_depends_param(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function has any Depends-related parameter.

    Detects:
    - param: SomeType = Depends(...)
    - param: Annotated[T, Depends(...)]  (raw form)
    - param: CurrentUser / SessionDep / etc. (well-known aliases)
    """
    all_args = node.args.args + node.args.kwonlyargs
    all_defaults = node.args.defaults + node.args.kw_defaults

    for arg in all_args:
        ann = arg.annotation
        if ann is None:
            continue
        # Alias patterns: CurrentUser, SessionDep, etc.
        if isinstance(ann, ast.Name) and _DEPENDS_ALIAS_PATTERNS.match(ann.id):
            return True
        # Annotated[T, Depends(...)]: ast.Subscript where .slice is a Tuple
        if isinstance(ann, ast.Subscript) and isinstance(ann.slice, ast.Tuple):
            for elt in ann.slice.elts:
                if isinstance(elt, ast.Call) and _call_name(elt.func) == "Depends":
                    return True

    for default in all_defaults:
        if default is None:
            continue
        if isinstance(default, ast.Call) and _call_name(default.func) == "Depends":
            return True

    return False


def _decorator_has_depends(decorator: ast.Call) -> bool:
    """Check if a route decorator has dependencies=[Depends(...)]."""
    for kw in decorator.keywords:
        if kw.arg == "dependencies" and isinstance(kw.value, ast.List):
            for elt in kw.value.elts:
                if isinstance(elt, ast.Call) and _call_name(elt.func) == "Depends":
                    return True
    return False


def test_4_route_consistency(project_dir: Path) -> tuple[bool, str]:
    """Test 4: Route registration sanity checks.

    Returns:
        (passed, message)
    """
    app_dir = project_dir / "app"
    routes = _collect_routes(app_dir)
    failures: list[str] = []

    # (a) No duplicate method + full_path combinations (within the same file)
    # We check per-file to avoid false positives from routers that get
    # mounted at different prefixes in main.py.
    file_route_map: dict[Path, dict[tuple[str, str], str]] = defaultdict(dict)
    for route in routes:
        key = (route["method"].upper(), route["full_path"])
        existing = file_route_map[route["file"]].get(key)
        if existing is not None and existing != route["fn_name"]:
            rel = route["file"].relative_to(project_dir)
            failures.append(
                f"Duplicate route {key[0]} {key[1]!r} in {rel}: "
                f"'{route['fn_name']}' conflicts with '{existing}'"
            )
        else:
            file_route_map[route["file"]][key] = route["fn_name"]

    # (b) All handlers must be async def
    for route in routes:
        if not route["is_async"]:
            rel = route["file"].relative_to(project_dir)
            failures.append(
                f"{route['fn_name']} ({rel}): {route['method'].upper()} {route['path']!r} "
                "is sync def — should be async def"
            )

    # (c) Mutating methods (POST/PATCH/DELETE) must have Depends-based injection
    # Exception: public endpoints like /signup, /password-recovery, /login, webhooks
    _PUBLIC_PATH_PATTERNS = re.compile(
        r"(/signup|/login|/password-recovery|/reset-password|/access-token|"
        r"/incoming/|/refresh)"
    )
    for route in routes:
        if route["method"] not in {"post", "patch", "delete"}:
            continue
        if route["has_depends"]:
            continue
        if _PUBLIC_PATH_PATTERNS.search(route["full_path"]):
            continue  # Public endpoints legitimately have no auth
        rel = route["file"].relative_to(project_dir)
        failures.append(
            f"{route['fn_name']} ({rel}): "
            f"{route['method'].upper()} {route['path']!r} has no Depends() injection "
            "— mutating handlers should use auth/session via Depends"
        )

    if failures:
        detail = "\n  ".join(failures)
        return False, f"Route consistency failures ({len(failures)}):\n  {detail}"

    return True, (
        f"All {len(routes)} routes consistent "
        f"(no duplicates, all async, mutating handlers have Depends)"
    )


# ---------------------------------------------------------------------------
# Test 5 — Alembic migration chain consistency
# ---------------------------------------------------------------------------

# Matches both:  revision = "foo"  and  revision: str = "foo"
_REVISION_RE = re.compile(
    r'^revision\s*(?::\s*\S+\s*)?\s*=\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)
# Matches: down_revision = "foo" | down_revision = None | down_revision: ... = None
_DOWN_REVISION_RE = re.compile(
    r'^down_revision\s*(?::\s*\S+\s*)?\s*=\s*(?:["\']([^"\']*)["\']|(None))',
    re.MULTILINE,
)


def _parse_migration(path: Path) -> dict | None:
    """Parse an Alembic migration file.

    Returns:
        Dict with revision, down_revision, has_upgrade, has_downgrade,
        downgrade_is_pass_only.  Returns None if parsing fails.
    """
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source)
    except SyntaxError:
        return None

    rev_match = _REVISION_RE.search(source)
    if rev_match is None:
        return None

    revision = rev_match.group(1)

    down_match = _DOWN_REVISION_RE.search(source)
    down_revision: str | None = None
    if down_match:
        # group(1) = string value, group(2) = "None"
        if down_match.group(1) is not None:
            down_revision = down_match.group(1)
        # group(2) = literal None → keep down_revision as None

    has_upgrade = bool(re.search(r"^def upgrade\(", source, re.MULTILINE))
    has_downgrade = bool(re.search(r"^def downgrade\(", source, re.MULTILINE))

    # Detect pass-only downgrade: body contains only "pass" (ignoring comments/docstrings)
    downgrade_is_pass_only = _is_downgrade_pass_only(source)

    return {
        "revision": revision,
        "down_revision": down_revision,
        "has_upgrade": has_upgrade,
        "has_downgrade": has_downgrade,
        "downgrade_is_pass_only": downgrade_is_pass_only,
        "file": path,
    }


def _is_downgrade_pass_only(source: str) -> bool:
    """Return True if the downgrade() function has only a pass statement."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            body = node.body
            # Filter out docstrings
            stmts = [
                s for s in body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
            ]
            return len(stmts) == 1 and isinstance(stmts[0], ast.Pass)
    return False


def test_5_migration_chain(project_dir: Path) -> tuple[bool, str]:
    """Test 5: Alembic migration chain integrity.

    Checks:
    - Every migration parses via ast.parse
    - Every migration has upgrade() and downgrade()
    - No downgrade() is pass-only
    - Revision chain is linear (no forks)

    Returns:
        (passed, message)
    """
    versions_dir = project_dir / "alembic" / "versions"
    if not versions_dir.exists():
        return False, "alembic/versions/ directory not found"

    migration_files = sorted(versions_dir.glob("*.py"))
    if not migration_files:
        return False, "No migration files found in alembic/versions/"

    failures: list[str] = []
    migrations: list[dict] = []

    for mf in migration_files:
        if mf.name == "__init__.py":
            continue
        info = _parse_migration(mf)
        if info is None:
            failures.append(
                f"{mf.name}: failed to parse — SyntaxError or missing 'revision' identifier"
            )
            continue
        migrations.append(info)

        if not info["has_upgrade"]:
            failures.append(f"{mf.name}: missing upgrade() function")

        if not info["has_downgrade"]:
            failures.append(f"{mf.name}: missing downgrade() function")

        if info["has_downgrade"] and info["downgrade_is_pass_only"]:
            failures.append(
                f"{mf.name}: downgrade() body is pass-only — must contain actual undo logic"
            )

    # Check for fork: two migrations pointing to same down_revision
    down_rev_to_files: dict[str | None, list[str]] = defaultdict(list)
    for m in migrations:
        down_rev_to_files[m["down_revision"]].append(m["file"].name)

    for down_rev, files in down_rev_to_files.items():
        if down_rev is None:
            if len(files) > 1:
                failures.append(
                    f"Migration chain fork: multiple root migrations "
                    f"(down_revision=None): {', '.join(sorted(files))}"
                )
        elif len(files) > 1:
            failures.append(
                f"Migration chain fork at '{down_rev}': "
                f"{len(files)} migrations share the same parent — "
                f"chain is not linear: {', '.join(sorted(files))}"
            )

    if failures:
        detail = "\n  ".join(failures)
        return False, f"Migration chain failures ({len(failures)}):\n  {detail}"

    return True, (
        f"All {len(migrations)} migrations valid "
        "(upgrade+downgrade present, chain is linear)"
    )


# ---------------------------------------------------------------------------
# Test 6 — Config consistency
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r'\bos\.getenv\(["\']([A-Z_][A-Z0-9_]*)["\']')
_SETTINGS_CLASS_FIELD_RE = re.compile(r'^\s{4}([A-Z_][A-Z0-9_]*)\s*(?::\s|\s*=)', re.MULTILINE)
_ENV_EXAMPLE_KEY_RE = re.compile(r'^([A-Z_][A-Z0-9_]*)=', re.MULTILINE)
# Module-level bare assignments like SECRET_KEY: int = 15 (added by tools outside Settings)
_MODULE_LEVEL_VAR_RE = re.compile(r'^([A-Z_][A-Z0-9_]*)\s*(?::\s*\S+\s*)?=', re.MULTILINE)


def test_6_config_consistency(project_dir: Path) -> tuple[bool, str]:
    """Test 6: Config/env-var coverage.

    Checks:
    - app/core/config.py exists and parses cleanly
    - All os.getenv() calls across app/ reference vars defined in
      Settings fields OR .env.example OR module-level config vars
    - SECRET_KEY has a warning/validation for the default value

    Returns:
        (passed, message)
    """
    failures: list[str] = []
    config_file = project_dir / "app" / "core" / "config.py"

    # (a) config.py must exist and parse
    if not config_file.exists():
        return False, "app/core/config.py not found"

    config_source = config_file.read_text(encoding="utf-8")
    try:
        ast.parse(config_source)
    except SyntaxError as exc:
        return False, f"app/core/config.py has SyntaxError: {exc}"

    # (b) Collect known variable names from config.py
    #     - Settings class fields
    #     - Module-level uppercase vars (added by tools like add_sse)
    settings_fields: set[str] = set(_SETTINGS_CLASS_FIELD_RE.findall(config_source))
    module_level_vars: set[str] = set(_MODULE_LEVEL_VAR_RE.findall(config_source))

    # (c) .env.example keys
    env_example_file = project_dir / ".env.example"
    env_example_keys: set[str] = set()
    if env_example_file.exists():
        env_example_keys = set(_ENV_EXAMPLE_KEY_RE.findall(env_example_file.read_text()))

    known_vars = settings_fields | env_example_keys | module_level_vars

    # (d) Scan all app/ Python files for os.getenv() calls
    app_py_files = _collect_py_files(project_dir / "app", exclude_dirs={"__pycache__"})
    undefined_refs: list[tuple[str, Path]] = []
    for py_file in app_py_files:
        source = py_file.read_text(encoding="utf-8")
        for match in _ENV_VAR_RE.finditer(source):
            var_name = match.group(1)
            if var_name not in known_vars:
                undefined_refs.append((var_name, py_file))

    if undefined_refs:
        seen_vars: set[str] = set()
        for var_name, py_file in undefined_refs:
            if var_name in seen_vars:
                continue
            seen_vars.add(var_name)
            rel = py_file.relative_to(project_dir)
            failures.append(
                f"os.getenv('{var_name}') in {rel}: "
                "not defined in Settings, module-level config, or .env.example"
            )

    # (e) SECRET_KEY must have default-value warning or validation
    has_secret_key_guard = (
        "SECRET_KEY" in config_source
        and (
            "changethis" in config_source
            or "warnings.warn" in config_source
            or "raise ValueError" in config_source
        )
    )
    if not has_secret_key_guard:
        failures.append(
            "app/core/config.py: SECRET_KEY has no default-value warning or validation"
        )

    if failures:
        detail = "\n  ".join(failures)
        return False, f"Config consistency failures ({len(failures)}):\n  {detail}"

    return True, (
        f"Config consistent: {len(settings_fields)} Settings fields, "
        f"{len(env_example_keys)} .env.example keys, "
        f"SECRET_KEY guarded"
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

_TESTS = [
    ("Import cycle detection", test_1_no_import_cycles),
    ("Model consistency",      test_2_model_consistency),
    ("Schema consistency",     test_3_schema_consistency),
    ("Route consistency",      test_4_route_consistency),
    ("Migration chain",        test_5_migration_chain),
    ("Config consistency",     test_6_config_consistency),
]


def run_all_tests() -> int:
    """Build the 10-tool project once, then run all 6 consistency tests.

    Returns:
        Number of tests that passed.
    """
    print("=" * 70)
    print("CONSISTENCY TESTS — 10-tool FastAPI project")
    print("=" * 70)

    print("\n[SETUP] Generating base project + applying 10 tools...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            project_dir = _build_10_tool_project(tmp_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[FATAL] Could not build project: {exc}")
            traceback.print_exc()
            return 0

        print(f"[SETUP] Project at: {project_dir}")
        print()

        passed = 0
        for i, (name, fn) in enumerate(_TESTS, 1):
            print(f"[TEST {i}/6] {name}")
            try:
                ok, msg = fn(project_dir)
            except Exception as exc:  # noqa: BLE001
                ok = False
                msg = f"EXCEPTION: {exc}"
                traceback.print_exc()

            status = "PASS" if ok else "FAIL"
            indented_msg = msg.replace("\n", "\n  ")
            print(f"  [{status}] {indented_msg}")
            if ok:
                passed += 1
            print()

        print("=" * 70)
        print(f"RESULT: {passed}/6 tests passed")
        print("=" * 70)

    return passed


if __name__ == "__main__":
    passed = run_all_tests()
    print(f"\nConsistency: {passed}/6 tests pass")
    sys.exit(0 if passed == 6 else 1)
