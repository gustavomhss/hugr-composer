# Realtime chat backend

## Requirements

- Users authenticate and open a persistent bidirectional connection.
- Messages sent to a room are delivered to all connected room members in under 200 ms.
- Disconnected clients, on reconnect, receive the messages they missed since their last seen offset.
- A room supports up to 1000 concurrent members on one backend node before sharding.
- Messages are persisted for 30 days; older messages are purged.

## Acceptance criteria

- Under 500 concurrent clients in one room, end-to-end message fan-out p95 latency < 200 ms.
- After a client disconnects for 10s and reconnects, it receives every message sent during the gap, in order, with no duplicates.
- A malicious client that opens 10 connections to the same room is not allowed to amplify fan-out above the per-user limit.
- Shutting down a node drains open connections: every connected client receives a "reconnect" hint before the socket is closed.

## Non-requirements

- No presence indicators beyond "connected" / "disconnected".
- No typing indicators.
- No file uploads.
- No end-to-end encryption — server reads messages for storage.
