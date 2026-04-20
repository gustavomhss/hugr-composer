# Maestro session — 04-realtime-chat

Plan-level transcript for `mid/02_realtime_chat.md` (v0.1.0 run, score 100).

## Requirement → kit mapping

1. **< 200 ms fan-out under 500 concurrent clients.**
   → `TopicBus` with non-blocking publish + per-subscriber async queue.
2. **Reconnect with missed-message replay.**
   → `SessionCache` stores last-seen offset (key=`(conn_id, room_id)`, TTL=30s).
     On reconnect, query `StreamSubject` for `(offset, now]`.
3. **No fan-out amplification from one user.**
   → `Bulkhead` with `max_conns_per_user_per_room=3`.
4. **Graceful drain on SIGTERM.**
   → `GracefulShutdown` → broadcast `{"event":"reconnect"}` → await
     in-flight sends → close sockets.

## Tool call sequence

```
1. fastapi_generate_project(name="chat")
2. fastapi_add_websocket_room(path="/ws/rooms/{id}")
3. fastapi_add_session_cache(on="ws_offset", ttl_s=30)
4. fastapi_add_per_user_connection_cap(max_per_room=3)
5. fastapi_add_graceful_shutdown(hooks=["ws_reconnect_hint"])
```

## Benchmark outcome

- Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
