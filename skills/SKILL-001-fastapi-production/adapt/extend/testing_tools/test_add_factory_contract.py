"""Generic tool-contract mutation coverage for add_factory.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_factory.py in the mutation
runner: ``--tests test_add_factory.py test_add_factory_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.testing_tools.add_factory import add_factory

    for check in UNIVERSAL_CHECKS:
        check(add_factory, "add_factory")
