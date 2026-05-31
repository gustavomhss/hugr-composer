"""B0.16 — ``no_silent_security_failures``.

CONTRACT.md scope: §B0.16 — security-tagged templates MUST NOT
silently swallow broad exceptions. A broad-catch handler
(``except Exception`` / bare ``except:``) whose body is a no-op,
log-only, or log-then-return turns a real security failure into
silence — replay protection drops nonces, rate limiters fail open,
tenant filters skip, DLP scrubbers pass PII through, sentinel
detectors miss injections.

Round-5 / Round-6 jurors clustered five concrete BLOCKER findings on
this shape (pattern P7):

* ``add_api_key_auth/rate_limit.py.tmpl`` — Redis-unavailable swallow:
  ``_get_redis_or_none`` returns ``None`` on any failure, then the
  caller skips rate limiting entirely (fail-open under maintenance).
* ``add_multi_tenancy/tenant_filter.py.tmpl`` — SQLAlchemy mapper
  inspect raises → tenant filter falls through to the "any table with
  ``tenant_id`` is scoped" heuristic. If the mapper introspection
  fails in a way that also corrupts the column dict, cross-tenant
  rows leak.
* ``add_runtime_sentinel/runtime_sentinel.py.tmpl`` — JSON body parse
  swallow: a malformed body that ALSO trips the SQL/command detector
  is dropped entirely; the sentinel reports no finding.
* ``add_tenant_onboarding/orchestrator.py.tmpl`` — compensation step
  failure swallow: a rollback that errors logs + continues; the saga
  is marked COMPENSATED even though state is half-rolled-back.
* ``add_runtime_sentinel`` request body classifier — parallel shape
  to the above; same fail-open class.

This rule makes the whole class unshippable:

Approach (AST, NOT regex):

1. Walk every ``adapt/extend/auth_access/**/*.py.tmpl`` template
   (whole sub-tree) PLUS every ``*.py.tmpl`` whose path matches
   ``tenant|rate_limit|audit|csrf|cors|dlp|sentinel|request_signing|api_key``.
   Templates use ``${var}`` / ``$var`` placeholders that break
   ``ast.parse``; they are normalised to the bare identifier first
   (same trick used by B0.12). Templates that still fail to parse
   are skipped — compose fragments, not standalone modules.
2. For every ``ast.ExceptHandler`` whose type is broad
   (``Exception`` / ``BaseException`` / bare ``except:``):
     - Skip if the handler is inside a ``__exit__`` / ``__aexit__``
       method body (context managers swallow by contract).
     - Skip if the handler body contains an explicit ``raise``
       statement anywhere (re-raise / chained-raise → not silent).
     - Skip if any line of the handler range carries the bypass
       pragma ``# pragma: B0.16-recoverable: <reason>``.
     - Skip if the handler body contains an explicit metric
       increment (``*.inc(`` / ``*.increment(`` — Prometheus
       Counter, statsd, OTLP gauge — surfacing the failure to the
       observability surface counts as a deliberate handler).
     - Otherwise reject if the body is any of:
         a) Single ``pass``.
         b) Only logger-method calls
            (``log.X(...)`` / ``logger.X(...)`` / ``logging.X(...)``)
            and nothing else.
         c) Logger-only calls followed by ``return`` /
            ``return None`` (the "log-then-swallow" shape).
3. Narrow-type catches (``except (KeyError, OSError)``) → ALLOW.
   The rule deliberately ONLY targets the broad-catch class because
   that is the shape jurors flagged: a tool that catches a specific
   recoverable error and logs it has made a real decision.
4. ``finally:`` block contents are NOT scanned — cleanup is fine.

What this rule deliberately does NOT flag (allow-list):

* **Narrow exception types.** ``except (ValueError, KeyError)`` /
  ``except OSError`` / ``except redis.ConnectionError`` are
  surgical handlers; we only target broad catches.
* **``__exit__`` / ``__aexit__`` methods.** Context-manager exit
  protocols MUST be able to swallow (returning ``True`` from
  ``__exit__`` is the documented "suppress" signal). Flagging
  these would force every CM to re-raise.
* **``finally`` blocks.** They run on both success and failure;
  they are not the silent-failure class.
* **Explicit metric increment.** A handler whose body bumps a
  counter (``failures.inc()`` / ``failures.labels(...).inc()`` /
  ``stat.increment(...)``) has surfaced the failure to the
  monitoring surface — that is the documented recoverable shape.
* **Async handlers.** Same rule shape applies — no special-case
  for ``async def`` because the silent-failure class is identical.

Bypass — when a handler is GENUINELY recoverable + disclosed:

Add a single-line comment INSIDE the handler body or on the
``except`` line itself::

    except Exception:
        # pragma: B0.16-recoverable: redis is best-effort cache;
        #   fallback is documented in warnings=
        return None

The pragma comment is matched as a substring (case-insensitive) on
any source line within the ``except`` block's range. Per-tool
waivers are listed in :pydata:`_WAIVED_TOOLS` for pre-existing
offenders (the waiver list IS the Wave-1 fix-PR backlog — see
B0.10 / B0.12 for the same pattern).

Trade-offs (declared, not hidden):

* **Compose fragments are skipped.** A ``main_patch.py.tmpl`` that
  splices into a host module may carry a silent handler this rule
  won't see (ast.parse fails on the bare fragment shape). We accept
  this — fragments inherit the host's contract enforcement.
* **`logging.exception` is treated as a logger call.** Some teams
  consider ``logger.exception(...)`` "the failure was surfaced".
  We disagree: it lands in the log stream but does not propagate
  to callers, alert pipelines, or the response. If a tool wants to
  log + count, it can bump a counter (which exits the silent class)
  OR log + ``raise`` (which exits the silent class). The rule's
  strict shape keeps the contract honest.
* **Logger-only with kwargs is logger-only.** ``log.warning("x",
  extra={...})`` is still a logger call. Structured logging does
  not change the "log-then-swallow" semantics.
* **A handler with mixed work is NOT flagged.** ``except
  Exception: db.rollback(); log.warning(...)`` is a real handler.
  The rule only fires when the body is exclusively ``pass`` or
  logger calls (optionally followed by a bare return).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._common import SKILL_ROOT

# --- Tool waivers --------------------------------------------------------
#
# Tool import paths (relative to ``adapt/``) that have explicitly opted
# into pre-existing silent-handler behaviour. Each entry MUST cite the
# audit finding it discloses, and SHOULD be paired with either:
#   * a ``# pragma: B0.16-recoverable: <reason>`` on the offending
#     handler (lifts the in-rule check), OR
#   * a ``warnings=`` entry in the tool's ``__init__.py`` that
#     surfaces the failure mode to agents at compose time.
#
# Wave-0 SOTA contract: rule lands strict + CI stays green. Each
# pre-existing offender is grandfathered here with a citation. As each
# tool migrates to "raise after log" / "counter increment" / pragma
# disclosure, its entry is removed in the SAME PR. NO new tool may be
# added without explicit reviewer approval — the rule rejects
# regressions in all other code paths.
#
# Format: { "extend/<wp>/<tool_name>", ... }  (relative to ADAPT_ROOT)
_WAIVED_TOOLS: frozenset[str] = frozenset({
    # P7-F1 — _get_redis_or_none returns None on any failure; caller
    # then skips rate limiting (Redis-down → fail-open).
    # Offender: rate_limit.py.tmpl:50 (`except Exception: return None`)
    "extend/auth_access/add_api_key_auth",
    # P7-F2 — SQLAlchemy mapper inspect swallow in tenant_filter; if
    # mapper introspection fails AND column dict is missing,
    # cross-tenant rows leak.
    # Offender: tenant_filter.py.tmpl:84 (`except Exception: pass`)
    "extend/auth_access/add_multi_tenancy",
    # P7-F3 — JSON body parse swallow in detection middleware; a
    # malformed body that also trips the SQL/command detector is
    # dropped → sentinel reports no finding.
    # Offender: runtime_sentinel.py.tmpl:258 (`except Exception: pass`)
    "extend/infrastructure/add_runtime_sentinel",
    # P7-F4 — closed in W2 PR (fix/w2-tenant-onboarding-close-waivers):
    # orchestrator.py.tmpl _compensate() now bumps a metric counter
    # (compensation_failures.inc()) AND records failed_compensations
    # on progress AND transitions to a distinct
    # OnboardingStatus.COMPENSATION_FAILED terminal state so callers
    # never see a misleading COMPENSATED on partial rollback.
})

# --- AST helpers ---------------------------------------------------------

# Replace ``${name}`` / ``$name`` placeholders with the bare identifier
# so the rest of the template parses. Same convention used by B0.12.
_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")

# The bypass-pragma marker. Matched as a substring on any line in the
# handler's source range, case-insensitive. The trailing ``<reason>``
# is required by convention but not enforced — readers grep the source
# to see why.
_PRAGMA_RE = re.compile(r"#\s*pragma:\s*B0\.16-recoverable", re.IGNORECASE)

# Identifiers we treat as logger objects: their method calls in a
# handler body count toward the "log-only" shape. Matches the names
# the templates in this repo actually use; a tool whose logger is
# bound to a different name will not be flagged — but the rule's job
# is to reject the CONVENTIONAL silent shape, and the convention in
# this codebase is ``log`` / ``logger`` / ``logging`` (case sensitive
# for the identifier; ``logger.X`` is the canonical idiom).
_LOGGER_NAMES: frozenset[str] = frozenset({
    "log", "logger", "logging",
    "_log", "_logger", "_LOG", "_LOGGER", "LOG", "LOGGER",
})

# Method-name tails that count as a metric-increment bypass. Covers
# Prometheus Counter (``.inc()``), statsd (``.increment()``), and OTLP
# UpDownCounter (``.inc()``). Walked at any depth so
# ``counter.labels(name="x").inc()`` counts.
_METRIC_TAILS: frozenset[str] = frozenset({"inc", "increment"})


def _is_broad_handler(handler: ast.ExceptHandler) -> bool:
    """Return True iff the handler catches ``Exception`` / ``BaseException``
    or is a bare ``except:`` (no type at all).
    """
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name) and handler.type.id in ("Exception", "BaseException"):
        return True
    return (
        isinstance(handler.type, ast.Attribute)
        and handler.type.attr in ("Exception", "BaseException")
    )


def _is_logger_call(stmt: ast.stmt) -> bool:
    """An expression statement that calls a recognised logger method.

    Matches ``log.X(...)`` / ``logger.X(...)`` / ``logging.X(...)``
    (and the underscore / upper-case variants in
    :pydata:`_LOGGER_NAMES`). Keyword arguments are irrelevant — a
    structured-log call (``log.warning("x", extra={...})``) is still
    a logger call. Method-name (``X``) is unconstrained: we accept
    ``debug`` / ``info`` / ``warning`` / ``error`` / ``critical`` /
    ``exception`` / ``log`` / etc.
    """
    if not isinstance(stmt, ast.Expr):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    base = func.value
    return isinstance(base, ast.Name) and base.id in _LOGGER_NAMES


def _body_contains_raise(body: list[ast.stmt]) -> bool:
    """True iff any statement in ``body`` (recursively) is ``raise ...``.

    Recursion is necessary because a ``raise`` may be nested inside an
    ``if`` branch: ``except Exception: if x: raise; else: log(...)``
    still propagates on the hot path and is NOT silent.
    """
    for node in body:
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                return True
    return False


def _body_contains_metric(body: list[ast.stmt]) -> bool:
    """True iff any expression in ``body`` calls ``*.inc(...)`` /
    ``*.increment(...)``.

    Walked recursively so chained calls (``counter.labels(...).inc()``)
    and conditional increments inside ``if`` branches both count.
    """
    for node in body:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in _METRIC_TAILS:
                return True
    return False


def _handler_has_pragma(handler: ast.ExceptHandler, source_lines: list[str]) -> bool:
    """True iff any source line within the handler's range carries the
    ``# pragma: B0.16-recoverable`` marker.
    """
    start = handler.lineno
    end = handler.end_lineno or start
    for i in range(start - 1, min(end, len(source_lines))):
        if _PRAGMA_RE.search(source_lines[i]):
            return True
    return False


def _is_silent_body(body: list[ast.stmt]) -> bool:
    """Match the documented silent shapes:

    1. Single ``pass``.
    2. Body is exclusively logger calls.
    3. Body is logger calls followed by a bare ``return`` / ``return None``.
    """
    if not body:
        # Empty handler body is not syntactically possible in Python,
        # but defend against malformed AST anyway.
        return False
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return True
    # Logger-only body.
    if all(_is_logger_call(s) for s in body):
        return True
    # Logger-only + trailing bare return / return None.
    last = body[-1]
    if isinstance(last, ast.Return) and (
        last.value is None
        or (isinstance(last.value, ast.Constant) and last.value.value is None)
    ):
        head = body[:-1]
        if all(_is_logger_call(s) for s in head):
            return True
    return False


def _walk_with_parents(tree: ast.AST):
    """Yield ``(node, parent_chain)`` for every node in ``tree``.

    Parent chain is ordered root-first. Needed because the
    ``__exit__`` / ``__aexit__`` skip depends on the enclosing
    function definition.
    """
    stack: list[tuple[ast.AST, list[ast.AST]]] = [(tree, [])]
    while stack:
        node, parents = stack.pop()
        yield node, parents
        new_parents = parents + [node]
        for child in ast.iter_child_nodes(node):
            stack.append((child, new_parents))


def _inside_exit_method(parents: list[ast.AST]) -> bool:
    """True iff any ancestor is a ``__exit__`` / ``__aexit__`` def."""
    for a in parents:
        if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)) and a.name in (
            "__exit__",
            "__aexit__",
        ):
            return True
    return False


def find_silent_handlers(src: str) -> list[tuple[int, str]]:
    """Return ``[(lineno, except_repr), …]`` for every silent broad-catch.

    ``src`` may contain ``${var}`` / ``$var`` placeholders; they are
    normalised before AST parse. Returns ``[]`` for files that still
    fail to parse (compose fragments — see module docstring).

    The returned ``except_repr`` is one of ``"bare"``, ``"Exception"``,
    ``"BaseException"``.
    """
    cleaned = _PLACEHOLDER_RE.sub(lambda m: m.group(1) or m.group(2), src)
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return []
    lines = cleaned.splitlines()

    hits: list[tuple[int, str]] = []
    for node, parents in _walk_with_parents(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _inside_exit_method(parents):
            continue
        if not _is_broad_handler(node):
            continue
        # Bypass checks (in order of cheapness).
        if _handler_has_pragma(node, lines):
            continue
        if _body_contains_raise(node.body):
            continue
        if _body_contains_metric(node.body):
            continue
        if not _is_silent_body(node.body):
            continue
        # Describe the except clause.
        if node.type is None:
            etype = "bare"
        elif isinstance(node.type, ast.Name):
            etype = node.type.id
        elif isinstance(node.type, ast.Attribute):
            etype = node.type.attr
        else:
            etype = "Exception"
        hits.append((node.lineno, etype))
    hits.sort()
    return hits


# --- Scope --------------------------------------------------------------

ADAPT_ROOT = SKILL_ROOT / "adapt"
AUTH_ACCESS_ROOT = ADAPT_ROOT / "extend" / "auth_access"

# Path-fragment keywords. A template whose path (relative to ADAPT_ROOT)
# matches ANY of these is in scope regardless of parent directory.
# These mirror the security-named tool surface used by B0.10.
_PATH_KEYWORDS_RE = re.compile(
    r"tenant|rate_limit|audit|csrf|cors|dlp|sentinel|request_signing|api_key"
)


def _in_scope(path: Path) -> bool:
    """A template is in scope iff it lives under ``adapt/extend/auth_access/``
    OR its path (relative to adapt/) matches the security-keywords regex.
    """
    try:
        rel = path.relative_to(ADAPT_ROOT)
    except ValueError:
        return False
    rel_str = str(rel).replace("\\", "/")
    if rel_str.startswith("extend/auth_access/"):
        return True
    return bool(_PATH_KEYWORDS_RE.search(rel_str))


def _tool_key_for(path: Path) -> str:
    """Map ``adapt/extend/<wp>/<tool>/templates/x.py.tmpl`` ↦
    ``"extend/<wp>/<tool>"`` (waiver granularity, same as B0.12).
    """
    try:
        rel = path.relative_to(ADAPT_ROOT)
    except ValueError:
        return ""
    parts = rel.parts
    if len(parts) >= 2 and parts[-2] == "templates":
        parts = parts[:-2]
    elif len(parts) >= 1:
        parts = parts[:-1]
    return "/".join(parts)


# --- The rule callback ---------------------------------------------------


def _r_no_silent_security_failures() -> tuple[bool, str]:
    """B0.16 — security-tagged templates MUST NOT silently swallow
    broad exceptions.

    See module docstring for full rule shape, allow-list, and bypass
    mechanism.
    """
    if not ADAPT_ROOT.exists():
        return False, f"missing: {ADAPT_ROOT}"

    offenders: list[tuple[Path, list[tuple[int, str]]]] = []
    scanned = 0
    for path in sorted(ADAPT_ROOT.rglob("*.py.tmpl")):
        if not _in_scope(path):
            continue
        tool_key = _tool_key_for(path)
        if tool_key in _WAIVED_TOOLS:
            continue
        scanned += 1
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"unreadable: {path} ({exc})"
        hits = find_silent_handlers(src)
        if hits:
            offenders.append((path, hits))

    if not offenders:
        return True, (
            f"B0.16 ok: scanned {scanned} security-surface template(s); "
            "no silent broad-catch handlers "
            f"({len(_WAIVED_TOOLS)} tool(s) waived)."
        )

    lines: list[str] = [
        f"B0.16 no_silent_security_failures: {len(offenders)} template(s) "
        "ship a broad-catch ``except`` whose body is silent — security "
        "failures vanish at runtime (see CONTRACT §B0.16 / triage P7):",
    ]
    rel_root = SKILL_ROOT.parent.parent
    for path, hits in offenders:
        try:
            rel = path.relative_to(rel_root)
        except ValueError:
            rel = path
        for lineno, etype in hits:
            label = "except:" if etype == "bare" else f"except {etype}"
            lines.append(f"  {rel}:{lineno}  {label} (silent body)")
    lines.append(
        "Fix by either: (a) re-raising after logging, "
        "(b) incrementing a metric counter so the failure surfaces, "
        "(c) catching a narrow exception type, OR "
        "(d) adding `# pragma: B0.16-recoverable: <reason>` to the "
        "handler body to disclose the deliberate swallow."
    )
    return False, "\n".join(lines)
