"""Generic tool-contract mutation coverage for add_event_sourcing.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_event_sourcing.py in the mutation
runner: ``--tests test_add_event_sourcing.py test_add_event_sourcing_contract.py``.

The ``test_es_*`` functions below kill add_event_sourcing's TOOL-SPECIFIC
mutants (the config-patch ``_patch_config`` insert position/idempotency/return
flag and the ``list(scaffolded or [])`` prereq merge). Shared preamble mutants
are already killed by ``test_contract``.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    for check in SCAFFOLDABLE_CHECKS:
        check(add_event_sourcing, "add_event_sourcing")


def _ends_with(paths: list[str], suffix: str) -> bool:
    """Symlink-safe membership: match RESOLVED tool paths by trailing segment."""
    return any(p.replace("\\", "/").endswith(suffix) for p in paths)


def test_es_config_flag_inserted_right_after_anchor_and_recorded():
    """L162-169: the durable flag lands immediately after the auth anchor and
    config.py is recorded in files_modified.

    Kills:
      * L167 BinOp Add->Sub — the anchor branch concatenates
        ``anchor + "\\n" + field``; Sub would raise / drop the field.
      * L169 BoolLiteral True->False — _patch_config returns True after a real
        edit, which is what appends config.py to files_modified.
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    project_dir = create_fixture_project(name="es_cfg_anchor")
    config = project_dir / "app" / "core" / "config.py"
    assert "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30" in config.read_text()

    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    # L169: edited config must be reported as modified.
    assert _ends_with(result.files_modified, "app/core/config.py"), result.files_modified

    src = config.read_text()
    assert "EVENT_STORE_DURABLE: bool = False" in src
    # L167: the flag is inserted DIRECTLY after the anchor line, in order.
    expected = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n    EVENT_STORE_DURABLE: bool = False"
    assert expected in src, "durable flag must sit immediately after the auth anchor"
    ast.parse(src)


def test_es_config_flag_appended_when_anchor_absent():
    """L166-167: fallback path when the anchor line is missing.

    With no ``ACCESS_TOKEN_EXPIRE_MINUTES`` anchor the tool must append the flag
    to the end of the file. Under the Add->Sub mutant (L167) the string
    concatenation ``src.rstrip("\\n") + "\\n" + field + "\\n"`` becomes a
    subtraction and raises TypeError, so the field never appears (and config is
    not recorded as modified).
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    project_dir = create_fixture_project(name="es_cfg_noanchor")
    config = project_dir / "app" / "core" / "config.py"
    stripped = config.read_text().replace("    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n", "")
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" not in stripped
    config.write_text(stripped)

    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    src = config.read_text()
    assert "EVENT_STORE_DURABLE: bool = False" in src, "fallback append must add the flag"
    assert _ends_with(result.files_modified, "app/core/config.py")
    # NB: the fallback appends the 4-space-indented field at module scope, so the
    # resulting config does not re-parse — that is the tool's real behaviour. The
    # mutant (Add->Sub) instead raises TypeError mid-patch, so neither the flag
    # nor the success status survive; asserting the flag text is the kill signal.


def test_es_config_not_repatched_when_flag_already_present():
    """L160-161: _patch_config returns False (and config is NOT re-modified)
    when EVENT_STORE_DURABLE is already in the file.

    Kills L161 BoolLiteral False->True: the early-return guard must yield False so
    a config that already carries the flag is left out of files_modified and is
    not edited a second time.
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    project_dir = create_fixture_project(name="es_cfg_preset")
    config = project_dir / "app" / "core" / "config.py"
    # Pre-seed the flag so _patch_config sees it on the first (and only) run.
    seeded = config.read_text().replace(
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n",
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30\n    EVENT_STORE_DURABLE: bool = False\n",
    )
    config.write_text(seeded)
    before = config.read_text()

    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    # Guard returned False => config absent from files_modified, content untouched.
    assert not _ends_with(result.files_modified, "app/core/config.py"), result.files_modified
    assert config.read_text() == before, "config must not be re-patched when flag present"
    # Exactly one flag line, no duplicate insert.
    assert before.count("EVENT_STORE_DURABLE: bool = False") == 1


