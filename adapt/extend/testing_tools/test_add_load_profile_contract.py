"""Generic tool-contract mutation coverage for add_load_profile.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_load_profile.py in the mutation
runner: ``--tests test_add_load_profile.py test_add_load_profile_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_load_profile import add_load_profile

    for check in SCAFFOLDABLE_CHECKS:
        check(add_load_profile, "add_load_profile")
