"""Generic tool-contract mutation coverage for add_csrf_protection.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_csrf_protection.py in the mutation
runner: ``--tests test_add_csrf_protection.py test_add_csrf_protection_contract.py``.
"""

import tempfile
from pathlib import Path

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_csrf_protection import add_csrf_protection

    for check in SCAFFOLDABLE_CHECKS:
        check(add_csrf_protection, "add_csrf_protection")


# ---------------------------------------------------------------------------
# Tool-specific mutation kills for _patch_main (L170 guard).
#
# Guard under test:
#     if "csrf_router" in src or "csrf.router" in src:
#         return                       # leave main.py untouched
#     # else: append a commented router-registration hint
#
# The hint block itself contains both "csrf_router" and "csrf.router".
# ---------------------------------------------------------------------------


def _run_patch_main(content: str) -> str:
    """Write *content* to a temp main.py, run _patch_main, return new text."""
    from adapt.extend.infrastructure.add_csrf_protection import _patch_main

    with tempfile.TemporaryDirectory() as td:
        main_file = Path(td) / "main.py"
        main_file.write_text(content)
        _patch_main(main_file)
        return main_file.read_text()


def test_patch_main_appends_hint_when_absent() -> None:
    """Fresh main.py (neither token present) gets the commented hint appended.

    Original guard: ``False or False`` -> no early return -> hint appended.
    Kills both ``In -> NotIn`` flips on L170: either flip makes the guard
    truthy on this input, forcing an early return so the hint is NOT appended.
    """
    base = "from fastapi import FastAPI\napp = FastAPI()\n"
    out = _run_patch_main(base)

    # The hint must have been appended.
    assert out != base, "hint must be appended when no csrf token present"
    assert "csrf_router" in out, "appended hint must reference csrf_router"
    assert "CSRFMiddleware" in out, "appended hint must mention CSRFMiddleware"
    # Original content preserved as a prefix.
    assert out.startswith(base.rstrip("\n"))


def test_patch_main_noop_when_csrf_router_present() -> None:
    """main.py already mentioning csrf_router is left byte-for-byte unchanged.

    Original guard: ``True or False`` -> early return -> no append.
    Kills the ``Or -> And`` flip on L170: ``True and False`` would be falsy,
    so the mutant would append a SECOND hint block and change the file.
    """
    content = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "# from app.api.routes.csrf import router as csrf_router\n"
    )
    assert "csrf.router" not in content  # only the first token is present
    out = _run_patch_main(content)
    assert out == content, "must not re-append hint when csrf_router already present"


def test_patch_main_noop_when_csrf_dot_router_present() -> None:
    """main.py mentioning csrf.router (second token only) is left unchanged.

    Reinforces the early-return path via the right-hand operand so the
    ``In -> NotIn`` flip on the second comparison cannot survive: with the
    original ``in`` this returns early (no append); the flipped guard would
    append the hint and grow the file.
    """
    content = "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(csrf.router)\n"
    assert "csrf_router" not in content  # only the second token is present
    out = _run_patch_main(content)
    assert out == content, "must not append hint when csrf.router already present"
