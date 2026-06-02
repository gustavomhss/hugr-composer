"""B0.15 — ``init_inside_lifespan_only``.

CONTRACT.md scope: §B0.15 (Wave-0 anti-pattern P6 from
``docs/wp/ROUND5_6_TRIAGE.md`` §3 P6).

This rule closes the "resource init at module-import time, not in
``lifespan``" class of bug — templates / patchers that splice an
``init_X(...)`` / ``create_X_pool(...)`` / ``configure_X(...)`` /
``start_X_listener(...)`` / ``start_X_worker(...)`` /
``register_X_routes(...)`` call as a bare module-level statement
into ``app/main.py`` instead of putting it inside the
``async def lifespan(...)`` context manager.

Why this matters (citations from ``docs/wp/ROUND5_6_TRIAGE.md`` §3 P6):

* **R5-O2-D12** — ``init_idempotency_cache`` patched at EOF of main →
  Redis client built at import time, no startup gate, no shutdown.
* **R6-O2-O2-1** — ``GracefulShutdownAdapter`` uses ``@on_event`` which
  FastAPI silently ignores when ``lifespan=`` is passed to ``FastAPI(...)``;
  the handler never fires.
* **R6-O2-O2-2** — same ``add_bulk_operations`` Redis init (Round-5
  unfixed).
* **R5-S5-F2** — ``init_metrics()`` re-registers globally; second
  import in tests crashes with ``Duplicated timeseries`` instead of
  binding to the app's lifespan.
* **R6-S3-F4** — ``_patch_main`` for cache reads ``REDIS_URL`` but
  never calls ``init_cache(...)``; partially mirrors the same class.

Approach (AST, NOT regex):

1. Walk every template under ``adapt/`` matching one of:
     - ``**/main_patch.py.tmpl``         (full module patch)
     - ``**/main_*_snippet*.tmpl``       (snippet splice, including
       ``.txt.tmpl`` flavour)
     - ``**/_patch_main.py.tmpl``        (alternate naming)
   Plus every ``_patches.py`` whose AST contains a function named
   ``patch_main`` / ``_patch_main`` / ``*_patch_main`` — those mutate
   ``app/main.py`` directly (intent detection per spec).
2. Normalise ``${var}`` / ``$var`` placeholders to bare identifiers
   so ``ast.parse`` succeeds. Templates that still fail to parse are
   treated as compose fragments (NOT standalone modules) and skipped —
   the rule is shape-only over what AST can see.
3. For each scanned source, walk the AST. Reject any ``ast.Call`` whose
   target name matches the offence pattern AND whose enclosing scope is
   "module top level (or the body of a ``patch_main``-named function in
   ``_patches.py``) AND not inside ``async def lifespan(``".

Match patterns (function-name tail after stripping leading underscores):

* ``init_*``
* ``create_*_pool``
* ``configure_*`` — EXCEPT ``configure_logging`` (allow).
* ``start_*_listener``
* ``start_*_worker``
* ``register_*_routes`` — EXCEPT ``register_router`` (allow).

Bypass (per-line OR per-tool):

* **Per-line**: append ``# pragma: B0.15: <reason>`` to the offending
  statement. A SUBSTANTIVE reason is required (R8-J4-1): ≥2 word
  tokens and ≥12 alphanumeric characters, so a single non-whitespace
  char (``# pragma: B0.15: .``) or a lone identifier no longer passes
  — the bypass is not a silent magic boolean. The pragma is matched
  against the SOURCE LINE (we read the file line-by-line and compare
  against the offending statement's ``lineno``); ``ast.parse`` drops
  comments, hence the line-table side-channel.
* **Per-tool**: the tool's ``__init__.py`` declares a module-level
  ``_LIFESPAN_EXEMPT: bool = True`` AND the tool returns a
  ``warnings=`` envelope that BOTH mentions ``"lifespan"`` AND NAMES
  the offending init/function (e.g. ``init_idempotency_cache``,
  ``create_redis_pool``) — a vague "no lifespan support" string is
  rejected (R8-J4-1). When both signals are present the tool's
  templates are skipped and the tool key is registered in
  :pydata:`_WAIVED_TOOLS`.

Trade-offs (declared, NOT hidden):

* **Compose fragments are skipped.** ``main_*_snippet*.txt.tmpl``
  fragments may be top-level Python that splices into a host
  ``main.py`` — when they don't parse we can't see the call. The
  observed fragments (``main_middleware_snippet`` /
  ``main_register_snippet`` / ``main_configure_snippet``) all parse
  cleanly with placeholder normalisation. A future fragment that
  uses ``${if}`` control flow would fail AST parse; the rule will
  silently allow it. This is consistent with B0.12's trade-off.
* **Lifespan detection is structural.** We treat the body of any
  ``async def lifespan(...)`` function (and any ``@asynccontextmanager``
  generator named ``lifespan``) as "inside lifespan". A nested
  ``async def lifespan_inner`` would NOT count — only the outermost
  named function. None of the catalog's patchers use nested lifespans.
* **Intent detection for `_patches.py`.** We scan the AST for any
  function whose name matches the ``*patch_main*`` regex; calls
  inside those function bodies are treated as "module-top-level
  splicing into main.py". This is structural — a helper named
  ``patch_main_router`` would also be in scope (intentional: any
  patcher that names itself after main is opting in). Bypass via
  ``# pragma: B0.15: <reason>`` still works.
* **`configure_logging` allow-list is literal.** A tool that ships
  ``_configure_structlog`` / ``configure_log_format`` /
  ``configure_log_pipeline`` will NOT be allowlisted — it must
  either rename, add the per-line pragma, or land in
  ``_WAIVED_TOOLS``. Rationale: structured-logging configuration
  IS a startup-ordering concern (R5-S5-F2 cluster), and the spec
  explicitly carves out only ``configure_logging``.
* **AnnAssign / Assign that DON'T call match patterns are ignored.**
  ``_redis_url = os.getenv(...)`` is a benign assignment. Only the
  Call node is the offence — an env-var read is fine.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._common import SKILL_ROOT

# ---------------------------------------------------------------------------
# WAIVER SET — tool import paths (relative to ``adapt/``) currently
# violating B0.15 whose fix-PR will land in Wave-1.
#
# Each entry MUST cite the originating triage finding so the waiver
# stays auditable. Removing an entry requires either (a) moving the
# init call inside ``async def lifespan(...)`` OR (b) installing the
# per-tool bypass (``_LIFESPAN_EXEMPT: bool = True`` in __init__.py
# + a ``warnings=`` entry mentioning ``"lifespan"``).
#
# Format: ``"<concern>/<tool>"`` rooted under ``adapt/``. Bundle
# prefix is preserved so the same key shape matches both ``extend/``
# and ``verify/`` paths.
# ---------------------------------------------------------------------------
_WAIVED_TOOLS: frozenset[str] = frozenset(
    {
        # All B0.15 waivers closed.
        #
        # Historical entries (kept as breadcrumbs for the next auditor):
        #
        # * "extend/crud_data/add_bulk_operations" — closed Wave-2 (PR #98):
        #   `_patch_main` now splices `init_idempotency_cache(...)` INSIDE
        #   `async def lifespan(...)` (mirroring `add_arq_worker`), and
        #   shutdown calls `await close_idempotency_cache()` after the
        #   `yield`. Triage R5-O2-D12 + R6-O2-O2-2.
        # * "extend/infrastructure/add_prometheus_metrics" — closed Wave-2
        #   (W2 FINAL B0.15 PR): `_patch_main` now splices
        #   `_init_metrics(prefix=...)` INSIDE `async def lifespan(...)`
        #   (registry bound once per worker startup, fixing R5-S5-F2
        #   "Duplicated timeseries" on hot-reload). Fallback for shapes
        #   without `lifespan` uses module-top init + per-line pragma.
        # * "extend/infrastructure/add_structured_logging" — closed Wave-2
        #   (W2 FINAL B0.15 PR): `_patch_main` now splices
        #   `_configure_structlog(...)` INSIDE `async def lifespan(...)`.
        #   Trade-off documented in the tool: module-import log records
        #   use stdlib defaults until lifespan-startup completes; request
        #   path is unaffected.
    }
)

# ---------------------------------------------------------------------------
# Pattern matching — offending function names
# ---------------------------------------------------------------------------

# Names that are ALWAYS allowed even if they match a pattern.
# Per spec:
#   * ``configure_logging`` — logging configuration is benign at top level
#   * ``register_router`` — registering a single APIRouter is benign
_ALLOWED_NAMES: frozenset[str] = frozenset(
    {
        "configure_logging",
        "register_router",
    }
)

# Patterns whose match-on-tail means the call is an init-class offence.
# Tail = function-name with leading underscores stripped (so
# ``_init_metrics`` matches ``init_*``; this mirrors how the catalog
# actually names private init helpers).
_OFFENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^init_.+$"),
    re.compile(r"^create_.+_pool$"),
    re.compile(r"^configure_.+$"),
    re.compile(r"^start_.+_listener$"),
    re.compile(r"^start_.+_worker$"),
    re.compile(r"^register_.+_routes$"),
)


def _is_offence_name(name: str) -> bool:
    """Return True iff ``name`` matches one of the offence patterns.

    Leading underscores are stripped before matching, so private
    helpers (``_init_metrics``) match the same as public ones
    (``init_metrics``). The allow-list short-circuits exact matches.
    """
    if not name:
        return False
    tail = name.lstrip("_")
    if tail in _ALLOWED_NAMES:
        return False
    return any(p.match(tail) for p in _OFFENCE_PATTERNS)


# ---------------------------------------------------------------------------
# Template discovery
# ---------------------------------------------------------------------------

ADAPT_ROOT = SKILL_ROOT / "adapt"

# Glob patterns for templates that splice into / replace main.py.
# Tuple form preserves a stable iteration order; results are deduped
# via a set in the caller.
_TEMPLATE_GLOBS: tuple[str, ...] = (
    "**/main_patch.py.tmpl",
    "**/main_*_snippet*.tmpl",  # main_middleware_snippet.txt.tmpl etc.
    "**/_patch_main.py.tmpl",
)

# Function-name regex flagging a ``_patches.py`` helper that mutates main.py.
# Any helper that names itself ``patch_main`` / ``_patch_main`` /
# ``patch_main_X`` is in scope. Intent: the function name announces
# "I splice into main.py" and we want its body audited.
_PATCH_MAIN_FN_RE = re.compile(r"^_?patch_main(_\w+)?$|^_?\w+_patch_main$")

# Placeholder normalisation — ``${var}`` / ``$var`` → bare identifier so
# ``ast.parse`` succeeds. Same shape as Python's ``string.Template``.
_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def _tool_key_for(path: Path) -> str:
    """Map a template / patches file to its tool key (relative to ADAPT_ROOT).

    Example: ``adapt/extend/crud_data/add_bulk_operations/templates/main_patch.py.tmpl``
    ↦ ``"extend/crud_data/add_bulk_operations"``.

    Used to look up :pydata:`_WAIVED_TOOLS`. Returns ``""`` when the
    path is outside ADAPT_ROOT (defensive).
    """
    try:
        rel = path.relative_to(ADAPT_ROOT)
    except ValueError:
        return ""
    parts = rel.parts
    # Trim trailing "templates/<file>" → keep "<a>/<b>/<tool>".
    if len(parts) >= 2 and parts[-2] == "templates":
        parts = parts[:-2]
    elif len(parts) >= 1:
        parts = parts[:-1]
    return "/".join(parts)


# ---------------------------------------------------------------------------
# AST walking
# ---------------------------------------------------------------------------


def _call_name(call: ast.Call) -> str:
    """Resolve the callable target's name.

    * ``foo(...)``   ↦ ``"foo"``
    * ``mod.foo(...)`` ↦ ``"foo"`` (we match on the tail — module
      prefix is irrelevant for offence classification)
    * ``obj.method(...)`` ↦ ``"method"``
    * Anything more exotic (subscript, lambda) ↦ ``""``.
    """
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _is_lifespan_func(node: ast.AST) -> bool:
    """True iff ``node`` is the ``lifespan`` async context manager."""
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
        return True
    # Treat ``@asynccontextmanager``-decorated generators named
    # ``lifespan`` as lifespans even when typed as sync generators
    # (an older FastAPI idiom).
    if isinstance(node, ast.FunctionDef) and node.name == "lifespan":
        for dec in node.decorator_list:
            chain_tail = ""
            cur: ast.AST | None = dec
            if isinstance(cur, ast.Call):
                cur = cur.func
            if isinstance(cur, ast.Attribute):
                chain_tail = cur.attr
            elif isinstance(cur, ast.Name):
                chain_tail = cur.id
            if chain_tail == "asynccontextmanager":
                return True
    return False


def _read_source_lines(src: str) -> list[str]:
    """Split source into lines (keep empty trailing) for pragma lookup."""
    return src.splitlines()


# R8-J4-1: the reason capture must be a STRUCTURED, semantic
# justification — not literal noise. The original regex accepted a
# single non-whitespace char (``# pragma: B0.15: .``) as a "reason",
# so any garbage satisfied the waiver. We now require the captured
# reason to clear a minimum length AND contain real word content
# (see ``_pragma_reason_is_substantive``); a bare pragma or a
# punctuation-only "reason" is rejected.
_PRAGMA_RE = re.compile(r"#\s*pragma:\s*B0\.15:\s*(\S.*?)\s*$", re.IGNORECASE)

# Minimum count of alphanumeric characters a pragma reason must carry
# to count as a genuine disclosure. 12 is deliberately conservative:
# it admits short-but-real reasons ("single-process") while rejecting
# ``.``, ``x``, ``- -``, ``B0.15`` and similar noise.
_PRAGMA_REASON_MIN_ALNUM = 12


def _pragma_reason_is_substantive(reason: str) -> bool:
    """True iff ``reason`` is a real justification, not literal noise.

    A reason must contain at least :pydata:`_PRAGMA_REASON_MIN_ALNUM`
    alphanumeric characters spread across ≥2 word tokens, so a single
    long identifier or a run of punctuation does not pass.
    """
    words = re.findall(r"[A-Za-z0-9]+", reason)
    if len(words) < 2:
        return False
    alnum = sum(len(w) for w in words)
    return alnum >= _PRAGMA_REASON_MIN_ALNUM


def _line_has_pragma(line: str) -> bool:
    """True iff the source line carries ``# pragma: B0.15: <reason>``.

    A SUBSTANTIVE reason is required (R8-J4-1): a bare
    ``# pragma: B0.15:`` or a punctuation-only / single-token "reason"
    is NOT a valid bypass — same defensive-justification posture B0.11
    takes with ``_PUBLIC_ROUTE_JUSTIFICATION``.
    """
    m = _PRAGMA_RE.search(line)
    if m is None:
        return False
    return _pragma_reason_is_substantive(m.group(1))


def _collect_indirect_init_funcs(tree: ast.Module) -> dict[str, str]:
    """Build a one-hop indirection map for top-level functions.

    Round-7 O3-F32/F33 (HIGH): two evasion shapes converge on this map.

      1. **Bootstrap indirection** — a top-level function (often
         ``_bootstrap`` / ``_setup`` / ``_init``) calls an offending
         ``init_X(...)`` / ``create_X_pool(...)`` and is then invoked
         at module top:

            def _bootstrap() -> None:
                init_idempotency_cache("redis://...")

            _bootstrap()  # <-- module-top call → effectively init at import

      2. **Decorator side-effect** — a top-level decorator whose body
         calls an offending name fires at import time:

            def some_init(fn):
                init_idempotency_cache("redis://...")
                return fn

            @some_init
            def health(): ...

    For every top-level FunctionDef / AsyncFunctionDef whose body
    contains an offending Call (NOT itself inside a ``lifespan``), we
    record ``{func_name: representative_offence_name}``. The walker
    consults this map: a module-top Call to ``Name(_bootstrap)`` or
    a module-top decorator naming ``some_init`` is reported under the
    *original* offence name (so the error message points at the real
    regression, not the indirection wrapper).

    Lifespan exemption is respected — if the wrapped offending call is
    inside ``async def lifespan(...)`` nested in the helper, we don't
    record it. Class bodies are skipped (consistent with the main
    walker's scope rules).
    """
    indirect: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Don't index lifespans themselves — by spec, calls inside a
        # lifespan are the legitimate end state.
        if _is_lifespan_func(node):
            continue
        hit = _first_offence_call_in_function(node)
        if hit is not None:
            indirect[node.name] = hit
    return indirect


def _first_offence_call_in_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    """Return the name of the first offending Call inside ``fn``'s body,
    skipping nested lifespan scopes and nested class bodies.

    Used by :func:`_collect_indirect_init_funcs` to keep the indirection
    map shallow (one hop only). Nested function bodies are walked so a
    helper that defines a sub-helper and then calls it at its own body
    top is still detected — but we never cross a lifespan boundary.
    """
    found: list[str] = []

    def walk(node: ast.AST, *, in_lifespan: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and not in_lifespan:
                name = _call_name(child)
                if _is_offence_name(name):
                    found.append(name)
                    return
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_in_lifespan = in_lifespan or _is_lifespan_func(child)
                walk(child, in_lifespan=child_in_lifespan)
            elif isinstance(child, ast.ClassDef):
                walk(child, in_lifespan=in_lifespan)
            else:
                walk(child, in_lifespan=in_lifespan)
            if found:
                return

    walk(fn, in_lifespan=False)
    return found[0] if found else None


def _find_offences_in_tree(
    tree: ast.Module,
    source_lines: list[str],
    *,
    treat_function_bodies_as_top: tuple[str, ...] = (),
) -> list[tuple[str, int]]:
    """Walk ``tree`` and return ``[(name, lineno), ...]`` for each
    offending Call.

    "Offending" means:
      * The Call's target name matches :func:`_is_offence_name`, AND
      * The Call's enclosing scope is module-top-level (or the body
        of a function listed in ``treat_function_bodies_as_top`` —
        used for ``_patches.py``'s ``patch_main`` family), AND
      * No ancestor scope is a ``lifespan`` async function body, AND
      * The Call's source line does NOT carry the per-line pragma.

    Additionally, Round-7 O3-F32/F33 (HIGH):

      * A module-top Call whose target Name is a same-module function
        that itself contains an offending init call is reported under
        the inner offence name (``_bootstrap`` indirection).
      * A module-top function decorator whose name resolves to a
        same-module function that contains an offending init call is
        likewise flagged — the decorator runs at import time.

    Both indirections are one hop only; deeper chains can still evade,
    but the catalog has no observed evidence of >1-hop bootstrap so we
    keep the rule cheap.
    """
    offences: list[tuple[str, int]] = []
    indirect = _collect_indirect_init_funcs(tree)

    def _emit(name: str, lineno: int) -> None:
        line = source_lines[lineno - 1] if 0 < lineno <= len(source_lines) else ""
        if not _line_has_pragma(line):
            offences.append((name, lineno))

    def walk(node: ast.AST, *, in_top: bool, in_lifespan: bool) -> None:
        # ``in_top``  : True iff every ancestor up to the module root
        #               is either the Module itself or a function whose
        #               name is in ``treat_function_bodies_as_top``.
        #               (For pure templates, only Module qualifies.)
        # ``in_lifespan`` : True iff any ancestor scope IS a lifespan
        #               function body. Once set it stays set for the
        #               sub-tree — lifespan exemption is inherited.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and in_top and not in_lifespan:
                name = _call_name(child)
                if _is_offence_name(name):
                    _emit(name, child.lineno)
                elif name in indirect:
                    # Bootstrap indirection (O3-F32): top-level call to
                    # a helper whose body fires an init.
                    _emit(indirect[name], child.lineno)
            # Decorator side-effects (O3-F33) — module-top function /
            # class decorators whose name resolves to a same-module
            # helper that contains an init.
            if (
                in_top
                and not in_lifespan
                and isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            ):
                for dec in child.decorator_list:
                    dec_name = _decorator_name(dec)
                    if dec_name and dec_name in indirect:
                        _emit(indirect[dec_name], dec.lineno)
            # Recurse with updated context.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_in_lifespan = in_lifespan or _is_lifespan_func(child)
                # Stay "in_top" only if we descend through a
                # treat-as-top function (patch_main family); a
                # lifespan body is also "in top from the module's
                # perspective" but offences inside it are exempt
                # via in_lifespan — so propagate in_top unchanged
                # for lifespan, and grant in_top for patch_main-like.
                child_in_top = in_top and (
                    child.name in treat_function_bodies_as_top or _is_lifespan_func(child)
                )
                walk(child, in_top=child_in_top, in_lifespan=child_in_lifespan)
            elif isinstance(child, ast.ClassDef):
                # Class body is NOT module-top for our purposes.
                walk(child, in_top=False, in_lifespan=in_lifespan)
            else:
                # Control-flow constructs (If, With, AsyncWith, Try…)
                # don't open a new function scope — keep ``in_top``.
                walk(child, in_top=in_top, in_lifespan=in_lifespan)

    walk(tree, in_top=True, in_lifespan=False)
    # Deterministic ordering.
    offences.sort(key=lambda t: (t[1], t[0]))
    return offences


def _decorator_name(dec: ast.expr) -> str:
    """Resolve a decorator expression to its leftmost callable name.

    ``@foo``        → ``"foo"``
    ``@foo()``      → ``"foo"``
    ``@mod.foo``    → ``"foo"`` (tail)
    ``@mod.foo()``  → ``"foo"``

    Used by the decorator-side-effect detection. The tail-name match
    is consistent with :func:`_call_name`.
    """
    target: ast.AST = dec
    if isinstance(dec, ast.Call):
        target = dec.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


# ---------------------------------------------------------------------------
# Public helpers (covered by tests)
# ---------------------------------------------------------------------------


def find_offences(src: str) -> list[tuple[str, int]]:
    """Scan a TEMPLATE source for module-top init offences.

    Returns ``[(name, lineno), ...]``. ``src`` may contain
    ``${var}`` / ``$var`` placeholders; we normalise them before
    ``ast.parse``. Returns ``[]`` for files that still fail to parse
    (compose fragments — see module docstring trade-offs).
    """
    cleaned = _PLACEHOLDER_RE.sub(lambda m: m.group(1) or m.group(2), src)
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return []
    # Use ORIGINAL source for pragma lookup so a comment on the source
    # line is preserved even though we parsed the cleaned variant.
    return _find_offences_in_tree(tree, _read_source_lines(src))


def find_offences_in_patches(src: str) -> list[tuple[str, int]]:
    """Scan a ``_patches.py`` source for offences inside ``patch_main*`` fns.

    The ``_patches.py`` files are real Python (no placeholders) that
    mutate ``app/main.py`` at orchestration time. We treat calls inside
    any function whose name matches :pydata:`_PATCH_MAIN_FN_RE` as
    "module-top-level into main.py" for offence classification.

    Returns ``[(name, lineno), ...]``.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    # Collect the names of ``patch_main``-like functions at any scope.
    patch_main_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _PATCH_MAIN_FN_RE.match(
            node.name
        ):
            patch_main_names.append(node.name)
    if not patch_main_names:
        return []
    return _find_offences_in_tree(
        tree,
        _read_source_lines(src),
        treat_function_bodies_as_top=tuple(patch_main_names),
    )


# ---------------------------------------------------------------------------
# Bypass disclosure check — _LIFESPAN_EXEMPT + warnings=
# ---------------------------------------------------------------------------


def _tool_init_path(tool_key: str) -> Path:
    """Resolve ``"extend/foo/add_bar"`` → ``adapt/extend/foo/add_bar/__init__.py``."""
    return ADAPT_ROOT / tool_key / "__init__.py"


def _tool_declares_lifespan_exempt(init_path: Path) -> bool:
    """True iff ``__init__.py`` declares ``_LIFESPAN_EXEMPT: bool = True``."""
    if not init_path.exists():
        return False
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        target = None
        value: ast.AST | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
            value = node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0].id
            value = node.value
        if target != "_LIFESPAN_EXEMPT":
            continue
        if isinstance(value, ast.Constant) and value.value is True:
            return True
    return False


