"""Layer E — static scan of the emitted source."""
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


def test_E_static__secrets_module_used_for_token_generation() -> None:
    """Random tokens must come from a cryptographically safe source:
    `secrets` module, or `os.urandom`, or `uuid.uuid4`. A plain
    `random.random()` / `random.randint()` is predictable → fail.
    """
    root = _emitted_dir()
    bad_random_calls = []
    safe_calls = False
    for py in _py_files(root):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if any(k in text for k in ("secrets.token", "os.urandom", "uuid.uuid4")):
            safe_calls = True
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if fn in ("random.random", "random.randint", "random.choice") and "token" in text.lower():
                    bad_random_calls.append(f"{py.name}: {fn}")
    assert safe_calls, "no cryptographically safe token source (secrets / os.urandom / uuid.uuid4)"
    assert not bad_random_calls, f"predictable random used for tokens: {bad_random_calls[:3]}"


def test_E_static__no_plaintext_password_field() -> None:
    """The spec doesn't require passwords, but naked agents sometimes add a
    `password = body.password` assignment and log it. Flag any write of a
    `password` key to a log/print or module-level store.
    """
    root = _emitted_dir()
    offending = []
    for py in _py_files(root):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            s = line.strip().lower()
            if s.startswith("print(") and "password" in s:
                offending.append(f"{py.name}: {line.strip()[:80]}")
    assert not offending, f"password leaked into print(): {offending[:3]}"
