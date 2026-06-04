"""Generic tool-contract mutation coverage for add_cors_config.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cors_config.py in the mutation
runner: ``--tests test_add_cors_config.py test_add_cors_config_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_cors_config import add_cors_config

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cors_config, "add_cors_config")
