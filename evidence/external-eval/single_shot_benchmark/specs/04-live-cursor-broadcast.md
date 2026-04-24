# live-cursor-broadcast

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: WebSocket endpoint that broadcasts cursor position to all
connected peers in a "room". Reconnect with last known position.]

## Acceptance criteria

- Connecting to `ws://.../room/{id}` succeeds with valid auth.
- A cursor update from peer A is delivered to peers B + C in <100ms locally.
- Disconnect + reconnect within 30s replays the last cursor state.
- Concurrent broadcasts do not duplicate or skip events.

## Non-requirements

- No persistence of cursor history beyond reconnect window.
- No reaction emojis / chat at v1.
