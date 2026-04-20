"""Layer C — concurrent refresh with the same token → at most one succeeds."""
from __future__ import annotations

import threading

import httpx


def test_C_concurrency__concurrent_refresh_same_token_at_most_one_success(
    client: httpx.Client, base_url: str, login,
) -> None:
    sess = login("bob")
    refresh = sess["refresh_token"]

    successes: list[dict] = []
    lock = threading.Lock()

    def worker() -> None:
        with httpx.Client(base_url=base_url, timeout=10.0) as c:
            r = c.post("/refresh", json={"refresh_token": refresh})
            if r.status_code == 200:
                with lock:
                    successes.append(r.json())

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(successes) <= 1, (
        f"same refresh token produced {len(successes)} rotations — must be at most one"
    )