# Accept both kwarg-style ``warnings=[...]`` (Python construction) AND
# dict-literal style ``"warnings": [...]`` (JSON-flavoured ToolResult
# envelopes). Either form satisfies the "warnings entry mentions
# lifespan" half of the bypass. We capture the bracketed list body so
# the caller can apply the R8-J4-1 semantic check below.
_WARNINGS_LIST_RE = re.compile(
    r"""(?:warnings\s*=|["']warnings["']\s*:)\s*\[([^\]]*)\]""",
    re.IGNORECASE | re.DOTALL,
)

# R8-J4-1: the warnings entry must NAME the offending init/function, not
# merely contain the word ``lifespan``. We require BOTH the substring
# ``lifespan`` AND a token shaped like an init-class offence
# (``init_X`` / ``create_X_pool`` / ``configure_X`` / ``start_X_listener``
# / ``start_X_worker`` / ``register_X_routes``) so a vague disclosure
# ("no lifespan support") no longer satisfies the waiver — the real
# regression has to be named.
_WARNINGS_LIFESPAN_TOKEN_RE = re.compile(r"lifespan", re.IGNORECASE)
_WARNINGS_INIT_NAME_RE = re.compile(
    r"\b_?("
    r"init_\w+|"
    r"create_\w+_pool|"
    r"configure_\w+|"
    r"start_\w+_listener|"
    r"start_\w+_worker|"
    r"register_\w+_routes"
    r")\b"
)


