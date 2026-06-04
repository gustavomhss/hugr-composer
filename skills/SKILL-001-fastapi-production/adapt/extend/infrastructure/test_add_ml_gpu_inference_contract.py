"""Generic tool-contract mutation coverage for add_ml_gpu_inference.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_ml_gpu_inference.py in the mutation
runner: ``--tests test_add_ml_gpu_inference.py test_add_ml_gpu_inference_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_ml_gpu_inference import add_ml_gpu_inference

    for check in SCAFFOLDABLE_CHECKS:
        check(add_ml_gpu_inference, "add_ml_gpu_inference")
