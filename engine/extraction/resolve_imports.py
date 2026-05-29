#!/usr/bin/env python3
"""Import resolver: infer the imports an extracted primitive needs.

The EXTEND tools emit code into scaffolded projects; the imports are added
separately by the tool writer, NOT included in the embedded string template.
When we lift a class/function out of a template, we lose the imports.

This module walks the AST, identifies every Name / Attribute reference to a
symbol NOT defined locally, and resolves each against a curated
`KNOWN_SYMBOLS` table mapping symbol-name → canonical import statement.

Two-pass resolution:
  1. Structural: stdlib + widely-used third-party (hmac, secrets, base64,
     datetime, dataclasses, typing, collections.abc, re, asyncio, threading,
     json, uuid, time, contextlib, pathlib, enum, functools, hashlib).
  2. Framework: FastAPI / Pydantic / SQLAlchemy / Redis / structlog /
     OpenTelemetry — these CAN be in scope for an extracted primitive but
     often indicate tool-specific coupling; we emit them but flag the
     primitive as `coupling_warning`.

Unresolved symbols are returned as `unresolved` so the caller decides:
suppress, stub, or reject.
"""

from __future__ import annotations

import ast
import builtins
from typing import Final

# --- Canonical symbol → import mapping. Ordered so stdlib wins on collision.
_STDLIB_SYMBOLS: Final[dict[str, str]] = {
    # hashlib / crypto
    "hashlib": "import hashlib",
    "hmac": "import hmac",
    "secrets": "import secrets",
    "base64": "import base64",
    # time / datetime
    "time": "import time",
    "datetime": "from datetime import datetime",
    "timezone": "from datetime import timezone",
    "timedelta": "from datetime import timedelta",
    "UTC": "from datetime import UTC",
    # types / collections — modern preferred
    "Any": "from typing import Any",
    "Callable": "from collections.abc import Callable",
    "Iterator": "from collections.abc import Iterator",
    "Mapping": "from collections.abc import Mapping",
    "MutableMapping": "from collections.abc import MutableMapping",
    "Sequence": "from collections.abc import Sequence",
    "MutableSequence": "from collections.abc import MutableSequence",
    "Iterable": "from collections.abc import Iterable",
    "AsyncIterator": "from collections.abc import AsyncIterator",
    "AsyncIterable": "from collections.abc import AsyncIterable",
    "Awaitable": "from collections.abc import Awaitable",
    "Coroutine": "from collections.abc import Coroutine",
    "Generator": "from collections.abc import Generator",
    "AsyncGenerator": "from collections.abc import AsyncGenerator",
    "Hashable": "from collections.abc import Hashable",
    "Container": "from collections.abc import Container",
    "Collection": "from collections.abc import Collection",
    "Final": "from typing import Final",
    "Protocol": "from typing import Protocol",
    "runtime_checkable": "from typing import runtime_checkable",
    "TypeVar": "from typing import TypeVar",
    "TypeAlias": "from typing import TypeAlias",
    "Literal": "from typing import Literal",
    "cast": "from typing import cast",
    "Self": "from typing import Self",
    "overload": "from typing import overload",
    "TYPE_CHECKING": "from typing import TYPE_CHECKING",
    "ClassVar": "from typing import ClassVar",
    "NoReturn": "from typing import NoReturn",
    # Legacy typing — plenty of real codebases still use these.
    "Optional": "from typing import Optional",
    "Union": "from typing import Union",
    "List": "from typing import List",
    "Dict": "from typing import Dict",
    "Tuple": "from typing import Tuple",
    "Set": "from typing import Set",
    "FrozenSet": "from typing import FrozenSet",
    "Type": "from typing import Type",
    # collections (concrete containers)
    "deque": "from collections import deque",
    "defaultdict": "from collections import defaultdict",
    "OrderedDict": "from collections import OrderedDict",
    "Counter": "from collections import Counter",
    "ChainMap": "from collections import ChainMap",
    "namedtuple": "from collections import namedtuple",
    # queue
    "Queue": "from queue import Queue",
    "LifoQueue": "from queue import LifoQueue",
    "PriorityQueue": "from queue import PriorityQueue",
    # abc
    "ABC": "from abc import ABC",
    "abstractmethod": "from abc import abstractmethod",
    # itertools
    "chain": "from itertools import chain",
    "count": "from itertools import count",
    "cycle": "from itertools import cycle",
    "islice": "from itertools import islice",
    "dataclass": "from dataclasses import dataclass",
    "field": "from dataclasses import field",
    "fields": "from dataclasses import fields",
    "replace": "from dataclasses import replace",
    "asdict": "from dataclasses import asdict",
    "is_dataclass": "from dataclasses import is_dataclass",
    "Enum": "from enum import Enum",
    "IntEnum": "from enum import IntEnum",
    "auto": "from enum import auto",
    "MappingProxyType": "from types import MappingProxyType",
    # concurrency
    "threading": "import threading",
    "asyncio": "import asyncio",
    "contextmanager": "from contextlib import contextmanager",
    "asynccontextmanager": "from contextlib import asynccontextmanager",
    "suppress": "from contextlib import suppress",
    "ContextVar": "from contextvars import ContextVar",
    # json / logging / paths / misc
    "json": "import json",
    "logging": "import logging",
    "Path": "from pathlib import Path",
    "uuid": "import uuid",
    "UUID": "from uuid import UUID",
    "re": "import re",
    "math": "import math",
    "copy": "import copy",
    "functools": "import functools",
    "wraps": "from functools import wraps",
    "cached_property": "from functools import cached_property",
    "lru_cache": "from functools import lru_cache",
    "partial": "from functools import partial",
    "os": "import os",
    "sys": "import sys",
}

