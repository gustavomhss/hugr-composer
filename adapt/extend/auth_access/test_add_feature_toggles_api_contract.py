"""Generic tool-contract mutation coverage for add_feature_toggles_api.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_feature_toggles_api.py in the mutation
runner: ``--tests test_add_feature_toggles_api.py test_add_feature_toggles_api_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.auth_access.add_feature_toggles_api import add_feature_toggles_api

    for check in SCAFFOLDABLE_CHECKS:
        check(add_feature_toggles_api, "add_feature_toggles_api")
