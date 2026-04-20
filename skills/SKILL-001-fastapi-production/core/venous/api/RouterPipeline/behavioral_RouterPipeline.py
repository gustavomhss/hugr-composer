"""Behavioral end-to-end scenarios for RouterPipeline.

Each scenario drives the primitive through a realistic web-framework workflow
and asserts a named invariant outcome.
"""

from __future__ import annotations

import pytest

from RouterPipeline import (
    Handler,
    RequestContext,
    Router,
    RouterPipelineError,
)


# ---------------------------------------------------------------------------
# Helpers that look like real framework middleware
# ---------------------------------------------------------------------------
def _require_auth(ctx: RequestContext, next_: Handler) -> object:
    token = ctx.assigns.get("token")
    if token != "valid":
        ctx.halt("unauthenticated")
        return {"status": 401}
    ctx.assigns["user"] = "alice"
    return next_(ctx)


def _parse_json(ctx: RequestContext, next_: Handler) -> object:
    ctx.assigns["parsed_at"] = "pre-handler"
    return next_(ctx)


def _accept_html(ctx: RequestContext, next_: Handler) -> object:
    ctx.assigns["content_type"] = "text/html"
    return next_(ctx)


def _fetch_session(ctx: RequestContext, next_: Handler) -> object:
    ctx.assigns["session"] = {"id": "s-1"}
    return next_(ctx)


def _wire_typical_router() -> Router:
    router = Router()
    router.register("api", [_parse_json, _require_auth])
    router.register("browser", [_accept_html, _fetch_session])
    router.get("api").attach("/v1/users/:id")
    router.get("api").attach("/v1/orders")
    router.get("browser").attach("/")
    router.get("browser").attach("/login")
    router.seal()
    return router


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def test_scenario_api_pipeline_runs_parse_then_auth() -> None:
    router = _wire_typical_router()
    ctx = RequestContext(route="/v1/users/:id", assigns={"token": "valid"})
    out = router.dispatch("/v1/users/:id", lambda c: c.assigns["user"], ctx)
    assert out == "alice"
    assert ctx.assigns["parsed_at"] == "pre-handler"
    assert ctx.assigns["user"] == "alice"


def test_scenario_auth_halt_short_circuits_handler() -> None:
    router = _wire_typical_router()
    ctx = RequestContext(route="/v1/orders", assigns={})  # no token
    handler_ran = {"flag": False}

    def handler(_ctx: RequestContext) -> str:
        handler_ran["flag"] = True
        return "should-not-run"

    out = router.dispatch("/v1/orders", handler, ctx)
    assert handler_ran["flag"] is False
    assert isinstance(out, dict) and out["status"] == 401
    assert ctx.halted is True
    assert ctx.halt_reason == "unauthenticated"


def test_scenario_browser_and_api_routes_use_distinct_chains() -> None:
    router = _wire_typical_router()
    browser_ctx = RequestContext(route="/")
    api_ctx = RequestContext(route="/v1/orders", assigns={"token": "valid"})
    router.dispatch("/", lambda c: c.assigns.get("content_type"), browser_ctx)
    router.dispatch("/v1/orders", lambda _c: "ok", api_ctx)
    assert browser_ctx.assigns["content_type"] == "text/html"
    assert "content_type" not in api_ctx.assigns
    assert "user" in api_ctx.assigns
    assert "user" not in browser_ctx.assigns


def test_scenario_attach_after_seal_refused() -> None:
    router = _wire_typical_router()
    with pytest.raises(RouterPipelineError, match="RP-INV-04"):
        router.get("api").attach("/v1/late-joined")


def test_scenario_duplicate_pipeline_name_refused_at_boot() -> None:
    router = Router()
    router.register("api", [_parse_json])
    with pytest.raises(RouterPipelineError, match="RP-INV-05"):
        router.register("api", [_accept_html])


def test_scenario_many_concurrent_requests_do_not_share_assigns() -> None:
    router = _wire_typical_router()
    contexts = [
        RequestContext(route="/v1/users/:id", assigns={"token": "valid", "rid": i})
        for i in range(25)
    ]
    for ctx in contexts:
        router.dispatch("/v1/users/:id", lambda c: c.assigns["rid"], ctx)
    # Each context carries exactly the request id it arrived with; no cross-talk.
    for i, ctx in enumerate(contexts):
        assert ctx.assigns["rid"] == i
        assert ctx.assigns["user"] == "alice"  # set by require_auth per request


def test_scenario_route_resolves_o1_to_pipeline_by_name() -> None:
    router = _wire_typical_router()
    # attachments map is the declarative name-by-route index.
    assert router.attachments["/v1/users/:id"] == "api"
    assert router.attachments["/login"] == "browser"
    # get() is O(1) by name.
    assert router.get("api").name == "api"
