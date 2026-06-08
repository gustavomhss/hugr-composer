"""B0.13 honesty test for ``extend/auth_access/add_mfa``.

The ``ToolResult(notes=…)`` shipped by ``add_mfa`` carries two claim-bearing
lines the B0.13 rule flags (claim tokens ``encrypted`` + ``single-use``):

    "Wrote app/models/mfa.py — MFADevice (Fernet-encrypted secret_enc) +
     MFARecoveryCode (single-use via used_at)."
    "Wrote app/crud/mfa.py — atomic single-use recovery-code consumption."

This module is the paired honesty evidence B0.13 requires. Every ``test_*``
name/docstring references the claim tokens (``encrypted`` / ``single_use``),
and the assertions are REAL: they parse the emitted templates (AST + content)
AND generate a project to assert the claims hold against the actually-emitted
files — not stubs.

What we actually assert
=======================

* ``test_totp_secret_encrypted_at_rest_fernet`` — the ``encrypted`` claim:
  ``MFADevice.secret_enc`` is a ``LargeBinary`` column (never a plaintext
  string), and the crypto helper wraps the secret with ``Fernet`` (so the
  bytes stored are ciphertext, not the raw TOTP secret).
* ``test_totp_secret_never_stored_plaintext`` — the ``encrypted`` claim's
  negative form: the model has NO ``secret`` / ``totp_secret`` plaintext
  ``String``/``Text`` column; the only secret column is the encrypted
  ``secret_enc`` LargeBinary.
* ``test_recovery_code_single_use_atomic`` — the ``single-use`` claim:
  ``consume_recovery_code`` issues a single ``UPDATE`` filtering
  ``used_at IS NULL`` and SETting ``used_at`` in the same statement, and only
  reports success when exactly one row was stamped (``rowcount == 1``) — so a
  code can be consumed exactly once even under a concurrent race.
* ``test_recovery_code_model_marks_used_at`` — the ``single-use`` claim's
  schema anchor: ``MFARecoveryCode`` carries a nullable ``used_at``
  ``DateTime`` column (NULL == still valid) that the consume path stamps.
* ``test_emitted_project_honours_encrypted_and_single_use`` — end-to-end:
  generate a project via ``add_mfa`` and assert the emitted (not template)
  ``app/models/mfa.py`` + ``app/crud/mfa.py`` carry the encrypted-at-rest and
  single-use shapes, so the notes claims cannot silently regress.

We deliberately do NOT import the templates as modules (they import
``app.core.config`` / ``app.models.base`` which only exist inside an emitted
project). Template-level assertions use AST/content parsing; the end-to-end
test exercises the real generator.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "auth_access" / "add_mfa"
MODEL_TMPL = TOOL_DIR / "templates" / "model.py.tmpl"
CRYPTO_TMPL = TOOL_DIR / "templates" / "crypto.py.tmpl"
CRUD_TMPL = TOOL_DIR / "templates" / "crud.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — symmetrical with the rule scanner.
# ---------------------------------------------------------------------------

_PLACEHOLDER_BRACED_RE = re.compile(r"\$\{[^}]+\}")
_PLACEHOLDER_BARE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _clean(src: str) -> str:
    src = _PLACEHOLDER_BRACED_RE.sub("PLACEHOLDER", src)
    src = _PLACEHOLDER_BARE_RE.sub("PLACEHOLDER", src)
    return src


def _parse_template(path: Path) -> ast.Module:
    return ast.parse(_clean(path.read_text(encoding="utf-8")))


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name}(...) not found in template")


def _find_func(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"def {name}(...) not found in template")


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


def _column_type_names(class_def: ast.ClassDef, attr: str) -> set[str]:
    """Return the SQLAlchemy column-type names referenced for ``attr``.

    Scans the ``attr: Mapped[...] = mapped_column(<Type>, ...)`` assignment and
    collects every type referenced in the RHS — both call forms
    (``LargeBinary()``) and bare-Name forms (``mapped_column(LargeBinary)``).
    """
    names: set[str] = set()
    for node in class_def.body:
        target_ok = False
        value: ast.AST | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_ok = node.target.id == attr
            value = node.value
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == attr for t in node.targets
        ):
            target_ok = True
            value = node.value
        if not target_ok or value is None:
            continue
        for sub in ast.walk(value):
            if isinstance(sub, ast.Call):
                chain = _attr_chain(sub)
                if chain:
                    names.add(chain.split(".")[-1])
            elif isinstance(sub, ast.Name):
                names.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.add(sub.attr)
    return names


# ---------------------------------------------------------------------------
# B0.13 — paired honesty evidence for the "encrypted" claim.
# ---------------------------------------------------------------------------


def test_totp_secret_encrypted_at_rest_fernet() -> None:
    """The notes claim ``"MFADevice (Fernet-encrypted secret_enc)"`` —
    the encrypted secret column is ``LargeBinary`` and the crypto helper
    wraps it with ``Fernet`` so stored bytes are ciphertext, not plaintext."""
    model = _parse_template(MODEL_TMPL)
    device = _find_class(model, "MFADevice")

    secret_types = _column_type_names(device, "secret_enc")
    assert "LargeBinary" in secret_types, (
        "MFADevice.secret_enc MUST be a LargeBinary column — the notes claim "
        "the TOTP secret is encrypted at rest (ciphertext bytes, not a "
        f"plaintext String). Found column types: {secret_types or '∅'}."
    )

    crypto = _parse_template(CRYPTO_TMPL)
    encrypt = _find_func(crypto, "encrypt_secret")
    fernet_chains = {_attr_chain(c).split(".")[-1] for c in _calls(encrypt)}
    assert "encrypt" in fernet_chains, (
        "encrypt_secret MUST call Fernet's `.encrypt(...)` — without it "
        "secret_enc would hold plaintext and the 'encrypted' claim is false."
    )
    src = CRYPTO_TMPL.read_text(encoding="utf-8")
    assert "Fernet" in src, (
        "crypto.py.tmpl MUST use Fernet — the notes claim Fernet encryption "
        "of the TOTP secret at rest."
    )


def test_totp_secret_never_stored_plaintext() -> None:
    """The ``encrypted`` claim's negative form: MFADevice has NO plaintext
    ``secret``/``totp_secret`` ``String``/``Text`` column — the only secret
    column is the encrypted ``secret_enc`` LargeBinary."""
    model = _parse_template(MODEL_TMPL)
    device = _find_class(model, "MFADevice")

    declared_attrs = {
        node.target.id
        for node in device.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    for forbidden in ("secret", "totp_secret", "secret_plain"):
        assert forbidden not in declared_attrs, (
            f"MFADevice MUST NOT declare a plaintext `{forbidden}` column — "
            "the 'encrypted' claim requires the secret to exist only as the "
            "Fernet-encrypted `secret_enc` LargeBinary."
        )
    assert "secret_enc" in declared_attrs, (
        "MFADevice MUST declare the encrypted `secret_enc` column."
    )


# ---------------------------------------------------------------------------
# B0.13 — paired honesty evidence for the "single-use" claim.
# ---------------------------------------------------------------------------


def test_recovery_code_single_use_atomic() -> None:
    """The notes claim ``"atomic single-use recovery-code consumption"`` —
    ``consume_recovery_code`` issues a single UPDATE filtering
    ``used_at IS NULL`` and SETting ``used_at`` in the same statement, and
    reports success only when exactly one row was stamped (rowcount == 1)."""
    crud = _parse_template(CRUD_TMPL)
    consume = _find_func(crud, "consume_recovery_code")

    call_tails = {_attr_chain(c).split(".")[-1] for c in _calls(consume)}
    assert "update" in call_tails or "where" in call_tails, (
        "consume_recovery_code MUST use a SQLAlchemy UPDATE ... WHERE — the "
        "single-use claim relies on an atomic conditional update, not a "
        "read-modify-write that races."
    )

    src = CRUD_TMPL.read_text(encoding="utf-8")
    # WHERE used_at IS NULL — only an un-consumed code is eligible.
    assert re.search(r"used_at\.is_\(\s*None\s*\)", src), (
        "consume_recovery_code MUST filter `used_at.is_(None)` — without it a "
        "previously-used code could be accepted again, breaking single-use."
    )
    # SET used_at = <now> — the same statement stamps consumption.
    assert re.search(r"\.values\(\s*used_at\s*=", src), (
        "consume_recovery_code MUST `.values(used_at=...)` in the same UPDATE "
        "— stamping atomically is what makes consumption exactly-once."
    )
    # rowcount == 1 — exactly one row may win the race.
    assert "rowcount == 1" in src, (
        "consume_recovery_code MUST return success only on `rowcount == 1` — "
        "this is how two concurrent requests racing the same code yield a "
        "single winner (atomic single-use)."
    )


def test_recovery_code_model_marks_used_at() -> None:
    """The ``single-use`` claim's schema anchor: ``MFARecoveryCode`` carries a
    nullable ``used_at`` ``DateTime`` column (NULL == still valid) the consume
    path stamps."""
    model = _parse_template(MODEL_TMPL)
    rc = _find_class(model, "MFARecoveryCode")

    used_at_types = _column_type_names(rc, "used_at")
    assert "DateTime" in used_at_types, (
        "MFARecoveryCode.used_at MUST be a DateTime column — the single-use "
        f"claim stamps it on consumption. Found: {used_at_types or '∅'}."
    )
    # used_at must be nullable: NULL means the code is still valid.
    src = MODEL_TMPL.read_text(encoding="utf-8")
    assert re.search(r"used_at[^\n]*nullable=True", src) or re.search(
        r"used_at:\s*Mapped\[datetime\s*\|\s*None\]", src
    ), (
        "MFARecoveryCode.used_at MUST be nullable (NULL == unused) — the "
        "consume path filters `used_at IS NULL` to enforce single-use."
    )


# ---------------------------------------------------------------------------
# B0.13 — end-to-end: claims hold against the EMITTED files, not just templates.
# ---------------------------------------------------------------------------


def test_emitted_project_honours_encrypted_and_single_use(tmp_path) -> None:
    """Generate a project via ``add_mfa`` and assert the EMITTED model + crud
    carry the encrypted-at-rest and single-use shapes — so the notes claims
    cannot silently regress at emission time."""
    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_mfa import add_mfa

    project = tmp_path / "proj"
    (project / "app").mkdir(parents=True)

    result = add_mfa(ToolInput(project_dir=str(project)))
    assert result.status == "success", f"add_mfa failed: {result.error}"

    model_text = (project / "app" / "models" / "mfa.py").read_text()
    # encrypted claim — secret column is encrypted LargeBinary, no plaintext.
    assert "secret_enc" in model_text and "LargeBinary" in model_text, (
        "emitted model must store the TOTP secret as encrypted LargeBinary "
        "(secret_enc) — the 'encrypted' notes claim."
    )
    assert not re.search(r"\n\s+secret:\s*Mapped\[", model_text), (
        "emitted model must NOT carry a plaintext `secret` column."
    )

    crud_text = (project / "app" / "crud" / "mfa.py").read_text()
    # single-use claim — atomic conditional update on used_at.
    assert re.search(r"used_at\.is_\(\s*None\s*\)", crud_text), (
        "emitted crud must filter `used_at.is_(None)` for single-use."
    )
    assert "rowcount == 1" in crud_text, (
        "emitted crud must gate success on `rowcount == 1` (atomic single-use)."
    )


def test_b0_13_waiver_absent() -> None:
    """add_mfa MUST NOT be waived for B0.13 — this pair test is the evidence."""
    from engine.audit.contract_rules.r_notes_match_behaviour import _WAIVED_TOOLS

    assert "extend/auth_access/add_mfa" not in _WAIVED_TOOLS, (
        "add_mfa must not be in B0.13 _WAIVED_TOOLS — the honesty claims are "
        "backed by this paired test, not a waiver."
    )
