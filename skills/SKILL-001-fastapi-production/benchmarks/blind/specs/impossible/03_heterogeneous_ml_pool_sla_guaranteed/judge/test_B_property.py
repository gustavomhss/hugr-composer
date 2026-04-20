"""Layer B — property: session stickiness."""
from __future__ import annotations

import httpx
from hypothesis import HealthCheck, given, settings, strategies as st


@settings(
    max_examples=5, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(sess_id=st.text(
    alphabet=st.characters(min_codepoint=0x61, max_codepoint=0x7A),
    min_size=3, max_size=8,
))
def test_B_property__sticky_session_same_class_majority(
    client: httpx.Client, sess_id: str,
) -> None:
    workers: list[str] = []
    for _ in range(10):
        r = client.post("/infer", json={
            "session_id": sess_id, "deadline_ms": 200, "prompt": "x",
        })
        if r.status_code == 200:
            workers.append(r.json()["worker"])
    if not workers:
        return
    most_common = max(set(workers), key=workers.count)
    ratio = workers.count(most_common) / len(workers)
    assert ratio >= 0.6, f"stickiness broken for {sess_id}: {workers}"
