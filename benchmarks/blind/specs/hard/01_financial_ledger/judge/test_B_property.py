"""Layer B — property-based invariants (hypothesis).

Conservation: for any sequence of deposits + internal transfers,
the sum of account balances equals total deposits. If the agent used
float, hypothesis will find a sequence that drifts.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st


_ACCOUNTS = 4
_MAX_DEPOSIT = 1_000_000
_MAX_TRANSFER = 500_000


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    deposits=st.lists(
        st.tuples(st.integers(0, _ACCOUNTS - 1), st.integers(1, _MAX_DEPOSIT)),
        min_size=1, max_size=6,
    ),
    transfers=st.lists(
        st.tuples(st.integers(0, _ACCOUNTS - 1), st.integers(0, _ACCOUNTS - 1),
                  st.integers(1, _MAX_TRANSFER)),
        min_size=0, max_size=10,
    ),
)
def test_B_property__exact_conservation_under_deposits_and_transfers(
    client: httpx.Client, deposits: list, transfers: list,
) -> None:
    accs = []
    for _ in range(_ACCOUNTS):
        r = client.post("/accounts")
        assert r.status_code in (200, 201), r.text[:200]
        j = r.json()
        accs.append(j.get("id") or j.get("account_id") or j.get("uuid"))

    total_deposited = 0
    for idx, amount in deposits:
        r = client.post(
            f"/accounts/{accs[idx]}/deposit", json={"amount_cents": int(amount)},
        )
        assert r.status_code in (200, 201), r.text[:200]
        total_deposited += int(amount)

    for src_idx, dst_idx, amount in transfers:
        if src_idx == dst_idx:
            continue
        client.post("/transfers", json={
            "source_account_id": accs[src_idx],
            "destination_account_id": accs[dst_idx],
            "amount_cents": int(amount),
            "idempotency_key": str(uuid.uuid4()),
        })  # may 4xx on insufficient funds; conservation still holds

    balances = []
    for a in accs:
        r = client.get(f"/accounts/{a}")
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        balances.append(int(j.get("balance_cents") or j.get("balance") or 0))

    assert sum(balances) == total_deposited, (
        f"conservation violated: deposited={total_deposited} "
        f"sum(balances)={sum(balances)} balances={balances}"
    )


def test_B_property__integer_cents_never_becomes_float(
    client: httpx.Client, open_account, deposit,
) -> None:
    """Agents that use float for money will occasionally return non-integer
    JSON values (e.g. 0.1 + 0.2). Assert integer-ness explicitly.
    """
    import json
    a = open_account()
    # Three awkward deposit amounts that expose float rounding.
    for cents in (10, 20, 30, 1, 3, 7, 100_007):
        deposit(a, cents)
    r = client.get(f"/accounts/{a}")
    assert r.status_code == 200
    raw = r.text
    # The balance field must be an integer literal — reject "0.1", "0.30000004", etc.
    data = json.loads(raw)
    val = data.get("balance_cents", data.get("balance"))
    assert isinstance(val, int), f"balance is {type(val).__name__}: {val!r} in raw={raw!r}"
    assert val == 10 + 20 + 30 + 1 + 3 + 7 + 100_007
