"""B0.14 — write_schemas_strict_forbid (CONTRACT.md anti-pattern P5).

CONTRACT.md scope: §B0.14 — every Pydantic *write* schema template under
``adapt/`` declares ``ConfigDict(extra="forbid")`` and never accepts an
unbounded type (``Any``, bare ``dict``, bare ``list``, ``dict[*, Any]``,
``list[Any]``, ``list[dict]``).

Pattern P5 (Round-5+6 triage, docs/wp/ROUND5_6_TRIAGE.md §3 P5): write
schemas across ~22 templates accept arbitrary keys, enabling mass-
assignment and key smuggling (the FeatureFlag `kill_switch=False +
enabled=True` race, the bulk_update `updates: list[dict]`, the passkey
`credential: dict[str, Any]`, etc.). The fix is structural — block the
class of finding via a contract rule rather than chasing the ~10 BLOCKER
findings one tool at a time.

This module hosts a single rule callback (``_r_write_schemas_strict``)
because the AST machinery + waiver list is too large to share a phase
module with unrelated checks. Naming convention follows the new
``r_<rule>.py`` layout introduced alongside B0.10+ (one module per rule;
the legacy ``phase*.py`` modules predate the split and continue to host
the original B0–B4 rules).

Scope of the check (in plain English):

  * Find every ``*schema*.py.tmpl`` / ``*schemas*.py.tmpl`` under
    ``adapt/`` (the per-tool template tree).
  * AST-parse each (after substituting ``${name}`` / ``$name``
    placeholders so jinja-style templates parse as Python).
  * For each ``class X(BaseModel):`` in the module:
      - Decide WRITE vs READ from the class name suffix (Create / Update
        / Request / In / Patch / Form / Input / Data → WRITE; Read /
        Public / Response / Out / Detail / View / List / Item → READ;
        verb-prefix like ``RegistrationBeginRequest`` / ``NewUser`` /
        ``EditProfile`` also → WRITE per spec heuristic). The Form /
        Input / Data suffixes + New / Edit prefixes were added in
        R8-J4-3 to close the ``UserForm`` / ``UserInput`` / ``NewUser`` /
        ``UserData`` mass-assignment evasion.
      - WRITE schemas must carry ``model_config = ConfigDict(extra=
        "forbid", ...)`` OR the Pydantic-v1 equivalent ``class Config:
        extra = "forbid"``. Missing → REJECT. (Read schemas exempt —
        they ride ``from_attributes=True`` and don't need ``extra``.)
      - Every non-READ schema's fields are scanned for forbidden type
        tokens. The annotation walk catches: bare ``Any``, bare ``dict``,
        bare ``list``, ``dict[*, Any]``, ``list[Any]``, ``list[dict]``,
        ``list[dict[*, Any]]``, and any nesting that puts ``Any`` inside
        a generic chain. Concrete value types like ``dict[str, str]``
        are ALLOWED (unbounded-key worries don't apply when the value
        type is itself bounded).
  * Bypass for the bare-dict/Any field rule: same line carries a
    ``# pragma: schema-any: <one-line reason>`` comment. The
    extra=forbid rule has NO bypass — write schemas without
    ``extra="forbid"`` are always rejected.
  * Tools listed in ``_WAIVED_TOOLS`` are skipped wholesale. Waivers
    are the legacy debt the rule is *installed against* (so the rule
    can land green and protect future PRs); they get cleared in
    Wave-1 fix-PRs (one tool, one PR).

Trade-offs (declared per WP-16 §13):

  1. AST-only — we deliberately do not import the templates. Templates
     are Python sources with ``${name}`` substitution holes; importing
     would either fail or require a fake substitution layer. AST after
     placeholder cleanup is strictly read-only and deterministic.
  2. Verb-prefix heuristic is closed at 9 tokens (Create/Update/Submit/
     Send/Register/Verify/Confirm/Begin/Complete). A tool that coins a
     new verb-form schema name (e.g. ``ResendEmailVerification``) won't
     be caught by the verb-prefix arm — but it *will* match the
     ``*Request`` / ``*In`` suffix arm. The two arms together catch
     every write-schema name pattern observed in the catalog.
  3. ``Response`` is treated as READ even though some templates use
     ``Response`` for synchronous endpoints that *write* state. We
     accept this false-negative because forcing every ``*Response`` to
     declare ``extra=forbid`` would break ``from_attributes=True``
     interop with ORM models (the documented Pydantic-v2 pattern). The
     write-side mass-assignment threat is on the input boundary.
  4. ``dict[str, str]`` is allowed even though some value types should
     themselves be enums. We allow it because (a) the unbounded-key
     attack surface is what P5 is about, and (b) a concrete value type
     is at least a hard schema constraint Pydantic enforces. Enum-vs-
     str hardening is a separate rule (deferred).
"""

