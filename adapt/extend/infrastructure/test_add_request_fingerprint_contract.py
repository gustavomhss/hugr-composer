"""Generic tool-contract mutation coverage for add_request_fingerprint.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_request_fingerprint.py in the mutation
runner: ``--tests test_add_request_fingerprint.py test_add_request_fingerprint_contract.py``.

The tool-specific tests below target the surviving, tool-logic mutants that
the shared preamble checks cannot reach. See the module-level note before each
``test_l90_*`` function for the exact mutant it kills.
"""

import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_request_fingerprint import add_request_fingerprint

    for check in SCAFFOLDABLE_CHECKS:
        check(add_request_fingerprint, "add_request_fingerprint")


def _bare_project() -> Path:
    """A bare project dir missing the auto-scaffoldable prereqs (config, reqs)."""
    d = Path(tempfile.mkdtemp()) / "fp_bare"
    d.mkdir(parents=True)
    return d


def test_l90_scaffolded_files_reported_in_files_created() -> None:
    """Kill L90 ``list(scaffolded or [])`` BoolOp Or->And.

    On a bare project, ``ensure_prerequisites(auto_scaffold=True)`` creates the
    missing CONFIG_SETTINGS prereq (``app/core/config.py``) plus its package
    ``__init__.py`` files and returns them as ``scaffolded``. The tool seeds
    ``files_created`` with ``list(scaffolded or [])`` so those auto-created
    files are reported back to the caller.

    Flipping ``or`` to ``and`` makes the expression ``scaffolded and []`` which,
    for a non-empty ``scaffolded`` list, evaluates to ``[]`` — silently dropping
    every auto-scaffolded prereq from ``files_created``. The tool's own
    fingerprint files (hasher/store/middleware) are appended afterwards, so the
    list stays non-empty and the generic ``check_bare_autoscaffold`` still
    passes; only an explicit assertion that a *scaffolded prereq* path is
    present distinguishes the two.
    """
    from adapt.extend.infrastructure.add_request_fingerprint import add_request_fingerprint

    p = _bare_project()
    r = add_request_fingerprint(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error

    created = r.files_created
    # The auto-scaffolded CONFIG_SETTINGS prereq must be reported. Use endswith
    # (not raw membership) because the tool returns resolved paths and macOS
    # TMPDIR resolves through the /private/var symlink.
    assert any(c.endswith("app/core/config.py") for c in created), (
        "auto-scaffolded app/core/config.py missing from files_created — "
        f"L90 'scaffolded or []' likely flipped to 'and'. Got: {created}"
    )
    # And at least one auto-created package __init__.py from the scaffold step.
    assert any(c.endswith("app/__init__.py") for c in created), (
        "auto-scaffolded app/__init__.py missing from files_created — "
        f"scaffolded files dropped. Got: {created}"
    )
