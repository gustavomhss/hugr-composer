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
5. Separately (R8-J4-7), detect ``setattr(<self-module>, 'name',
   <mutable-literal>)`` calls anywhere in the module — e.g.
   ``setattr(sys.modules[__name__], '_X', {})`` invoked from a
   function. These install module-level mutable state with NO
   module-level assignment target, so steps 2–4 saw zero offenders.
   The install call itself is treated as the offence.

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

The waiver is a CURATED frozenset (:pydata:`_WAIVED_TOOLS`): a tool
listed there has its templates skipped, and nothing else. The rule
does NOT open any ``__init__.py`` — there is no automatic signal-based
bypass. (R8-J4-2: an earlier version of this docstring advertised a
dual-signal bypass — ``_SINGLE_PROCESS_OK = True`` in ``__init__.py``
PLUS a ``warnings=`` entry containing ``"single-process"`` — that the
rule never enforced. That claim is removed here so the docstring no
longer documents a bypass the code doesn't check.)

Convention for adding a waiver: a tool that genuinely needs
single-process semantics SHOULD still ship ``_SINGLE_PROCESS_OK = True``
in its ``__init__.py`` AND a ``warnings=`` entry containing
``"single-process"`` so the intent is visible in code review — but
those signals are advisory documentation, not a rule-checked gate. The
waiver list is hand-maintained: a new offending template fails the
rule UNTIL the tool dir is explicitly added to :pydata:`_WAIVED_TOOLS`
(reviewer-approved). The set is currently EMPTY — every offender has
been migrated to a process-shared store or a class-instance wrapper.

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
# CURATED frozenset of tool import paths (relative to ``adapt/``) whose
# templates are skipped wholesale. The rule does NOT inspect any
# ``__init__.py`` — membership here is the ONLY bypass (R8-J4-2). A
# waived tool SHOULD still document its single-process intent in code
# (``_SINGLE_PROCESS_OK = True`` + a ``warnings=`` "single-process"
# entry) and each entry MUST carry a comment citing the audit finding it
# discloses — but those are review conventions, not rule-checked signals.
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
_WAIVED_TOOLS: frozenset[str] = frozenset(
    {
        # "extend/auth_access/add_passkey_auth" — closed Wave-2
        # (fix/w2-passkey-auth-close-waivers): the module-level
        # ``_CHALLENGE_STORE: dict[str, bytes] = {}`` is replaced by a
        # ``_ChallengeStore()`` class instance whose primary backend is Redis
        # (``webauthn:challenge:{session_id}`` SETEX with TTL =
        # ``WEBAUTHN_CHALLENGE_TTL_SECONDS``) and whose per-worker dict
        # fallback is encapsulated inside the class. Closes R5-O4-H4.
        # "extend/auth_access/add_api_key_auth" — closed Wave-2
        # (fix/w2-api-key-auth-close-waivers): _local_counters is now a
        # _LocalCounters() class instance (allow-listed by this rule) AND
        # _SINGLE_PROCESS_OK + warnings= disclosure shipped in the tool's
        # __init__.py. The Redis-up path is cross-worker durable; the
        # fallback is the documented fail-degraded path.
        # "extend/infrastructure/add_adaptive_throttle" — removed by Wave-2
        # close-out: _PENALTY_STORE is now a _PenaltyStore() class instance
        # (Redis-backed primary, per-worker dict fallback encapsulated in
        # the class). Closes R6-O1-F10/F14/F15.
        # "extend/infrastructure/add_scheduled_tasks" — closed Wave-2
        # (fix/w2-final-b012-all-module-state): _JOBS is now a
        # _JobsRegistry() class instance (allow-listed by this rule) AND
        # _SINGLE_PROCESS_OK + warnings= disclosure shipped in the tool's
        # __init__.py. Decorator-registered jobs re-populate identically
        # on every worker at module-import time; the duplicate-fire risk
        # across multiple scheduler instances remains a separate concern
        # mitigated by SCHEDULER_JOBSTORE_URL. Closes R6-S5-F5.
        # "extend/infrastructure/add_api_monetization" — closed in W2 PR
        # (fix/w2-api-monetization-close-waivers): _RULES is now wrapped
        # in a _RulesRegistry class instance and _DEAD_LETTER in a
        # _DeadLetterQueue class instance (both allow-listed by this
        # rule), AND the tool ships _SINGLE_PROCESS_OK = True + a
        # warnings= entry containing "single-process" in its __init__.py.
        # Closes R6-O3-F9 family.
        # R5-O3-F2 family — closed in W2 PR (fix/w2-tenant-onboarding-close-waivers):
        # _PROGRESS_REGISTRY now wrapped in ProgressRegistry class instance
        # (allow-listed by this rule) AND _SINGLE_PROCESS_OK + warnings=
        # disclosure shipped in the tool's __init__.py.
        # "extend/crud_data/add_data_export" — closed Wave-2
        # (fix/w2-final-b012-all-module-state): _MODEL_REGISTRY is now a
        # _ModelRegistry() class instance (allow-listed by this rule) AND
        # _SINGLE_PROCESS_OK + warnings= disclosure shipped in the tool's
        # __init__.py. Every worker (including the ARQ background worker
        # that runs the export jobs) re-registers models identically at
        # module-import time. Closes R5-S5-F2 / R6-S3-F1 family.
        # "evolve/add_event_driven" — closed Wave-2
        # (fix/w2-final-b012-all-module-state): _HANDLERS is now a
        # _HandlerRegistry() class instance (allow-listed by this rule)
        # AND _SINGLE_PROCESS_OK + warnings= disclosure shipped in the
        # tool's __init__.py. Closes P3-cluster handler-registry waiver.
        # "evolve/add_i18n" — closed Wave-2
        # (fix/w2-final-b012-all-module-state): _CATALOGS is now a
        # _CatalogCache() class instance (allow-listed by this rule) AND
        # _SINGLE_PROCESS_OK + warnings= disclosure shipped in the tool's
        # __init__.py. Closes R6-S8.
    }
)

# --- AST helpers ---------------------------------------------------------

# Replace ``${name}`` / ``$name`` placeholders with the bare identifier
# so the rest of the template parses. Same shape as Python's
# ``string.Template`` substitution syntax; tools that use it always
# pick valid Python identifiers.
_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")

# Callables that produce a fresh mutable container.
#
# Round-7 O3-F14 (HIGH) added ``SimpleNamespace`` and ``type`` (3-arg
# dynamic class call): both are wrappers around an attribute dict and
# are observed in the wild as evasions of the dict/list/set check. A
# ``_X = SimpleNamespace(d={})`` is still per-worker mutable state
# (``_X.d[k] = v`` mutates the inner dict); a ``_X = type('X', (), {'d':
# {}})()`` is the same shape with extra ceremony. Both are flagged as
# mutable initializers; classification of the 3-arg ``type(...)`` is
# refined via ``_type_3arg_is_mutable`` below to keep zero-payload
# dynamic classes (``type('X', (), {})``) out of scope.
_MUTABLE_CALL_NAMES: frozenset[str] = frozenset(
    {
        "dict",
        "list",
        "set",
        "defaultdict",
        "OrderedDict",
        "WeakValueDictionary",
        "WeakKeyDictionary",
        "WeakSet",
        "Counter",
        "deque",
        "SimpleNamespace",
    }
)

# Callables we explicitly allow even if they LOOK like state.
# ``frozenset`` / ``tuple`` / ``MappingProxyType`` are immutable.
# Lock-family + Queue-family coordinate INSIDE a process — not the
# "invisible-per-worker" pattern B0.12 targets.
# ``ContextVar`` is per-context by design.
_ALLOWED_TAIL_NAMES: frozenset[str] = frozenset(
    {
        "frozenset",
        "tuple",
        "MappingProxyType",
        "Lock",
        "RLock",
        "Event",
        "Semaphore",
        "BoundedSemaphore",
        "Condition",
        "Queue",
        "LifoQueue",
        "PriorityQueue",
        "ContextVar",
    }
)

# Annotation type names that signal a mutable container shape.
_MUTABLE_ANNO_TAILS: frozenset[str] = frozenset(
    {
        "dict",
        "list",
        "set",
        "Dict",
        "List",
        "Set",
        "DefaultDict",
    }
)

# Method names that mutate a container in place.
_MUTATION_METHODS: frozenset[str] = frozenset(
    {
        "append",
        "extend",
        "add",
        "update",
        "pop",
        "popitem",
        "setdefault",
        "clear",
        "remove",
        "discard",
        "insert",
        "__setitem__",
        "__delitem__",
        "sort",
        "reverse",
    }
)


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
        # Optionally-called dynamic class: ``type('X', (), {...})()`` —
        # the outer Call's ``.func`` is itself a ``type(...)`` Call.
        # Round-7 O3-F14 (HIGH).
        if isinstance(value.func, ast.Call):
            inner = value.func
            inner_chain = _attr_chain(inner.func)
            inner_tail = inner_chain.rsplit(".", 1)[-1] if inner_chain else ""
            return inner_tail == "type" and _type_3arg_is_mutable(inner)
        chain = _attr_chain(value.func)
        if not chain:
            return False
        tail = chain.rsplit(".", 1)[-1]
        if tail in _ALLOWED_TAIL_NAMES:
            return False
        if tail in _MUTABLE_CALL_NAMES:
            return True
        # Round-7 O3-F14: dynamic-class ``type(name, bases, body_dict)``
        # whose body dict carries any mutable value is module-level state
        # smuggled through the metaclass front door. ``type('X', (), {})``
        # with an empty body is class-creation, not state.
        if tail == "type" and _type_3arg_is_mutable(value):
            return True
    return False


def _type_3arg_is_mutable(call: ast.Call) -> bool:
    """True iff ``call`` is a 3-arg ``type(name, bases, body)`` whose
    body dict declares at least one mutable value.

    Round-7 O3-F14 (HIGH): ``_X = type('X', (), {'d': {}})()`` shipped
    a per-worker mutable ``_X.d`` without tripping the rule (the call
    is to ``type``, which isn't in the mutable-call allow-list). We
    inspect the third positional arg: if it's a Dict literal that
    contains any value classified as a mutable initializer, the whole
    construction is module-level mutable state.

    A bare ``type('X', (), {})`` with an empty body is normal dynamic
    class creation (not state) and returns False.
    """
    args = call.args
    if len(args) < 3:
        return False
    body = args[2]
    if not isinstance(body, ast.Dict):
        return False
    for v in body.values:
        if v is None:
            continue
        if _is_mutable_initializer(v):
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

        def _root_name(self, expr: ast.AST) -> str | None:
            """Walk ``X.a.b[i].c`` ↦ ``"X"`` (return the root Name id).

            Used so attribute-then-subscript mutations on a
            ``SimpleNamespace`` candidate (``_X.d[k] = v`` — Round-7
            O3-F14) are correctly attributed to ``_X``.
            """
            cur: ast.AST | None = expr
            while True:
                if isinstance(cur, ast.Name):
                    return cur.id if cur.id in names else None
                if isinstance(cur, ast.Attribute):
                    cur = cur.value
                    continue
                if isinstance(cur, ast.Subscript):
                    cur = cur.value
                    continue
                return None

        def visit_Assign(self, node: ast.Assign) -> None:
            for tgt in node.targets:
                if isinstance(tgt, ast.Subscript):
                    root = self._root_name(tgt.value)
                    if root is not None:
                        hits[root].append(node.lineno)
                elif isinstance(tgt, ast.Attribute):
                    # ``_X.attr = v`` — direct attribute assignment on a
                    # SimpleNamespace-style candidate counts as mutation.
                    root = self._root_name(tgt.value)
                    if root is not None:
                        hits[root].append(node.lineno)
                elif isinstance(tgt, ast.Name) and tgt.id in names and self.depth > 0:
                    hits[tgt.id].append(node.lineno)
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            tgt = node.target
            if isinstance(tgt, (ast.Subscript, ast.Attribute)):
                root = self._root_name(tgt.value)
                if root is not None:
                    hits[root].append(node.lineno)
            elif isinstance(tgt, ast.Name) and tgt.id in names:
                hits[tgt.id].append(node.lineno)
            self.generic_visit(node)

        def visit_Delete(self, node: ast.Delete) -> None:
            for tgt in node.targets:
                if isinstance(tgt, (ast.Subscript, ast.Attribute)):
                    root = self._root_name(tgt.value)
                    if root is not None:
                        hits[root].append(node.lineno)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _MUTATION_METHODS:
                root = self._root_name(func.value)
                if root is not None:
                    hits[root].append(node.lineno)
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


def _is_self_module_ref(node: ast.AST) -> bool:
    """True iff ``node`` references the CURRENT module object.

    Recognised shapes (R8-J4-7):
      * ``sys.modules[__name__]``        — subscript on ``sys.modules``
        by the ``__name__`` Name.
      * ``modules[__name__]``            — when ``modules`` was imported
        from ``sys`` (``from sys import modules``).
      * ``sys.modules.get(__name__)``    — the ``.get(...)`` accessor.

    Kept deliberately tight: an aliased arbitrary module object is NOT
    matched (we cannot resolve it without execution), so the detection
    has near-zero false-positive surface — only the documented
    ``setattr(sys.modules[__name__], ...)`` smuggling pattern trips.
    """
    # ``sys.modules.get(__name__)`` — Call on a ``...modules.get`` attr.
    if isinstance(node, ast.Call):
        fn = node.func
        return (
            isinstance(fn, ast.Attribute)
            and fn.attr == "get"
            and _attr_chain(fn.value).rsplit(".", 1)[-1] == "modules"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__name__"
        )
    # ``sys.modules[__name__]`` / ``modules[__name__]`` — subscript.
    if isinstance(node, ast.Subscript):
        base_tail = _attr_chain(node.value).rsplit(".", 1)[-1]
        if base_tail != "modules":
            return False
        idx = node.slice
        return isinstance(idx, ast.Name) and idx.id == "__name__"
    return False


def _find_setattr_module_state(tree: ast.Module) -> list[tuple[str, int, int, list[int]]]:
    """Find ``setattr(<self-module>, 'name', <mutable-literal>)`` installs.

    R8-J4-7: ``setattr(sys.modules[__name__], '_X', {})`` called from a
    function installs module-level mutable state with NO module-level
    assignment target, so the candidate scan in :func:`find_module_state`
    saw zero offenders. We treat such a call as a direct offence — the
    installed name is module-level state and the mutable literal is the
    smoking gun (mirrors the assignment-time classification).

    Only flags when (a) the 1st arg resolves to the current module, (b)
    the 2nd arg is a string-literal attribute name (not a dunder), and
    (c) the 3rd arg is a fresh mutable initialiser.
    """
    out: list[tuple[str, int, int, list[int]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fn_name = (
            fn.id
            if isinstance(fn, ast.Name)
            else (fn.attr if isinstance(fn, ast.Attribute) else "")
        )
        if fn_name != "setattr" or len(node.args) < 3:
            continue
        target, name_arg, value_arg = node.args[0], node.args[1], node.args[2]
        if not _is_self_module_ref(target):
            continue
        if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
            continue
        attr_name = name_arg.value
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        if not _is_mutable_initializer(value_arg):
            continue
        out.append((attr_name, node.lineno, node.col_offset, [node.lineno]))
    out.sort(key=lambda t: (t[1], t[0]))
    return out


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

    # R8-J4-7: setattr-installed module state has no assignment target,
    # so it's collected independently and merged in.
    setattr_offenders = _find_setattr_module_state(tree)

    if not candidates:
        return setattr_offenders
    mutations = _find_mutations(tree, set(candidates.keys()))
    result: list[tuple[str, int, int, list[int]]] = list(setattr_offenders)
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
            lines.append(f"  {rel}:{lineno}:{col}  {name}  (mutated at L{mut_preview})")
    lines.append(
        "Fix by moving state into a process-shared backing store "
        "(Redis / DB / external cache) OR — if single-process is "
        "genuinely acceptable — add the tool to `_WAIVED_TOOLS` in "
        "`r_no_module_state.py` (reviewer-approved curated waiver; "
        "document the intent with `_SINGLE_PROCESS_OK = True` + a "
        "`warnings=` `single-process` entry for code review)."
    )
    return False, "\n".join(lines)