from __future__ import annotations

import ast
import glob
import re
from pathlib import Path

from ._common import SKILL_ROOT

# ---------------------------------------------------------------------------
# Tunables — kept module-level so unit tests can patch them deterministically.
# ---------------------------------------------------------------------------

# Class-name suffixes that mark a WRITE schema (input boundary).
#
# R8-J4-3: a write schema named WITHOUT a Create|Update|Request|In|Patch
# suffix or an imperative-verb prefix (``UserForm``, ``UserInput``,
# ``NewUser``, ``UserData``) was classified as NEITHER write nor read,
# so ``extra="forbid"`` was never required on it — a mass-assignment
# evasion. We BROADEN write-name detection with the ``Form|Input|Data``
# input-boundary suffixes and the ``New|Edit`` verb prefixes. (The full
# "every non-read schema is a write" flip was rejected: it newly flags
# 24 legit read-side response schemas in the catalog — ``UsageSummary``,
# ``TopConsumer``, ``RevenueAnalytics``, ``*Status``, ``*Created`` … —
# that legitimately omit ``extra="forbid"`` because they ride
# ``from_attributes=True``. Broadening the write allow-list catches the
# documented evasion shapes with zero false positives; the residual is
# that an exotically-named write schema with neither a known suffix nor
# verb prefix still escapes — tracked, low incidence.)
_WRITE_SUFFIXES: tuple[str, ...] = (
    "Create",
    "Update",
    "Request",
    "In",
    "Patch",
    "Form",
    "Input",
    "Data",
)

# Imperative verb-form prefixes (per pattern P5 spec + R8-J4-3 New/Edit).
_WRITE_VERB_RE = re.compile(
    r"^(Create|Update|Submit|Send|Register|Verify|Confirm|Begin|Complete|New|Edit)[A-Z]"
)

# Class-name suffixes that mark a READ / response schema (exempt from
# extra=forbid; from_attributes=True is the documented Pydantic-v2 pattern).
_READ_SUFFIXES: tuple[str, ...] = (
    "Read",
    "Public",
    "Response",
    "Out",
    "Detail",
    "View",
    "List",
    "Item",
)

# Per-line bypass for the bare-dict / Any field rule.
_PRAGMA_RE = re.compile(r"#\s*pragma:\s*schema-any:\s*(.+?)\s*$")