_FRAMEWORK_SYMBOLS: Final[dict[str, str]] = {
    # Pydantic — usage implies DTO/config coupling.
    "BaseModel": "from pydantic import BaseModel",
    "Field": "from pydantic import Field",
    "ConfigDict": "from pydantic import ConfigDict",
    "field_validator": "from pydantic import field_validator",
    "model_validator": "from pydantic import model_validator",
    # FastAPI / Starlette
    "HTTPException": "from fastapi import HTTPException",
    "Depends": "from fastapi import Depends",
    "Request": "from fastapi import Request",
    "Response": "from fastapi import Response",
    "APIRouter": "from fastapi import APIRouter",
    "status": "from fastapi import status",
    "BaseHTTPMiddleware": "from starlette.middleware.base import BaseHTTPMiddleware",
    "ASGIApp": "from starlette.types import ASGIApp",
    # SQLAlchemy
    "AsyncSession": "from sqlalchemy.ext.asyncio import AsyncSession",
    "select": "from sqlalchemy import select",
    # Redis
    "Redis": "from redis.asyncio import Redis",
    # Structlog / OTel
    "structlog": "import structlog",
    "trace": "from opentelemetry import trace",
    "metrics": "from opentelemetry import metrics",
}

_ALL_KNOWN: Final[dict[str, str]] = {**_STDLIB_SYMBOLS, **_FRAMEWORK_SYMBOLS}

_BUILTINS = frozenset(dir(builtins))