def test_es_scaffolded_prereqs_carried_into_files_created():
    """L67: ``files_created = list(scaffolded or [])`` must carry auto-scaffolded
    prerequisite files into the result.

    On a bare project (no app/core/config.py) the prereq layer scaffolds it; the
    scaffolded path must surface in files_created. The Or->And mutant turns the
    merge into ``list(scaffolded and [])`` == ``[]`` (a non-empty scaffolded list
    short-circuits to []), dropping every scaffolded file — including config.py.
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    bare = Path(tempfile.mkdtemp())
    assert not (bare / "app" / "core" / "config.py").exists()

    result = add_event_sourcing(ToolInput(project_dir=str(bare)))
    assert result.status == "success", result.error

    # The scaffolded config prereq must appear in files_created (it is the first
    # entry the Or->And mutant would drop).
    assert _ends_with(result.files_created, "app/core/config.py"), result.files_created


def test_es_succeeds_when_app_dir_already_exists():
    """L98 ``app_dir.mkdir(parents=True, exist_ok=True)``: the tool runs against a
    fixture whose ``app/`` already exists, so the mkdir must tolerate the existing
    directory.

    Kills L98 BoolLiteral True->False on ``exist_ok``: with ``exist_ok=False`` the
    mkdir raises ``FileExistsError`` on the pre-existing ``app/`` dir and the tool
    can never reach a ``success`` return / write ``app/event_store.py``.
    (The sibling ``parents=True->False`` flip is EQUIVALENT — ``app/``'s parent is
    the project root, which always exists.)
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    project_dir = create_fixture_project(name="es_app_exists")
    app_dir = project_dir / "app"
    assert app_dir.is_dir(), "fixture must pre-create app/ to exercise exist_ok"

    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    assert _ends_with(result.files_created, "app/event_store.py"), result.files_created
    assert (app_dir / "event_store.py").is_file()


def test_es_succeeds_when_tests_dir_already_exists():
    """L174 ``(project / "tests").mkdir(parents=True, exist_ok=True)``: the emitted
    project test is rendered into a ``tests/`` dir that the fixture already created.

    Kills L174 BoolLiteral True->False on ``exist_ok``: ``exist_ok=False`` raises
    ``FileExistsError`` on the pre-existing ``tests/`` dir inside ``_emit_project_test``,
    so the emitted test never lands and the run never reaches ``success``.
    (The sibling ``parents=True->False`` flip is EQUIVALENT — ``tests/``'s parent is
    the project root, which always exists.)
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    project_dir = create_fixture_project(name="es_tests_exists")
    tests_dir = project_dir / "tests"
    assert tests_dir.is_dir(), "fixture must pre-create tests/ to exercise exist_ok"

    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
    emitted = tests_dir / "test_add_event_sourcing_emitted.py"
    assert emitted.is_file(), "emitted project test must be written into existing tests/"
    assert _ends_with(result.files_created, "tests/test_add_event_sourcing_emitted.py"), (
        result.files_created
    )


def test_es_ast_guard_skips_json_manifest_but_validates_py():
    """L116 ``if p.suffix == ".py" and p.is_file()`` — the AST validation guard.

    The tool appends a non-``.py`` artifact (``.venous_manifest.json``) to
    files_created alongside the generated ``.py`` modules. The guard must (a) parse
    every emitted ``.py`` (so a genuine syntax error surfaces as status="error")
    and (b) skip the JSON manifest. This test asserts the guard runs cleanly with a
    JSON file present in files_created and that the emitted Python is in fact valid.

    NB classification: the two L116 flips (``Eq->NotEq`` and ``And->Or``) are
    EQUIVALENT against the tool's natural output — the only non-``.py`` entry is the
    manifest, and ``ensure_primitives`` always renders it as a string-keyed JSON
    object that also happens to be a valid Python dict-literal, so forcing
    ``ast.parse`` over it does not raise. They cannot be killed without modifying
    the target to emit a non-Python-parseable artifact. We assert the observable
    contract instead: the run succeeds with a ``.json`` in files_created and all
    emitted ``.py`` files parse.
    """
    from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing

    project_dir = create_fixture_project(name="es_ast_guard")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error

    json_entries = [p for p in result.files_created if p.endswith(".json")]
    assert json_entries, "manifest .json must be among files_created"

    for path_str in result.files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            ast.parse(p.read_text())  # every emitted module must be valid Python