# Templates under tools in this set are skipped wholesale.
# Populated from the catalog scan run at rule-authoring time. Each entry
# corresponds to a real BLOCKER/REAL finding from Round-5/6 P5 cluster;
# Wave-1 fix-PRs will clear them one by one (each fix → one waiver
# removed → next CI run keeps the rule green).
_WAIVED_TOOLS: frozenset[str] = frozenset(
    {
        # "add_api_key_auth" — closed Wave-2
        # (fix/w2-api-key-auth-close-waivers): APIKeyCreate + APIKeyUpdate
        # now declare ``model_config = ConfigDict(extra="forbid")``. Drift
        # field ``environment`` removed.
        # "add_api_monetization" — closed Wave-2
        # (fix/w2-api-monetization-close-waivers): UpgradeRequest now
        # carries ``model_config = ConfigDict(extra="forbid")``,
        # RevenueAnalytics replaces ``list[dict]`` with typed
        # ``list[TopConsumer]``, money fields migrated to integer cents.
        # Closes R6-O3-P14 + R6-S8-F2.
        # "add_bulk_operations" — closed Wave-2 (B0.14):
        #   schema_addition.py.tmpl now ships `model_config =
        #   ConfigDict(extra="forbid")` on every Bulk{Create,Update,Delete}
        #   request schema, and replaces `updates: list[dict]` with the
        #   typed `list[${Model}BulkUpdateItem]` (subclass of the existing
        #   strict ${Model}Update, plus a required `id`). See triage
        #   R5-O2-D8 — the original "updates: list[dict]" mass-assignment
        #   surface is now bound by Pydantic-v2 strict validation.
        # "add_compliance_engine" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): ErasureRequest now declares
        # ``model_config = ConfigDict(extra="forbid")``. Other classes in
        # the template are READ-suffix (Public/Response/Record/Certificate)
        # and exempt by spec.
        # "add_data_versioning" — removed by R6-O3-P1 cluster fix-PR:
        # ``VersionCreate`` now declares ``extra="forbid"`` and replaces
        # the bare ``dict[str, Any]`` snapshot with a JSON-scalar bound
        # (``dict[str, str | int | float | bool | None]``). ``VersionDiff``
        # response fields use the same bound.
        # "add_email_templates" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): EmailPreviewRequest now
        # declares extra="forbid"; the ``context: dict`` field carries a
        # ``# pragma: schema-any: ...`` bypass because Jinja2 template
        # context is arbitrary per template and validated downstream by
        # the renderer.
        # "add_feature_flags" — closed Wave-2 (B0.14) in
        # fix/w2-feature-flags-close-waivers:
        #   schemas.py.tmpl now ships ``model_config = ConfigDict(extra=
        #   "forbid")`` on both ``FeatureFlagCreate`` and
        #   ``FeatureFlagUpdate``, and replaces the legacy
        #   ``targeting_rules: list[dict[str, Any]]`` / ``variants:
        #   list[dict[str, Any]]`` mass-assignment surface with typed
        #   sub-models (``TargetingRule`` / ``Variant``, both also
        #   extra=forbid). Cites R6-O3-P9. The strict bounds match the
        #   evaluator runtime keys (``attribute``/``operator``/``value``/
        #   ``return_value`` + ``name``/``weight``).
        # "add_file_upload" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): PresignedUploadRequest +
        # UploadConfirmRequest now declare extra="forbid".
        # PresignedUploadResponse keeps ``fields: dict`` (it's a
        # Response → READ-suffix → exempt).
        # "add_ml_model_registry" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): MLModelCreate + MLModelPromote
        # declare extra="forbid". ``metrics_json: dict[str, Any] | None``
        # on Create + ``metrics_a/_b`` on the Compare response carry
        # ``# pragma: schema-any: ...`` bypasses because metric blobs are
        # framework-specific (sklearn/xgboost/torch emit different keys
        # and value shapes) and stored opaquely in JSONB.
        # "add_ml_model_server" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): PredictionRequest +
        # BatchPredictionRequest declare extra="forbid"; ``input: Any``
        # and ``inputs: list[Any]`` carry ``# pragma: schema-any: ...``
        # bypasses because model input is framework-defined (sklearn
        # array, torch tensor JSON, dict-of-features) and shape-checked
        # by the loaded model at predict time.
        # "add_multi_tenancy" — closed Wave-2
        # (fix/w2-multi-tenancy-close-waivers): TenantCreate/Update now
        # declare extra="forbid"; status Literal-bound. Closes R6-O3-P13.
        # "add_notifications" — closed Wave-2 (B0.14) in
        # fix/w2-notifications-close-waivers: NotificationCreate declares
        # extra="forbid". Closes the R6-O3 P5 cluster on this surface.
        # add_passkey_auth — closed Wave-2
        # (fix/w2-passkey-auth-close-waivers): every WRITE schema
        # (RegistrationBeginRequest / RegistrationCompleteRequest /
        # AuthenticationCompleteRequest) now declares
        # ``model_config = ConfigDict(extra="forbid")`` so the outer
        # envelope rejects key smuggling at parse time. The
        # ``credential: dict[str, Any]`` field on the two CompleteRequest
        # schemas carries a ``# pragma: schema-any: ...`` bypass because
        # the WebAuthn payload shape is validated end-to-end downstream
        # by ``py_webauthn`` (RegistrationCredential.parse_raw /
        # AuthenticationCredential.parse_raw +
        # verify_{registration,authentication}_response — signature,
        # attestation, RP-ID hash, origin, challenge, sign-count, UV
        # flag). Closes R6-O3-P2.
        # "add_pdf_reports" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): ReportRequest now declares
        # ``model_config = ConfigDict(extra="forbid")`` (previously
        # carried only the wrong-shape ``from_attributes=True``).
        # ``context: dict`` carries a ``# pragma: schema-any: ...`` bypass
        # because the Jinja2 template context is template-defined and
        # validated by the renderer.
        # "add_push_notifications_native" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): DeviceTokenCreate +
        # PushSendRequest declare extra="forbid". ``data: dict[str, str]``
        # is already concrete-typed (value type bound to str) — no pragma
        # needed.
        # "add_sms_otp" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): OtpSendRequest +
        # OtpVerifyRequest declare extra="forbid". ConfigDict imported.
        # "add_stripe_checkout" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): CheckoutSessionCreate declares
        # extra="forbid". ``metadata_json: dict[str, str] | None`` is
        # already concrete-typed (value bound to str) — no pragma needed.
        # Money field already int cents (mirrors PR #102).
        # "add_stripe_refund_flow" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): RefundRequest declares
        # extra="forbid". Money field already int cents.
        # add_stripe_subscription — closed in W2 PR
        # (fix/w2-stripe-subscription-close-waivers): SubscriptionCreate
        # and ChangePlanRequest now carry ``model_config =
        # ConfigDict(extra="forbid")``; sibling Read/Public/List response
        # schemas are READ-suffix (exempt by spec). Closes R6-O3-P10
        # write-side mass-assignment surface on the Stripe input boundary.
        # add_tenant_onboarding — closed in W2 PR
        # (fix/w2-tenant-onboarding-close-waivers): OnboardingRequest now
        # carries ``model_config = ConfigDict(extra="forbid")``; sibling
        # response schemas are READ-suffix (exempt by spec).
        # "add_webhook_sender" — closed Wave-2
        # (fix/w2-batch-b014-all-schemas): WebhookCreate + WebhookUpdate
        # declare extra="forbid". ``events: list[str]`` already concrete.
    }
)

