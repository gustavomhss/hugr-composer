from __future__ import annotations


async def graphql_ws_handler(websocket: WebSocket) -> None:
    """Handle a single GraphQL WebSocket connection (graphql-ws protocol).

    Accepts the WebSocket, resolves a per-connection context (including
    optional JWT auth from ``connection_init``), then delegates to the
    Strawberry schema's WebSocket handler.

    Args:
        websocket: Incoming Starlette ``WebSocket`` connection.
    """
    from app.graphql.schema import schema as _schema
    from app.core.config import settings as _settings
    keepalive_ms: int = getattr(_settings, 'GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS', 30000)
    enabled: bool = getattr(_settings, 'GRAPHQL_WS_ENABLED', True)
    if not enabled:
        await websocket.close(code=4400, reason='GraphQL subscriptions disabled.')
        return
    context = await _build_ws_context(websocket)
    await _schema.handle_websocket(websocket, context_value=context)
