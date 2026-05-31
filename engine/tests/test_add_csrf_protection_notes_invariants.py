"""B0.13 honesty test for ``extend/infrastructure/add_csrf_protection``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "GET /csrf/token endpoint issues a signed token for JS clients."

The matched B0.13 claim token is ``"signed"``. This module ships a
paired honesty test whose name references the claim so the rule's
fuzzy matcher recognises it as covered.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

The "signed token" claim collapses to one structural question: does
the emitted ``CSRFProtection`` class actually HMAC-sign the token
AND verify the signature with a constant-time comparison (not ``==``,
which leaks via timing)?

1. ``test_csrf_token_is_signed_with_hmac_sha256`` — the emitted
   ``csrf_core.py.tmpl`` defines ``CSRFProtection._sign`` that calls
   ``hmac.new(secret, payload, hashlib.sha256)``. Anchors the
   ``signed`` claim's "how" (HMAC-SHA256 named in the module
   docstring).

2. ``test_csrf_signed_token_verified_with_constant_time_compare`` —
   ``CSRFProtection.validate_token`` uses
   ``hmac.compare_digest(sig, expected_sig)``, NEVER ``sig ==
   expected_sig``. A naive ``==`` would let an attacker recover the
   signature byte-by-byte via timing and the "signed" claim would
   be silently undermined (CWE-208). This is the load-bearing
   assertion.

3. ``test_csrf_signed_token_rejects_tampered_sig`` — exec the
   template into a hermetic namespace, generate a token, mutate the
   signature byte, and assert ``validate_token`` returns ``False``.
   AST checks confirm the *shape*; this confirms the *behaviour* at
   the function boundary. Behavioural anchor for ``signed``.

4. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS`` once this test file lands.

Bypass surface declared
=======================

* The function names contain ``signed`` so the fuzzy matcher binds
  to the ``signed`` claim. A future note edit that adds a new
  claim token (``encrypted``, ``verified``, …) WILL re-fail B0.13
  until a referencing test lands.
* The behavioural test exec's the template directly (no project
  scaffold) — the template imports only ``starlette.responses``,
  which is available in the dev/CI env. If a future template edit
  adds an emitted-project-only import (e.g. ``app.core.config``),
  the exec test becomes brittle and must be downgraded to AST-only.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_csrf_protection"
CORE_TMPL = TOOL_DIR / "templates" / "csrf_core.py.tmpl"


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


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


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
# B0.13 — paired evidence for the ``signed`` claim.
# ---------------------------------------------------------------------------


def test_csrf_token_is_signed_with_hmac_sha256() -> None:
    """Notes claim "signed token" — ``CSRFProtection._sign`` MUST
    call ``hmac.new(secret, payload, hashlib.sha256)``. A
    placeholder ``hashlib.sha256(payload).hexdigest()`` would be
    unkeyed (no secret) and the "signed" claim would be false.
    """
    tree = _parse(CORE_TMPL)
    cls = _find_class(tree, "CSRFProtection")
    sign_fn = _find_func(cls, "_sign")

    hmac_new_calls = [
        c for c in _calls(sign_fn) if _attr_chain(c).endswith("hmac.new")
    ]
    assert hmac_new_calls, (
        "CSRFProtection._sign MUST call `hmac.new(secret, payload, "
        "hashlib.sha256)`; an unkeyed `hashlib.sha256(...)` would "
        "make the `signed` claim structurally false."
    )

    # And the call uses sha256 (not md5/sha1 — both broken for HMAC
    # in practice, and the module docstring promises sha256).
    src = ast.unparse(sign_fn)
    assert "sha256" in src, (
        "CSRFProtection._sign MUST use sha256; the module docstring "
        "and notes line both name HMAC-SHA256."
    )


def test_csrf_signed_token_verified_with_constant_time_compare() -> None:
    """Notes claim ``signed`` requires the verification path use
    constant-time comparison — a plain ``==`` would leak the signature
    byte-by-byte via timing (CWE-208) and the claim would be silently
    undermined. ``validate_token`` MUST call ``hmac.compare_digest``.
    """
    tree = _parse(CORE_TMPL)
    cls = _find_class(tree, "CSRFProtection")
    validate_fn = _find_func(cls, "validate_token")

    compare_calls = [
        c
        for c in _calls(validate_fn)
        if _attr_chain(c).endswith("hmac.compare_digest")
        or _attr_chain(c).endswith("compare_digest")
    ]
    assert compare_calls, (
        "CSRFProtection.validate_token MUST call `hmac.compare_digest"
        "(sig, expected_sig)`. Without constant-time comparison the "
        "`signed` claim is undermined by a timing oracle (CWE-208)."
    )

    # AND the validation path must NEVER use `sig == expected_sig` —
    # find Compare nodes between two Name targets that look like
    # signature/digest.
    for node in ast.walk(validate_fn):
        if not isinstance(node, ast.Compare):
            continue
        if any(isinstance(op, ast.Eq) for op in node.ops):
            srcline = ast.unparse(node)
            # The `len(parts) != 3` and `age > self.max_age` shape
            # checks are fine; only flag a `sig`-vs-`expected_sig`
            # equality.
            low = srcline.lower()
            if (
                ("sig" in low and "expected" in low)
                or ("signature" in low and "expected" in low)
            ):
                raise AssertionError(
                    f"CSRFProtection.validate_token MUST NOT compare "
                    f"signatures with `==` — use `hmac.compare_digest"
                    f"`. Offending expression: {srcline!r}"
                )


def test_csrf_signed_token_rejects_tampered_signature() -> None:
    """Behavioural anchor for ``signed``: exec the template in a
    hermetic namespace, generate a token, flip the signature byte,
    and confirm ``validate_token`` returns ``False``.

    This complements the AST checks above: shape can lie (a future
    edit could call ``hmac.compare_digest(x, x)`` and pass the
    structural test); behaviour cannot.
    """
    src = _clean(CORE_TMPL.read_text(encoding="utf-8"))
    ns: dict = {"__name__": "under_test_csrf_core"}
    exec(compile(src, str(CORE_TMPL), "exec"), ns)  # noqa: S102 — exec is the test
    CSRFProtection = ns["CSRFProtection"]

    protection = CSRFProtection(secret_key="x" * 32)
    token = protection.generate_token()
    assert protection.validate_token(token) is True, (
        "freshly generated CSRF token MUST validate; sanity check."
    )

    # Flip the last char of the signature segment.
    random_part, ts_str, sig = token.split(".")
    bad_sig_char = "0" if sig[-1] != "0" else "1"
    tampered = f"{random_part}.{ts_str}.{sig[:-1]}{bad_sig_char}"
    assert protection.validate_token(tampered) is False, (
        "validate_token MUST reject a token with a tampered signature "
        "— the `signed` claim REQUIRES forgery detection."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_csrf_protection`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_csrf_protection" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_csrf_protection was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