# Glob patterns that select schema templates under adapt/.
_SCHEMA_TMPL_GLOBS: tuple[str, ...] = (
    "adapt/**/*schema*.py.tmpl",
    "adapt/**/*schemas*.py.tmpl",
)

# Templates whose basename starts with "test_" are tests (not schemas
# themselves) — exclude even though they match the glob.
_EXCLUDE_BASENAME_PREFIX: tuple[str, ...] = ("test_",)


# ---------------------------------------------------------------------------
# Placeholder cleanup — adapt templates use ``${name}`` / ``$name`` holes.
# We replace them with a valid identifier before AST-parse so the rule
# is side-effect free and never executes template code.
# ---------------------------------------------------------------------------
_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean_placeholders(src: str) -> str:
    """Substitute ``${name}`` / ``$name`` holes so AST can parse."""
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


# ---------------------------------------------------------------------------
# Class classification.
# ---------------------------------------------------------------------------


def _is_read_schema(name: str) -> bool:
    return any(name.endswith(s) for s in _READ_SUFFIXES)


def _is_write_schema(name: str) -> bool:
    if _is_read_schema(name):
        return False
    if any(name.endswith(s) for s in _WRITE_SUFFIXES):
        return True
    return bool(_WRITE_VERB_RE.match(name))


def _inherits_pydantic_model(cls: ast.ClassDef) -> bool:
    """Best-effort: any class whose base list mentions ``BaseModel`` (direct
    or via attribute access) OR any same-module class. The over-include
    side errs safe: a non-pydantic class that happens to be named
    ``XCreate`` and lacks ``extra="forbid"`` will trip the rule, but
    those don't exist in the catalog (every schema-template class lives
    on top of pydantic). We trade a theoretical false-positive for a
    much simpler scanner — and any future false-positive can opt out
    by *not* matching the WRITE-name pattern."""
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
        if isinstance(base, ast.Name):
            # Any Name base — likely a same-module BaseModel subclass.
            return True
    return False


# ---------------------------------------------------------------------------
# `extra="forbid"` detection.
# ---------------------------------------------------------------------------


