"""Layer B — property: within a 1-s window, the number of 200s for a
class never exceeds the class budget."""
from __future__ import annotations

import time

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st

BUDGETS = {"gold": 20, "silver": 5, "bronze": 1}
KEY_FOR = {"gold": "gold-1", "silver": "silver-1", "bronze": "bronze-1"}


@settings(
    max_examples=6, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(cls=st.sampled_from(["gold", "silver", "bronze"]))
def test_B_property__accepted_within_window_never_exceeds_budget(
    client: httpx.Client, cls: str,
) -> None:
    time.sleep(1.1)
    key = KEY_FOR[cls]
    accepted = 0
    t0 = time.monotonic()
    # Fire budget + 10 in a tight loop (<1s on localhost).
    for _ in range(BUDGETS[cls] + 10):
        r = client.post("/call", json={}, headers={"X-Api-Key": key})
        if r.status_code == 200:
            accepted += 1
        if time.monotonic() - t0 >= 0.9:
            break
    assert accepted <= BUDGETS[cls], (
        f"{cls}: budget {BUDGETS[cls]}, accepted {accepted} in <1s window"
    )