def _warnings_body_is_substantive(body: str) -> bool:
    """True iff a ``warnings=[...]`` body discloses lifespan AND names an init.

    The body must mention ``lifespan`` (the concern) AND carry a token
    shaped like an offending init/function name (the specific
    regression). ``configure_logging`` / ``register_router`` (the
    rule's allow-list) are excluded so the disclosure can't be satisfied
    by naming a benign call.
    """
    if not _WARNINGS_LIFESPAN_TOKEN_RE.search(body):
        return False
    for m in _WARNINGS_INIT_NAME_RE.finditer(body):
        tail = m.group(1).lstrip("_")
        if tail in _ALLOWED_NAMES:
            continue
        return True
    return False


def _tool_warnings_mention_lifespan(tool_dir: Path) -> bool:
    """True iff any ``.py`` under ``tool_dir`` ships a SUBSTANTIVE
    ``warnings=[..."lifespan"... + <init name>...]`` disclosure (R8-J4-1)."""
    if not tool_dir.is_dir():
        return False
    for py in tool_dir.rglob("*.py"):
        try:
            body = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _WARNINGS_LIST_RE.finditer(body):
            if _warnings_body_is_substantive(m.group(1)):
                return True
    return False


# ---------------------------------------------------------------------------
# Rule entry point
# ---------------------------------------------------------------------------