def _call_extra_forbid(node: ast.expr) -> bool:
    """True if `node` is a call carrying kwarg ``extra="forbid"``.

    Accepts any callee (``ConfigDict(...)``, ``pydantic.ConfigDict(...)``,
    ``dict(...)`` — Pydantic accepts any mapping shape). The kwarg
    presence is what matters; we don't tie the rule to a specific
    factory name."""
    if not isinstance(node, ast.Call):
        return False
    for kw in node.keywords:
        if kw.arg == "extra" and isinstance(kw.value, ast.Constant) and kw.value.value == "forbid":
            return True
    return False


def _class_has_extra_forbid(cls: ast.ClassDef) -> bool:
    """True if the class body declares ``extra="forbid"`` directly.

    Supports both Pydantic v2 (``model_config = ConfigDict(extra=
    "forbid", ...)``, plain ``Assign`` or ``AnnAssign``) and Pydantic
    v1 (``class Config: extra = "forbid"``)."""
    for stmt in cls.body:
        # v2 — assignment.
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id == "model_config"
                    and _call_extra_forbid(stmt.value)
                ):
                    return True
        elif isinstance(stmt, ast.AnnAssign):
            if (
                isinstance(stmt.target, ast.Name)
                and stmt.target.id == "model_config"
                and stmt.value is not None
                and _call_extra_forbid(stmt.value)
            ):
                return True
        # v1 — `class Config: extra = "forbid"`.
        elif isinstance(stmt, ast.ClassDef) and stmt.name == "Config":
            for sub in stmt.body:
                if isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        if (
                            isinstance(tgt, ast.Name)
                            and tgt.id == "extra"
                            and isinstance(sub.value, ast.Constant)
                            and sub.value.value == "forbid"
                        ):
                            return True
    return False


def _ancestor_has_extra_forbid(class_name: str, tree: ast.AST) -> bool:
    """Walk same-module ancestors of ``class_name`` looking for extra=forbid.

    Used so a write schema that subclasses a same-module strict base
    inherits its config. Cross-module inheritance is out of scope (the
    AST rule cannot follow imports without execution); same-module
    coverage handles every observed pattern in the catalog."""
    by_name: dict[str, ast.ClassDef] = {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
    }
    seen: set[str] = set()
    stack: list[str] = [class_name]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        cls = by_name.get(cur)
        if cls is None:
            continue
        if _class_has_extra_forbid(cls):
            return True
        for base in cls.bases:
            if isinstance(base, ast.Name):
                stack.append(base.id)
    return False


# ---------------------------------------------------------------------------
# Annotation walker — finds forbidden type tokens.
# ---------------------------------------------------------------------------


def _annotation_offenses(ann: ast.expr) -> list[str]:
    """Return a list of human-readable offense tokens for the annotation.

    Examples:
        ``dict``             → ``["bare-dict"]``
        ``Any``              → ``["Any"]``
        ``dict[str, Any]``   → ``["dict[..., Any]"]``
        ``list[Any]``        → ``["list[Any]"]``
        ``list[dict]``       → ``["list[dict]"]``
        ``dict[str, str]``   → ``[]``  (allowed)
        ``list[dict[str, list[Any]]]`` → ``["list[dict[..., Any]]", "list[Any]"]``
    """
    offenses: list[str] = []
    _walk_annotation(ann, offenses)
    return offenses


