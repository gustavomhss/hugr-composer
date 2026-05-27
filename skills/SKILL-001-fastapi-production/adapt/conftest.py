"""Test isolation for the adapt/ tree.

Several behavior / e2e tests scaffold a throwaway FastAPI project into a
tempdir, push it onto ``sys.path``, and import its ``app.*`` (which in turn
imports the copied-in ``core.venous.*`` tree). Each test purges ``app.*`` from
``sys.modules`` before importing — but **not** ``core.*``. So whichever such
test runs first pins ``core.venous.__path__`` to its own tempdir; a later test
needing a submodule that project did not copy (e.g. ``core.venous._adapters``)
then fails with ``ModuleNotFoundError`` even though the kit itself ships it.

The symptom is order-dependent: every test passes in isolation, but under the
full ``pytest adapt/`` run a cluster of infrastructure behavior tests goes red
(11 failed + 8 errors observed). That non-determinism is what this fixture
removes.

``_isolate_app_core_modules`` snapshots the ``app``/``core`` slice of
``sys.modules`` (and all of ``sys.path``) before each test and restores it
after, so every test starts from the same baseline — the kit's own complete
``core`` tree — regardless of what the previous test imported or failed to
clean up. The snapshot/restore is a small dict diff, negligible per-test cost.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Namespaces that get re-imported from scaffolded tempdirs and therefore leak
# across tests. ``app`` is the generated application; ``core`` is the copied-in
# primitive/adapter tree the generated app imports.
_VOLATILE_PREFIXES = ("app", "core")

# Skill root (adapt/conftest.py -> skills/SKILL-001-fastapi-production). The
# kit ships its own complete ``core`` tree here; anything imported from outside
# this root is a throwaway scaffold under a tempdir and must never survive a
# test.
_KIT_ROOT = Path(__file__).resolve().parent.parent


def _matching_keys() -> list[str]:
    """Return loaded module names belonging to a volatile namespace."""
    return [
        name
        for name in sys.modules
        if any(name == p or name.startswith(p + ".") for p in _VOLATILE_PREFIXES)
    ]


def _is_kit_module(module: object) -> bool:
    """True if *module* was imported from the kit tree (not a scaffold tempdir)."""
    origin = getattr(module, "__file__", None)
    if origin is None:
        path = getattr(module, "__path__", None)
        origin = next(iter(path), None) if path else None
    if origin is None:
        return False
    try:
        return Path(origin).resolve().is_relative_to(_KIT_ROOT)
    except (OSError, ValueError):
        return False


@pytest.fixture(autouse=True, scope="module")
def _isolate_app_core_modules():
    """Pin the app/core module + path state to the kit baseline around every module.

    Snapshots only the *kit-origin* ``app.*`` / ``core.*`` modules before the
    module's first test, then after its last test drops every such module —
    including any imported from a scaffold tempdir — and reinstates the
    kit-origin baseline. Filtering to kit-origin is what makes this
    order-independent: a tempdir ``core`` (e.g. one missing
    ``core.venous._adapters``) can never be carried forward to pin ``__path__``
    for a neighbour, no matter which test file ran first.

    Scope is ``module``, not ``function``, on purpose: the leak that motivated
    this is cross-*file* (one behavior test file pinning a stale tree for the
    next). Several files build a single module-scoped app and rely on its
    ``app.*`` submodules staying importable for lazy imports at request time
    across their tests — purging per function would break those. Cleaning at
    the file boundary fixes the cross-file leak without disturbing intra-file
    shared apps.
    """
    saved_modules = {
        name: sys.modules[name]
        for name in _matching_keys()
        if _is_kit_module(sys.modules[name])
    }
    saved_path = sys.path.copy()
    try:
        yield
    finally:
        for name in _matching_keys():
            del sys.modules[name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path
        # Reclaim the throwaway scaffold dirs this module's tests created via
        # create_fixture_project(tmp_dir=None). Module scope (not function) keeps
        # module-cached fixture projects alive across their tests, while still
        # bounding disk to ~one test-file's worth instead of the whole session.
        from tests.common.fixture_factory import purge_tracked_dirs

        purge_tracked_dirs()
