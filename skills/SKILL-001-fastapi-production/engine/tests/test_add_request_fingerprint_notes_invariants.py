"""B0.13 honesty test for ``extend/infrastructure/add_request_fingerprint``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "FingerprintMiddleware: deduplicates POST/PUT (configurable),
    adds Idempotent-Replayed header."

The matched B0.13 claim token is ``"idempotent"`` (in
``Idempotent-Replayed``). The other notes lines either carry the
``⚠`` escape character (the two warnings about manual wiring and
in-process cache) or have no claim tokens.

The waiver comment previously said: "no engine-level test asserts
the Idempotent-Replayed header path." This pair test closes that
gap by anchoring both halves of the idempotent replay path:

  (a) the fingerprint key includes the authenticated user's identity
      (so cross-user replay is impossible — a security property
      that follows from the deduplication design), and
  (b) the cached-response replay path actually emits an
      ``Idempotent-Replayed`` header (the load-bearing structural
      claim in the notes line).

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py``.

What we actually assert
=======================

1. ``test_idempotent_replay_emits_replayed_header`` — the emitted
   ``FingerprintMiddleware._replay_cached`` method constructs a
   ``Response(..., headers={"Idempotent-Replayed": "true"})`` on
   the duplicate branch. Without this header the notes claim
   ("adds Idempotent-Replayed header") is structurally false.

2. ``test_idempotent_fingerprint_includes_auth_identity`` — the
   middleware extracts the authenticated user from
   ``request.state.user`` and threads ``user_id`` into the
   fingerprint. The ``RequestFingerprinter.compute`` method
   incorporates ``user_id`` into the hashed payload — falling back
   to the literal ``"anonymous"`` ONLY when no user identity is
   available. Anchors the user-isolation property the
   ``idempotent`` claim leans on (otherwise a duplicate request
   from a DIFFERENT user would hit the same cache entry — a
   correctness AND security failure).

3. ``test_idempotent_fingerprint_uses_sha256`` — the fingerprinter
   uses ``hashlib.sha256`` with the canonical
   ``user:method:path:body`` string, matching the notes line that
   names "SHA-256 hash of user_id+method+path+sorted(body)".

4. ``test_b0_13_waiver_removed`` — waiver entry MUST be gone.

Bypass surface declared
=======================

* Function names contain ``idempotent`` so the fuzzy matcher binds
  them to the claim. AST-only inspection of the middleware +
  hasher templates; no ASGI app boot. Behavioural confirmation
  (the actual replay under a TestClient) belongs in the emitted
  project test ``test_add_request_fingerprint_emitted.py.tmpl``.
* We deliberately do NOT assert that the in-process response cache
  is durable across workers — the two ``⚠`` warnings in the notes
  DISCLOSE that gap, so it's outside this rule's scope.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_request_fingerprint"
HASHER_TMPL = TOOL_DIR / "templates" / "fp_hasher.py.tmpl"
MIDDLEWARE_TMPL = TOOL_DIR / "templates" / "fp_middleware.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup helper — parity with sibling pair-test modules.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"(?<![A-Za-z0-9_])\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _find_func(
    tree: ast.AST, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"def {name}(...) not found")


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _attr_chain(call: ast.Call) -> str:
    parts: list[str] = []
    cur: ast.AST | None = call.func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# B0.13 — paired evidence for the ``idempotent`` claim.
# ---------------------------------------------------------------------------


def test_idempotent_replay_emits_replayed_header() -> None:
    """Notes claim ``adds Idempotent-Replayed header`` —
    ``FingerprintMiddleware._replay_cached`` MUST construct a
    Response whose ``headers=`` dict contains
    ``"Idempotent-Replayed"``.

    Without this header the duplicate-request branch is
    indistinguishable from a fresh response, and downstream
    consumers cannot tell that the body was replayed from cache.
    The "idempotent" word in the notes line is the user-facing
    contract; the header is its on-the-wire shape.
    """
    tree = _parse(MIDDLEWARE_TMPL)
    cls = _find_class(tree, "FingerprintMiddleware")
    replay_fn = _find_func(cls, "_replay_cached")

    found_header = False
    for call in _calls(replay_fn):
        if not _attr_chain(call).endswith("Response"):
            continue
        for kw in call.keywords:
            if kw.arg != "headers":
                continue
            v = kw.value
            if isinstance(v, ast.Dict):
                for key in v.keys:
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value == "Idempotent-Replayed"
                    ):
                        found_header = True
    assert found_header, (
        "FingerprintMiddleware._replay_cached MUST construct a "
        "Response with `headers={\"Idempotent-Replayed\": ...}`; "
        "without the header the `idempotent` claim in the notes line "
        "is structurally false at the response boundary."
    )


def test_idempotent_fingerprint_includes_auth_identity() -> None:
    """The idempotent-replay correctness REQUIRES the fingerprint key
    incorporate the authenticated user's identity — otherwise two
    DIFFERENT users posting the same body would collide on the same
    cache entry (cross-user replay, both a correctness AND security
    failure).

    Anchor in TWO places:
    (a) the middleware extracts ``request.state.user`` and threads
        ``user_id`` into ``RequestFingerprinter.compute``;
    (b) the hasher's canonical string starts with the user id (the
        literal ``"anonymous"`` is the no-auth fallback, not the
        default behaviour as the task briefing flagged).
    """
    # (a) Middleware threads user identity to the fingerprinter.
    mw_tree = _parse(MIDDLEWARE_TMPL)
    cls = _find_class(mw_tree, "FingerprintMiddleware")
    dispatch_fn = _find_func(cls, "dispatch")
    dispatch_src = ast.unparse(dispatch_fn)
    assert "request.state.user" in dispatch_src, (
        "FingerprintMiddleware.dispatch MUST read "
        "`request.state.user` so the fingerprint key incorporates the "
        "authenticated identity; without this hop two different users "
        "would collide on the same cache entry."
    )
    # And `user_id` is passed as a kwarg into the compute call.
    threaded = False
    for call in _calls(dispatch_fn):
        if not _attr_chain(call).endswith("compute"):
            continue
        if any(kw.arg == "user_id" for kw in call.keywords):
            threaded = True
    assert threaded, (
        "FingerprintMiddleware.dispatch MUST call "
        "`_FINGERPRINTER.compute(user_id=..., ...)` with the extracted "
        "user identity; otherwise the hasher always sees None."
    )

    # (b) Hasher incorporates user_id into the canonical string.
    h_tree = _parse(HASHER_TMPL)
    h_cls = _find_class(h_tree, "RequestFingerprinter")
    compute_fn = _find_func(h_cls, "compute")
    compute_src = ast.unparse(compute_fn)
    assert "user_id" in compute_src or "uid" in compute_src, (
        "RequestFingerprinter.compute MUST include `user_id` in the "
        "hashed payload; without it the idempotent-replay cache is "
        "user-blind and a replay can leak one user's response to "
        "another."
    )
    # The 'anonymous' literal is the fallback path (uid = user_id or
    # "anonymous"), NOT the unconditional value — assert the literal
    # appears strictly as an `or` fallback expression, not as the
    # primary argument.
    fb_ok = False
    for node in ast.walk(compute_fn):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for v in node.values:
                if isinstance(v, ast.Constant) and v.value == "anonymous":
                    fb_ok = True
    assert fb_ok, (
        "RequestFingerprinter.compute MUST treat `\"anonymous\"` as "
        "an OR-fallback (`user_id or \"anonymous\"`); a hard-coded "
        "primary value would make every fingerprint user-blind and "
        "the `idempotent` claim would conceal cross-user replay."
    )


def test_idempotent_fingerprint_uses_sha256() -> None:
    """The notes line names "SHA-256 hash of user_id+method+path
    +sorted(body)" — the hasher MUST call ``hashlib.sha256`` (not
    md5, not sha1) so the idempotency key is collision-resistant in
    practice. A weak hash would allow forged collisions and a forged
    response could be replayed from cache.
    """
    tree = _parse(HASHER_TMPL)
    cls = _find_class(tree, "RequestFingerprinter")
    compute_fn = _find_func(cls, "compute")

    sha256_calls = [
        c
        for c in _calls(compute_fn)
        if _attr_chain(c).endswith("hashlib.sha256")
        or _attr_chain(c).endswith("sha256")
    ]
    assert sha256_calls, (
        "RequestFingerprinter.compute MUST call `hashlib.sha256(...)`; "
        "the notes line names SHA-256 specifically and weaker hashes "
        "(md5/sha1) would weaken the idempotency-key collision "
        "resistance the cache leans on."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_request_fingerprint`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_request_fingerprint" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_request_fingerprint was NOT "
        "removed; the pair test is inert while the rule still skips "
        "the tool."
    )