def _annotation_tail(node: ast.AST) -> str:
    """Resolve ``X`` / ``foo.X`` / nested ``a.b.X`` → ``"X"`` (the tail).

    Used by the bare-name walker so ``typing.Dict``, ``t.Dict``,
    ``typing.Any`` all resolve to ``Dict`` / ``Any`` and match the same
    offence shape as bare ``dict`` / ``Any``. Round-7 O3-F26 (HIGH):
    capital-D variants from the ``typing`` module evaded the rule
    because the walker only matched bare ``ast.Name``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


# Bare-name tails that signal an unbounded mutable container or Any.
# Lowercase forms are the Python builtins; capitalised forms are the
# ``typing`` aliases (``typing.Dict``, ``typing.List``, ``typing.Set``,
# ``typing.Any``) which behave identically at runtime but evaded the
# original walker — Round-7 O3-F26.
_DICT_TAILS: frozenset[str] = frozenset({"dict", "Dict"})
_LIST_TAILS: frozenset[str] = frozenset({"list", "List"})
_SET_TAILS: frozenset[str] = frozenset({"set", "Set", "FrozenSet"})
_ANY_TAILS: frozenset[str] = frozenset({"Any"})


def _walk_annotation(node: ast.expr, offenses: list[str]) -> None:
    tail = _annotation_tail(node)
    if isinstance(node, (ast.Name, ast.Attribute)):
        if tail in _ANY_TAILS:
            offenses.append("Any")
            return
        if tail in _DICT_TAILS:
            offenses.append("bare-dict")
            return
        if tail in _LIST_TAILS:
            offenses.append("bare-list")
            return
        if tail in _SET_TAILS:
            offenses.append("bare-set")
            return
        return
    if isinstance(node, ast.Subscript):
        base = node.value
        base_tail = _annotation_tail(base)
        if base_tail in _DICT_TAILS:
            _walk_dict_subscript(node.slice, offenses)
            return
        if base_tail in _LIST_TAILS:
            _walk_list_subscript(node.slice, offenses)
            return
        # Other generics (Optional, Annotated, Sequence, …) — walk
        # children blindly so a nested ``Any`` still trips the rule.
        _walk_annotation(base, offenses)
        _walk_annotation_slice(node.slice, offenses)
        return
    if isinstance(node, ast.BinOp):
        # ``X | Y`` union — walk both arms.
        _walk_annotation(node.left, offenses)
        _walk_annotation(node.right, offenses)
        return
    if isinstance(node, ast.Tuple):
        for elt in node.elts:
            _walk_annotation(elt, offenses)
        return
    # ast.Constant — fine. (ast.Attribute is handled above by tail-match;
    # an unmatched Attribute like ``uuid.UUID`` falls through silently.)


def _walk_dict_subscript(slc: ast.expr, offenses: list[str]) -> None:
    """``dict[K, V]`` — reject if V (or anything nested in V) is ``Any``."""
    if not (isinstance(slc, ast.Tuple) and len(slc.elts) >= 2):
        # Malformed shape — walk blindly.
        _walk_annotation_slice(slc, offenses)
        return
    _, val_t = slc.elts[0], slc.elts[1]
    val_offenses: list[str] = []
    _walk_annotation(val_t, val_offenses)
    # Translate value-side `Any` into the parent-shape token.
    if "Any" in val_offenses:
        offenses.append("dict[..., Any]")
    # Bubble up other non-Any offenses (e.g. nested `list[Any]`).
    for off in val_offenses:
        if off != "Any":
            offenses.append(off)


def _walk_list_subscript(slc: ast.expr, offenses: list[str]) -> None:
    """``list[T]`` — reject ``list[dict]``, ``list[Any]``, ``list[dict[*, Any]]``."""
    inner: list[str] = []
    _walk_annotation(slc, inner)
    for off in inner:
        if off == "Any":
            offenses.append("list[Any]")
        elif off == "bare-dict":
            offenses.append("list[dict]")
        elif off == "dict[..., Any]":
            offenses.append("list[dict[..., Any]]")
        else:
            offenses.append(off)


def _walk_annotation_slice(slc: ast.expr, offenses: list[str]) -> None:
    if isinstance(slc, ast.Tuple):
        for elt in slc.elts:
            _walk_annotation(elt, offenses)
    else:
        _walk_annotation(slc, offenses)


# ---------------------------------------------------------------------------
# Pragma detection (per-line bypass for the bare-dict / Any rule).
# ---------------------------------------------------------------------------


def _line_has_pragma(src_lines: list[str], lineno: int) -> str | None:
    """Return the pragma reason (≥1 word) if the line carries the bypass."""
    if 1 <= lineno <= len(src_lines):
        m = _PRAGMA_RE.search(src_lines[lineno - 1])
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# File scanner — pure (no I/O outside the file read).
# ---------------------------------------------------------------------------


def _tool_name_from_template_path(path: Path, root: Path) -> str | None:
    """Return the per-tool dir name (e.g. ``add_feature_flags``) the
    template lives under, or None if the path doesn't match the
    expected ``adapt/<verb>/<group>/<add_*>/templates/<x>.py.tmpl``
    shape."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    for part in parts:
        if part.startswith("add_"):
            return part
    return None


