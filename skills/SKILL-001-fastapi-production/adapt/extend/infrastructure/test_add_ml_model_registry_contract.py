"""Generic tool-contract mutation coverage for add_ml_model_registry.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_ml_model_registry.py in the mutation
runner: ``--tests test_add_ml_model_registry.py test_add_ml_model_registry_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_ml_model_registry import add_ml_model_registry

    for check in SCAFFOLDABLE_CHECKS:
        check(add_ml_model_registry, "add_ml_model_registry")
