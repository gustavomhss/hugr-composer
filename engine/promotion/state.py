"""Machine-measured state inspection for staged primitives.

Every field here is derived deterministically from files on disk. No
heuristic names, no LLM calls, no hidden magic. Two runs over an
unchanged tree produce identical output.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import yaml

from engine.promotion.schemas import StateFlags

SKILL_ROOT = Path(__file__).resolve().parents[2]


def _count_replace_me(primitive_dir: Path) -> int:
    """Sum of REPLACE_ME markers across every file in the tree."""
    n = 0
    for f in primitive_dir.rglob("*"):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        try:
            n += f.read_text(encoding="utf-8", errors="ignore").count("REPLACE_ME")
        except OSError:
            continue
    return n


def _primary_py(primitive_dir: Path, name: str) -> Path | None:
    """The primitive's canonical implementation file."""
    candidate = primitive_dir / f"{name}.py"
    return candidate if candidate.exists() else None


_CONCURRENCY_MODULES = {"threading", "multiprocessing", "asyncio"}
_CONCURRENCY_NAMES = {"Lock", "RLock", "Semaphore", "Event", "Queue", "Condition"}

# Registered primitives may not import these (CONTRACT §B1.0.1).
_FRAMEWORK_MODULES = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "sqlmodel",
    "pydantic",
    "django",
    "flask",
    "tornado",
    "aiohttp",
}


def _detect_concurrency(py_path: Path | None) -> bool:
    """True if the primitive's primary .py imports or uses concurrency."""
    if py_path is None:
        return False
    try:
        text = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _CONCURRENCY_MODULES:
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _CONCURRENCY_MODULES:
                return True
            for alias in node.names:
                if alias.name in _CONCURRENCY_NAMES:
                    return True
        elif isinstance(node, ast.Attribute):
            # e.g. threading.Lock() used after an `import threading`
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in _CONCURRENCY_MODULES
            ):
                return True
    return False


def _detect_mutable_class_state(py_path: Path | None) -> bool:
    """Heuristic: any class with >1 `self.<name> = ` mutation outside __init__."""
    if py_path is None:
        return False
    try:
        text = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        mutations_outside_init = 0
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                continue
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(item):
                if (
                    isinstance(sub, ast.Assign)
                    and any(
                        isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == "self"
                        for t in sub.targets
                    )
                ):
                    mutations_outside_init += 1
        if mutations_outside_init > 0:
            return True
    return False


# Implicit framework signatures: names that strongly imply framework
# coupling even when the file lacks the import (an extraction bug we
# inherit — the registered-primitive rule still applies).
_IMPLICIT_FRAMEWORK_TOKENS = {
    # SQLAlchemy 2.0 ORM
    "Mapped[": "sqlalchemy",
    "mapped_column(": "sqlalchemy",
    "DeclarativeBase": "sqlalchemy",
    "class Base(": "sqlalchemy",
    "(Base)": "sqlalchemy",
    # FastAPI / Starlette
    "APIRouter(": "fastapi",
    "Depends(": "fastapi",
    "FastAPI(": "fastapi",
    "Request(": "starlette",
    "BaseHTTPMiddleware": "starlette",
    # Pydantic v2 hints
    "class Config:\n": "pydantic",
}


def _detect_framework_imports(py_path: Path | None) -> list[str]:
    """Framework imports (explicit or implicit) in the primitive's primary .py.

    Explicit: AST-detected imports of known framework modules.
    Implicit: textual tokens like `Mapped[`, `APIRouter(`, etc. that
    appear without the corresponding import — strong signal the
    primitive was extracted incompletely and isn't framework-free.

    Registered primitives are framework-agnostic (CONTRACT §B1.0.1).
    Any match here is a hard blocker for promotion.
    """
    if py_path is None or not py_path.exists():
        return []
    try:
        text = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FRAMEWORK_MODULES:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _FRAMEWORK_MODULES:
                found.add(top)
    for token, label in _IMPLICIT_FRAMEWORK_TOKENS.items():
        if token in text:
            found.add(label)
    return sorted(found)


def _count_loc(py_path: Path | None) -> int:
    if py_path is None or not py_path.exists():
        return 0
    try:
        return sum(1 for _ in py_path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def _has_tla(primitive_dir: Path, name: str) -> bool:
    return (primitive_dir / f"{name}.tla").exists()


def _quarantine_metadata(primitive_dir: Path) -> tuple[str, list[str]]:
    q = primitive_dir / "_quarantined.json"
    if not q.exists():
        return "", []
    try:
        data = json.loads(q.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "", []
    return data.get("reason", ""), list(data.get("forbidden_modules", []))


def _origin_primitive_score(primitive_dir: Path) -> tuple[int, str]:
    o = primitive_dir / "_origin.json"
    if not o.exists():
        return 0, ""
    try:
        data = json.loads(o.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0, ""
    candidate = data.get("candidate", {}) if isinstance(data.get("candidate"), dict) else {}
    score = int(candidate.get("primitive_score", 0) or 0)
    tool = data.get("tool") or candidate.get("tool") or ""
    return score, tool


def _invariants_stubbed(primitive_dir: Path, name: str) -> bool:
    """REPLACE_ME markers specifically inside invariant_bindings.json or test file."""
    ib = primitive_dir / "invariant_bindings.json"
    tf = primitive_dir / f"test_{name}.py"
    for f in (ib, tf):
        if f.exists():
            try:
                if "REPLACE_ME" in f.read_text(encoding="utf-8", errors="ignore"):
                    return True
            except OSError:
                continue
    return False


def _registered_primitive_names() -> set[str]:
    reg_yaml = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
    if not reg_yaml.exists():
        return set()
    try:
        data = yaml.safe_load(reg_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return set()
    if not isinstance(data, dict):
        return set()
    return {p.get("name", "") for p in data.get("primitives", []) if p.get("name")}


def _shape_hash(primitive_dir: Path) -> str:
    o = primitive_dir / "_origin.json"
    if not o.exists():
        return ""
    try:
        data = json.loads(o.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    candidate = data.get("candidate", {})
    return str(candidate.get("shape_hash", "") or "")


def measure(
    primitive_dir: Path,
    name: str,
    namespace: str,
    is_quarantined: bool,
    registered_names: set[str] | None = None,
) -> StateFlags:
    """Compute all state flags for one staged primitive."""
    primary = _primary_py(primitive_dir, name)
    q_reason, q_forbidden = _quarantine_metadata(primitive_dir)
    score, tool = _origin_primitive_score(primitive_dir)
    registered_names = registered_names or _registered_primitive_names()
    duplicate = name if name in registered_names else None

    return StateFlags(
        name=name,
        namespace=namespace,
        is_quarantined=is_quarantined,
        replace_me_count=_count_replace_me(primitive_dir),
        has_tla=_has_tla(primitive_dir, name),
        has_concurrency=_detect_concurrency(primary),
        has_mutable_class_state=_detect_mutable_class_state(primary),
        loc=_count_loc(primary),
        primitive_score=score,
        origin_tool=tool,
        quarantine_reason=q_reason,
        forbidden_modules=q_forbidden,
        duplicate_of_registered=duplicate,
        test_file_present=(primitive_dir / f"test_{name}.py").exists(),
        invariants_stubbed=_invariants_stubbed(primitive_dir, name),
        framework_imports=_detect_framework_imports(primary),
    )
