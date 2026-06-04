"""Generic tool-contract mutation coverage for add_factory.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_factory.py in the mutation
runner: ``--tests test_add_factory.py test_add_factory_contract.py``.

Plus tool-specific tests targeting add_factory's bespoke logic that the generic
preamble checks do not cover (backend selection, sub-factory FK imports,
conftest re-patch guard, emitted-test render guard).
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_factory import (
    _patch_conftest,
    _sub_factory_imports,
    add_factory,
)
from tests.common.fixture_factory import create_fixture_project
from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_factory import add_factory

    for check in UNIVERSAL_CHECKS:
        check(add_factory, "add_factory")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills
# ---------------------------------------------------------------------------


def _multi_model_project(name: str) -> Path:
    """Fresh fixture project with two domain models so FK sub-factories exist."""
    return create_fixture_project(
        name=name,
        models={"Item": {"title": "str"}, "Tag": {"name": "str"}},
    )


def test_polyfactory_pip_hint_is_polyfactory() -> None:
    """L147 Eq->NotEq: default backend resolves the polyfactory pip hint.

    The ternary ``'polyfactory faker' if backend == 'polyfactory' else
    'factory-boy faker'`` flips to the wrong branch if Eq becomes NotEq.
    """
    project_dir = create_fixture_project(name="fac_c_poly")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    pip_lines = [s for s in result.next_steps if "pip install" in s]
    assert pip_lines, "expected a pip install next step"
    assert any("polyfactory faker" in s for s in pip_lines)
    assert not any("factory-boy faker" in s for s in pip_lines)


def test_factory_boy_pip_hint_is_factory_boy() -> None:
    """L147 Eq->NotEq (other branch): factory_boy backend resolves its pip hint."""
    project_dir = create_fixture_project(name="fac_c_fb")
    result = add_factory(ToolInput(project_dir=str(project_dir)), backend="factory_boy")
    assert result.status == "success"
    pip_lines = [s for s in result.next_steps if "pip install" in s]
    assert any("factory-boy faker" in s for s in pip_lines)
    assert not any("polyfactory faker" in s for s in pip_lines)


def test_sub_factory_imports_present_for_multi_model() -> None:
    """L164 UnaryNot (``if not others``): with >1 model, FK sub-imports emit.

    Flipping ``not others`` to ``others`` short-circuits to an empty string,
    so the generated factory would carry no sub-factory imports.
    """
    project_dir = _multi_model_project("fac_c_subimp")
    add_factory(ToolInput(project_dir=str(project_dir)))
    item_src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "# sub-factory (FK)" in item_src
    assert "tag_factory import TagFactory" in item_src


def test_sub_factory_excludes_self() -> None:
    """L163 NotEq->Eq: a model never imports its own factory as a sub-factory.

    ``[m for m in all_models if m != model_name]`` becomes ``== model_name``
    under the flip, which would import only the model itself.
    """
    project_dir = _multi_model_project("fac_c_self")
    add_factory(ToolInput(project_dir=str(project_dir)))
    item_src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "item_factory import ItemFactory  # sub-factory (FK)" not in item_src
    # And it must still import the *other* models as sub-factories.
    assert "tag_factory import TagFactory  # sub-factory (FK)" in item_src


def test_sub_factory_imports_empty_for_single_model_helper() -> None:
    """L163/L164 direct: single-model list yields no sub-factory imports."""
    assert _sub_factory_imports("Item", ["Item"]) == ""
    out = _sub_factory_imports("Item", ["Item", "Tag"])
    assert "TagFactory" in out
    assert "ItemFactory" not in out


def test_conftest_skipped_when_only_registry_marker_present() -> None:
    """L274 Or->And: re-patch guard returns on EITHER marker alone.

    A conftest containing only ``FACTORY_REGISTRY`` (no ``ItemFactory``)
    must be left untouched. Under ``Or->And`` the guard would require both
    markers and would wrongly re-patch.
    """
    d = Path(tempfile.mkdtemp())
    cf = d / "conftest.py"
    original = "# pre-existing FACTORY_REGISTRY usage\nx = 1\n"
    cf.write_text(original)
    _patch_conftest(cf, ["Item", "Tag"])
    assert cf.read_text() == original


def test_conftest_skipped_when_only_itemfactory_marker_present() -> None:
    """L274 Or->And (other operand): ``ItemFactory`` marker alone also skips."""
    d = Path(tempfile.mkdtemp())
    cf = d / "conftest.py"
    original = "# pre-existing ItemFactory usage\ny = 2\n"
    cf.write_text(original)
    _patch_conftest(cf, ["Item", "Tag"])
    assert cf.read_text() == original


def test_conftest_patched_when_no_markers() -> None:
    """L274 sanity: a clean conftest IS patched (drives the non-return path)."""
    d = Path(tempfile.mkdtemp())
    cf = d / "conftest.py"
    cf.write_text("# clean conftest\nz = 3\n")
    _patch_conftest(cf, ["Item"])
    patched = cf.read_text()
    assert "item_factory" in patched
    assert "FACTORY_REGISTRY" in patched


def test_emitted_test_file_rendered() -> None:
    """L133 UnaryNot (``if not emitted.exists()``): emitted test is rendered.

    Flipping to ``if emitted.exists()`` skips the render on a fresh project,
    so the file would never be created.
    """
    project_dir = create_fixture_project(name="fac_c_emit")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    emitted = project_dir / "tests" / "test_add_factory_emitted.py"
    assert emitted.exists()
    assert any(p.endswith("tests/test_add_factory_emitted.py") for p in result.files_created)


def test_tests_dir_mkdir_does_not_crash_when_present() -> None:
    """L131 BoolLiteral (``exist_ok=True``): tool succeeds though tests/ exists.

    The fixture always ships a ``tests/`` directory; ``exist_ok=True->False``
    would raise FileExistsError on the second mkdir and fail the run.
    """
    project_dir = create_fixture_project(name="fac_c_mkdir")
    assert (project_dir / "tests").is_dir()
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", result.error
