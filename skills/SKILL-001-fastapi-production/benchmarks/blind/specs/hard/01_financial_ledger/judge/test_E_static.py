"""Layer E — static scan of the emitted source.

These tests run WITHOUT booting the app. They read BLIND_EMITTED_DIR and
assert code-level hygiene invariants that often trip naked agents.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


def _emitted_dir() -> Path:
    p = os.environ.get("BLIND_EMITTED_DIR")
    if not p:
        pytest.skip("BLIND_EMITTED_DIR not set")
    return Path(p)


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file() and "__pycache__" not in p.parts]


def test_E_static__no_float_type_annotations_for_money() -> None:
    """Money must be int cents, per Requirements §1. Any `float` annotation
    whose name contains 'amount', 'balance', or 'cents' is a failure —
    checked on function args, return types, AnnAssign (module/class vars),
    and generic container parameters like `dict[str, float]`.
    """
    root = _emitted_dir()
    offending: list[str] = []
    money_names = ("amount", "balance", "cents", "_balances", "_amount")

    def _is_money_name(name: str | None) -> bool:
        if not name:
            return False
        n = name.lower()
        return any(k in n for k in money_names)

    def _flag(where: str, ann_src: str) -> None:
        if "float" in ann_src and "int" not in ann_src:
            offending.append(f"{where}: {ann_src}")

    for py in _py_files(root):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            # Function arg + return annotations
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args + node.args.kwonlyargs:
                    if arg.annotation and _is_money_name(arg.arg):
                        _flag(f"{py.name}::{node.name}({arg.arg})", ast.unparse(arg.annotation))
                if node.returns and _is_money_name(node.name):
                    _flag(f"{py.name}::{node.name}() -> ", ast.unparse(node.returns))
            # Module/class variable annotations: `_balances: dict[str, float]`
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if _is_money_name(node.target.id) and node.annotation:
                    _flag(f"{py.name}::{node.target.id}", ast.unparse(node.annotation))

    assert not offending, (
        f"money-typed values use float; must be int cents per spec §1: {offending[:5]}"
    )


def test_E_static__idempotency_primitive_or_store_present() -> None:
    """Emitted code must reference SOME idempotency mechanism — either the
    kit's IdempotencyStore / IdempotentConsumer primitive, or at minimum a
    persistent dedup table / set keyed by idempotency_key. A pure
    `seen = set()` module-level global is NOT acceptable — it loses state
    across workers and is caught here by the module-global heuristic.
    """
    root = _emitted_dir()
    found_kit = False
    found_table = False
    offending_global_set: list[str] = []
    for py in _py_files(root):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "IdempotencyStore" in text or "IdempotentConsumer" in text:
            found_kit = True
        if "idempotency_key" in text and (
            "class " in text or "Table(" in text or "__tablename__" in text
        ):
            found_table = True
        # detect naive `seen = set()` at module level as a failure signal
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id.lower() in ("seen", "processed", "keys", "idempotency")
                        and isinstance(node.value, ast.Call)
                        and getattr(node.value.func, "id", "") == "set"
                    ):
                        offending_global_set.append(f"{py.name}:{target.id} = set()")
    assert found_kit or found_table, (
        "no idempotency mechanism detected — neither kit primitive "
        "(IdempotencyStore / IdempotentConsumer) nor a persistent dedup table is present"
    )
    assert not offending_global_set, (
        f"naive in-memory idempotency globals detected: {offending_global_set}"
    )
