"""Generic tool-contract mutation coverage for add_docker_production.

Auto-generated: applies the shared fleet contract checks
(tests/common/tool_contract.py) so the common preamble mutants are killed
without per-tool bespoke tests. Run alongside test_add_docker_production.py in the mutation
runner: ``--tests test_add_docker_production.py test_add_docker_production_contract.py``.
"""

from tests.common.tool_contract import SCAFFOLDABLE_CHECKS


def test_contract():
    from adapt.extend.infrastructure.add_docker_production import add_docker_production

    for check in SCAFFOLDABLE_CHECKS:
        check(add_docker_production, "add_docker_production")
