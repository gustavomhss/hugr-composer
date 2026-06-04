"""Generic tool-contract mutation coverage for add_anomaly_detector.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_anomaly_detector.py in the mutation
runner: ``--tests test_add_anomaly_detector.py test_add_anomaly_detector_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_anomaly_detector import add_anomaly_detector

    for check in SCAFFOLDABLE_CHECKS:
        check(add_anomaly_detector, "add_anomaly_detector")
