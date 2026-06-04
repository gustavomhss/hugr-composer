"""Generic tool-contract mutation coverage for add_batch_endpoint.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_batch_endpoint.py in the mutation
runner: ``--tests test_add_batch_endpoint.py test_add_batch_endpoint_contract.py``.
"""

from tests.common.tool_contract import UNIVERSAL_CHECKS


def test_contract():
    from adapt.extend.api_design.add_batch_endpoint import add_batch_endpoint

    for check in UNIVERSAL_CHECKS:
        check(add_batch_endpoint, "add_batch_endpoint")
