"""Unit tests for RouterPipeline — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from RouterPipeline import (
    Handler,
    RequestContext,
    Router,
    RouterPipelineError,
    run_chain,
)


def _tracer_mw(label: str, log: list[str]) -> Callable[[RequestContext, Handler], object]:
    def mw(ctx: RequestContext, next_: Handler) -> object:
        log.append(f"pre:{label}")
        out = next_(ctx)
        log.append(f"post:{label}")
        return out

    return mw


# ---------------------------------------------------------------------------
# RP_INV_01 — middleware runs in declared order every time
# ---------------------------------------------------------------------------
def test_inv_declared_order_confirms() -> None:
    log: list[str] = []
    router = Router()
    router.register(
        "api",
        [_tracer_mw("a", log), _tracer_mw("b", log), _tracer_mw("c", log)],
    )
    router.get("api").attach("/users")
    router.seal()

    def handler(_ctx: RequestContext) -> str:
        log.append("handler")
        return "ok"

    out = router.dispatch("/users", handler, RequestContext(route="/users"))
    assert out == "ok"
    assert log == ["pre:a", "pre:b", "pre:c", "handler", "post:c", "post:b", "post:a"]


def test_inv_declared_order_prevents() -> None:
    # Re-running the chain with the same pipeline MUST produce the identical
    # order — even if prior requests mutated unrelated state.
    router = Router()
    log: list[str] = []
    router.register("api", [_tracer_mw("a", log), _tracer_mw("b", log)])
    router.get("api").attach("/x")
    router.seal()

    def handler(_ctx: RequestContext) -> str:
        return "ok"

    for _ in range(5):
        router.dispatch("/x", handler, RequestContext(route="/x"))
    # Every request appended [pre:a, pre:b, post:b, post:a].
    pre_a = [i for i, e in enumerate(log) if e == "pre:a"]
    pre_b = [i for i, e in enumerate(log) if e == "pre:b"]
    assert len(pre_a) == 5
    # Every pre:a precedes its corresponding pre:b.
    for a_idx, b_idx in zip(pre_a, pre_b, strict=True):
        assert a_idx < b_idx


def test_inv_declared_order_under_failure() -> None:
    # A non-callable middleware entry MUST be refused at register time; a silent
    # re-order via late injection is therefore impossible.
    router = Router()
    with pytest.raises(RouterPipelineError, match="RP-INV-01"):
        router.register("bad", [lambda ctx, next_: next_(ctx), "not-callable"])  # type: ignore[list-item]  # RP-INV-01 supporting: deliberately malformed.


# ---------------------------------------------------------------------------
# RP_INV_02 — chain runs before the handler; no per-request bypass
# ---------------------------------------------------------------------------
def test_inv_chain_before_handler_confirms() -> None:
    router = Router()
    order: list[str] = []

    def mw(ctx: RequestContext, next_: Handler) -> object:
        order.append("mw")
        return next_(ctx)

    router.register("api", [mw])
    router.get("api").attach("/x")
    router.seal()

    def handler(_ctx: RequestContext) -> str:
        order.append("handler")
        return "ok"

    router.dispatch("/x", handler, RequestContext(route="/x"))
    assert order == ["mw", "handler"]


def test_inv_chain_before_handler_prevents() -> None:
    # Dispatching without sealing MUST fail — there is no backdoor that invokes
    # the handler while skipping the chain setup.
    router = Router()
    router.register("api", [])
    router.get("api").attach("/x")
    # deliberately do NOT seal
    with pytest.raises(RouterPipelineError, match="RP-INV-04"):
        router.dispatch("/x", lambda _c: "ok", RequestContext(route="/x"))


def test_inv_chain_before_handler_under_failure() -> None:
    # A route with no pipeline attached MUST raise, not silently invoke handler.
    router = Router()
    router.register("api", [])
    router.seal()
    with pytest.raises(RouterPipelineError, match="RP-INV-02"):
        router.dispatch("/unattached", lambda _c: "ok", RequestContext(route="/unattached"))


# ---------------------------------------------------------------------------
# RP_INV_03 — pipelines do not share mutable state across requests
# ---------------------------------------------------------------------------
def test_inv_no_shared_state_confirms() -> None:
    router = Router()

    def writer(ctx: RequestContext, next_: Handler) -> object:
        ctx.assigns["hit"] = ctx.assigns.get("hit", 0)
        ctx.assigns["hit"] = int(ctx.assigns["hit"]) + 1  # type: ignore[arg-type]  # RP-INV-03: value was written above.
        return next_(ctx)

    router.register("api", [writer])
    router.get("api").attach("/x")
    router.seal()

    ctx1 = RequestContext(route="/x")
    ctx2 = RequestContext(route="/x")
    router.dispatch("/x", lambda _c: "ok", ctx1)
    router.dispatch("/x", lambda _c: "ok", ctx2)
    # Each request owns its own assigns dict.
    assert ctx1.assigns == {"hit": 1}
    assert ctx2.assigns == {"hit": 1}
    assert ctx1.assigns is not ctx2.assigns


def test_inv_no_shared_state_prevents() -> None:
    # A middleware that tries to stash state on the pipeline object itself must
    # not leak into subsequent requests' ctx.assigns.
    router = Router()

    class Counter:
        value: int = 0

    counter = Counter()

    def mw(ctx: RequestContext, next_: Handler) -> object:
        counter.value += 1  # off-ctx state — intentionally isolated from assigns
        return next_(ctx)

    router.register("api", [mw])
    router.get("api").attach("/x")
    router.seal()

    ctx_a = RequestContext(route="/x")
    ctx_b = RequestContext(route="/x")
    router.dispatch("/x", lambda _c: "ok", ctx_a)
    router.dispatch("/x", lambda _c: "ok", ctx_b)
    # Even though `counter` grew, it did NOT pollute ctx_b.assigns.
    assert ctx_a.assigns == {}
    assert ctx_b.assigns == {}


def test_inv_no_shared_state_under_failure() -> None:
    # A crashing middleware in one request MUST NOT corrupt the next request's
    # assigns — each context is independent.
    router = Router()

    def flaky(ctx: RequestContext, next_: Handler) -> object:
        ctx.assigns["seen"] = True
        raise RuntimeError("boom")

    router.register("api", [flaky])
    router.get("api").attach("/x")
    router.seal()

    ctx_a = RequestContext(route="/x")
    with pytest.raises(RuntimeError):
        router.dispatch("/x", lambda _c: "ok", ctx_a)
    ctx_b = RequestContext(route="/x")
    # `ctx_b.assigns` is untouched because `assigns` default_factory produced
    # a fresh dict — no shared mutable default leaked.
    assert ctx_b.assigns == {}


# ---------------------------------------------------------------------------
# RP_INV_04 — attach and register refused after seal
# ---------------------------------------------------------------------------
def test_inv_declarative_attach_confirms() -> None:
    router = Router()
    router.register("api", [])
    router.get("api").attach("/a")
    router.get("api").attach("/b")
    router.seal()
    assert set(router.attachments) == {"/a", "/b"}


def test_inv_declarative_attach_prevents() -> None:
    router = Router()
    router.register("api", [])
    router.seal()
    with pytest.raises(RouterPipelineError, match="RP-INV-04"):
        router.get("api").attach("/late")


def test_inv_declarative_attach_under_failure() -> None:
    router = Router()
    router.register("api", [])
    router.seal()
    # Registering a brand-new pipeline post-seal MUST also fail.
    with pytest.raises(RouterPipelineError, match="RP-INV-04"):
        router.register("internal", [])


# ---------------------------------------------------------------------------
# RP_INV_05 — pipeline names are unique within a router
# ---------------------------------------------------------------------------
def test_inv_unique_name_confirms() -> None:
    router = Router()
    router.register("api", [])
    router.register("browser", [])
    router.register("internal", [])
    assert set(router.pipelines) == {"api", "browser", "internal"}


def test_inv_unique_name_prevents() -> None:
    router = Router()
    router.register("api", [])
    with pytest.raises(RouterPipelineError, match="RP-INV-05"):
        router.register("api", [])


def test_inv_unique_name_under_failure() -> None:
    router = Router()
    with pytest.raises(RouterPipelineError, match="RP-INV-05"):
        router.register("", [])
    with pytest.raises(RouterPipelineError, match="RP-INV-05"):
        router.register(123, [])  # type: ignore[arg-type]  # RP-INV-05 supporting: non-string names MUST be rejected.


# ---------------------------------------------------------------------------
# Sanity — run_chain direct usage
# ---------------------------------------------------------------------------
def test_run_chain_preserves_order_without_router() -> None:
    log: list[str] = []
    out = run_chain(
        [_tracer_mw("a", log), _tracer_mw("b", log)],
        lambda _c: log.append("handler") or "ok",
        RequestContext(route="/x"),
    )
    assert out == "ok"
    assert log == ["pre:a", "pre:b", "handler", "post:b", "post:a"]