def _scan_file(
    path: Path,
) -> tuple[list[str], list[tuple[str, str, int, list[str]]]]:
    """Scan one template; return (missing_forbid_class_names, bad_fields).

    bad_fields elements are ``(class_name, field_name, lineno, offenses)``.
    A parse error is converted to a single missing-forbid entry tagged
    ``__parse_error__`` so the caller fails loudly (parse must work for
    every template; the placeholder cleanup is supposed to handle every
    real-world case)."""
    raw = path.read_text(encoding="utf-8")
    cleaned = _clean_placeholders(raw)
    src_lines = raw.splitlines()  # original — pragma lives on raw line

    missing_forbid: list[str] = []
    bad_fields: list[tuple[str, str, int, list[str]]] = []

    try:
        tree = ast.parse(cleaned)
    except SyntaxError as exc:
        missing_forbid.append(f"__parse_error__: {exc.msg} (line {exc.lineno})")
        return missing_forbid, bad_fields

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _inherits_pydantic_model(node):
            continue

        if (
            _is_write_schema(node.name)
            and not _class_has_extra_forbid(node)
            and not _ancestor_has_extra_forbid(node.name, tree)
        ):
            missing_forbid.append(node.name)

        if not _is_read_schema(node.name):
            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign) or stmt.annotation is None:
                    continue
                offenses = _annotation_offenses(stmt.annotation)
                if not offenses:
                    continue
                if _line_has_pragma(src_lines, stmt.lineno):
                    continue
                field = stmt.target.id if isinstance(stmt.target, ast.Name) else "?"
                bad_fields.append((node.name, field, stmt.lineno, sorted(set(offenses))))

    return missing_forbid, bad_fields


# ---------------------------------------------------------------------------
# Public API — the rule callback consumed by ``_registry.RULES``.
# ---------------------------------------------------------------------------


def find_schema_templates(skill_root: Path | None = None) -> list[Path]:
    """Return every schema template under ``adapt/`` (sorted, dedup'd).

    Exposed so unit tests can introspect the discovery list."""
    root = skill_root or SKILL_ROOT
    found: set[Path] = set()
    for pat in _SCHEMA_TMPL_GLOBS:
        for p in glob.glob(str(root / pat), recursive=True):
            path = Path(p)
            if any(path.name.startswith(pref) for pref in _EXCLUDE_BASENAME_PREFIX):
                continue
            found.add(path)
    return sorted(found)


def _r_write_schemas_strict() -> tuple[bool, str]:
    """B0.14 — write schemas declare ``extra="forbid"`` and refuse bare-Any fields.

    See module docstring for the full spec + trade-off declaration.
    """
    templates = find_schema_templates()
    if not templates:
        return False, ("B0.14: no schema templates discovered under adapt/ — globs broken?")

    failures: list[str] = []
    scanned = 0
    waived_skipped = 0
    for tmpl in templates:
        tool = _tool_name_from_template_path(tmpl, SKILL_ROOT)
        if tool is not None and tool in _WAIVED_TOOLS:
            waived_skipped += 1
            continue
        scanned += 1
        missing_forbid, bad_fields = _scan_file(tmpl)
        rel = tmpl.relative_to(SKILL_ROOT)
        for cls in missing_forbid:
            failures.append(f'{rel}::{cls} missing extra="forbid"')
        for cls, field, line, offenses in bad_fields:
            failures.append(f"{rel}::{cls}.{field} (line {line}) forbidden type(s) {offenses}")

    if failures:
        head = failures[:5]
        more = f" (+{len(failures) - len(head)} more)" if len(failures) > len(head) else ""
        joined = "\n    - ".join(head)
        return False, (
            f"B0.14 write_schemas_strict_forbid: {len(failures)} violation(s) across "
            f"{scanned} scanned template(s) "
            f"({waived_skipped} waived){more}:\n    - {joined}"
        )

    return True, (
        f'B0.14 satisfied: {scanned} write-schema template(s) carry extra="forbid"'
        f" + no bare-Any fields ({waived_skipped} waived for Wave-1 fix-PRs)"
    )
