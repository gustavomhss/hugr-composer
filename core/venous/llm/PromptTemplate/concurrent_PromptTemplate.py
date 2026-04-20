"""Concurrency tests for PromptRegistry — linearizability under races."""

from __future__ import annotations

import threading

from PromptTemplate import (
    FrozenPromptTemplate,
    PromptRegistry,
    PromptTemplateInvariantError,
)


def test_concurrent_conflicting_registers_exactly_one_winner() -> None:
    reg = PromptRegistry()
    errs: list[BaseException] = []
    wins: list[str] = []

    def _try(i: int) -> None:
        try:
            tpl = FrozenPromptTemplate(
                name="c", version=1, target_model="m",
                text=f"v{i} {{{{x}}}}", variables=("x",),
            )
            reg.register(tpl)
            wins.append(tpl.fingerprint())
        except PromptTemplateInvariantError as e:
            errs.append(e)

    threads = [threading.Thread(target=_try, args=(i,)) for i in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert len(errs) == 31
    # Winner is resolvable and stable.
    resolved = reg.resolve("c", 1)
    assert resolved.fingerprint() == wins[0]


def test_concurrent_idempotent_identical_registers_all_succeed() -> None:
    reg = PromptRegistry()
    errs: list[BaseException] = []

    def _reg() -> None:
        try:
            reg.register(FrozenPromptTemplate(
                name="c", version=1, target_model="m",
                text="identical {{x}}", variables=("x",),
            ))
        except PromptTemplateInvariantError as e:
            errs.append(e)

    threads = [threading.Thread(target=_reg) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errs == []  # identical fingerprint -> idempotent
    assert reg.versions("c") == (1,)


def test_concurrent_render_is_pure_under_contention() -> None:
    tpl = FrozenPromptTemplate(name="r", version=1, target_model="m",
                                text="Hi {{x}}", variables=("x",))
    results: list[str] = []
    lock = threading.Lock()

    def _go() -> None:
        out = tpl.render({"x": "thread"})
        with lock:
            results.append(out)

    threads = [threading.Thread(target=_go) for _ in range(64)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 64
    assert all(r == "Hi thread" for r in results)


def test_concurrent_versions_view_is_consistent() -> None:
    reg = PromptRegistry()

    def _pub(v: int) -> None:
        reg.register(FrozenPromptTemplate(
            name="p", version=v, target_model="m",
            text=f"p{v} {{{{x}}}}", variables=("x",),
        ))

    threads = [threading.Thread(target=_pub, args=(v,)) for v in range(1, 33)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert reg.versions("p") == tuple(range(1, 33))
