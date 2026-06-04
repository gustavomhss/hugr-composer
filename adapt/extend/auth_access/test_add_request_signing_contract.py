"""Generic tool-contract mutation coverage for add_request_signing.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_request_signing.py in the mutation
runner: ``--tests test_add_request_signing.py test_add_request_signing_contract.py``.

The ``test_patch_*`` functions below target this tool's bespoke insertion logic
in ``_patch_config`` / ``_patch_routes_init`` — the anchor/target/append branch
selection and the routes-init newline guard — which the generic contract checks
do not exercise.
"""

import tempfile
from pathlib import Path

from adapt.extend.auth_access.add_request_signing import (
    _patch_config,
    _patch_routes_init,
)
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def _tmp_file(content: str, name: str = "config.py") -> Path:
    d = Path(tempfile.mkdtemp())
    f = d / name
    f.write_text(content)
    return f


def test_contract():
    from adapt.extend.auth_access.add_request_signing import add_request_signing

    for check in SCAFFOLDABLE_CHECKS:
        check(add_request_signing, "add_request_signing")


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L154-156)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_after_anchor() -> None:
    """L155 ``anchor in src``: when the anchor line is present, the fields land
    immediately after it (NOT via the settings=Settings() fallback)."""
    anchor = "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    src = f"class Settings:\n{anchor}\n\nsettings = Settings()\n"
    f = _tmp_file(src)
    _patch_config(f)
    out = f.read_text()

    assert "REQUEST_SIGNING_SECRET" in out
    # Field must sit directly after the anchor line.
    anchor_idx = out.index(anchor)
    secret_idx = out.index("REQUEST_SIGNING_SECRET")
    target_idx = out.index("settings = Settings()")
    assert anchor_idx < secret_idx < target_idx, (
        "Fields must be inserted right after the anchor, before settings=Settings()"
    )
    # Exact contiguity: the SECRET line is the line right after the anchor.
    lines = out.splitlines()
    a_line = next(i for i, ln in enumerate(lines) if ln.strip() == anchor.strip())
    assert "REQUEST_SIGNING_SECRET" in lines[a_line + 1], (
        "REQUEST_SIGNING_SECRET must be the line immediately after the anchor"
    )


# ---------------------------------------------------------------------------
# _patch_config — target (settings=Settings()) branch (L158-160)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_before_settings_when_no_anchor() -> None:
    """L159 ``target in src`` + L160 ``fields + target``: with no anchor but a
    ``settings = Settings()`` line, fields are inserted right before that line.

    The L160 Add->Sub flip would raise TypeError (str - str); the L159 In->NotIn
    flip would fall through to the append-at-end branch, putting the fields
    AFTER ``settings = Settings()``."""
    src = "class Settings:\n    DEBUG: bool = False\n\nsettings = Settings()\n"
    f = _tmp_file(src)
    _patch_config(f)
    out = f.read_text()

    assert "REQUEST_SIGNING_SECRET" in out
    secret_idx = out.index("REQUEST_SIGNING_SECRET")
    target_idx = out.index("settings = Settings()")
    assert secret_idx < target_idx, (
        "Without an anchor, fields must be inserted before settings=Settings()"
    )


# ---------------------------------------------------------------------------
# _patch_config — append-at-end branch (L162)
# ---------------------------------------------------------------------------


def test_patch_config_appends_when_no_anchor_no_target() -> None:
    """L162 ``src.rstrip() + fields``: with neither anchor nor target, fields are
    appended at the end. The Add->Sub flip would raise TypeError on str - str."""
    src = "class Settings:\n    DEBUG: bool = False\n"
    f = _tmp_file(src)
    _patch_config(f)
    out = f.read_text()

    assert "REQUEST_SIGNING_SECRET" in out
    assert "REQUEST_SIGNING_TIMESTAMP_WINDOW_S" in out
    # Original content preserved and fields tacked on at the end.
    assert out.startswith("class Settings:\n    DEBUG: bool = False\n")
    assert out.index("DEBUG") < out.index("REQUEST_SIGNING_SECRET")


def test_patch_config_idempotent() -> None:
    """A second patch is a no-op (existing REQUEST_SIGNING_SECRET short-circuits),
    so the field is never inserted twice."""
    anchor = "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    src = f"class Settings:\n{anchor}\nsettings = Settings()\n"
    f = _tmp_file(src)
    _patch_config(f)
    _patch_config(f)
    out = f.read_text()
    assert out.count("REQUEST_SIGNING_SECRET") == 1, "Config field must not be duplicated"


# ---------------------------------------------------------------------------
# _patch_routes_init — marker idempotency (L170)
# ---------------------------------------------------------------------------


def test_patch_routes_init_idempotent_marker() -> None:
    """L170 ``marker in content``: if the deps marker is already present, the
    function returns unchanged (no second comment appended)."""
    content = "api_router = APIRouter()\n# from app.core.signing.deps import verify_signature\n"
    f = _tmp_file(content, name="__init__.py")
    _patch_routes_init(f)
    out = f.read_text()
    assert out == content, "Existing marker must short-circuit — no re-append"
    assert out.count("app.core.signing.deps") == 1


def test_patch_routes_init_appends_when_marker_absent() -> None:
    """L170 (the In branch must actually run when the marker is absent): the
    deps comment is appended exactly once."""
    content = 'api_router = APIRouter()\n__all__ = ["api_router"]\n'
    f = _tmp_file(content, name="__init__.py")
    _patch_routes_init(f)
    out = f.read_text()
    assert "app.core.signing.deps import verify_signature" in out
    assert out.startswith(content), "Original content must be preserved verbatim"


# ---------------------------------------------------------------------------
# _patch_routes_init — trailing-newline guard (L176)
# ---------------------------------------------------------------------------


def test_patch_routes_init_normalizes_missing_trailing_newline() -> None:
    """L176 ``not content.endswith('\\n')``: when content lacks a trailing
    newline, the guard adds one so the appended comment starts on its own line.

    Flipping ``not`` would skip the guard for newline-less content, gluing the
    appended block's leading newline directly after the last char (one fewer
    blank line)."""
    content = 'api_router = APIRouter()\n__all__ = ["api_router"]'  # no trailing \n
    f = _tmp_file(content, name="__init__.py")
    _patch_routes_init(f)
    out = f.read_text()
    # Guard adds the missing \n, then the addition (which itself starts with \n)
    # -> a blank line separates the last code line from the comment.
    assert '__all__ = ["api_router"]\n\n# Request signing' in out, (
        "Missing trailing newline must be normalized before appending"
    )


def test_patch_routes_init_preserves_existing_trailing_newline() -> None:
    """L176 (the guard must be skipped when a trailing newline already exists):
    no extra blank line beyond the addition's own leading newline."""
    content = 'api_router = APIRouter()\n__all__ = ["api_router"]\n'  # has trailing \n
    f = _tmp_file(content, name="__init__.py")
    _patch_routes_init(f)
    out = f.read_text()
    assert '__all__ = ["api_router"]\n\n# Request signing' in out
    # Exactly one blank line — not two (which would mean the guard wrongly fired).
    assert '__all__ = ["api_router"]\n\n\n# Request signing' not in out
