# Mobile backend as a service

## Requirements

- Sync endpoint: client sends last-seen cursor; server returns all records changed since that cursor.
- Push notifications: server triggers a notification to a user's registered devices.
- Device registration: a client registers its push token at login; unregisters at logout.
- Conflict resolution: if a client pushes an update that conflicts with server state, the server's version wins and the client is told.
- Offline-tolerant: a client can batch its queued mutations and send them on reconnect.

## Acceptance criteria

- Two clients pushing conflicting updates to the same record: both receive a clear conflict response; server state reflects one winner and both clients converge on the next sync.
- A push notification is delivered to all of a user's active devices; stale tokens that are rejected by the push provider are removed from the registry.
- Sync cursor is monotonic: consecutive sync requests never show records older than the cursor.
- A batch of 100 mutations from one client is processed atomically or reports precise per-item failures.

## Non-requirements

- No realtime sync (polling is fine).
- No end-to-end encryption.
- No server-side image resizing.
- No geofencing.
