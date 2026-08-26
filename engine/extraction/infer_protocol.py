#!/usr/bin/env python3
"""Protocol inference: auto-generate a `Protocol` wrapper from an extracted class.

For a class `FooService` with public methods `bar(x: int) -> str` and
`baz(y: bytes) -> bool`, synthesize:

    @runtime_checkable
    class FooService(Protocol):
        def bar(self, x: int) -> str: ...
        def baz(self, y: bytes) -> bool: ...

Rules:
  - Only public methods are included (no leading underscore).
  - Dunder methods are excluded EXCEPT `__call__` (classes-as-callables).
  - Type annotations are preserved byte-for-byte when present; missing
    annotations are emitted as `...` (caller must review).
  - `classmethod` / `staticmethod` are kept in the Protocol with the
    original decorator.
  - Return type defaults to `None` for coroutines with no explicit return;
    sync methods default to `object`.
"""

from __future__ import annotations

import ast

_INCLUDED_DUNDERS: frozenset[str] = frozenset({"__call__"})


def _arg_str(args: ast.arguments) -> str:
    parts: list[str] = []
    # Positional + keyword-only.
    defaults = args.defaults
    default_offset = len(args.args) - len(defaults)
    for i, a in enumerate(args.args):
        if a.arg == "self":
            parts.append("self")
            continue
        annot = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        default = ""
        if i >= default_offset:
            d = defaults[i - default_offset]
            default = f" = {ast.unparse(d)}"
        parts.append(f"{a.arg}{annot}{default}")
    if args.kwonlyargs:
        parts.append("*")
        for i, a in enumerate(args.kwonlyargs):
            annot = f": {ast.unparse(a.annotation)}" if a.annotation else ""
            d = args.kw_defaults[i] if i < len(args.kw_defaults) else None
            default = f" = {ast.unparse(d)}" if d is not None else ""
            parts.append(f"{a.arg}{annot}{default}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)


def _decorator_names_named(decorators: list[ast.expr]) -> list[str]:
    names: list[str] = []
    for d in decorators:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            names.append(d.attr)
    return names


def _method_signature(method: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    name = method.name
    if name.startswith("_") and name not in _INCLUDED_DUNDERS:
        return None
    if name.startswith("__") and name.endswith("__") and name not in _INCLUDED_DUNDERS:
        return None
    is_async = isinstance(method, ast.AsyncFunctionDef)
    # Protocol methods with no declared return default to `None` — `object`
    # is too permissive and would let runtime_checkable succeed against any
    # return shape, defeating the point of the Protocol surface.
    ret = ast.unparse(method.returns) if method.returns else "None"
    dec_names = _decorator_names_named(method.decorator_list)
    is_static = "staticmethod" in dec_names
    is_classmethod = "classmethod" in dec_names
    is_property = "property" in dec_names or "cached_property" in dec_names
    is_abstract = "abstractmethod" in dec_names

    # Start with full arg list, then drop the leading `self` if the decorator
    # says this is a staticmethod (no implicit self in the Protocol surface).
    args_str = _arg_str(method.args)
    if is_static and args_str.startswith("self"):
        args_str = args_str[len("self") :].lstrip(", ").strip()

    prefix = "async def " if is_async else "def "
    sig = f"    {prefix}{name}({args_str}) -> {ret}: ..."
    decs: list[str] = []
    if is_abstract:
        decs.append("abstractmethod")
    if is_classmethod:
        decs.append("classmethod")
    if is_static:
        decs.append("staticmethod")
    if is_property:
        decs.append("property")
    decorator_block = "".join(f"    @{d}\n" for d in decs)
    return decorator_block + sig


def _module_defined_names(tree: ast.Module) -> set[str]:
    """Names defined at module level in `tree` (classes, functions, aliases)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
            else:
                names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _annotation_names(class_node: ast.ClassDef) -> set[str]:
    """Collect bare names referenced in the class's method annotations."""
    names: set[str] = set()

    def _walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
            return
        for child in ast.iter_child_nodes(node):
            _walk(child)

    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in (*item.args.args, *item.args.kwonlyargs, *item.args.posonlyargs):
                if arg.annotation:
                    _walk(arg.annotation)
            if item.returns:
                _walk(item.returns)
    return names


def infer_protocol(class_node: ast.ClassDef, suffix: str = "Protocol") -> str | None:
    """Produce a `@runtime_checkable` Protocol class source for the given class.

    The Protocol is named `<ClassName><suffix>` to avoid shadowing the impl.
    Returns None when the class has zero eligible public methods (not useful).
    """
    methods: list[str] = []
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _method_signature(item)
            if sig is not None:
                methods.append(sig)
    if not methods:
        return None
    body = "\n".join(methods)
    protocol_name = f"{class_node.name}{suffix}"
    return (
        "@runtime_checkable\n"
        f"class {protocol_name}(Protocol):\n"
        f'    """Auto-inferred Protocol surface for `{class_node.name}`.\n'
        "\n"
        "    Generated by `engine.extraction.infer_protocol`; review and tighten\n"
        "    annotations before promoting the primitive out of `_staging/`.\n"
        '    """\n\n'
        f"{body}\n"
    )


def protocol_for_source(source: str, module_name: str | None = None) -> list[str]:
    """Return one Protocol source string per public class in `source`.

    `module_name` is the impl module's file stem (e.g. ``KeyValueBucket``
    for ``KeyValueBucket.py``). When given, types defined in the same module
    that the protocol references are imported from it — without this the
    standalone ``*.protocol.py`` is an F821 (undefined-name) bug.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    module_names = _module_defined_names(tree)
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            proto = infer_protocol(node)
            if proto is not None:
                if module_name:
                    referenced = _annotation_names(node)
                    missing = sorted(referenced & module_names - {node.name})
                    if missing:
                        proto = f"from {module_name} import {', '.join(missing)}\n\n" + proto
                out.append(proto)
    return out
