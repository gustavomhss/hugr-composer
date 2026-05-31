"""B0.13 honesty test for ``extend/crud_data/add_file_upload``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The pre-fix
notes line was unconditional:

    "MIME validation uses magic bytes — never trusts Content-Type
     header or extension."

The rule's ``"never trusts"`` claim token was matched but R5-S1-F6
documented the claim is TRUE for ``LocalStorage`` (``upload_file_local``
calls ``validate_file`` on ``UploadFile.file`` via libmagic) and FALSE
for the S3 presign-confirm path (``confirm_upload`` only calls
``s3.head_object`` — the bytes uploaded directly to S3 via the
presigned URL are never fetched and re-validated).

The fix in this PR is option (b) from the briefing — qualify the
claim honestly + add a ``warnings=`` disclosure for the S3-confirm
gap. Closing via option (a) (real S3-confirm-side magic-byte fetch)
needed > 40 LOC of S3 plumbing and was explicitly de-prioritised in
the briefing: false marketing is the bug; toning down the claim
plus structurally anchoring the qualified shape is what this PR
ships.

What we actually assert
=======================

* ``test_local_upload_path_never_trusts_content_type`` — the
  ``upload_file_local`` route in ``file_routes.py.tmpl`` calls
  ``validate_file(file.file, ...)``. The token ``"never trusts"``
  appears in the test name so B0.13's fuzzy matcher recognises
  this as paired evidence for the (now qualified) claim.
* ``test_validate_file_uses_libmagic_magic_byte_detection`` —
  ``file_validator.py.tmpl::detect_mime`` calls
  ``magic.from_buffer(head, mime=True)`` and reads ``_HEAD_BYTES``
  (the magic-byte half of the qualified claim). Anchors the
  primitive the notes line names by name.
* ``test_s3_confirm_only_reads_metadata_not_object_bytes`` — anchors
  the S3-gap half of the disclosure. The ``confirm_upload`` route
  MUST call ``s3.head_object(...)`` and MUST NOT call
  ``get_object`` / ``download_fileobj`` (the boto3 entry points
  that would let the route re-validate bytes). The moment a future
  PR adds the GetObject + libmagic re-check, this test FAILS and
  the operator must remove the ⚠ warning from the notes line.

We deliberately do NOT execute the templates (they import
``app.core.config`` / ``app.crud._file`` which do not exist outside
an emitted project). AST inspection is sufficient per the rule's
documented honesty-test contract.

Bypass surface declared (per WP-16 §13)
=======================================

* The notes line carries ``"⚠"`` so the rule's escape gate exempts
  it from requiring evidence; the pair test is the *belt-and-braces*
  half — it locks the qualified shape into the template so the
  disclosure cannot silently desync.
* The S3-gap assertion uses substring-grade matching against the
  ``confirm_upload`` AST. A future S3 plumbing change that fetches
  bytes via an indirect helper (e.g. a wrapper that itself calls
  ``get_object``) will not be caught by name alone; the test fails
  loudly when the direct call lands, which is the boundary the rule
  was designed to police.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = (
    SKILL_ROOT
    / "adapt"
    / "extend"
    / "crud_data"
    / "add_file_upload"
)
TEMPLATES_DIR = TOOL_DIR / "templates"
ROUTES_TMPL = TEMPLATES_DIR / "file_routes.py.tmpl"
VALIDATOR_TMPL = TEMPLATES_DIR / "file_validator.py.tmpl"


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


def _find_func(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
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


# ---------------------------------------------------------------------------
# B0.13 — paired honesty evidence
# ---------------------------------------------------------------------------


def test_local_upload_path_never_trusts_content_type() -> None:
    """The LocalStorage half of the qualified claim is structural:
    ``upload_file_local`` calls ``validate_file(file.file, ...)`` —
    the libmagic-driven validator — before persisting the row.

    The test name carries ``"never trusts"`` so B0.13's fuzzy matcher
    treats this file as paired evidence for the now-qualified
    "never trusts Content-Type" claim.
    """
    tree = _parse_template(ROUTES_TMPL)
    handler = _find_func(tree, "upload_file_local")

    validator_calls = [
        c for c in _calls(handler)
        if _attr_chain(c).endswith("validate_file")
    ]
    assert validator_calls, (
        "`upload_file_local` MUST call `validate_file(...)` — without it "
        "the magic-byte half of the qualified claim is structurally false."
    )

    # validate_file MUST receive the UploadFile.file stream (the bytes
    # we are about to persist), not the client-declared content_type
    # alone. The first positional arg must be a `file.*` attribute.
    call = validator_calls[0]
    assert len(call.args) >= 1, (
        "validate_file(...) MUST receive the upload stream as its first "
        "positional arg — the client-declared content_type is informational."
    )
    first = call.args[0]
    assert isinstance(first, ast.Attribute) and first.attr == "file", (
        "validate_file(...) first positional MUST be `file.file` (the "
        "actual bytes stream); passing `file.content_type` would invert "
        "the claim by trusting the client header."
    )


def test_validate_file_uses_libmagic_magic_byte_detection() -> None:
    """Anchor the "magic bytes" half: ``file_validator.detect_mime``
    calls ``magic.from_buffer(head, mime=True)`` after reading
    ``_HEAD_BYTES`` from the stream.

    If a future PR swaps libmagic for an extension-sniffer, this
    test fails and the notes line MUST drop "magic bytes".
    """
    tree = _parse_template(VALIDATOR_TMPL)
    detect_mime = _find_func(tree, "detect_mime")

    magic_calls = [
        c for c in _calls(detect_mime)
        if _attr_chain(c).endswith("magic.from_buffer")
        or _attr_chain(c).endswith("from_buffer")
    ]
    assert magic_calls, (
        "`detect_mime` MUST call `magic.from_buffer(...)` — the libmagic "
        "byte-signature path is the entire point of the qualified claim."
    )

    # mime=True keyword MUST be present so the return is a MIME string,
    # not a free-form description.
    call = magic_calls[0]
    has_mime_kw = any(
        kw.arg == "mime"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in call.keywords
    )
    assert has_mime_kw, (
        "magic.from_buffer(...) MUST be called with `mime=True` — without "
        "it the return is a libmagic description string, not a MIME, and "
        "the SAFE_DEFAULTS allow-list check downstream becomes meaningless."
    )


def test_s3_confirm_only_reads_metadata_not_object_bytes() -> None:
    """Anchor the S3-gap half of the warning.

    ``confirm_upload`` MUST call ``s3.head_object(...)`` and MUST NOT
    call ``s3.get_object`` / ``download_fileobj`` (the boto3 entries
    that would re-fetch bytes and let the route re-run libmagic).

    If a future PR adds the GetObject + libmagic re-check, this test
    FAILS — at which point the ⚠ warning in the notes/warnings block
    becomes inaccurate and the operator must remove it before merge.
    """
    tree = _parse_template(ROUTES_TMPL)
    handler = _find_func(tree, "confirm_upload")

    head_calls = [
        c for c in _calls(handler) if _attr_chain(c).endswith("head_object")
    ]
    assert head_calls, (
        "`confirm_upload` MUST call `s3.head_object(...)` — the "
        "metadata-only check is the current (gap-disclosed) behaviour."
    )

    forbidden = ("get_object", "download_fileobj", "download_file")
    for c in _calls(handler):
        name = _attr_chain(c).split(".")[-1]
        assert name not in forbidden, (
            f"`confirm_upload` calls `{name}` — bytes are being re-fetched. "
            "If this is intentional (real magic-byte re-validation on S3 "
            "path), remove the ⚠ warning from the notes/warnings block "
            "AND replace this assertion with a positive shape check that "
            "confirms `validate_file` is called on the fetched bytes."
        )


def test_s3_path_presigned_url_workflow_is_signed_by_boto3() -> None:
    """The notes claim "Files are never proxied through the server on the
    S3 path (presigned URL workflow)" matches B0.13's ``"signed"`` token
    (substring of "presigned"). Anchor the claim by asserting that
    ``presigned_urls.py.tmpl`` invokes boto3's signing entry points
    rather than ``upload_fileobj`` / ``download_fileobj`` (which would
    proxy bytes through the server process).

    The test name carries ``"signed"`` so B0.13's fuzzy matcher
    recognises this as paired evidence for the presigned-URL claim.
    """
    presigned_tmpl = TEMPLATES_DIR / "presigned_urls.py.tmpl"
    tree = _parse_template(presigned_tmpl)

    # At least one call to S3's `generate_presigned_url(...)` or
    # `generate_presigned_post(...)` — the boto3 entries that sign
    # the URL via AWS Sigv4 without ever touching the bytes.
    signing_calls = [
        c for c in _calls(tree)
        if _attr_chain(c).endswith("generate_presigned_url")
        or _attr_chain(c).endswith("generate_presigned_post")
    ]
    assert signing_calls, (
        "presigned_urls.py.tmpl MUST call `generate_presigned_url(...)` "
        "or `generate_presigned_post(...)` — these are the boto3 entries "
        "that sign the upload URL via AWS Sigv4 without proxying bytes "
        "through the server. Without them the `presigned URL workflow` "
        "claim is structurally false."
    )

    # Negative anchor: byte-proxy paths must NOT be wired here. If they
    # land, the "never proxied" half of the claim becomes a lie.
    forbidden = ("upload_fileobj", "download_fileobj", "upload_file", "download_file")
    for c in _calls(tree):
        name = _attr_chain(c).split(".")[-1]
        assert name not in forbidden, (
            f"presigned_urls.py.tmpl calls `{name}` — this proxies bytes "
            "through the API process and breaks the `never proxied` half "
            "of the notes claim. Re-route through generate_presigned_*."
        )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry MUST be removed from ``_WAIVED_TOOLS``."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/crud_data/add_file_upload" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_file_upload was NOT removed; "
        "the pair test is meaningless if the rule still skips the tool."
    )
