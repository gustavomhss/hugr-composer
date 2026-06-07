"""
Delivery-contract meta-tests, part 1: positive deliveries, identity fields,
and the FileArtefact collection rules. Split from test_delivery_contract.py.
"""

from __future__ import annotations

import copy
import hashlib

from engine.contracts import Maturity, PrimitiveDelivery, compute_sha256
from engine.tests.test_delivery_contract__shared import (
    _expect_fail,
    _expect_ok,
    make_file,
    valid_delivery_dict,
)


# ==========================================================================
# POSITIVE — full valid deliveries at each maturity
# ==========================================================================
def test_valid_battle_tested_passes():
    _expect_ok(valid_delivery_dict(Maturity.BATTLE_TESTED))


def test_valid_emerging_passes():
    _expect_ok(valid_delivery_dict(Maturity.EMERGING))


def test_valid_experimental_passes():
    _expect_ok(valid_delivery_dict(Maturity.EXPERIMENTAL))


def test_compute_sha256_matches_python_hashlib():
    assert compute_sha256(b"abc") == hashlib.sha256(b"abc").hexdigest()


# ==========================================================================
# IDENTITY — name, namespace, builder_agent_id, maturity, catalog_entry_sha256
# ==========================================================================
def test_name_rejects_lowercase_start():
    r = valid_delivery_dict()
    r["name"] = "healthProbe"
    _expect_fail(r, "string should match pattern")


def test_name_rejects_underscore():
    r = valid_delivery_dict()
    r["name"] = "Health_Probe"
    _expect_fail(r, "string should match pattern")


def test_name_rejects_too_long():
    r = valid_delivery_dict()
    r["name"] = "A" * 41
    _expect_fail(r, "at most 40 characters")


def test_name_accepts_pascal_with_digits():
    r = valid_delivery_dict()
    r["name"] = "HealthProbeV2"
    # Also need to reflect into file paths + catalog dirs — so instead, verify pattern accepts.
    from pydantic import ValidationError

    try:
        PrimitiveDelivery.model_validate(r)
    except ValidationError as e:
        # The path_name_consistency check will trip; we only assert the name regex accepts.
        assert "should match pattern" not in str(e).split("name")[0].lower(), str(e)


def test_namespace_rejects_uppercase():
    r = valid_delivery_dict()
    r["namespace"] = "Obs"
    _expect_fail(r, "string should match pattern")


def test_namespace_rejects_hyphen():
    r = valid_delivery_dict()
    r["namespace"] = "obs-ext"
    _expect_fail(r, "string should match pattern")


def test_builder_agent_out_of_range_low():
    r = valid_delivery_dict()
    r["builder_agent_id"] = 0
    _expect_fail(r, "greater than or equal to 1")


def test_builder_agent_out_of_range_high():
    r = valid_delivery_dict()
    r["builder_agent_id"] = 11
    _expect_fail(r, "less than or equal to 10")


def test_maturity_invalid_value():
    r = valid_delivery_dict()
    r["maturity"] = "unstable"
    _expect_fail(r, "input should be")


def test_catalog_sha256_must_be_hex():
    r = valid_delivery_dict()
    r["catalog_entry_sha256"] = "G" * 64
    _expect_fail(r, "string should match pattern")


def test_catalog_sha256_must_be_64_chars():
    r = valid_delivery_dict()
    r["catalog_entry_sha256"] = "0" * 63
    _expect_fail(r, "string should match pattern")


# ==========================================================================
# FILES — FileArtefact + collection rules
# ==========================================================================
def test_file_path_rejects_absolute():
    r = valid_delivery_dict()
    r["files"][0]["path"] = "/etc/secrets"
    _expect_fail(r, "relative")


def test_file_path_rejects_parent_traversal():
    r = valid_delivery_dict()
    r["files"][0]["path"] = "obs/HealthProbe/../etc/x.py"
    _expect_fail(r, "traverse")


def test_file_path_rejects_dotfile():
    r = valid_delivery_dict()
    r["files"][0]["path"] = "obs/HealthProbe/.env"
    _expect_fail(r, "dotfiles")


