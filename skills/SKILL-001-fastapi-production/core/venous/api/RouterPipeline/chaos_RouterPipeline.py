"""Chaos / fault-injection for RouterPipeline.

Game-day scenarios: crashing middleware, late attach attempts, duplicate
registration under thread contention, bogus route lookup, halted chains,
mutating a sealed router. The primitive MUST preserve the five invariants.
"""

from __future__ import annotations

import threading

import pytest

from RouterPipeline import (
    Handler,
    RequestContext,
    Router,
    RouterPipelineError,
)


def _noop(ctx: RequestContext, next_: Handler) -> object:
    return next_(ctx)


def test_chaos_crashing_middleware_propagates_and_isolates_contexts() -> None:
    router = Router()

    def boom(_ctx: RequestContext, _next: Handler) -> object:
        raise RuntimeError("middleware crash")

    router.register("api", [boom])
    router.get("api").attach("/x")
    router.seal()

    ctx_crashed = RequestContext(route="/x")
    with pytest.raises(RuntimeError):
        router.dispatch("/x", lambda _c: "ok", ctx_crashed)
    # A subsequent request with a fresh context observes no residue.
    ctx_next = RequestContext(route="/x")
    with pytest.raises(RuntimeError):
        router.dispatch("/x", lambda _c: "ok", ctx_next)
    assert ctx_next.assigns == {}


def test_chaos_concurrent_registration_serialised() -> None:
    router = Router()
    winners: list[bool] = []
    failures: list[BaseException] = []

    def try_register() -> None:
        try:
            router.register("api", [_noop])
            winners.append(True)
        except RouterPipelineError:
            pass  # Expected: RP-INV-05 for all but one thread.
        except BaseException as exc:  # pragma: no cover
            failures.append(exc)

    threads = [threading.Thread(target=try_register) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not failures
    assert len(winners) == 1  # exactly one registration succeeded
    assert set(router.pipelines) == {"api"}


def test_chaos_attach_after_seal_is_refused_loudly() -> None:
    router = Router()
    router.register("api", [])
    router.seal()
    with pytest.raises(RouterPipelineError, match="RP-INV-04"):
        router.get("api").attach("/sneaky")


def test_chaos_dispatch_unattached_route_fails_fast() -> None:
    router = Router()
    router.register("api", [])
    router.get("api").attach("/known")
    router.seal()
    with pytest.raises(RouterPipelineError, match="RP-INV-02"):
        router.dispatch("/unknown", lambda _c: "ok", RequestContext(route="/unknown"))


def test_chaos_route_double_attach_across_pipelines_refused() -> None:
    router = Router()
    router.register("api", [])
    router.register("browser", [])
    router.get("api").attach("/shared")
    with pytest.raises(RouterPipelineError, match="RP-INV-02"):
        router.get("browser").attach("/shared")


def test_chaos_halt_preserves_invariant_chain_up_to_halt() -> None:
    router = Router()
    seen: list[str] = []

    def a(ctx: RequestContext, next_: Handler) -> object:
        seen.append("a")
        return next_(ctx)

    def halter(ctx: RequestContext, _next: Handler) -> object:
        seen.append("halt")
        ctx.halt("denied")
        return {"status": 403}

    def c(ctx: RequestContext, next_: Handler) -> object:
        seen.append("c")  # should NOT run
        return next_(ctx)

    router.register("api", [a, halter, c])
    router.get("api").attach("/x")
    router.seal()

    out = router.dispatch("/x", lambda _c: "handler", RequestContext(route="/x"))
    assert isinstance(out, dict) and out["status"] == 403
    assert seen == ["a", "halt"]  # 'c' never ran — but a and halt did, in order


def test_chaos_storm_of_requests_preserves_per_context_isolation() -> None:
    router = Router()

    def stamp(ctx: RequestContext, next_: Handler) -> object:
        ctx.assigns["stamp"] = ctx.assigns.get("rid")
        return next_(ctx)

    router.register("api", [stamp])
    router.get("api").attach("/x")
    router.seal()

    contexts = [RequestContext(route="/x", assigns={"rid": i}) for i in range(100)]
    threads = [
        threading.Thread(
            target=router.dispatch,
            args=("/x", lambda _c: "ok", ctx),
        )
        for ctx in contexts
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i, ctx in enumerate(contexts):
        assert ctx.assigns["stamp"] == i


def test_chaos_empty_name_registration_refused() -> None:
    router = Router()
    with pytest.raises(RouterPipelineError, match="RP-INV-05"):
        router.register("", [])


def test_chaos_get_unknown_pipeline_raises() -> None:
    router = Router()
    with pytest.raises(RouterPipelineError, match="RP-INV-05"):
        router.get("ghost")
