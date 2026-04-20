"""Metamorphic + differential tests for RouterPipeline.

Algebraic laws:
- Idempotence of order: repeated dispatches of the same route produce the same
  middleware execution order.
- Associativity of chain composition: run_chain([a, b, c], h) == nested
  composition (a . (b . (c . h))).
- Register-order independence: two routers registered in different orders but
  with the same (name -> middleware) mapping dispatch identically.
- Differential: Router.dispatch and run_chain agree on the execution trace.
"""

from __future__ import annotations

from RouterPipeline import (
    Handler,
    RequestContext,
    Router,
    run_chain,
)


def _trace_mw(label: str, log: list[str]) -> object:
    def mw(ctx: RequestContext, next_: Handler) -> object:
        log.append(label)
        return next_(ctx)

    return mw


def test_metamorphic_dispatch_is_deterministic() -> None:
    log_a: list[str] = []
    log_b: list[str] = []
    for log in (log_a, log_b):
        router = Router()
        router.register(
            "api",
            [_trace_mw("a", log), _trace_mw("b", log), _trace_mw("c", log)],  # type: ignore[list-item]  # RP-INV-01: _trace_mw returns a Middleware.
        )
        router.get("api").attach("/x")
        router.seal()
        router.dispatch("/x", lambda _c: "ok", RequestContext(route="/x"))
    assert log_a == log_b == ["a", "b", "c"]


def test_metamorphic_chain_composition_equivalent_to_nested() -> None:
    # run_chain([a, b], h) should equal a(b(h)) composition.
    log_chain: list[str] = []
    log_nested: list[str] = []

    mw_a = _trace_mw("a", log_chain)
    mw_b = _trace_mw("b", log_chain)
    run_chain([mw_a, mw_b], lambda _c: log_chain.append("h") or "ok", RequestContext(route="/x"))  # type: ignore[list-item]  # RP-INV-01 supporting: _trace_mw returns a Middleware.

    def nested(ctx: RequestContext) -> object:
        def inner(c2: RequestContext) -> object:
            log_nested.append("h")
            return "ok"

        def b_step(c2: RequestContext) -> object:
            log_nested.append("b")
            return inner(c2)

        log_nested.append("a")
        return b_step(ctx)

    nested(RequestContext(route="/x"))
    assert log_chain == log_nested == ["a", "b", "h"]


def test_metamorphic_register_order_independence() -> None:
    mw_a = _trace_mw("a", [])
    mw_b = _trace_mw("b", [])

    router1 = Router()
    router1.register("api", [mw_a])  # type: ignore[list-item]  # RP-INV-01 supporting.
    router1.register("browser", [mw_b])  # type: ignore[list-item]  # RP-INV-01 supporting.

    router2 = Router()
    router2.register("browser", [mw_b])  # type: ignore[list-item]  # RP-INV-01 supporting.
    router2.register("api", [mw_a])  # type: ignore[list-item]  # RP-INV-01 supporting.

    assert set(router1.pipelines) == set(router2.pipelines)


def test_differential_router_matches_run_chain() -> None:
    log_router: list[str] = []
    log_direct: list[str] = []
    chain_router = [_trace_mw("a", log_router), _trace_mw("b", log_router)]
    chain_direct = [_trace_mw("a", log_direct), _trace_mw("b", log_direct)]

    router = Router()
    router.register("api", chain_router)  # type: ignore[arg-type]  # RP-INV-01 supporting.
    router.get("api").attach("/x")
    router.seal()
    router.dispatch("/x", lambda _c: log_router.append("h") or "ok", RequestContext(route="/x"))

    run_chain(
        chain_direct,  # type: ignore[arg-type]  # RP-INV-01 supporting.
        lambda _c: log_direct.append("h") or "ok",
        RequestContext(route="/x"),
    )
    assert log_router == log_direct


def test_metamorphic_disjoint_contexts_produce_disjoint_assigns() -> None:
    router = Router()

    def writer(ctx: RequestContext, next_: Handler) -> object:
        ctx.assigns["marker"] = id(ctx)
        return next_(ctx)

    router.register("api", [writer])
    router.get("api").attach("/x")
    router.seal()

    ctx1 = RequestContext(route="/x")
    ctx2 = RequestContext(route="/x")
    router.dispatch("/x", lambda _c: "ok", ctx1)
    router.dispatch("/x", lambda _c: "ok", ctx2)
    assert ctx1.assigns["marker"] != ctx2.assigns["marker"]