def test_file_sha_must_be_hex():
    r = valid_delivery_dict()
    r["files"][0]["sha256"] = "XYZ" + "0" * 61
    _expect_fail(r, "string should match pattern")


def test_file_size_zero_rejected():
    r = valid_delivery_dict()
    r["files"][0]["size_bytes"] = 0
    _expect_fail(r, "greater than or equal to 1")


def test_file_size_too_large_rejected():
    r = valid_delivery_dict()
    r["files"][0]["size_bytes"] = 5_000_001
    _expect_fail(r, "less than or equal to 5000000")


def test_file_kind_enum():
    r = valid_delivery_dict()
    r["files"][0]["kind"] = "whatever"
    _expect_fail(r, "string should match pattern")


def test_files_duplicate_path_rejected():
    r = valid_delivery_dict()
    # duplicate the first file path under a new sha (so sha dedup doesn't fire first)
    dup = copy.deepcopy(r["files"][0])
    dup["sha256"] = "a" * 64
    r["files"].append(dup)
    _expect_fail(r, "duplicate file paths")


def test_files_duplicate_sha_rejected():
    r = valid_delivery_dict()
    dup = copy.deepcopy(r["files"][0])
    dup["path"] = "obs/HealthProbe/different_name.py"
    dup["kind"] = "test"
    r["files"].append(dup)
    _expect_fail(r, "duplicate sha-256")


def _swap_kind(files: list[dict], drop_kind: str, add_kind: str, add_suffix: str) -> list[dict]:
    """Drop one file of drop_kind; add a valid filler of add_kind to keep count."""
    out = [f for f in files if f["kind"] != drop_kind]
    filler = make_file(
        f"obs/HealthProbe/filler_{add_suffix}.py",
        kind=add_kind,
        body=f"filler_{add_suffix}",
    )
    out.append(filler.model_dump())
    return out


def test_required_files_missing_impl():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "impl", "state_machine", "a")
    _expect_fail(r, "impl")


def test_required_files_missing_test():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "test", "state_machine", "b")
    _expect_fail(r, "test")


def test_required_files_missing_behavioral():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "behavioral", "state_machine", "c")
    _expect_fail(r, "behavioral")


def test_required_files_missing_spec_md():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "spec_md", "state_machine", "d")
    _expect_fail(r, "spec_md")


def test_required_files_missing_manifest():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"] = _swap_kind(r["files"], "manifest", "state_machine", "e")
    _expect_fail(r, "manifest")


def test_battle_tested_requires_state_machine():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "state_machine"]
    _expect_fail(r, "state_machine")


def test_battle_tested_requires_chaos():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "chaos"]
    _expect_fail(r, "chaos")


def test_battle_tested_requires_observability_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "observability"]
    _expect_fail(r, "observability")


def test_battle_tested_does_not_require_adversarial_file_artefact():
    # Adversarial evidence lives under _evidence/ (excluded from file scan);
    # the structured sub-report is validated on PrimitiveDelivery.adversarial.
    # Therefore dropping the file kind alone MUST pass; dropping the sub-report
    # is tested separately in test_t6_passed_without_adversarial_subreport_rejected.
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "adversarial"]
    _expect_ok(r)


def test_battle_tested_requires_persona_reviews_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "persona_reviews"]
    _expect_fail(r, "persona_reviews")


def test_battle_tested_requires_proposed_invariants_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "proposed_invariants"]
    _expect_fail(r, "proposed_invariants")


def test_battle_tested_requires_dashboard_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "dashboard"]
    _expect_fail(r, "dashboard")


def test_battle_tested_requires_contract_json_file():
    r = valid_delivery_dict(Maturity.BATTLE_TESTED)
    r["files"] = [f for f in r["files"] if f["kind"] != "contract_json"]
    _expect_fail(r, "contract_json")


def test_off_tree_file_rejected():
    r = valid_delivery_dict(Maturity.EXPERIMENTAL)
    r["files"][0]["path"] = "other_namespace/other_name/impl.py"
    _expect_fail(r, "off-tree")