def _r_init_inside_lifespan_only() -> tuple[bool, str]:
    """B0.15 — no module-top init calls in main-patch templates.

    See module docstring for the full rule shape, allow-list, and
    bypass mechanism.
    """
    if not ADAPT_ROOT.exists():
        return False, f"missing: {ADAPT_ROOT}"

    # Deduplicate matches across overlapping globs.
    seen: set[Path] = set()
    for pat in _TEMPLATE_GLOBS:
        seen.update(ADAPT_ROOT.glob(pat))

    offenders: list[tuple[Path, list[tuple[str, int]]]] = []

    # 1. Template scans.
    for path in sorted(seen):
        tool_key = _tool_key_for(path)
        if tool_key in _WAIVED_TOOLS:
            continue
        if _bypass_satisfied(tool_key):
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"unreadable: {path} ({exc})"
        hits = find_offences(src)
        if hits:
            offenders.append((path, hits))

    # 2. _patches.py scans (intent-detected mutators).
    for patches in sorted(ADAPT_ROOT.rglob("_patches.py")):
        tool_key = _tool_key_for(patches)
        if tool_key in _WAIVED_TOOLS:
            continue
        if _bypass_satisfied(tool_key):
            continue
        try:
            src = patches.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"unreadable: {patches} ({exc})"
        hits = find_offences_in_patches(src)
        if hits:
            offenders.append((patches, hits))

    if not offenders:
        return True, (
            f"§B0.15 satisfied: 0 unwaived module-top init offences "
            f"({len(_WAIVED_TOOLS)} tool(s) in waiver set)"
        )

    rel_root = SKILL_ROOT.parent.parent
    lines: list[str] = [
        f"{len(offenders)} template(s) / patcher(s) call an init-class "
        "function at module-top-level (NOT inside `async def lifespan(...)`) "
        "— see CONTRACT §B0.15 / triage P6:",
    ]
    for path, hits in offenders:
        try:
            rel = path.relative_to(rel_root)
        except ValueError:
            rel = path
        for name, lineno in hits:
            lines.append(f"  {rel}:{lineno}  {name}(...)")
    lines.append(
        "Fix by moving the call INSIDE `async def lifespan(app):` (FastAPI "
        "lifespan startup block), OR — if module-top init is genuinely "
        "required — annotate the line with `# pragma: B0.15: <reason>`, OR "
        "add the tool to `_WAIVED_TOOLS` in `r_init_inside_lifespan.py` "
        "after the tool's `__init__.py` ships `_LIFESPAN_EXEMPT = True` "
        "AND the tool returns a `warnings=` entry containing `lifespan`."
    )
    return False, "\n".join(lines)


def _bypass_satisfied(tool_key: str) -> bool:
    """Per-tool bypass: ``_LIFESPAN_EXEMPT = True`` AND ``warnings=...lifespan...``."""
    if not tool_key:
        return False
    init_path = _tool_init_path(tool_key)
    if not _tool_declares_lifespan_exempt(init_path):
        return False
    return _tool_warnings_mention_lifespan(init_path.parent)
