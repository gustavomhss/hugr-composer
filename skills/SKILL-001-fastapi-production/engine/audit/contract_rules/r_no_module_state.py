"""B0.12 — `no_module_state_in_templates`.

CONTRACT.md scope: §B0.12 (Wave-0 anti-pattern P3 from
``docs/wp/ROUND5_6_TRIAGE.md`` §3 P3).

This rule closes the "module-level mutable state silently per-worker"
class of bug — templates that declare a top-level ``dict`` / ``list`` /
``set`` (or ``defaultdict`` / ``WeakValueDictionary`` / …) and then
mutate it from request handlers. Under a multi-worker deployment
(``gunicorn -w 4`` / ``uvicorn --workers``) each worker holds its
own copy: writes vanish on next request, replay protection fails open,
nonce stores become per-worker, "global" registries half-populate, etc.

Approach (AST, NOT regex):

1. Walk every ``adapt/**/*.py.tmpl`` template. Templates carry
   ``${var}`` and ``$var`` placeholders that break ``ast.parse``;
   they are normalised to the bare identifier first. Templates that
   still fail to parse after normalisation are skipped — they are
   compose-time fragments (not standalone modules) and the rule is
   designed for full-module shape (R6-S5-F1 / R5-O2-D6 / R5-O4-C8 etc.
   are all full modules).
2. Collect every module-level assignment target whose RHS is a fresh
   mutable container — ``{}``, ``[]``, ``set()``, ``dict()``,
   ``list()``, ``defaultdict(...)``, ``OrderedDict()``,
   ``WeakValueDictionary()``, ``WeakKeyDictionary()``, ``WeakSet()``,
   ``Counter()``, ``deque()`` — or whose annotation is a mutable
   container type initialised with one of the above (e.g.
   ``X: dict[str, int] = {}``).
3. For each candidate Name, scan the WHOLE module for mutations:
   * ``Name[key] = value`` / ``del Name[key]`` (Subscript Store / Del)
   * ``Name += ...`` / ``Name[key] += ...``
   * ``Name.append(...) / .extend / .add / .update / .pop / .popitem /
     .setdefault / .clear / .remove / .discard / .insert /
     .__setitem__ / .__delitem__ / .sort / .reverse``
   * Re-assignment ``Name = <anything>`` from inside a function /
     class / async function (i.e. ``global X; X = …``)
4. If ANY mutation is found → REJECT.

What this rule deliberately does NOT flag (allow-list):

* **Module-level CONSTANTS** — read-only sets / tuples / frozenset /
  ``MappingProxyType``. A mutable initialiser that is never mutated
  passes (treated as a constant — the rule has zero false positives on
  ``_HEADERS = {"X-Foo"}`` style read-only sets).
* **Concurrency primitives** — ``threading.Lock`` / ``RLock`` /
  ``Event`` / ``Semaphore`` / ``Condition`` / ``Queue`` /
  ``LifoQueue`` / ``PriorityQueue`` instances (and their ``asyncio.``
  counterparts). These ARE state but not the "per-worker invisible
  state" class the rule targets — they coordinate INSIDE a process.
* **ContextVar / contextvars.ContextVar** — intentionally
  per-context, not per-worker shared. Adding to the allow-list is
  load-bearing for any tool that uses request-scoped state correctly.
* **Cache decorators** (``@functools.lru_cache``, ``@cache``,
  ``@cached_property``) — target functions / methods, never matched
  by this rule (we only scan assignment targets).
* **Frozen initialisers** — ``frozenset(...)``, ``tuple(...)``,
  ``MappingProxyType(...)`` — immutable by construction.
* **Dunders** — ``__all__``, ``__version__``, etc. — these may be
  lists/dicts but mutation belongs to the module loader / pytest
  collector, not to the tool itself. Skipped by name pattern.

Bypass (per-tool waiver):

A tool may declare ``_SINGLE_PROCESS_OK: bool = True`` in its
``__init__.py`` AND return ``warnings=`` (NOT ``notes=``) containing
the substring ``"single-process"`` (case-insensitive). When both are
present the tool is registered in :pydata:`_WAIVED_TOOLS` below and
the rule skips its templates. The waiver list is hand-maintained: a
new offending template fails the rule UNTIL the tool's ``__init__.py``
ships both signals AND the tool dir is added to ``_WAIVED_TOOLS``.

Trade-offs (declared, not hidden):

* **Compose fragments are skipped.** A ``main_patch.py.tmpl`` or
  ``routes_addition.py.tmpl`` that splices into a host module may
  introduce module-level state that this rule will not see because
  the fragment fails AST parsing. We accept this — fragments are
  inspected by the host-app contract rules instead.
* **Class-instance singletons not flagged.** ``_store = MyStore()``
  where ``MyStore`` holds an internal ``self._dict`` is real
  per-worker state but is structurally invisible to a pattern-match
  rule. The triage doc cites several such cases (``DPoPNonceStore``,
  ``CanaryRegistry``); those need a follow-up rule (B0.12b) that
  walks instance methods. Out of scope here.
* **AnnAssign without value is ALLOWED.** ``_x: dict[str, int]`` on
  its own at module top is a type declaration, not storage. We do
  not flag it. Mutation later (``_x[k] = v``) would be flagged
  ONLY if a matching initialiser also exists.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._common import SKILL_ROOT

# --- Tool waivers --------------------------------------------------------
#
# Tool import paths (relative to ``adapt/``) that have explicitly opted
# into single-process semantics. Each entry MUST be backed by:
#   * ``_SINGLE_PROCESS_OK: bool = True`` in the tool's ``__init__.py``
#   * a ``warnings=`` entry containing the substring "single-process"
#     (case-insensitive) returned by the tool's runtime envelope
# AND a comment line citing the audit finding the waiver discloses.
#
# Wave-0 SOTA contract: rule lands strict + CI stays green. Each
# pre-existing offender is grandfathered here with a citation pointing
# to the audit finding it discloses; the waiver list IS the Wave-1
# fix-PR backlog. As each tool migrates to Redis/DB-backed state or
# adopts the bypass mechanism (_SINGLE_PROCESS_OK + warnings=), the
# entry is removed in the same PR. NO new tool may be added to this
# set without explicit reviewer approval — the rule rejects regressions
# in all other code paths.
#
# Format: { "extend/<wp>/<tool_name>", ... }  (relative to ADAPT_ROOT)
_WAIVED_TOOLS: frozenset[str] = frozenset({
    # R5-O4-H4 — passkey challenge dict per-worker; multi-worker breaks login
    "extend/auth_access/add_passkey_auth",
    # R6-O1-F18 — api_key rate-limit Redis-down fallback uses local dict
    "extend/auth_access/add_api_key_auth",
    # "extend/infrastructure/add_adaptive_throttle" — removed by Wave-2
    # close-out: _PENALTY_STORE is now a _PenaltyStore() class instance
    # (Redis-backed primary, per-worker dict fallback encapsulated in
    # the class). Closes R6-O1-F10/F14/F15.
    # R6-S5-F5 — _JOBS dict mutated without lock; cron state not shared
    "extend/infrastructure/add_scheduled_tasks",
    # R6-O3-F9 — _RULES + _DEAD_LETTER per-worker; monetization state lost
    "extend/infrastructure/add_api_monetization",
    # R5-O3-F2 family — closed in W2 PR (fix/w2-tenant-onboarding-close-waivers):
    # _PROGRESS_REGISTRY now wrapped in ProgressRegistry class instance
    # (allow-listed by this rule) AND _SINGLE_PROCESS_OK + warnings=
    # disclosure shipped in the tool's __init__.py.
    # R5-S5-F2 / R6-S3-F1 family — _MODEL_REGISTRY for export columns; benign today
    "extend/crud_data/add_data_export",
    # P3 cluster — _HANDLERS event subscriber registry; per-worker subscription split
    "evolve/add_event_driven",
    # R6-S8 — _CATALOGS i18n catalog cache; reload not propagated cross-worker
    "evolve/add_i18n",
})

# --- AST helpers ---------------------------------------------------------

# Replace ``${name}`` / ``$name`` placeholders with the bare identifier
# so the rest of the template parses. Same shape as Python's
# ``string.Template`` substitution syntax; tools that use it always
# pick valid Python identifiers.
_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")

# Callables that produce a fresh mutable container.
_MUTABLE_CALL_NAMES: frozenset[str] = frozenset({
    "dict", "list", "set",
    "defaultdict", "OrderedDict",
    "WeakValueDictionary", "WeakKeyDictionary", "WeakSet",
    "Counter", "deque",
})

# Callables we explicitly allow even if they LOOK like state.
# ``frozenset`` / ``tuple`` / ``MappingProxyType`` are immutable.
# Lock-family + Queue-family coordinate INSIDE a process — not the
# "invisible-per-worker" pattern B0.12 targets.
# ``ContextVar`` is per-context by design.
_ALLOWED_TAIL_NAMES: frozenset[str] = frozenset({
    "frozenset", "tuple", "MappingProxyType",
    "Lock", "RLock", "Event", "Semaphore", "BoundedSemaphore",
    "Condition", "Queue", "LifoQueue", "PriorityQueue",
    "ContextVar",
})

# Annotation type names that signal a mutable container shape.
_MUTABLE_ANNO_TAILS: frozenset[str] = frozenset({
    "dict", "list", "set",
    "Dict", "List", "Set", "DefaultDict",
})

# Method names that mutate a container in place.
_MUTATION_METHODS: frozenset[str] = frozenset({
    "append", "extend", "add", "update", "pop", "popitem",
    "setdefault", "clear", "remove", "discard", "insert",
    "__setitem__", "__delitem__", "sort", "reverse",
})


def _attr_chain(node: ast.AST) -> str:
    """Resolve ``a.b.c`` ↦ ``"a.b.c"``; bare Name ↦ ``"a"``; else ``""``."""
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    elif cur is not None:
        return ""
    return ".".join(reversed(parts))


def _is_mutable_initializer(value: ast.AST) -> bool:
    """Return True iff ``value`` constructs a fresh mutable container.

    Treats literal dict/list/set, dict/list/set comprehensions, and
    callable-style constructors (``dict()`` / ``list()`` /
    ``defaultdict(...)`` etc.) as mutable. Explicitly excludes
    ``frozenset``, ``tuple``, ``MappingProxyType``, ``Lock`` family,
    ``Queue`` family, and ``ContextVar``.
    """
    if isinstance(value, (ast.Dict, ast.List, ast.Set)):
        return True
    if isinstance(value, (ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        chain = _attr_chain(value.func)
        if not chain:
            return False
        tail = chain.rsplit(".", 1)[-1]
        if tail in _ALLOWED_TAIL_NAMES:
            return False
        if tail in _MUTABLE_CALL_NAMES:
            return True
    return False


def _anno_is_mutable_container(anno: ast.AST | None) -> bool:
    """Whether an annotation names a mutable-container type."""
    if anno is None:
        return False
    chain = _attr_chain(anno)
    if chain:
        tail = chain.rsplit(".", 1)[-1]
        if tail in _MUTABLE_ANNO_TAILS:
            return True
    if isinstance(anno, ast.Subscript):
        chain = _attr_chain(anno.value)
        if chain:
            tail = chain.rsplit(".", 1)[-1]
            if tail in _MUTABLE_ANNO_TAILS:
                return True
    return False


def _find_mutations(tree: ast.Module, names: set[str]) -> dict[str, list[int]]:
    """For each candidate name, return the lines on which it is mutated.

    Mutations counted:
      * Subscript Store / Del:   ``Name[k] = v`` ; ``del Name[k]``
      * AugAssign:               ``Name += ...`` / ``Name[k] += ...``
      * Method calls in :pydata:`_MUTATION_METHODS`
      * Re-assignment from a function / class body (``global Name``)
    """
    hits: dict[str, list[int]] = {n: [] for n in names}

    class V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0  # 0 = module top, >0 = inside func/class

        def visit_Assign(self, node: ast.Assign) -> None:
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id in names
                ):
                    hits[tgt.value.id].append(node.lineno)
                elif (
                    isinstance(tgt, ast.Name)
                    and tgt.id in names
                    and self.depth > 0
                ):
                    hits[tgt.id].append(node.lineno)
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            tgt = node.target
            if (
                isinstance(tgt, ast.Subscript)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id in names
            ):
                hits[tgt.value.id].append(node.lineno)
            elif isinstance(tgt, ast.Name) and tgt.id in names:
                hits[tgt.id].append(node.lineno)
            self.generic_visit(node)

        def visit_Delete(self, node: ast.Delete) -> None:
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id in names
                ):
                    hits[tgt.value.id].append(node.lineno)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _MUTATION_METHODS
                and isinstance(func.value, ast.Name)
                and func.value.id in names
            ):
                hits[func.value.id].append(node.lineno)
            self.generic_visit(node)

        def _enter(self, node: ast.AST) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_FunctionDef = _enter  # type: ignore[assignment]  # noqa: N815
        visit_AsyncFunctionDef = _enter  # type: ignore[assignment]  # noqa: N815
        visit_ClassDef = _enter  # type: ignore[assignment]  # noqa: N815

    V().visit(tree)
    return {k: sorted(set(v)) for k, v in hits.items() if v}


def find_module_state(src: str) -> list[tuple[str, int, int, list[int]]]:
    """Return ``[(name, lineno, col, mutation_lines), …]`` for offenders.

    ``src`` may contain ``${var}`` / ``$var`` placeholders; we normalise
    them before AST parse. Returns ``[]`` for files that still fail to
    parse (compose fragments — see module docstring trade-offs).
    """
    cleaned = _PLACEHOLDER_RE.sub(lambda m: m.group(1) or m.group(2), src)
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return []

    candidates: dict[str, tuple[int, int]] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
                if name.startswith("__") and name.endswith("__"):
                    continue
                if _is_mutable_initializer(stmt.value):
                    candidates[name] = (stmt.lineno, stmt.col_offset)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            if name.startswith("__") and name.endswith("__"):
                continue
            if stmt.value is not None and _is_mutable_initializer(stmt.value):
                candidates[name] = (stmt.lineno, stmt.col_offset)
            # AnnAssign WITHOUT value is a bare type declaration — allowed.

    if not candidates:
        return []
    mutations = _find_mutations(tree, set(candidates.keys()))
    result: list[tuple[str, int, int, list[int]]] = []
    for name, (lineno, col) in candidates.items():
        if name in mutations:
            result.append((name, lineno, col, mutations[name]))
    # Stable ordering: by line, then name.
    result.sort(key=lambda t: (t[1], t[0]))
    return result


# --- The rule callback ---------------------------------------------------

ADAPT_ROOT = SKILL_ROOT / "adapt"


def _tool_key_for(path: Path) -> str:
    """Map ``adapt/extend/auth_access/add_dpop_tokens/templates/x.py.tmpl``
    ↦ ``"extend/auth_access/add_dpop_tokens"`` (relative to ADAPT_ROOT).

    Used to look up waivers. The waiver granularity is per-tool, not
    per-template, because all of a tool's templates share the same
    runtime semantics.
    """
    try:
        rel = path.relative_to(ADAPT_ROOT)
    except ValueError:
        return ""
    parts = rel.parts
    # Trim trailing "templates/<file>.py.tmpl" → keep "<a>/<b>/<tool>".
    if len(parts) >= 2 and parts[-2] == "templates":
        parts = parts[:-2]
    elif len(parts) >= 1:
        parts = parts[:-1]
    return "/".join(parts)


def _r_no_module_state_in_templates() -> tuple[bool, str]:
    """B0.12 — no module-level mutable state in adapt/ templates.

    See module docstring for the full rule shape, allow-list, and
    bypass mechanism.
    """
    if not ADAPT_ROOT.exists():
        return False, f"missing: {ADAPT_ROOT}"

    offenders: list[tuple[Path, list[tuple[str, int, int, list[int]]]]] = []
    for path in sorted(ADAPT_ROOT.rglob("*.py.tmpl")):
        tool_key = _tool_key_for(path)
        if tool_key in _WAIVED_TOOLS:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"unreadable: {path} ({exc})"
        hits = find_module_state(src)
        if hits:
            offenders.append((path, hits))

    if not offenders:
        return True, "no module-level mutable state in adapt/ templates"

    # Build a deterministic, copy-pasteable message.
    lines: list[str] = [
        f"{len(offenders)} template(s) ship module-level mutable state "
        "that is mutated at runtime — silently per-worker under "
        "multi-worker deployments (see CONTRACT §B0.12 / triage P3):",
    ]
    rel_root = SKILL_ROOT.parent.parent
    for path, hits in offenders:
        try:
            rel = path.relative_to(rel_root)
        except ValueError:
            rel = path
        for name, lineno, col, muts in hits:
            mut_preview = ", ".join(str(m) for m in muts[:5])
            if len(muts) > 5:
                mut_preview += f", …(+{len(muts) - 5})"
            lines.append(
                f"  {rel}:{lineno}:{col}  {name}  (mutated at L{mut_preview})"
            )
    lines.append(
        "Fix by moving state into a process-shared backing store "
        "(Redis / DB / external cache) OR — if single-process is "
        "genuinely acceptable — add the tool to "
        "`_WAIVED_TOOLS` in `r_no_module_state.py` after the "
        "tool's `__init__.py` ships `_SINGLE_PROCESS_OK = True` "
        "AND returns a `warnings=` entry containing `single-process`."
    )
    return False, "\n".join(lines)
