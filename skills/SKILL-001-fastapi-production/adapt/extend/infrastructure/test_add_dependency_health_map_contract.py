"""Generic tool-contract mutation coverage for add_dependency_health_map.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_dependency_health_map.py in the mutation
runner: ``--tests test_add_dependency_health_map.py test_add_dependency_health_map_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_dependency_health_map import add_dependency_health_map

    for check in SCAFFOLDABLE_CHECKS:
        check(add_dependency_health_map, "add_dependency_health_map")
