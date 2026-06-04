"""Generic tool-contract mutation coverage for add_feature_flags.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_feature_flags.py in the mutation
runner: ``--tests test_add_feature_flags.py test_add_feature_flags_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_feature_flags import add_feature_flags

    for check in UNIVERSAL_CHECKS:
        check(add_feature_flags, "add_feature_flags")
