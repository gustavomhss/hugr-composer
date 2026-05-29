"""Layout-vs-import-path reconciliation contract (Codex 3 F-003).

Pre-fix, the tree dispatchers wrote primitives to
``<output_dir>/app/core/venous/<ns>/<Name>/`` while
``generators.scaffold_venous`` and ``mcp_tools.compose`` emitted imports
of the form ``from core.venous.<ns>.<Name>.<Name> import <Name>``. A
user following the emitted next-steps would crash with ``ModuleNotFoundError``.

This test exercises the WHOLE pipe in a fixture project: copy a primitive
via each tree dispatcher, then prove the canonical
``from core.venous.<ns>.<Name>.<Name> import <Name>`` import resolves
inside that project root.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from mcp_tools.tree.auth import fastapi_auth
from mcp_tools.tree.data import fastapi_data
from mcp_tools.tree.realtime import fastapi_realtime

CASES = (
    (fastapi_auth, "SessionStore", "auth"),
    (fastapi_data, "Aggregate", "data"),
    (fastapi_realtime, "CausalReorderBuffer", "events"),
)


def _load_module(qualified: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(qualified, file_path)
    assert spec is not None and spec.loader is not None, (
        f"spec_from_file_location returned None for {file_path}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("dispatcher", "primitive", "ns"), CASES)
def test_emitted_import_path_resolves_in_fixture_project(
    dispatcher, primitive: str, ns: str, tmp_path: Path
) -> None:
    """The path emitted in next_steps MUST resolve in the project tree."""
    r = dispatcher(
        action="primitive",
        params={"name": primitive, "output_dir": str(tmp_path)},
    )
    assert r["ok"] is True
    assert r["result"]["status"] == "copied"

    # Canonical emitted import line (matches compose._primitive_import_line
    # + scaffold_venous.copy_primitive layout).
    expected = f"from core.venous.{ns}.{primitive}.{primitive} import {primitive}"
    assert any(expected in step for step in r["next_steps"]), (
        f"next_steps must advertise the canonical import: {expected!r}; got {r['next_steps']!r}"
    )

    # Physically resolve the import inside the fixture project root, bypassing
    # sys.path manipulation (which would pollute the test process).
    expected_file = tmp_path / "core" / "venous" / ns / primitive / f"{primitive}.py"
    assert expected_file.is_file(), (
        f"copy target missing at {expected_file}; "
        f"the layout disagrees with the emitted import path."
    )

    # Load the copy at the FIXTURE path directly (not the skill-repo source).
    # Using a distinct qualified name avoids collision with the test process's
    # own `core.venous` package (loaded via PYTHONPATH=.).
    qualified = f"_fixture_{ns}_{primitive}"
    sys.modules.pop(qualified, None)
    try:
        mod = _load_module(qualified, expected_file)
        # Verify it loaded from the FIXTURE, not the skill repo.
        assert Path(mod.__file__).resolve() == expected_file.resolve(), (
            f"resolved {mod.__file__} but expected fixture {expected_file}; "
            "the layout doesn't reconcile with the emitted import path."
        )
        symbol = getattr(mod, primitive, None)
        assert symbol is not None, f"primitive {primitive!r} not exposed in {expected_file}"
    finally:
        sys.modules.pop(qualified, None)
