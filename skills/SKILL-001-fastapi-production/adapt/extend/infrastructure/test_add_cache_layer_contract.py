"""Generic tool-contract mutation coverage for add_cache_layer.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_cache_layer.py in the mutation
runner: ``--tests test_add_cache_layer.py test_add_cache_layer_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_cache_layer import add_cache_layer

    for check in SCAFFOLDABLE_CHECKS:
        check(add_cache_layer, "add_cache_layer")
