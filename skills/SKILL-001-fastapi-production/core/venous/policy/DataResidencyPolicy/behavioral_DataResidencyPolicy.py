"""Behavioral scenarios for DataResidencyPolicy."""

from __future__ import annotations

import pytest

from DataResidencyPolicy import (
    DataResidencyPolicy,
    DataResidencyPolicyError,
    InMemoryResidencyEnforcer,
)


def test_scenario_eu_profile_to_us_requires_scc() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(DataResidencyPolicy(
        data_class="eu_user_profile",
        allowed_regions=("DE", "IE", "FR", "US"),
        transfer_mechanism="SCC_2021/914",
    ))
    e.check_transfer("eu_user_profile", source="DE", destination="US")


def test_scenario_unallowed_region_rejected() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(DataResidencyPolicy(
        data_class="eu_user_profile",
        allowed_regions=("DE", "IE", "FR"),
        transfer_mechanism="SCC_2021/914",
    ))
    with pytest.raises(DataResidencyPolicyError):
        e.check_write("eu_user_profile", "CN")


def test_scenario_invalid_mechanism_rejected() -> None:
    with pytest.raises(DataResidencyPolicyError):
        DataResidencyPolicy(
            data_class="x", allowed_regions=("DE",),
            transfer_mechanism="handshake",
        )


def test_scenario_adequacy_decision_allowed() -> None:
    e = InMemoryResidencyEnforcer()
    e.bind(DataResidencyPolicy(
        data_class="x", allowed_regions=("DE", "JP"),
        transfer_mechanism="adequacy_decision",
    ))
    e.check_transfer("x", source="DE", destination="JP")


def test_scenario_unbound_class_write_rejected() -> None:
    e = InMemoryResidencyEnforcer()
    with pytest.raises(DataResidencyPolicyError):
        e.check_write("unbound", "DE")
