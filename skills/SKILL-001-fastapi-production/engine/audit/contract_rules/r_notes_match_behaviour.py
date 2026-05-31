"""B0.13 — ``notes_match_emitted_behaviour`` (honesty meta-rule).

CONTRACT.md scope: §B0.13 (Wave-0.5 anti-pattern P4 — "notes claim
properties the template never enforces"). Closes the *honesty gap*
between what a tool *says* in its ``ToolResult(notes=[...])`` and
what the emitted template *actually* does at runtime.

Background — why this exists
============================

Agents read ``notes`` as success prose: when a notes line says
*"signed"*, *"verified"*, *"append-only"*, *"hash-chained"*,
*"idempotent"*, … the agent treats that as a guarantee and stops
auditing. Round-6-S12-F4 / Round-5 audit cluster P4 documented ~12
tools whose notes assert properties the templates can demonstrably NOT
deliver under the documented deployment shape (single-worker only,
best-effort, opt-in flag never set, …).

This rule does NOT verify the claim itself — it cannot, claims like
"hash-chained" are correctness properties not lint targets. Instead
it enforces the **pair invariant**: every claim-bearing notes line
must have a *paired honesty test* — an engine-level test asserting
the claim holds against the template's actual emitted shape — OR
the notes line must carry an explicit escape phrase that downgrades
the claim ("only when", "requires manual", "see next_steps", "⚠").

Tools whose notes claim properties that no paired test demonstrates
AND that carry no escape language are added to :pydata:`_WAIVED_TOOLS`
(Wave-0.5 grandfathering). The waiver list IS the Wave-1 honesty-test
backlog: each tool migrated out is one fewer P4 finding.

Approach
========

1. Walk every ``adapt/**/<tool>/__init__.py`` (depth ≥ 3 under
   ``adapt/`` — category ``__init__``s at depth ≤ 2 are skipped).
2. AST-collect every string that ends up in a
   ``ToolResult(notes=[…])`` keyword — direct list-literal AND
   indirect Name → module-level constant List. ``warnings=`` entries
   are NEVER scanned (those ARE the disclosure surface — they
   already disclose; scanning them would defeat the bypass).
3. For each note string, if it contains a *claim-token* AND does
   NOT contain an *escape phrase*, mark the tool as "needs honesty
   evidence".
4. Honesty evidence = an engine-level test file at one of:
     - ``engine/tests/test_<tool>_notes_invariants.py``
     - ``engine/tests/test_<tool>_emitted.py``
   ``<tool>`` is the leaf tool directory name (the last segment of
   the tool key). Fuzzy match: any ``def test_*`` whose function name
   OR docstring contains the offending claim-token (case-insensitive)
   counts as paired evidence.
5. If the tool key is in :pydata:`_WAIVED_TOOLS`, skip (Wave-0.5
   grandfathering — see waiver list comments for the finding each
   tool discloses).
6. Otherwise REJECT with a copy-pasteable offender list.

What this rule deliberately does NOT do
========================================

* **Does NOT scan ``warnings=`` entries.** Those are meant to disclose
  the gap a claim might leave open ("WARNING: fan-out is best-effort
  — no per-channel retry budget"). Treating them as claims would
  invert the bypass.
* **Does NOT scan ``next_steps=`` entries.** Those describe operator
  TODOs, not finished behaviour.
* **Does NOT verify the claim itself.** Whether the "hash-chained
  ledger" template is *actually* hash-chained is a property the
  paired honesty test asserts — this rule just enforces the pair
  exists. A vacuous honesty test (``def test_signed(): assert True``)
  passes B0.13 and would be caught by code review / mutation testing.
* **Does NOT scan tool docstrings.** Module-level docstrings are
  developer-facing prose, not agent-facing tool output. Only
  ``ToolResult(notes=…)`` strings are scanned.

Tool-key resolution
===================

Same shape as B0.10 / B0.12: ``adapt/<bundle>/<category>/<tool>/__init__.py``
↦ ``"<bundle>/<category>/<tool>"`` relative to ``ADAPT_ROOT``. The
``verify/`` bundle uses two-segment keys (``verify/<tool>``) because
its tools live at ``adapt/verify/<tool>/__init__.py`` with no
``<category>`` middle segment.

Trade-offs (declared, not hidden)
=================================

* **Token list is hand-curated.** The 15 claim-tokens were chosen from
  the audit cluster P4 review. A future tool that lies in a different
  vocabulary (``"tamper-proof"``, ``"durable"``, ``"exactly-once"``,
  ``"strongly consistent"``) slips through until the token list grows.
  Token list is in this file (not a YAML) so adding tokens is a
  reviewable code change with a test diff.
* **Pair-test name match is fuzzy.** ``test_signed_token_validates``
  satisfies the "signed" claim by name alone — we do not parse the
  test body. This buys speed (no test execution) at the cost of a
  vacuous-test loophole. Documented; mitigated by mutation testing
  and PR review.
* **Escape phrases are substring-matched.** A note containing
  ``"only when X"`` for any X passes the escape gate, including
  pathological cases like ``"only when running tests"``. We accept
  this — the alternative (regex constraint on the escape clause) is
  brittle and the false-negative rate from over-broad escapes is
  bounded by reviewer attention on the diff.
* **Grandfathering is per-tool, not per-line.** A waived tool gets
  ALL its notes skipped even for additional claim tokens added later.
  This is intentional: the unit of fix is a *paired test file*, not a
  *paired test per claim token*. When the tool's pair test lands, the
  waiver is removed and the rule re-scans ALL claims.
* **The escape ``⚠`` is exact-character-matched.** Non-ASCII; one
  byte. We rely on UTF-8 reads (default). Templates emitted on
  Windows with cp1252 are NOT a supported authoring shape.

Bypass mechanism (for *new* tools added post-Wave-0.5)
======================================================

A new tool MUST either:

* Ship a paired test file at one of the two pair-test paths AND that
  test must contain ``def test_*`` whose name or docstring references
  the claim token; OR
* Add the escape phrase (``"only when"`` / ``"requires manual"`` /
  ``"see next_steps"`` / ``"⚠"``) to the offending notes line; OR
* Be added to :pydata:`_WAIVED_TOOLS` with an inline citation
  pointing to the audit finding the waiver discloses — reviewer
  approval required, same shape as B0.12's waiver expansion gate.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ._common import SKILL_ROOT

# --- Public knobs --------------------------------------------------------

#: Tokens that, when present in a notes string, mark it as a "claim"
#: requiring paired honesty evidence. All matched case-insensitively.
#: Curated from Round-5 / Round-6 audit cluster P4.
_CLAIM_TOKENS: frozenset[str] = frozenset({
    "automatically",
    "never trusts",
    "append-only",
    "fan-out",
    "hot reload",
    "verified",
    "encrypted",
    "hash-chained",
    "distributed",
    "cross-worker",
    "production-grade",
    "tamper-evident",
    "single-use",
    "idempotent",
    "signed",
})

#: Phrases that, when present in the SAME notes string, downgrade the
#: claim to a conditional / qualified statement and exempt the line
#: from requiring paired evidence. Substring-matched case-insensitively
#: (except ``⚠`` which is matched as-is).
_ESCAPE_PHRASES: tuple[str, ...] = (
    "only when",
    "requires manual",
    "see next_steps",
    "⚠",
)

#: Test-file name templates probed for honesty evidence. ``{tool}`` is
#: the leaf tool directory name (e.g. ``add_dpop_tokens``).
_PAIR_TEST_PATTERNS: tuple[str, ...] = (
    "test_{tool}_notes_invariants.py",
    "test_{tool}_emitted.py",
)

# --- Tool waivers --------------------------------------------------------
#
# Tool keys (format: ``<bundle>/<category>/<tool>`` for extend/evolve/
# operate/proactive, ``<bundle>/<tool>`` for verify) that are
# grandfathered under Wave-0.5: their notes carry claim tokens AND no
# paired engine-level test exists yet. Each entry MUST cite the
# audit finding the waiver discloses; the waiver list IS the Wave-1
# honesty-test backlog (one PR per tool migrating out).
#
# NO new tool may be added to this set without reviewer approval — the
# rule rejects regressions everywhere else.
_WAIVED_TOOLS: frozenset[str] = frozenset({
    # add_feature_flags — closed Wave-2 (B0.13) in
    # fix/w2-feature-flags-close-waivers:
    #   notes are now honest about the single-node 60s-TTL cache, the
    #   commented-out invalidation listener (R5-S2-F7), and the kill-
    #   switch TTL race (R5-S2-F8). The over-claim "Redis pubsub
    #   invalidation (< 1s fan-out)" was replaced with the per-worker
    #   reality and the gap was moved to warnings=. Paired test:
    #   engine/tests/test_add_feature_flags_notes_invariants.py asserts
    #   the disclosure shape against the template content.
    # P4 — "verified email" claim; no engine-level test asserts the
    # account-linking branch actually checks email_verified=true.
    "extend/auth_access/add_social_login",
    # add_audit_log — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-tests:
    #   pair test at
    #   engine/tests/test_add_audit_log_notes_invariants.py asserts
    #   (a) emitted glue wires `core.venous._adapters.fastapi.AuditLogAdapter.install`
    #   (not a placeholder InMemoryAuditLog); (b) the adapter
    #   instantiates `InMemoryTamperEvidentAuditLog` with an
    #   `HmacReferenceSigner`; (c) primitive append builds a SHA-256
    #   `prev_hash` chain; (d) `_signer.sign(payload)` is called and
    #   `HmacReferenceSigner.verify` uses `hmac.compare_digest`; and
    #   (e) the impl exposes no `update`/`delete`/`pop`/`__setitem__`
    #   mutators — anchoring `hash-chained`, `signed`, and
    #   `append-only` end-to-end. Closes R5-S1-F5 regression guard.
    # add_file_upload — REMAINS WAIVED after Wave-2
    # fix/w2-batch-b013-honesty-cluster-2 review:
    #   the "never trusts Content-Type" claim is TRUE for the
    #   LocalStorage path (``upload_file_local`` calls
    #   ``validate_file`` on ``UploadFile.file`` via libmagic byte
    #   signature) but FALSE for the S3 confirm path
    #   (``confirm_upload`` only calls ``s3.head_object`` — the bytes
    #   uploaded directly to S3 via the presigned URL are NEVER
    #   fetched back and re-validated). R5-S1-F6 was correct.
    #   Closing this waiver requires either (a) a real S3-confirm-side
    #   magic-byte fetch (significant template change, out of scope
    #   for the honesty-test PR), or (b) qualifying the notes line
    #   ("⚠ S3 path validates only object metadata"). Tracked as a
    #   tool-fix follow-up; shipping a vacuous honesty test would let
    #   the gap regress silently — which the rule's docstring
    #   §"Trade-offs" explicitly forbids.
    "extend/crud_data/add_file_upload",
    # P4 — "distributed" / "fan-out" claims; no engine-level test
    # asserts the wired primitives actually coordinate cross-worker.
    "extend/infrastructure/add_cache_layer",
    # add_csrf_protection — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-tests
    # add_notifications — closed Wave-2 (B0.13) in
    # fix/w2-notifications-close-waivers: notes no longer claim
    # "fan-out"; honest single-channel disclosure moved to warnings=.
    # Paired test: engine/tests/test_add_notifications_notes_invariants.py
    # add_outbox_pattern — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-tests
    # add_rate_limiting — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-tests
    # add_request_fingerprint — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-tests
    # add_response_armor — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_add_response_armor_notes_invariants.py
    # AST-anchors the "automatically" Cache-Control claim against the
    # emitted ``ResponseArmorMiddleware._apply_cache_control``: the
    # gate is ``response.status_code >= 400`` (covers ALL 4xx AND 5xx,
    # not 5xx-only) and the assigned header value contains the literal
    # ``no-store``. Also asserts ``dispatch`` actually invokes
    # ``_apply_cache_control`` so the gate is reachable from the
    # request boundary.
    # add_s3_storage — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_add_s3_storage_notes_invariants.py
    # AST-anchors the "presigned" / "signed" URL claim against
    # ``S3Client.presigned_upload_url`` and ``presigned_download_url``:
    # both MUST call ``self._client.generate_presigned_url(...)`` with
    # ``"put_object"`` / ``"get_object"`` (the boto3 entry point that
    # signs the URL via AWS Sigv4). Also asserts the emitted routes
    # delegate to ``presigned_upload_url`` AND do NOT call
    # ``upload_fileobj`` / ``download_fileobj`` (the boto3 methods
    # that would proxy bytes through the API process and break the
    # "never buffers binary data" half of the claim). SSE stays
    # disclosed in ``warnings=`` — out of scope of the B0.13 tokens.
    # add_stripe_refund_flow — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_add_stripe_refund_flow_notes_invariants.py
    # mirrors the add_stripe_subscription pattern shipped in PR #103:
    # AST-asserts the emitted ``stripe_refund_webhook`` handler in
    # ``refunds_routes.py.tmpl`` (a) calls
    # ``stripe.Webhook.construct_event(payload, sig_header, secret)``,
    # (b) wraps it in try/except that re-raises ``HTTPException(400)``
    # on verification failure (blocks the B0.16-style silent-fail
    # pattern), and (c) reads the ``stripe-signature`` header before
    # the verify call so the SDK has a signature to validate against.
    # add_stripe_subscription — closed in W2 PR
    # (fix/w2-stripe-subscription-close-waivers): pair test at
    # engine/tests/test_add_stripe_subscription_notes_invariants.py
    # asserts (a) the emitted stripe_webhook route calls
    # billing.construct_webhook_event(payload, sig_header), (b) the call
    # is wrapped in try/except that re-raises HTTPException(400) on
    # verification failure, and (c) the StripeBillingAdapter wrapper
    # delegates to stripe.Webhook.construct_event so the chain anchors
    # to the SDK primitive named in the notes line. Closes
    # R6-S2-F11 / R5-O3-F5 cluster for this tool.
    # add_webhook_receiver — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_add_webhook_receiver_notes_invariants.py
    # AST-asserts the "idempotent" consumer claim against (a) the
    # emitted ``glue.py.tmpl`` (imports ``install`` from
    # ``WebhookReceiverAdapter`` and calls it inside
    # ``install_webhook_receiver``), and (b) the adapter source
    # (``WebhookReceiverAdapter.install`` constructs its consumer
    # with ``inbox=InMemoryInboxDeduplicator(...)`` — the primitive
    # enforcing IDC-INV-02 — and the consumer class inherits from
    # ``BaseIdempotentConsumer`` so IDC-INV-01 cached-retry semantics
    # apply).
    # add_websocket_chat — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_add_websocket_chat_notes_invariants.py
    # AST-asserts the "Redis fan-out, multi-worker safe" claim:
    # ``WebSocketManager.broadcast`` calls ``redis.publish(...)`` (the
    # publish half), ``subscribe_loop`` calls ``redis.pubsub()`` +
    # ``pubsub.subscribe(...)`` and forwards via ``ws.send_text``,
    # and the chat endpoint spawns the subscribe loop per accepted
    # socket via ``asyncio.create_task``. The fire-and-forget
    # disclosure remains in the function docstrings (already shipped).
    # add_websocket_presence — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_add_websocket_presence_notes_invariants.py
    # AST-asserts the "Fan-out via Redis pub/sub — multi-worker safe"
    # claim against ``PresenceManager``: ``mark_online`` and
    # ``mark_offline`` call ``self._publish_event(..., status, ...)``
    # with literal "online"/"offline"; ``_publish_event`` calls
    # ``redis.publish(channel, payload)``; and the "multi-worker safe"
    # half is anchored by ``mark_online`` persisting state through
    # ``redis.sadd`` + ``redis.set`` (shared Redis, not per-process
    # dicts). Intentionally does NOT assert an in-tool subscribe loop:
    # presence is fire-and-forget publish for downstream consumers
    # (notification services, the chat tool's presence overlay), not
    # in-tool consumption.
    # verify/security_scan — closed Wave-2 (B0.13) in
    # fix/w2-batch-b013-honesty-cluster-2: pair test at
    #   engine/tests/test_security_scan_notes_invariants.py
    # asserts the "uploads to GitHub Security tab automatically" claim
    # against ``ci_workflow.yml.tmpl``: an ``upload-sarif@v<N>`` step
    # exists with a ``.sarif`` ``with.sarif_file`` path, that step
    # carries ``if: always()`` so failed scans still upload, the job
    # grants ``security-events: write`` (required for upload-sarif),
    # and the orchestrator emits the SARIF filename the workflow
    # references (no path mismatch).
})

# --- Scanner -------------------------------------------------------------

ADAPT_ROOT = SKILL_ROOT / "adapt"
TESTS_ROOT = SKILL_ROOT / "engine" / "tests"


def _tool_key_for_init(init_path: Path, adapt_root: Path) -> str:
    """Map ``adapt/extend/auth_access/add_dpop_tokens/__init__.py``
    ↦ ``"extend/auth_access/add_dpop_tokens"`` (relative to
    ``adapt_root``).

    Category-level ``__init__.py`` files (depth < 3) return ``""``
    so the caller can skip them.
    """
    try:
        rel = init_path.relative_to(adapt_root)
    except ValueError:
        return ""
    parts = list(rel.parts)
    if parts[-1] != "__init__.py":
        return ""
    parts = parts[:-1]
    if len(parts) < 2:
        # depth 0/1 — adapt/__init__.py or adapt/extend/__init__.py
        return ""
    return "/".join(parts)


def _string_lists_at_module_level(tree: ast.Module) -> dict[str, list[tuple[int, str]]]:
    """Collect module-level ``NAME = [str, str, …]`` constants.

    Used to follow indirect ``ToolResult(notes=_NOTES_SUCCESS)`` refs.
    Only Lists whose elements are ALL string constants are collected.
    """
    out: dict[str, list[tuple[int, str]]] = {}
    for stmt in tree.body:
        target_name: str | None = None
        value: ast.AST | None = None
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            target_name = stmt.targets[0].id
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target_name = stmt.target.id
            value = stmt.value
        if target_name is None or not isinstance(value, ast.List):
            continue
        items: list[tuple[int, str]] = []
        all_strings = True
        for el in value.elts:
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                items.append((el.lineno, el.value))
            else:
                all_strings = False
                break
        if all_strings and items:
            out[target_name] = items
    return out


def _toolresult_func_name(call: ast.Call) -> str:
    """Return the trailing identifier of ``call.func``, or ``""``."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def extract_notes_strings(src: str) -> list[tuple[int, str]]:
    """Return ``[(lineno, note_string), …]`` for every string passed
    as ``ToolResult(notes=…)`` anywhere in the module.

    Handles both shapes:

    * Direct list literal: ``ToolResult(notes=["…", "…"])``
    * Indirect Name: ``ToolResult(notes=_NOTES_SUCCESS)`` where
      ``_NOTES_SUCCESS = ["…", "…"]`` is a module-level constant.

    Modules that fail to parse return ``[]`` (a tool ``__init__.py``
    that doesn't parse can't actually run — it's a different bug).
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    name_to_strings = _string_lists_at_module_level(tree)
    collected: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _toolresult_func_name(node) != "ToolResult":
            continue
        for kw in node.keywords:
            if kw.arg != "notes":
                continue
            v = kw.value
            if isinstance(v, ast.List):
                for el in v.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        collected.append((el.lineno, el.value))
            elif isinstance(v, ast.Name) and v.id in name_to_strings:
                collected.extend(name_to_strings[v.id])
    return collected


def _note_has_escape(note: str) -> bool:
    """Substring match (case-insensitive for ASCII phrases)."""
    if "⚠" in note:
        return True
    low = note.lower()
    return any(esc.lower() in low for esc in _ESCAPE_PHRASES if esc != "⚠")


def find_claim_tokens(note: str) -> list[str]:
    """Return matched claim tokens (lowercase) — case-insensitive."""
    low = note.lower()
    return [tok for tok in _CLAIM_TOKENS if tok in low]


_TEST_FUNC_RE = re.compile(r"def\s+(test_\w+)\s*\(")


def _pair_test_files_for(tool_leaf: str, tests_root: Path) -> list[Path]:
    """Return existing pair-test paths for a tool, in lookup order."""
    return [
        tests_root / pat.format(tool=tool_leaf)
        for pat in _PAIR_TEST_PATTERNS
        if (tests_root / pat.format(tool=tool_leaf)).exists()
    ]


def _claim_covered_by_test(test_src: str, claim: str) -> bool:
    """Fuzzy: any ``def test_*`` whose name OR docstring contains
    ``claim`` (case-insensitive) covers it.

    Hyphens in claim tokens (``"append-only"``) are normalised to
    underscores when matching against function names; underscores
    match either form.
    """
    claim_low = claim.lower()
    claim_underscored = claim_low.replace("-", "_").replace(" ", "_")
    try:
        tree = ast.parse(test_src)
    except SyntaxError:
        # Fall back to regex so a partial-edit doesn't crash the rule.
        for m in _TEST_FUNC_RE.finditer(test_src):
            fname = m.group(1).lower()
            if claim_low in fname or claim_underscored in fname:
                return True
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        name_low = node.name.lower()
        if claim_low in name_low or claim_underscored in name_low:
            return True
        ds = ast.get_docstring(node) or ""
        if claim_low in ds.lower():
            return True
    return False


def _audit_tool_init(
    init_path: Path,
    tool_key: str,
    tests_root: Path,
) -> list[tuple[int, str, list[str]]]:
    """Return offending claims for one tool ``__init__.py``.

    Returns ``[(lineno, note, [unmatched_claims]), …]``. Empty list
    means OK — either no claims OR all claims have either an escape
    phrase OR a paired test covering them.
    """
    try:
        src = init_path.read_text(encoding="utf-8")
    except OSError:
        # File became unreadable mid-run — treat as offender so CI
        # surfaces it rather than silently passing.
        return [(0, f"<unreadable: {init_path}>", ["<read-error>"])]
    notes = extract_notes_strings(src)
    if not notes:
        return []

    tool_leaf = tool_key.rsplit("/", 1)[-1]
    pair_files = _pair_test_files_for(tool_leaf, tests_root)
    pair_srcs = [p.read_text(encoding="utf-8") for p in pair_files]

    offenders: list[tuple[int, str, list[str]]] = []
    for lineno, note in notes:
        if _note_has_escape(note):
            continue
        claims = find_claim_tokens(note)
        if not claims:
            continue
        unmatched = [c for c in claims if not any(_claim_covered_by_test(s, c) for s in pair_srcs)]
        if unmatched:
            offenders.append((lineno, note, unmatched))
    return offenders


def _r_notes_match_emitted_behaviour() -> tuple[bool, str]:
    """B0.13 — every claim in ``notes`` must have paired honesty evidence
    OR an escape phrase OR a waiver entry."""
    if not ADAPT_ROOT.exists():
        return False, f"missing: {ADAPT_ROOT}"
    if not TESTS_ROOT.exists():
        return False, f"missing: {TESTS_ROOT}"

    offenders: list[tuple[str, Path, list[tuple[int, str, list[str]]]]] = []
    for init in sorted(ADAPT_ROOT.rglob("__init__.py")):
        tool_key = _tool_key_for_init(init, ADAPT_ROOT)
        if not tool_key:
            continue
        if tool_key in _WAIVED_TOOLS:
            continue
        result = _audit_tool_init(init, tool_key, TESTS_ROOT)
        if result:
            offenders.append((tool_key, init, result))

    if not offenders:
        return True, (
            f"{len(_WAIVED_TOOLS)} tool(s) waived; all other notes "
            "claims either carry escape phrases or are covered by "
            "paired honesty tests"
        )

    lines: list[str] = [
        f"{len(offenders)} tool(s) ship `ToolResult(notes=…)` claims "
        "without paired honesty evidence and without escape language "
        "(see CONTRACT §B0.13 / audit cluster P4):",
    ]
    rel_root = SKILL_ROOT.parent.parent
    for tool_key, init_path, items in offenders:
        try:
            rel = init_path.relative_to(rel_root)
        except ValueError:
            rel = init_path
        for lineno, note, claims in items:
            preview = note if len(note) <= 80 else note[:77] + "…"
            lines.append(
                f"  {rel}:{lineno}  claim(s)={claims!r}  note={preview!r}"
            )
    lines.append(
        "Fix by EITHER (a) adding an engine-level pair test at "
        "`engine/tests/test_<tool>_notes_invariants.py` OR "
        "`engine/tests/test_<tool>_emitted.py` with `def test_*` whose "
        "name or docstring references the claim token, OR (b) "
        "qualifying the notes line with an escape phrase "
        "(\"only when\" / \"requires manual\" / \"see next_steps\" / "
        "\"⚠\"), OR (c) adding the tool key to `_WAIVED_TOOLS` in "
        "`r_notes_match_behaviour.py` with an inline citation."
    )
    return False, "\n".join(lines)
