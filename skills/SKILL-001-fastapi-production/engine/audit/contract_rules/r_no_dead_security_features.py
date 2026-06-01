"""B0.10 — no_dead_security_features.

CONTRACT.md scope: §B0.10 — no ``# TODO`` / ``# FIXME`` / ``# XXX``
markers and no ``pass``-only function bodies in security-tagged tool
templates / ``_patches.py`` / ``_helpers.py``.

Rationale (Round-5 / Round-6 anti-pattern P1, see
``docs/wp/ROUND5_6_TRIAGE.md`` §3): Round-5/6 jurors converged on a
common shape — security features documented in tool ``notes=`` /
``description`` whose template ships a ``# TODO`` placeholder, so the
feature does not exist at runtime. Eight concrete BLOCKER findings
clustered on this pattern (jti blocklist, family-invalidation listener,
DPoP ``bind_access_token`` formula, adaptive_throttle ``cost_weight``,
feature_flags invalidation listener, DLQ across 4 jobs tools, refund
Stripe call, etc.).

This rule makes the whole class unshippable:

* Scans every ``*.py.tmpl`` template + every ``_patches.py`` /
  ``_helpers.py`` under the **security surface**:
    - ``adapt/extend/auth_access/**`` (every tool)
    - ``adapt/extend/infrastructure/<security-named-tool>/`` for the
      explicit list (rate_limiting, csrf_protection, cors_config,
      audit_log [under crud_data], dlp_shield, runtime_sentinel,
      canary_tokens, request_signing, dpop_tokens)
    - any tool whose ``catalog.json`` entry has a ``security`` tag.
* For each scanned file rejects on:
    1. ``# TODO`` / ``# FIXME`` / ``# XXX`` comments **inside a function
       body** (module-level comment-block "future work" notes are NOT
       a security regression — they are documentation; allowed).
    2. A function whose body is exactly ``pass`` (with or without a
       trailing placeholder comment) — except for ``@abstractmethod``-
       decorated methods, which are legitimate abstract declarations,
       not security placeholders.

Test-template skip (Round-5 jurors confirmed): templates that emit
pytest test scaffolding for the user (``test_*_emitted.py.tmpl``,
``bola_test_gen.py.tmpl``, ``bola_block_per_model.py.tmpl``) carry
intentional ``# TODO`` markers for the user to fill in (JWT, fixture
data). Test templates are detected by name (``test_`` prefix /
``_test`` suffix) OR content (``@pytest.fixture``, top-level
``def test_``, ``import pytest``) and skipped. The rule scans
**implementation** templates only.

Bypass — when a security feature is genuinely incomplete-but-disclosed:

  1. The tool's ``__init__.py`` declares a module-level mapping::

        _FEATURE_INCOMPLETE: dict[str, str] = {
            "feature_name": "one-line justification",
        }

  2. The tool's ``ToolResult`` returns ``warnings=[...]`` (NOT
     ``notes=``) and at least one warning string mentions the
     ``feature_name`` key. Round-6-S12-F4 flagged tools that disclose
     security gaps inside ``notes=`` (which agents read as success
     prose) instead of ``warnings=`` (which agents must surface);
     the bypass enforces the correct field.

The ``warnings=`` audit is conservative: we grep the source for
``warnings=`` and check at least one occurrence is followed by a
literal list whose elements mention each ``_FEATURE_INCOMPLETE`` key.

Trade-offs:

* **AST `Constant` scan vs token scan.** We scan source lines with a
  regex for the marker tokens, then use AST function-range information
  to decide if the line is inside a function body. This is cheap and
  matches the ``contract_check`` style; the alternative — walking AST
  ``ast.Constant`` nodes — would miss tokens in regular comments
  because comments are not in the AST.
* **Module-level `# TODO` allowed.** A file-top comment block
  describing future work for the file as a whole is documentation,
  not a silent security gap. Function-body markers are the regression
  the P1 cluster identified.
* **Whole-file pass-only skip.** The pass-only body check matches a
  function whose body is ONLY ``pass`` after optional docstring. It
  does NOT flag a function that contains a real implementation plus a
  ``pass`` statement inside a branch — that is valid control flow.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from ._common import SKILL_ROOT

# ---------------------------------------------------------------------------
# Scope — security surface
# ---------------------------------------------------------------------------

# Per docs/wp/ROUND5_6_TRIAGE.md §3 P1: explicit list of security-named
# tools regardless of catalog tagging. ``add_audit_log`` lives under
# ``crud_data/`` not ``infrastructure/`` (catalog confirms).
_SECURITY_NAMED_TOOLS: dict[str, str] = {
    # tool-dir-name -> parent extend-category
    "add_rate_limiting": "infrastructure",
    "add_csrf_protection": "infrastructure",
    "add_cors_config": "infrastructure",
    "add_dlp_shield": "infrastructure",
    "add_runtime_sentinel": "infrastructure",
    "add_canary_tokens": "infrastructure",
    "add_request_signing": "auth_access",
    "add_dpop_tokens": "auth_access",
    "add_audit_log": "crud_data",
}

# Waiver list — populated by current catalog scan (none today). Listed
# here so a future contributor can grep-find every tool that ever had
# a sanctioned incomplete-security-feature exception. A tool waived
# via this set must STILL ship the ``_FEATURE_INCOMPLETE`` +
# ``warnings=`` bypass; the set just acknowledges the known case at
# the rule level for audit traceability.
_WAIVED_TOOLS: frozenset[str] = frozenset()

# Markers that indicate an unresolved placeholder.
_MARKER_RE = re.compile(r"#\s*(TODO|FIXME|XXX)\b", re.IGNORECASE)

# Marker scan for docstring-embedded "future work" disclosures. Round-7
# O3-F2 (HIGH) showed that the body-comment rule (``# TODO``) is evaded
# by hoisting the marker into the function's docstring — the same
# disclosure shape, but invisible to a comment-only scan. Pattern does
# NOT require a leading ``#`` since docstrings are string-literal text.
_DOCSTRING_MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX)\b", re.IGNORECASE)

# Test-template content sentinels.
_TEST_CONTENT_SENTINELS: tuple[str, ...] = (
    "@pytest.fixture",
    "\nimport pytest",
    "\nfrom pytest",
)


# ---------------------------------------------------------------------------
# Tool-directory discovery
# ---------------------------------------------------------------------------


def _security_tool_dirs() -> list[Path]:
    """Return every tool directory in scope for the security audit.

    Order: auth_access tools (sorted), then explicit security-named
    tools (sorted), then catalog-tagged ``security`` tools not already
    covered. Each entry is a directory containing an ``__init__.py``
    plus ``templates/`` (the standard tool layout); single-file
    tools (e.g. ``add_mfa.py``) are also included.
    """
    extend = SKILL_ROOT / "adapt" / "extend"
    dirs: list[Path] = []
    seen: set[Path] = set()

    auth = extend / "auth_access"
    if auth.is_dir():
        for child in sorted(auth.iterdir()):
            if child.is_dir() and not child.name.startswith("_"):
                dirs.append(child)
                seen.add(child)

    for tool_name, category in sorted(_SECURITY_NAMED_TOOLS.items()):
        p = extend / category / tool_name
        if p.is_dir() and p not in seen:
            dirs.append(p)
            seen.add(p)

    # Catalog-tagged security tools.
    catalog_path = SKILL_ROOT / "engine" / "index" / "catalog.json"
    if catalog_path.exists():
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for tool in data.get("tools", []) or []:
            tags = tool.get("tags") or []
            if "security" not in [str(t).lower() for t in tags]:
                continue
            mp = tool.get("module_path") or ""
            if not mp:
                continue
            tool_path = SKILL_ROOT / mp
            tool_dir = tool_path.parent if tool_path.suffix == ".py" else tool_path
            if tool_dir.is_dir() and tool_dir not in seen:
                dirs.append(tool_dir)
                seen.add(tool_dir)

    return dirs


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


def _is_in_scope(path: Path) -> bool:
    """A scanned file is in scope iff it is a template / patches / helpers
    file."""
    name = path.name
    if name.endswith(".py.tmpl"):
        return True
    return name in ("_patches.py", "_helpers.py")


def _is_test_template(path: Path, body: str) -> bool:
    """Detect templates that emit pytest test scaffolding.

    Name-based: ``test_<name>_emitted.py.tmpl`` (per spec),
    ``test_<…>.py.tmpl``, ``<…>_test.py.tmpl``. Content-based:
    file uses ``@pytest.fixture`` or imports pytest at module level.
    Also flags ``bola_test_gen.py.tmpl`` (the test-case generator
    for BOLA) and ``bola_block_per_model.py.tmpl`` (the per-model
    test-block emitter, detected via ``@pytest.fixture``).
    """
    name = path.name
    if name.startswith("test_") or "_test." in name or name.startswith("test."):
        return True
    head = body[:4000]
    return any(sentinel in head for sentinel in _TEST_CONTENT_SENTINELS)


# ---------------------------------------------------------------------------
# AST helpers — function-body ranges + pass-only detection
# ---------------------------------------------------------------------------


def _parse_template(body: str) -> ast.Module | None:
    """Parse a template body as Python. Templates may use ``${var}``
    substitution syntax that is invalid Python; in that case parsing
    fails and we fall back to a line-based scan (the body-range check
    becomes "any function-like context" approximated by indentation).
    Tools may avoid the false negative by emitting valid Python in
    their templates (the current convention).
    """
    try:
        return ast.parse(body)
    except SyntaxError:
        return None


def _function_body_line_ranges(
    tree: ast.Module,
) -> list[tuple[int, int, str]]:
    """Return ``(start_line, end_line, fn_name)`` for every function.

    Start line is the ``def`` signature line, end line is the function's
    ``end_lineno``. We use the def-line (not the first body statement)
    because Python comments are NOT in the AST — a ``# TODO`` on the
    line immediately after the ``def`` signature would otherwise fall
    OUTSIDE the range (the first body statement starts on a later
    line) and the rule would silently let it through.

    Markers inside the function's docstring are string-literal text,
    not comments, so they will not match ``_MARKER_RE`` (which
    requires a literal ``#``).

    The function name is returned alongside so the marker scanner can
    apply per-function bypass-key matching (a ``# TODO`` inside a
    function whose name contains a declared ``_FEATURE_INCOMPLETE``
    key is treated as the disclosed gap, not a violation).
    """
    ranges: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.body:
            continue
        start = node.lineno
        end = node.end_lineno or start
        ranges.append((start, end, node.name))
    return ranges


def _enclosing_function_for_line(lineno: int, ranges: list[tuple[int, int, str]]) -> str | None:
    """Return the innermost enclosing function name for a source line.

    "Innermost" matters when a security tool has nested defs: we
    prefer the closest function so the bypass check sees the most
    specific name.
    """
    best: tuple[int, str] | None = None  # (start_line, name)
    for start, end, name in ranges:
        if start <= lineno <= end and (best is None or start > best[0]):
            best = (start, name)
    return None if best is None else best[1]


def _pass_only_functions(tree: ast.Module) -> list[tuple[str, int, str]]:
    """Return (function_name, lineno, shape) for every function whose body
    is a placeholder shape.

    Placeholder shapes (all strictly worse than a real implementation in
    a security context):

    * ``pass`` — the documented Round-5/6 regression (P1).
    * ``raise NotImplementedError`` / ``raise NotImplementedError(...)``
      — closes Round-7 O3-F1 (HIGH). Substituting NotImplementedError
      for ``pass`` is strictly WORSE semantics (runtime crash instead
      of silent no-op) but evaded the rule that only checked for
      ``ast.Pass``. A function whose only statement raises NotImplemented
      is a placeholder — the security path documented in the tool's
      notes does not run.

    Skips ``@abstractmethod``-decorated methods — those are legitimate
    abstract declarations, NOT security placeholders. Both shapes
    (``pass`` and ``raise NotImplementedError``) are idiomatic in
    abstract bases.
    """
    hits: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if _has_abstractmethod_decorator(node):
            continue
        body = list(node.body)
        # Strip a leading docstring if present.
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if len(body) != 1:
            continue
        only = body[0]
        if isinstance(only, ast.Pass):
            hits.append((node.name, node.lineno, "pass"))
        elif _is_raise_notimplemented(only):
            hits.append((node.name, node.lineno, "raise NotImplementedError"))
    return hits


def _is_raise_notimplemented(stmt: ast.stmt) -> bool:
    """True iff ``stmt`` is ``raise NotImplementedError`` / ``raise NotImplementedError(...)``.

    Also matches attribute-qualified forms (``raise builtins.NotImplementedError``)
    via tail-name resolution. A bare ``raise`` (re-raise) is NOT matched —
    that has a real semantic meaning.
    """
    if not isinstance(stmt, ast.Raise):
        return False
    exc = stmt.exc
    if exc is None:  # bare ``raise`` (re-raise) is not a placeholder.
        return False
    target: ast.AST = exc
    if isinstance(exc, ast.Call):
        target = exc.func
    tail = ""
    if isinstance(target, ast.Name):
        tail = target.id
    elif isinstance(target, ast.Attribute):
        tail = target.attr
    return tail == "NotImplementedError"


def _docstring_marker_functions(
    tree: ast.Module,
) -> list[tuple[str, int]]:
    """Return ``(function_name, lineno)`` for every function whose
    docstring carries a ``TODO`` / ``FIXME`` / ``XXX`` marker.

    Round-7 O3-F2 (HIGH): the body-comment rule (``# TODO``) is evaded
    by hoisting the marker into the docstring. For the security surface
    we treat a docstring-embedded marker as the same regression as the
    ``# TODO`` comment — the prose acknowledges the gap but the rule
    used to allow it (the original docstring even said docstring TODOs
    were "allowed", which is wrong on the security surface).

    Scope: this scanner is invoked only for files inside the
    security-tagged tool surface (the same scope as the comment-based
    marker scan), so general library helpers are unaffected.

    Skips ``@abstractmethod`` declarations — those are abstract, not
    placeholders. A docstring TODO on an abstract method is read as a
    "subclasses must wire this" hint and is allowed.
    """
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if _has_abstractmethod_decorator(node):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            continue
        if _DOCSTRING_MARKER_RE.search(doc):
            hits.append((node.name, node.lineno))
    return hits


def _has_abstractmethod_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for dec in node.decorator_list:
        name = ""
        if isinstance(dec, ast.Name):
            name = dec.id
        elif isinstance(dec, ast.Attribute):
            name = dec.attr
        if name in ("abstractmethod", "abstractproperty"):
            return True
    return False


# ---------------------------------------------------------------------------
# Bypass — _FEATURE_INCOMPLETE + warnings=
# ---------------------------------------------------------------------------


def _bypass_features(init_path: Path) -> dict[str, str]:
    """Return the ``_FEATURE_INCOMPLETE`` mapping declared by a tool's
    ``__init__.py``, or ``{}`` if absent.
    """
    if not init_path.is_file():
        return {}
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        for t in targets:
            if (
                isinstance(t, ast.Name)
                and t.id == "_FEATURE_INCOMPLETE"
                and isinstance(value, ast.Dict)
            ):
                out: dict[str, str] = {}
                for k, v in zip(value.keys, value.values, strict=False):
                    if (
                        isinstance(k, ast.Constant)
                        and isinstance(k.value, str)
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                    ):
                        out[k.value] = v.value
                return out
    return {}


def _warnings_mention(init_path: Path, feature_keys: list[str]) -> set[str]:
    """Return the subset of ``feature_keys`` that appear in at least
    one ``warnings=`` literal list in the tool's ``__init__.py``.

    Walks ToolResult constructions: every keyword ``warnings=[...]``
    whose elements are string literals (or known module-level list
    constants assigned to all-string literals) is checked. Tracks
    module-level list constants (``_WARNINGS = ["x"]``) because the
    convention in this repo is to hoist long lists to module-level.
    """
    if not init_path.is_file() or not feature_keys:
        return set()
    src = init_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()

    # Collect module-level list constants of strings.
    list_consts: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.List):
                items = []
                ok = True
                for el in node.value.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        items.append(el.value)
                    else:
                        ok = False
                        break
                if ok:
                    list_consts[tgt.id] = items

    found: set[str] = set()

    def _check_strings(strings: list[str]) -> None:
        for s in strings:
            for key in feature_keys:
                if key in s:
                    found.add(key)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "warnings":
                continue
            v = kw.value
            if isinstance(v, ast.List):
                strings = [
                    el.value
                    for el in v.elts
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                ]
                _check_strings(strings)
            elif isinstance(v, ast.Name) and v.id in list_consts:
                _check_strings(list_consts[v.id])
    return found


# ---------------------------------------------------------------------------
# Per-file scan
# ---------------------------------------------------------------------------


def _scan_file(
    path: Path,
    bypass_keys: list[str],
) -> list[str]:
    """Return a list of violation strings for one in-scope file.

    A violation is silenced if the offending line / function name
    mentions any of the ``bypass_keys`` (the ``_FEATURE_INCOMPLETE``
    feature names that are ALSO covered by a ``warnings=`` literal in
    the tool's ``__init__.py``).
    """
    try:
        body = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if _is_test_template(path, body):
        return []

    violations: list[str] = []
    lines = body.splitlines()

    tree = _parse_template(body)
    ranges: list[tuple[int, int, str]] = (
        _function_body_line_ranges(tree) if tree is not None else []
    )

    # Marker scan — only in-function-body matches.
    for idx, line in enumerate(lines, start=1):
        m = _MARKER_RE.search(line)
        if not m:
            continue
        # Module-level markers are documentation, not a security gap.
        # If we could not parse the template (ranges == []), fall
        # back to indentation: a marker on a line that starts at
        # column 0 (after stripping) is module-level → allow.
        if ranges:
            fn_name = _enclosing_function_for_line(idx, ranges)
            in_func = fn_name is not None
        else:
            fn_name = None
            in_func = len(line) - len(line.lstrip()) > 0
        if not in_func:
            continue
        # Bypass: line text OR enclosing function name mentions a key.
        if _line_matches_bypass(line, bypass_keys):
            continue
        if fn_name is not None and _name_matches_bypass(fn_name, bypass_keys):
            continue
        violations.append(
            f"{path.name}:{idx}: {m.group(0)} marker in function body — `{line.strip()[:100]}`"
        )

    # Placeholder function bodies (pass / raise NotImplementedError).
    if tree is not None:
        for fn_name, fn_line, shape in _pass_only_functions(tree):
            if _name_matches_bypass(fn_name, bypass_keys):
                continue
            violations.append(f"{path.name}:{fn_line}: function `{fn_name}` body is only `{shape}`")

    # TODO/FIXME/XXX markers smuggled inside a function docstring
    # (Round-7 O3-F2). Comment-based detection misses these because
    # docstring text is a string literal, not a ``#`` comment. For the
    # security surface a TODO inside a docstring is the same regression
    # class as a ``# TODO`` in the body — the security path documented
    # in the prose is acknowledged-as-incomplete but the rule used to
    # let it through.
    if tree is not None:
        for fn_name, fn_line in _docstring_marker_functions(tree):
            if _name_matches_bypass(fn_name, bypass_keys):
                continue
            violations.append(
                f"{path.name}:{fn_line}: function `{fn_name}` docstring "
                f"contains TODO/FIXME/XXX marker (security surface)"
            )

    return violations


def _line_matches_bypass(line: str, bypass_keys: list[str]) -> bool:
    return any(key.lower() in line.lower() for key in bypass_keys)


def _name_matches_bypass(name: str, bypass_keys: list[str]) -> bool:
    n = name.lower()
    return any(key.lower() in n for key in bypass_keys)


# ---------------------------------------------------------------------------
# Public rule callback (B0.10)
# ---------------------------------------------------------------------------


def _r_no_dead_security_features() -> tuple[bool, str]:
    """B0.10 — every security-tagged tool's templates ship live code.

    See module docstring for full rationale and bypass mechanism.
    """
    tool_dirs = _security_tool_dirs()
    if not tool_dirs:
        # Mis-configured repo, not a content failure. Surface clearly.
        return False, (
            "B0.10: no security tool directories found under "
            "adapt/extend/auth_access/ or the named-security list. "
            "Repo layout drift? Expected ≥9 tool dirs."
        )

    failures: list[str] = []
    scanned_tools = 0

    for tool_dir in tool_dirs:
        tool_name = tool_dir.name

        # Discover bypass declarations on the tool's __init__.py.
        init_path = tool_dir / "__init__.py"
        if not init_path.is_file():
            # Single-file tool e.g. add_mfa.py — the tool's source IS
            # the parent dir's same-named .py file. Skip; templates
            # don't apply.
            continue
        feature_map = _bypass_features(init_path)
        warned = _warnings_mention(init_path, list(feature_map.keys()))
        # Bypass keys = those that BOTH declare AND warn.
        bypass_keys = [k for k in feature_map if k in warned]
        # If a tool declared _FEATURE_INCOMPLETE without ANY
        # warnings= disclosure, surface that as a hard failure: the
        # bypass mechanism explicitly requires warnings=, not notes=.
        for key in feature_map:
            if key not in warned:
                failures.append(
                    f"{tool_name}: _FEATURE_INCOMPLETE['{key}'] declared but "
                    f"no `warnings=` literal in __init__.py mentions it "
                    f"(must use warnings=, NOT notes=)"
                )

        if tool_name in _WAIVED_TOOLS:
            # The tool is on the rule-level waiver set — still scan,
            # but only require that the bypass mechanism (`warnings=`
            # + `_FEATURE_INCOMPLETE`) is wired correctly above. Skip
            # file-level violations for waived tools.
            scanned_tools += 1
            continue

        for path in sorted(tool_dir.rglob("*")):
            if not path.is_file():
                continue
            if not _is_in_scope(path):
                continue
            failures.extend(_scan_file(path, bypass_keys))
        scanned_tools += 1

    if failures:
        sample = "\n    - ".join(failures[:6])
        more = f"\n    … (+{len(failures) - 6} more)" if len(failures) > 6 else ""
        return False, (
            f"B0.10 no_dead_security_features: {len(failures)} violation(s) "
            f"across {scanned_tools} security-tagged tool(s):\n"
            f"    - {sample}{more}\n"
            "    Bypass: declare `_FEATURE_INCOMPLETE: dict[str,str]` in "
            "the tool's __init__.py AND return ToolResult(warnings=[...]) "
            "mentioning each feature key (warnings=, NOT notes=)."
        )

    return True, (
        f"B0.10 ok: scanned {scanned_tools} security-tagged tool(s); "
        "no TODO/FIXME/XXX markers in function bodies, no pass-only "
        f"function bodies in implementation templates ({len(_WAIVED_TOOLS)} "
        "waived)."
    )
