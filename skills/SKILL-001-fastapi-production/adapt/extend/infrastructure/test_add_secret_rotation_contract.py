"""Generic tool-contract mutation coverage for add_secret_rotation.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_secret_rotation.py in the mutation
runner: ``--tests test_add_secret_rotation.py test_add_secret_rotation_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation

    for check in SCAFFOLDABLE_CHECKS:
        check(add_secret_rotation, "add_secret_rotation")
