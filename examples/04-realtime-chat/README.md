# Example 04 — Realtime chat backend

**Tier:** mid · **Benchmark spec:** `mid/02_realtime_chat.md`

Room-scoped message fan-out with reconnect replay. Demonstrates the
**`TopicBus` + `SessionCache` + `GracefulShutdown`** recipe.

## What this example shows

- Room `TopicBus` — deliver-once to each connected client.
- Per-client seen offset in `SessionCache` — on reconnect within TTL,
  replay missed messages in order, no duplicates.
- Graceful drain — connected clients receive a `reconnect` hint before
  the socket closes.

## How to run

```bash
cd examples/04-realtime-chat
python3.12 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                          |
| ------------------------------------ | --------------------------------------------- |
| `fastapi_add_websocket_room`         | WS endpoint + room routing.                   |
| `fastapi_add_session_cache`          | Per-connection offset store.                  |
| `fastapi_add_graceful_shutdown`      | Drain hook on SIGTERM.                        |
| `fastapi_add_per_user_connection_cap`| Reject > N sockets per user per room.         |

## Primitives imported

| Primitive           | Role                                                           |
| ------------------- | -------------------------------------------------------------- |
| `TopicBus`          | Room → subscriber fan-out with monotonic offsets.              |
| `SessionCache`      | Per-connection last-seen offset, TTL = 30s.                    |
| `GracefulShutdown`  | Drain handshake + `reconnect` hint broadcast.                  |
| `StreamSubject`     | Ordered stream of messages per room.                           |
| `Bulkhead`          | Caps connections per user to prevent fan-out amplification.    |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
