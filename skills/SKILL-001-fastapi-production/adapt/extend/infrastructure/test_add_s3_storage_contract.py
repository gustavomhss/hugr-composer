"""Generic tool-contract mutation coverage for add_s3_storage.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_s3_storage.py in the mutation
runner: ``--tests test_add_s3_storage.py test_add_s3_storage_contract.py``.

The hand-written tests below target this tool's SPECIFIC logic — the config
``Settings`` patch (``_patch_config``) and the route-registration insertion
(``_register_router``) — which the generic preamble checks do not cover.
"""

import tempfile
import textwrap
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_s3_storage import (
    _patch_config,
    _register_router,
    add_s3_storage,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS

_ANCHOR = "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
_S3_COMMENT = "    # --- S3/MinIO object storage — added by add_s3_storage tool ---"
_SETTINGS_LINE = "settings = Settings()"
_APIROUTER_LINE = "api_router = APIRouter()"


def test_contract():
    from adapt.extend.infrastructure.add_s3_storage import add_s3_storage

    for check in SCAFFOLDABLE_CHECKS:
        check(add_s3_storage, "add_s3_storage")


def _write_config(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    f = d / "config.py"
    f.write_text(textwrap.dedent(text))
    return f


def _write_routes(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    f = d / "__init__.py"
    f.write_text(textwrap.dedent(text))
    return f


# ---------------------------------------------------------------------------
# _patch_config — anchor branch (L207 In->NotIn)
# ---------------------------------------------------------------------------


def test_patch_config_inserts_block_directly_after_anchor():
    """L207 ``if anchor in src``: the S3 block must land immediately after the
    ACCESS_TOKEN anchor line — not in the fallback ``settings =`` position.
    """
    f = _write_config(
        """\
        class Settings:
            SECRET_KEY: str = "x"
            ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
            OTHER: int = 1

        settings = Settings()
        """
    )
    _patch_config(f)
    lines = f.read_text().splitlines()
    anchor_idx = lines.index(_ANCHOR)
    # The S3 block opens on the very next line after the anchor.
    assert lines[anchor_idx + 1] == _S3_COMMENT
    # And it lands BEFORE the original OTHER field (which followed the anchor),
    # proving the anchor branch (not the settings-line fallback) ran.
    assert lines.index(_S3_COMMENT) < lines.index("    OTHER: int = 1")


def test_patch_config_block_precedes_settings_when_no_anchor():
    """L211 ``if settings_line in src``: with no ACCESS_TOKEN anchor but a
    ``settings = Settings()`` line, the block must land BEFORE that line.

    A NotIn flip would skip this branch and append the block at end-of-file
    (after ``settings = Settings()``), which this asserts against.
    """
    f = _write_config(
        """\
        class Settings:
            SECRET_KEY: str = "x"

        settings = Settings()
        """
    )
    _patch_config(f)
    src = f.read_text()
    assert _S3_COMMENT in src
    assert src.index(_S3_COMMENT) < src.index(_SETTINGS_LINE)


def test_patch_config_appends_when_no_anchor_no_settings():
    """L214 ``src.rstrip() + "\\n" + block``: the final fallback appends the
    block. Both ``+`` are string concatenation; an Add->Sub flip turns this
    into ``str - str`` -> TypeError, so a clean success here kills it.
    """
    f = _write_config(
        """\
        class Settings:
            SECRET_KEY = "x"
        """
    )
    _patch_config(f)  # must not raise
    src = f.read_text()
    assert _S3_COMMENT in src
    assert 'S3_BUCKET_NAME: str = "my-app-bucket"' in src


def test_patch_config_idempotent():
    """Second call is a no-op (single S3 block, no double-insert)."""
    f = _write_config(
        """\
        class Settings:
            ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

        settings = Settings()
        """
    )
    _patch_config(f)
    first = f.read_text()
    _patch_config(f)
    assert f.read_text() == first
    assert first.count(_S3_COMMENT) == 1


# ---------------------------------------------------------------------------
# _register_router — normal path with app imports
# (L236 Eq->NotEq, L241 Add->Sub, L246 Eq->NotEq, L251 Add->Sub)
# ---------------------------------------------------------------------------


def test_register_router_import_after_last_app_import():
    """L236 / L241: import_line lands immediately after the LAST ``from app.``
    import, and include_line after the LAST ``api_router.include_router`` line.
    """
    f = _write_routes(
        """\
        from fastapi import APIRouter

        from app.api.routes.item import router as item_router
        from app.api.routes.users import router as users_router

        api_router = APIRouter()
        api_router.include_router(users_router)
        api_router.include_router(item_router)
        """
    )
    _register_router(f, import_line="IMPORT_LINE", include_line="INCLUDE_LINE")
    lines = f.read_text().splitlines()
    last_app = max(i for i, ln in enumerate(lines) if ln.startswith("from app."))
    # IMPORT_LINE sits directly after the last app import (L236 false branch +
    # L241 +1). A NotEq flip would route through the fallback and place it next
    # to the APIRouter() def; an Add->Sub flip would place it one slot earlier.
    assert lines[last_app + 1] == "IMPORT_LINE"
    # And it is NOT adjacent to the APIRouter() def (the fallback slot).
    assert lines[lines.index(_APIROUTER_LINE) - 1] != "IMPORT_LINE"

    # INCLUDE_LINE follows the last include (L246 false branch + L251 +1). A
    # NotEq/Sub flip would drop it right after the APIRouter() def instead.
    real_incs = [i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")]
    assert lines[max(real_incs) + 1] == "INCLUDE_LINE"
    # Sanity: it is NOT sitting right after the APIRouter() def (the fallback slot).
    assert lines[lines.index(_APIROUTER_LINE) + 1] != "INCLUDE_LINE"


def test_register_router_idempotent():
    """A second registration with the same import_line is a no-op."""
    f = _write_routes(
        """\
        from app.api.routes.item import router as item_router

        api_router = APIRouter()
        api_router.include_router(item_router)
        """
    )
    _register_router(f, import_line="IMPORT_LINE", include_line="INCLUDE_LINE")
    first = f.read_text()
    _register_router(f, import_line="IMPORT_LINE", include_line="INCLUDE_LINE")
    assert f.read_text() == first
    assert first.count("IMPORT_LINE") == 1


# ---------------------------------------------------------------------------
# _register_router — fallback path (no app imports)
# (L238 And->Or / In->NotIn, L239 Sub->Add, L248 And->Or / In->NotIn)
# ---------------------------------------------------------------------------


def test_register_router_fallback_no_app_imports():
    """When there are no ``from app.`` imports, the import falls back to the
    line that has BOTH ``api_router`` AND ``APIRouter()`` (L238 And, In) and
    lands one slot before it (L239 ``idx - 1``). A comment that mentions
    ``api_router`` but NOT ``APIRouter()`` precedes the def to distinguish the
    And/In/Sub flips.
    """
    f = _write_routes(
        """\
        from fastapi import APIRouter

        # preface api_router note
        api_router = APIRouter()
        """
    )
    _register_router(f, import_line="IMPORT_LINE", include_line="INCLUDE_LINE")
    lines = f.read_text().splitlines()
    def_idx = lines.index(_APIROUTER_LINE)
    comment_idx = lines.index("# preface api_router note")
    # CORRECT places IMPORT_LINE directly before the def and directly after the
    # comment. And->Or puts it before the comment; In->NotIn puts it at index 0;
    # Sub->Add pushes it past the def.
    assert lines[def_idx - 1] == "IMPORT_LINE"
    assert lines[comment_idx + 1] == "IMPORT_LINE"
    # The include fallback (L248 And/In) drops INCLUDE_LINE right after the def.
    assert lines[lines.index(_APIROUTER_LINE) + 1] == "INCLUDE_LINE"


def test_register_router_include_fallback_no_includes():
    """L248 And->Or / In->NotIn: with no existing ``include_router`` lines, the
    include falls back to the APIRouter() def line and lands directly after it.
    """
    f = _write_routes(
        """\
        from app.api.routes.item import router as item_router

        api_router = APIRouter()
        """
    )
    _register_router(f, import_line="IMPORT_LINE", include_line="INCLUDE_LINE")
    lines = f.read_text().splitlines()
    assert lines[lines.index(_APIROUTER_LINE) + 1] == "INCLUDE_LINE"


# ---------------------------------------------------------------------------
# End-to-end through add_s3_storage — exercises _emit_project_test mkdir
# (L175 exist_ok True->False) and the real-fixture anchor/register paths.
# ---------------------------------------------------------------------------


def test_end_to_end_patches_config_and_routes_and_emits_test():
    """A full fixture run wires config + routes and emits the project test.

    The fixture project already contains a ``tests/`` directory, so
    ``_emit_project_test`` re-mkdirs it. L175 ``exist_ok=True`` flipped to
    ``False`` raises FileExistsError; a clean success status kills it.
    """
    project = create_fixture_project(name="s3_e2e")
    result = add_s3_storage(ToolInput(project_dir=str(project)))
    assert result.status == "success"

    # Anchor branch (L207) on the real generated config.
    cfg = (project / "app" / "core" / "config.py").read_text().splitlines()
    anchor_idx = cfg.index(_ANCHOR)
    assert cfg[anchor_idx + 1] == _S3_COMMENT

    # Route registration landed in the real routes/__init__.py.
    routes = (project / "app" / "routes" / "__init__.py").read_text().splitlines()
    last_app = max(i for i, ln in enumerate(routes) if ln.startswith("from app."))
    assert routes[last_app] == "from app.api.routes.storage import router as storage_router"
    last_inc = max(i for i, ln in enumerate(routes) if ln.startswith("api_router.include_router"))
    assert routes[last_inc] == "api_router.include_router(storage_router)"

    # The emitted project test was created (mkdir exist_ok path executed).
    assert (project / "tests" / "test_add_s3_storage_emitted.py").exists()
    assert any(p.endswith("tests/test_add_s3_storage_emitted.py") for p in result.files_created)
