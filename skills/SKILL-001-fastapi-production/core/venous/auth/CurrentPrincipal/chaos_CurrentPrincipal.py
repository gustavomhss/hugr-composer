"""Chaos / fault-injection for CurrentPrincipal.

Game-day scenarios: adversarial credential strings, mutation attempts from
malicious downstreams, concurrent read contention, log-injection payloads.
"""

from __future__ import annotations

import json
import threading

import pytest

from CurrentPrincipal import (
    CurrentPrincipal,
    PrincipalInvariantError,
    StaticPrincipalProvider,
    anonymous,
    authenticated,
)


def test_chaos_concurrent_reads_are_safe() -> None:
    p = authenticated("a", roles=["admin", "billing"], claims={"k": "v"})
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(500):
                assert p.has_role("admin")
                assert p.claim("k") == "v"
                assert p.for_log()["subject_id"] == "a"
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_chaos_log_injection_in_subject_id_rejected() -> None:
    bad_inputs = [
        "user\nADMIN=true",
        "user\r\nX-Role: admin",
        "user\x1b[31mFAKE\x1b[0m",
        "user\x00admin",
        "\u202euser",  # RTL override
        "\t",
    ]
    for bad in bad_inputs:
        with pytest.raises(PrincipalInvariantError):
            authenticated(bad)


def test_chaos_large_role_set_accepted_but_bounded() -> None:
    # Large role sets are accepted; frozenset behaviour is O(1) per lookup.
    roles = [f"role-{i}" for i in range(10_000)]
    p = authenticated("a", roles=roles)
    assert len(p.roles) == 10_000
    assert p.has_role("role-5000")
    assert not p.has_role("role-99999")


def test_chaos_credential_disclosure_in_for_log() -> None:
    p = authenticated(
        "a",
        claims={
            "Authorization": "Bearer sk-live-LEAK",
            "Cookie": "session=LEAK",
            "x-api-key": "AKIA-LEAK",
            "password": "LEAK",
            "innocent": "public",
        },
    )
    payload = json.dumps(p.for_log(), sort_keys=True)
    for secret in ("sk-live-LEAK", "AKIA-LEAK", "session=LEAK"):
        assert secret not in payload
    # Even non-sensitive-looking keys have values redacted by policy.
    assert "public" not in payload


def test_chaos_provider_table_mutation_after_construction_has_no_effect() -> None:
    table: dict[str, CurrentPrincipal] = {"tok": authenticated("alice", roles=["user"])}
    provider = StaticPrincipalProvider(table)
    # Mutate the source mapping.
    table["tok"] = authenticated("mallory", roles=["admin"])
    # Provider was built over a defensive copy; original binding survives.
    assert provider.resolve("tok").subject_id == "alice"


def test_chaos_reject_non_frozenset_even_if_hashable() -> None:
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="a",
            tenant_id=None,
            roles=("admin",),  # type: ignore[arg-type]  # PRINCIPAL-INV-03: tuple rejected.
            claims={},
            is_anonymous=False,
        )


def test_chaos_anonymous_never_has_roles() -> None:
    # Any attempt to synthesise an "anonymous with privileges" is rejected.
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="",
            tenant_id=None,
            roles=frozenset({"admin"}),
            claims={},
            is_anonymous=True,
        )
    # The canonical anonymous constant has no privileges.
    assert not anonymous().roles


def test_chaos_claims_view_is_read_only_even_under_cast() -> None:
    p = authenticated("a", claims={"k": "v"})
    # Reading through .claims returns a read-only view.
    with pytest.raises(TypeError):
        p.claims["k"] = "mutated"  # type: ignore[index]  # PRINCIPAL-INV-01.
    with pytest.raises(TypeError):
        del p.claims["k"]  # type: ignore[attr-defined]  # PRINCIPAL-INV-01.


def test_chaos_huge_claim_values_do_not_leak_in_repr() -> None:
    huge = "X" * 100_000
    p = authenticated("a", claims={"token": huge})
    assert huge not in repr(p)
    assert huge not in json.dumps(p.for_log())