class _DefinedNames(ast.NodeVisitor):
    """Collect every symbol name *defined* at any scope — modules, classes,
    functions. We don't preserve scope because import resolution is a
    whole-module concern; a `from x import y` at module-level covers every
    reference to `y`, including those inside function bodies.

    Defining sites we track:
      - class/function/async-function names (+ their bodies recursively)
      - assignment targets (simple, ann-assign, aug-assign)
      - function parameters (positional, kw-only, *args, **kwargs)
      - comprehension loop variables
      - `for`/`async for` targets
      - `with`/`async with` `as` targets
      - `except ... as e` targets
      - walrus (`:=`) targets
      - import aliases
    """

    def __init__(self) -> None:
        self.defined: set[str] = set()

    # --- class/function shells ------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined.add(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defined.add(node.name)
        self._collect_args(node.args)
        self.generic_visit(node)  # descend so nested classes' names register

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.defined.add(node.name)
        self._collect_args(node.args)
        self.generic_visit(node)

    def _collect_args(self, args: ast.arguments) -> None:
        for a in args.posonlyargs:
            self.defined.add(a.arg)
        for a in args.args:
            self.defined.add(a.arg)
        for a in args.kwonlyargs:
            self.defined.add(a.arg)
        if args.vararg is not None:
            self.defined.add(args.vararg.arg)
        if args.kwarg is not None:
            self.defined.add(args.kwarg.arg)

    # --- assignments ----------------------------------------------------------
    def _record_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.defined.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._record_target(elt)
        elif isinstance(target, ast.Starred):
            self._record_target(target.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_target(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        # Walrus: `x := expr`
        self._record_target(node.target)
        self.generic_visit(node)

    # --- loops / with / except ------------------------------------------------
    def visit_For(self, node: ast.For) -> None:
        self._record_target(node.target)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._record_target(node.target)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._record_target(node.target)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._record_target(item.optional_vars)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._record_target(item.optional_vars)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.defined.add(node.name)
        self.generic_visit(node)

    # --- imports (already-imported symbols) -----------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # `import foo.bar` binds `foo`; `import foo.bar as baz` binds `baz`.
            self.defined.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.defined.add(alias.asname or alias.name)


class _ReferencedNames(ast.NodeVisitor):
    """Collect every bare Name reference in load-context (i.e. read, not write)."""

    def __init__(self) -> None:
        self.referenced: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.referenced.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Attribute references like `foo.bar` — we care about `foo` (the root).
        # Default visit_Name handles it via `generic_visit`.
        self.generic_visit(node)


def resolve_imports(source: str) -> tuple[list[str], set[str], set[str]]:
    """Return (import_statements, resolved_symbol_names, unresolved_symbol_names).

    Deterministic: imports are sorted. Unresolved = referenced but neither
    builtin nor in the `_ALL_KNOWN` table nor defined locally; caller decides.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], set(), set()

    defined = _DefinedNames()
    defined.visit(tree)

    referenced = _ReferencedNames()
    referenced.visit(tree)

    needed = referenced.referenced - defined.defined - _BUILTINS

    stmts: set[str] = set()
    resolved: set[str] = set()
    unresolved: set[str] = set()
    for name in needed:
        if name in _ALL_KNOWN:
            stmts.add(_ALL_KNOWN[name])
            resolved.add(name)
        else:
            unresolved.add(name)

    # `from __future__ import annotations` always leads the block — it is
    # critical for the HuGR typing style and must precede any other import.
    sorted_stmts = ["from __future__ import annotations", *sorted(stmts)]
    return sorted_stmts, resolved, unresolved


def prepend_imports(source: str) -> tuple[str, set[str]]:
    """Prepend resolved imports to `source` and return (new_source, unresolved).

    Skips any import already present in `source` — avoids duplicate
    `from __future__ import annotations` (which is benign per CPython but
    tripped by linters / py-compile strictness) and avoids cluttering
    already-import-complete sources.
    """
    stmts, _resolved, unresolved = resolve_imports(source)
    # Detect existing imports via a trivial line-prefix scan. This is a string
    # comparison, not AST — good enough to dedupe the single-line canonical
    # forms we emit.
    existing_prefixes = {
        ln.split("#", 1)[0].strip()
        for ln in source.splitlines()
        if ln.startswith(("import ", "from "))
    }
    new_stmts = [s for s in stmts if s not in existing_prefixes]
    if not new_stmts:
        return source, unresolved
    header = "\n".join(new_stmts) + "\n\n\n"
    return header + source, unresolved
