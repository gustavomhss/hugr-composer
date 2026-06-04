"""Generic tool-contract mutation coverage for add_kubernetes_manifests.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_kubernetes_manifests.py in the mutation
runner: ``--tests test_add_kubernetes_manifests.py test_add_kubernetes_manifests_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_kubernetes_manifests import add_kubernetes_manifests

    for check in SCAFFOLDABLE_CHECKS:
        check(add_kubernetes_manifests, "add_kubernetes_manifests")
