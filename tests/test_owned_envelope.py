"""``hugr-owned-tool-v1``: the canonical envelope on the two Composer tools that write.

The inventory must be what the filesystem shows, so the failure paths run real writes against a temp tree and
only the producer is replaced where a real failure cannot be provoked deterministically.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_tools import compose, owned_envelope, tier1
from mcp_tools.error_codes import ERROR_CODES

LEGACY_KEYS = {"ok", "code", "what_happened", "result", "next_steps", "elapsed_ms"}
CANONICAL_KEYS = {
    "schema",
    "tool",
    "status",
    "effects",
    "observed_changes",
    "mode",
    "artifact_kind",
}
PRIMS = ["SessionCache"]  # ad_hoc skeleton
ADAPTER = ["WebhookReceiverAdapter"]


def paths(envelope: dict) -> set[str]:
    return {c["path"] for c in envelope["observed_changes"]}


def files_on_disk(root: Path) -> set[str]:
    return {
        os.path.relpath(os.path.join(d, f), root) for d, _, names in os.walk(root) for f in names
    }


def assert_canonical(
    envelope: dict, tool: str, status: str, effects: str, code: str | None = None
) -> None:
    assert LEGACY_KEYS <= envelope.keys() and CANONICAL_KEYS <= envelope.keys()
    assert envelope["schema"] == "hugr-owned-tool-v1"
    assert (envelope["tool"], envelope["status"], envelope["effects"]) == (tool, status, effects)
    assert envelope.get("error", {}).get("code") == code
    if code is not None:
        assert envelope["error"]["producer_code"] == envelope["code"]


# ---- compose ---------------------------------------------------------------------------------------------------


def test_compose_dry_run_is_previewed_with_no_effects(tmp_path: Path) -> None:
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS, dry_run=True)
    assert_canonical(r, "hugr-compose", "previewed", "none")
    assert r["ok"] is True and r["code"] is None
    assert r["observed_changes"] == []
    assert r["artifacts"][0]["content"] == r["result"]["composition_source"]
    assert r["planned_files"] == [r["artifacts"][0]["path"]]
    assert (r["mode"], r["artifact_kind"]) == ("ad_hoc", "skeleton")
    assert list(tmp_path.iterdir()) == []


def test_compose_write_reports_exactly_what_changed(tmp_path: Path) -> None:
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    assert_canonical(r, "hugr-compose", "generated", "observed")
    assert {c["change"] for c in r["observed_changes"]} == {"created"}
    assert paths(r) - {"app/", "app/compositions/"} == files_on_disk(tmp_path)
    assert paths(r) >= set(r["result"]["files_written"])


def test_compose_force_overwrite_is_modified_and_leaves_bystanders_out(tmp_path: Path) -> None:
    first = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    bystander = tmp_path / "app" / "keep.py"
    bystander.write_text("x = 1\n")
    target = next(p for p in paths(first) if p.endswith(".py") and "__init__" not in p)
    os.utime(tmp_path / target, ns=(1, 1))  # a rewrite must show even when sizes match

    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS, force=True)
    assert_canonical(r, "hugr-compose", "generated", "observed")
    assert r["observed_changes"] == [{"path": target, "change": "modified"}]


def test_compose_inventory_includes_writes_the_tool_did_not_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = compose._emit_ad_hoc

    def noisy(*args, **kwargs):
        (tmp_path / "app").mkdir(exist_ok=True)
        (tmp_path / "app" / "stray.txt").write_text("unclaimed")
        return real(*args, **kwargs)

    monkeypatch.setattr(compose, "_emit_ad_hoc", noisy)
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    assert "app/stray.txt" in paths(r)
    assert "app/stray.txt" not in r["result"]["files_written"]


def test_compose_tool_delegate_is_blocked_not_generated(tmp_path: Path) -> None:
    r = compose.fastapi_meta_compose(
        output_dir=str(tmp_path), primitives=["AuditEvent", "TamperEvidentAuditLog"]
    )
    assert_canonical(r, "hugr-compose", "blocked", "none", "UNSUPPORTED_OUTPUT")
    assert r["ok"] is True and r["code"] is None and r["mode"] == "tool_delegate"
    assert r["observed_changes"] == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("kwargs", "producer", "f4"),
    [
        ({}, "missing-selection", "INVALID_INPUT"),
        ({"primitives": ["DoesNotExist"]}, "unknown-primitive", "SELECTION_UNAVAILABLE"),
        ({"recipe_id": "bogus__00"}, "unknown-recipe", "SELECTION_UNAVAILABLE"),
        ({"primitives": ["Aggregate", "SessionCache"]}, "domain-boundary", "UNSUPPORTED_OUTPUT"),
    ],
)
def test_compose_refusals_are_blocked_before_any_write(
    tmp_path: Path, kwargs: dict, producer: str, f4: str
) -> None:
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), **kwargs)
    assert_canonical(r, "hugr-compose", "blocked", "none", f4)
    assert (r["ok"], r["code"]) == (False, producer)
    assert list(tmp_path.iterdir()) == []


def test_compose_recipe_mismatch_and_existing_target_are_blocked(tmp_path: Path) -> None:
    recipe = compose._load_catalog()["recipes"][0]["id"]
    r = compose.fastapi_meta_compose(
        output_dir=str(tmp_path), recipe_id=recipe, primitives=["NotInRecipe"]
    )
    assert_canonical(r, "hugr-compose", "blocked", "none", "INVALID_INPUT")

    compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    again = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    assert_canonical(again, "hugr-compose", "blocked", "none", "OUTPUT_CONFLICT")
    assert again["code"] == "target-exists" and again["observed_changes"] == []


def test_compose_create_race_fails_with_conflict_and_keeps_the_other_writers_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = compose._ast_validate
    target = tmp_path / "app" / "compositions" / "racer.py"

    def other_writer_wins(source: str):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("theirs")
        return real(source)

    monkeypatch.setattr(compose, "_ast_validate", other_writer_wins)
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS, name="racer")
    # The other writer's file is a write under the observed tree, so it is inventoried; ours never happened.
    assert_canonical(r, "hugr-compose", "failed", "partial", "OUTPUT_CONFLICT")
    assert (r["ok"], r["code"]) == (False, "target-exists")
    assert target.read_text() == "theirs"
    assert paths(r) - {"app/", "app/compositions/"} == {"app/compositions/racer.py"}
    assert not (target.parent / "__init__.py").exists()


def test_compose_midway_write_failure_is_partial_with_the_written_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Path.write_text

    def fail_on_init(self: Path, *args, **kwargs):
        if self.name == "__init__.py":
            raise OSError("disk full")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_init)
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    assert_canonical(r, "hugr-compose", "failed", "partial", "PRODUCER_FAILED")
    assert (r["ok"], r["code"]) == (False, "write-failed")
    assert paths(r) - {"app/", "app/compositions/"} == files_on_disk(tmp_path)
    assert len(files_on_disk(tmp_path)) == 1


def test_compose_permission_error_maps_to_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(*args, **kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr("builtins.open", deny)
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    assert_canonical(r, "hugr-compose", "failed", "partial", "PERMISSION_DENIED")
    assert r["code"] == "write-failed"
    assert paths(r) == {
        "app/",
        "app/compositions/",
    }  # the directories were created before the denial


def test_compose_invalid_emission_fails_without_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "_ast_validate", lambda source: (False, "forced"))
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS, dry_run=True)
    assert_canonical(r, "hugr-compose", "failed", "none", "INVALID_PRODUCER_RESULT")
    assert r["code"] == "invalid-output"


def test_compose_unobservable_tree_is_never_generated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(owned_envelope, "MAX_ENTRIES", 1)
    r = compose.fastapi_meta_compose(output_dir=str(tmp_path), primitives=PRIMS)
    assert_canonical(r, "hugr-compose", "failed", "unknown", "INVALID_PRODUCER_RESULT")
    assert r["observed_changes"] == []


def test_compose_adapter_reuse_is_a_composition(tmp_path: Path) -> None:
    r = compose.fastapi_meta_compose(
        output_dir=str(tmp_path),
        primitives=[
            "SignatureVerifier",
            "IdempotentConsumer",
            "AuditEvent",
            "InboxDeduplicator",
            "TransactionalOutbox",
        ],
        mount_path="/webhooks/in",
        dry_run=True,
    )
    assert r["mode"] == "adapter_reuse" and r["artifact_kind"] == "composition"


# ---- scaffold --------------------------------------------------------------------------------------------------


def scaffold(out: Path, **kwargs) -> dict:
    return tier1.fastapi_meta_scaffold(
        output_dir=str(out), name="demo", profile="minimal", with_auth=False, **kwargs
    )


def test_scaffold_inventory_is_the_tree_it_produced(tmp_path: Path) -> None:
    r = scaffold(tmp_path)
    assert_canonical(r, "hugr-scaffold", "generated", "observed")
    assert (r["mode"], r["artifact_kind"]) == ("minimal", "scaffold")
    assert {c["change"] for c in r["observed_changes"]} == {"created"}
    assert {p for p in paths(r) if not p.endswith("/")} == files_on_disk(tmp_path)
    assert (
        len(r["observed_changes"]) > len(r["result"]["files_created"]) // 2
    )  # non-trivial, not a stub


def test_scaffold_reports_modified_and_skips_untouched_files(tmp_path: Path) -> None:
    scaffold(tmp_path)
    (tmp_path / "mine.txt").write_text("keep")
    victim = next(p for p in sorted(files_on_disk(tmp_path)) if p != "mine.txt")
    os.utime(tmp_path / victim, ns=(1, 1))
    r = scaffold(tmp_path)
    changes = {c["path"]: c["change"] for c in r["observed_changes"]}
    assert changes[victim] == "modified"
    assert "mine.txt" not in changes


def test_scaffold_rejected_input_is_blocked(tmp_path: Path) -> None:
    r = tier1.fastapi_meta_scaffold(output_dir=str(tmp_path / "x"), profile="nope")
    assert_canonical(r, "hugr-scaffold", "blocked", "none", "INVALID_INPUT")
    assert (r["ok"], r["code"]) == (False, "scaffold-failed")
    assert not (tmp_path / "x").exists()


def test_scaffold_failure_after_writes_is_partial_with_those_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dies_midway(output_dir: str, **kwargs):
        Path(output_dir).mkdir()
        (Path(output_dir) / "half.py").write_text("x")
        raise ValueError(
            "late validation"
        )  # a ValueError is not "blocked" once something was written

    monkeypatch.setattr("generators.orchestrator.generate_project", dies_midway)
    r = tier1.fastapi_meta_scaffold(output_dir=str(tmp_path / "out"))
    assert_canonical(r, "hugr-scaffold", "failed", "partial", "PRODUCER_FAILED")
    assert paths(r) == {"./", "half.py"}


def test_scaffold_claimed_success_without_observed_files_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "generators.orchestrator.generate_project", lambda **kwargs: {"files_created": ["ghost.py"]}
    )
    (tmp_path / "existing").mkdir()
    r = tier1.fastapi_meta_scaffold(output_dir=str(tmp_path / "existing"))
    assert_canonical(r, "hugr-scaffold", "failed", "none", "INVALID_PRODUCER_RESULT")
    assert (r["ok"], r["code"]) == (False, "scaffold-failed")


def test_scaffold_permission_error_maps_to_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(**kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr("generators.orchestrator.generate_project", denied)
    r = tier1.fastapi_meta_scaffold(output_dir=str(tmp_path))
    assert_canonical(r, "hugr-scaffold", "failed", "none", "PERMISSION_DENIED")


def test_scaffold_unobservable_tree_is_never_generated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(owned_envelope, "MAX_ENTRIES", 1)
    r = scaffold(tmp_path)
    assert_canonical(r, "hugr-scaffold", "failed", "unknown", "INVALID_PRODUCER_RESULT")


# ---- both tools ------------------------------------------------------------------------------------------------


def test_path_guard_refusal_is_blocked_on_both_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "worktree").mkdir()
    monkeypatch.setenv("HUGR_WORKTREE_ROOT", str(tmp_path / "worktree"))
    outside = str(tmp_path / "outside")
    assert_canonical(
        compose.fastapi_meta_compose(output_dir=outside, primitives=PRIMS),
        "hugr-compose",
        "blocked",
        "none",
        "PERMISSION_DENIED",
    )
    assert_canonical(
        tier1.fastapi_meta_scaffold(output_dir=outside),
        "hugr-scaffold",
        "blocked",
        "none",
        "PERMISSION_DENIED",
    )
    assert not (tmp_path / "outside").exists()


def test_write_failed_is_in_the_closed_set() -> None:
    assert "write-failed" in ERROR_CODES


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "status": "generated",
            "effects": "none",
            "observed_changes": [{"path": "a", "change": "created"}],
        },
        {"status": "generated", "effects": "observed"},
        {
            "status": "generated",
            "effects": "observed",
            "observed_changes": [{"path": "a", "change": "created"}],
            "code": "PRODUCER_FAILED",
        },
        {"status": "previewed", "effects": "observed", "artifacts": [{"kind": "source"}]},
        {"status": "previewed", "effects": "none"},
        {"status": "blocked", "effects": "partial", "code": "INVALID_INPUT"},
        {"status": "blocked", "effects": "none", "code": "PRODUCER_FAILED"},
        {"status": "blocked", "effects": "none"},
        {"status": "failed", "effects": "none"},
        {"status": "failed", "effects": "none", "code": "INVALID_INPUT"},
        {"status": "interrupted", "effects": "observed", "code": "CANCELLED"},
        {"status": "done", "effects": "none"},
    ],
)
def test_illegal_status_effects_code_combinations_are_refused(kwargs: dict) -> None:
    with pytest.raises((ValueError, KeyError)):
        owned_envelope.owned(tool="hugr-compose", **kwargs)


def test_unknown_tool_is_refused() -> None:
    with pytest.raises(ValueError):
        owned_envelope.owned(
            tool="hugr-search", status="blocked", effects="none", code="INVALID_INPUT"
        )
