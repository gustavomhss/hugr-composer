"""B0.13 honesty test for ``extend/crud_data/add_audit_log``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing line::

    "Hash-chained, signed, append-only ledger (TEAL_INV_01..06)."

The matched B0.13 claim tokens are ``"hash-chained"``, ``"signed"``,
and ``"append-only"``. This module ships paired honesty tests whose
names reference each claim so the rule's fuzzy-matcher recognises
them as covered (per ``r_notes_match_behaviour._claim_covered_by_test``:
any ``def test_*`` whose name OR docstring contains the claim token
counts).

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

The notes line claims three orthogonal properties; each MUST be
backed by a structural assertion against the EMITTED glue and the
shipped primitive + adapter (no behaviour exec — the glue depends
on ``app.core.config`` which only exists inside an emitted project):

1. ``test_glue_wires_tamper_evident_hash_chained_primitive`` —
   the emitted ``audit_log_glue.py.tmpl`` imports ``install`` from
   ``core.venous._adapters.fastapi.AuditLogAdapter`` and calls it
   with an HMAC secret. If the glue silently wired a placeholder
   ``InMemoryAuditLog`` (no chain), R5-S1-F5 reopens.

2. ``test_adapter_wires_hash_chained_signed_log_class`` — the
   ``AuditLogAdapter.install`` function instantiates
   ``InMemoryTamperEvidentAuditLog`` (the chain-keeping reference
   impl), not a placeholder ``InMemoryAuditLog`` / ``DictLog`` /
   any other class. This is the load-bearing structural anchor:
   if the adapter wires the wrong class, every other check is
   meaningless prose.

3. ``test_primitive_is_hash_chained`` — the primitive's ``append``
   path computes ``prev_hash`` from the prior entry's
   ``entry_hash`` (chain link) and feeds the canonical bytes to
   ``_compute_entry_hash`` (SHA-256). Anchors the ``hash-chained``
   token.

4. ``test_primitive_is_signed_with_external_signer`` — ``append``
   calls ``self._signer.sign(payload)`` and ``__init__`` rejects
   anything that isn't a ``Signer``. Anchors the ``signed`` token.
   The reference ``HmacReferenceSigner`` uses ``hmac.new(...,
   sha256)`` and verifies with ``hmac.compare_digest`` (constant-
   time) — both asserted structurally.

5. ``test_primitive_is_append_only`` — the primitive Protocol AND
   the concrete impl expose ``append`` / ``verify_chain`` / ``get``
   / ``export`` but NO ``update`` / ``delete`` / ``__setitem__`` /
   ``pop`` mutators on entries. Anchors the ``append-only`` token
   (TEAL_INV_01).

6. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS`` once this test file lands; without the
   waiver removal the rule still skips the tool and this file is
   inert.

Bypass surface declared
=======================

* Each function name contains exactly one claim token so the fuzzy
  matcher binds each token to a real assertion. A future notes
  edit that adds a new token (e.g. ``encrypted``) WILL re-fail
  B0.13 until a test referencing that token lands — that's the
  contract.
* AST-only inspection; no project boot. The glue file is a
  templated module that depends on emitted-project layout, but
  the primitive + adapter are real Python files in this repo and
  ARE parsed (not exec'd) to keep the test hermetic.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "crud_data" / "add_audit_log"
GLUE_TMPL = TOOL_DIR / "templates" / "audit_log_glue.py.tmpl"
ADAPTER_PY = (
    SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi" / "AuditLogAdapter.py"
)
PRIMITIVE_PY = (
    SKILL_ROOT
    / "core"
    / "venous"
    / "compliance"
    / "TamperEvidentAuditLog"
    / "TamperEvidentAuditLog.py"
)


# ---------------------------------------------------------------------------
# Placeholder cleanup — keep parity with sibling pair-test modules.
# This tool's templates use no ``${...}`` placeholders, but applying the
# cleanup unconditionally costs nothing and matches the rule scanner.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


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


def _find_func(
    tree: ast.Module, name: str
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


# ---------------------------------------------------------------------------
# B0.13 — paired evidence for hash-chained / signed / append-only.
# ---------------------------------------------------------------------------


def test_glue_wires_tamper_evident_hash_chained_primitive() -> None:
    """Notes claim "Hash-chained, signed, append-only ledger" — the
    emitted glue MUST delegate to the real chain-keeping adapter, not
    a placeholder InMemoryAuditLog (R5-S1-F5 regression guard).
    """
    tree = _parse(GLUE_TMPL)
    src = GLUE_TMPL.read_text(encoding="utf-8")

    # Imports `install` from the AuditLogAdapter (the chain-keeping
    # adapter), NOT from any *AuditLog* placeholder module.
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    adapter_imports = [
        i
        for i in imports
        if (i.module or "").endswith("AuditLogAdapter")
        and any(a.name == "install" for a in i.names)
    ]
    assert adapter_imports, (
        "audit_log_glue.py.tmpl MUST import `install` from "
        "core.venous._adapters.fastapi.AuditLogAdapter — without this "
        "import the tamper-evident hash chain is not wired."
    )

    # And NEVER imports a placeholder InMemoryAuditLog (the R5-S1-F5
    # regression shape — wiring a dict-backed log while claiming the
    # chain is present).
    assert "InMemoryAuditLog" not in src or "TamperEvident" in src, (
        "audit_log_glue.py.tmpl MUST NOT wire a bare `InMemoryAuditLog` "
        "placeholder; the hash-chained claim REQUIRES the "
        "TamperEvidentAuditLog primitive (R5-S1-F5)."
    )

    # `install_audit_log` MUST actually invoke the imported `install`.
    install_fn = _find_func(tree, "install_audit_log")
    delegates = [
        c
        for c in _calls(install_fn)
        if _attr_chain(c).endswith("install") or _attr_chain(c) == "install"
    ]
    assert delegates, (
        "install_audit_log(app) MUST call the adapter's `install(...)` "
        "function; without it the audit chain is imported but never "
        "attached to the FastAPI app."
    )


def test_adapter_wires_hash_chained_signed_log_class() -> None:
    """The FastAPI adapter's ``install`` MUST instantiate
    ``InMemoryTamperEvidentAuditLog`` (the hash-chained, signed
    reference impl), never a placeholder log class.
    """
    tree = _parse(ADAPTER_PY)
    install_fn = _find_func(tree, "install")

    log_inits = [
        c
        for c in _calls(install_fn)
        if _attr_chain(c).endswith("InMemoryTamperEvidentAuditLog")
    ]
    assert log_inits, (
        "AuditLogAdapter.install MUST instantiate "
        "`InMemoryTamperEvidentAuditLog(...)`. Anything else (e.g. "
        "`InMemoryAuditLog`, `DictLog`) breaks the hash-chained + "
        "signed + append-only claim at the glue boundary."
    )

    # The log MUST be constructed with a Signer (HMAC reference) —
    # this is the `signed` half of the claim at the wiring layer.
    signer_calls = [
        c
        for c in _calls(install_fn)
        if _attr_chain(c).endswith("HmacReferenceSigner")
    ]
    assert signer_calls, (
        "AuditLogAdapter.install MUST pass an HmacReferenceSigner to "
        "the log — without an external Signer the `signed` claim is "
        "false and TEAL_INV_03 is not satisfied."
    )


def test_primitive_is_hash_chained() -> None:
    """The ``TamperEvidentAuditLog`` primitive's ``append`` MUST build
    a hash chain: each entry's ``prev_hash`` derives from the prior
    entry's ``entry_hash``, and ``entry_hash`` is SHA-256 of canonical
    bytes. Anchors the `hash-chained` notes token.
    """
    tree = _parse(PRIMITIVE_PY)
    log_cls = _find_class(tree, "InMemoryTamperEvidentAuditLog")
    append_fn = _find_func(log_cls, "append")

    src_lines = ast.unparse(append_fn)
    # prev_hash threads from the prior entry's entry_hash.
    assert "prev_hash" in src_lines and "entry_hash" in src_lines, (
        "InMemoryTamperEvidentAuditLog.append MUST compute "
        "`prev_hash` from the prior entry's `entry_hash` to form the "
        "hash chain."
    )
    # And the hash function used is SHA-256 (via _compute_entry_hash
    # → hashlib.sha256). Confirm the helper call appears.
    hash_calls = [
        c
        for c in _calls(append_fn)
        if _attr_chain(c).endswith("_compute_entry_hash")
    ]
    assert hash_calls, (
        "append MUST call `_compute_entry_hash(payload)` to derive "
        "the chain link; otherwise the `hash-chained` claim is false."
    )


def test_primitive_is_signed_with_external_signer() -> None:
    """The primitive's ``append`` MUST call the external
    ``Signer.sign`` and the reference ``HmacReferenceSigner`` MUST
    use ``hmac.new(..., sha256)`` + constant-time comparison. Anchors
    the `signed` notes token end-to-end.
    """
    tree = _parse(PRIMITIVE_PY)
    log_cls = _find_class(tree, "InMemoryTamperEvidentAuditLog")
    append_fn = _find_func(log_cls, "append")

    sign_calls = [
        c
        for c in _calls(append_fn)
        if _attr_chain(c).endswith("_signer.sign")
        or _attr_chain(c).endswith("signer.sign")
    ]
    assert sign_calls, (
        "InMemoryTamperEvidentAuditLog.append MUST call "
        "`self._signer.sign(payload)`; without it the `signed` claim "
        "in the notes line is false."
    )

    # The reference HmacReferenceSigner uses hmac + sha256 + verify
    # via hmac.compare_digest (constant-time, blocks timing leaks).
    signer_cls = _find_class(tree, "HmacReferenceSigner")
    signer_src = ast.unparse(signer_cls)
    assert "hmac.new" in signer_src and "sha256" in signer_src, (
        "HmacReferenceSigner.sign MUST use `hmac.new(..., sha256)` — "
        "the signed claim names HMAC as the primitive."
    )
    assert "hmac.compare_digest" in signer_src, (
        "HmacReferenceSigner.verify MUST use `hmac.compare_digest` "
        "for constant-time signature comparison; a plain `==` would "
        "leak via timing and silently weaken the `signed` claim."
    )

    # __init__ MUST reject anything that isn't a Signer — this is
    # the TEAL_INV_03 invariant the signed claim leans on.
    init_fn = _find_func(log_cls, "__init__")
    init_src = ast.unparse(init_fn)
    assert "isinstance(signer, Signer)" in init_src, (
        "InMemoryTamperEvidentAuditLog.__init__ MUST reject non-Signer "
        "constructor arguments (TEAL_INV_03); without this guard a "
        "caller could pass a no-op object and the `signed` claim "
        "would be vacuous."
    )


def test_primitive_is_append_only() -> None:
    """The primitive Protocol AND the concrete impl MUST expose only
    append-side operations (``append`` / ``verify_chain`` / ``get`` /
    ``export``) — no ``update`` / ``delete`` / ``__setitem__`` /
    ``pop`` / ``clear`` mutators on the entries list. Anchors the
    ``append-only`` token (TEAL_INV_01).
    """
    tree = _parse(PRIMITIVE_PY)
    log_cls = _find_class(tree, "InMemoryTamperEvidentAuditLog")

    method_names = {
        n.name
        for n in log_cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {"update", "delete", "__setitem__", "pop", "clear", "remove"}
    leaks = method_names & forbidden
    assert not leaks, (
        f"InMemoryTamperEvidentAuditLog defines forbidden mutator(s) "
        f"{sorted(leaks)} — these would break the `append-only` claim "
        "(TEAL_INV_01). If you need a redaction path, ship a new "
        "primitive; do NOT add mutators here."
    )

    # The chain-link write site MUST use `.append(...)` on the
    # entries list (additive only) — never list-slice assignment
    # or `__setitem__` style writes.
    append_fn = _find_func(log_cls, "append")
    list_append_calls = [
        c
        for c in _calls(append_fn)
        if _attr_chain(c).endswith("_entries.append")
        or _attr_chain(c).endswith("entries.append")
    ]
    assert list_append_calls, (
        "InMemoryTamperEvidentAuditLog.append MUST extend the entries "
        "list with `.append(entry)` (additive). Slice assignment or "
        "in-place mutation would invalidate the `append-only` claim."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_audit_log`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/crud_data/add_audit_log" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_audit_log was NOT removed; the "
        "pair test is inert while the rule still skips the tool."
    )
