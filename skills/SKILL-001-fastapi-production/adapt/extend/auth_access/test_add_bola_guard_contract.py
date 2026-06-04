"""Generic tool-contract mutation coverage for add_bola_guard.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_bola_guard.py in the mutation
runner: ``--tests test_add_bola_guard.py test_add_bola_guard_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_bola_guard import add_bola_guard

    for check in SCAFFOLDABLE_CHECKS:
        check(add_bola_guard, "add_bola_guard")
