"""B0.13 honesty test for ``extend/infrastructure/add_s3_storage``.

Closes the B0.13 ``_WAIVED_TOOLS`` entry for this tool. The tool's
``ToolResult(notes=…)`` carries the claim-bearing lines::

    "POST /storage/upload (presigned PUT URL), GET /storage/{key}
     (presigned GET URL), …"
    "Files go directly to S3/MinIO via presigned URLs — the API never
     buffers binary data."

The matched B0.13 claim token is ``"signed"`` (substring of
"presigned"). The honest reading: the emitted ``S3Client`` MUST
generate the URLs via ``boto3.client.generate_presigned_url`` (the
SDK call that actually constructs an HMAC-SHA256-signed query string
per AWS Signature V4) AND the HTTP routes MUST hand back those URLs
without proxying the binary payload through the API process.

A future edit that returned an unsigned bucket URL, or that streamed
the file through FastAPI before re-uploading to S3, would silently
break the "presigned" claim AND the "API never buffers binary data"
discipline.

Pair test path: ``engine/tests/test_<tool>_notes_invariants.py`` —
matches ``_PAIR_TEST_PATTERNS[0]``.

What we actually assert
=======================

1. ``test_s3_signed_upload_url_calls_boto_generate_presigned_url`` —
   ``S3Client.presigned_upload_url`` MUST call
   ``self._client.generate_presigned_url("put_object", ...)``. This
   is the boto3 entry point that performs AWS Signature V4 HMAC
   signing; without it the returned URL is unsigned and the
   "presigned" claim is structurally false.

2. ``test_s3_signed_download_url_calls_boto_generate_presigned_url``
   — same for ``presigned_download_url`` against ``"get_object"``.
   Symmetric assertion — the download path is the other half of the
   "presigned URL workflow".

3. ``test_s3_signed_upload_route_delegates_to_presigned_url`` — the
   ``POST /storage/upload`` route MUST call
   ``client.presigned_upload_url(...)`` and return its result. A
   route that called ``upload_fileobj`` (proxied upload through the
   API) would pass an import-presence check but break the "never
   buffers binary data" promise.

4. ``test_s3_signed_routes_do_not_proxy_via_upload_fileobj`` — none
   of the route handlers may call ``upload_fileobj`` or
   ``download_file`` / ``download_fileobj``; those are the boto3
   methods that *would* stream bytes through the API process. The
   absence is structurally load-bearing for the
   "API never buffers binary data" half of the claim.

5. ``test_b0_13_waiver_removed`` — the waiver entry MUST be gone
   from ``_WAIVED_TOOLS``.

Bypass surface declared
=======================

* AST-only inspection of ``client.py.tmpl`` + ``routes.py.tmpl``.
  No boto3 invocation, no AWS network calls.
* The SDK itself is trusted to implement Sigv4 correctly; we assert
  the call exists with the right ``ClientMethod`` argument
  (``"put_object"`` / ``"get_object"``), not the signature algorithm.
* The waiver comment also mentioned "quota enforcement"; that is NOT
  in the notes line and is therefore NOT a B0.13 claim against this
  tool — quota lives in ``add_file_upload``'s ``upload_quota.py``
  template, not here.
* SSE (server-side encryption) is intentionally out of scope: the
  tool's own ``warnings=`` line discloses "server-side encryption
  (SSE) is NOT enforced; configure bucket-level SSE separately." A
  test asserting SSE would invent a claim the notes never made.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
sys.path.insert(0, str(SKILL_ROOT))

TOOL_DIR = SKILL_ROOT / "adapt" / "extend" / "infrastructure" / "add_s3_storage"
CLIENT_TMPL = TOOL_DIR / "templates" / "client.py.tmpl"
ROUTES_TMPL = TOOL_DIR / "templates" / "routes.py.tmpl"


# ---------------------------------------------------------------------------
# Placeholder cleanup — parity with sibling pair-test modules.
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


def _find_method(
    cls: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(cls):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"method {name} not found on class {cls.name}")


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
# B0.13 — paired evidence for ``signed`` (presigned URL).
# ---------------------------------------------------------------------------


def test_s3_signed_upload_url_calls_boto_generate_presigned_url() -> None:
    """``S3Client.presigned_upload_url`` MUST call
    ``self._client.generate_presigned_url("put_object", ...)``. This
    is the boto3 entry point that performs AWS Sigv4 HMAC signing;
    without it the returned URL is unsigned and the "presigned"
    claim is structurally false.
    """
    tree = _parse(CLIENT_TMPL)
    cls = _find_class(tree, "S3Client")
    fn = _find_method(cls, "presigned_upload_url")

    found = False
    for call in _calls(fn):
        if not _attr_chain(call).endswith("generate_presigned_url"):
            continue
        # First positional arg MUST be the string "put_object".
        if call.args and isinstance(call.args[0], ast.Constant):
            if call.args[0].value == "put_object":
                found = True
    assert found, (
        "S3Client.presigned_upload_url MUST call "
        "`self._client.generate_presigned_url(\"put_object\", ...)` "
        "— the boto3 entry point that signs the URL with AWS Sigv4. "
        "Without it the `presigned` (signed) claim is false."
    )


def test_s3_signed_download_url_calls_boto_generate_presigned_url() -> None:
    """``S3Client.presigned_download_url`` MUST call
    ``self._client.generate_presigned_url("get_object", ...)``.
    Symmetric assertion — the download path is the other half of the
    "presigned URL workflow".
    """
    tree = _parse(CLIENT_TMPL)
    cls = _find_class(tree, "S3Client")
    fn = _find_method(cls, "presigned_download_url")

    found = False
    for call in _calls(fn):
        if not _attr_chain(call).endswith("generate_presigned_url"):
            continue
        if call.args and isinstance(call.args[0], ast.Constant):
            if call.args[0].value == "get_object":
                found = True
    assert found, (
        "S3Client.presigned_download_url MUST call "
        "`self._client.generate_presigned_url(\"get_object\", ...)` "
        "— without it the download URL is unsigned and the "
        "`presigned` claim is false."
    )


def test_s3_signed_upload_route_delegates_to_presigned_url() -> None:
    """The ``POST /storage/upload`` route MUST delegate to
    ``client.presigned_upload_url(...)``. A route that called
    ``upload_fileobj`` would proxy bytes through the API process and
    break the "never buffers binary data" promise (which is the
    operational consequence of the `presigned` claim).
    """
    tree = _parse(ROUTES_TMPL)

    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _attr_chain(node).endswith("presigned_upload_url"):
            found = True
    assert found, (
        "The S3 storage routes module MUST call "
        "`client.presigned_upload_url(...)` from the POST /storage/"
        "upload handler; without this hop the route either proxies "
        "the upload or returns an unsigned URL — both break the "
        "`presigned` claim."
    )


def test_s3_signed_routes_do_not_proxy_via_upload_fileobj() -> None:
    """None of the route handlers may call ``upload_fileobj`` or
    ``download_fileobj`` — those are the boto3 methods that stream
    bytes THROUGH the API process. Their absence is load-bearing for
    the "API never buffers binary data" half of the claim.
    """
    tree = _parse(ROUTES_TMPL)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node)
        if chain.endswith("upload_fileobj") or chain.endswith("download_fileobj"):
            offenders.append(chain)
    assert not offenders, (
        f"S3 storage routes MUST NOT call boto3 streaming methods "
        f"`upload_fileobj`/`download_fileobj` (found: {offenders}). "
        f"Those proxy bytes through the API process and break the "
        f"`API never buffers binary data` promise — the structural "
        f"consequence of the `presigned URL workflow` claim."
    )


def test_b0_13_waiver_removed() -> None:
    """The B0.13 waiver entry for ``add_s3_storage`` MUST be gone."""
    from engine.audit.contract_rules.r_notes_match_behaviour import (
        _WAIVED_TOOLS,
    )

    assert "extend/infrastructure/add_s3_storage" not in _WAIVED_TOOLS, (
        "B0.13 waiver entry for add_s3_storage was NOT removed; "
        "the pair test is inert while the rule still skips the tool."
    )
