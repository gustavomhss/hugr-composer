# Stateless API with session-aware behavior

## Requirements

- The API tier must be completely stateless so any request can hit any node.
- Requests must behave as if the caller has a session: per-caller rate limits, quota, feature flags, and last-seen cursor must persist across calls.
- No sticky load balancing; any node must be able to handle any request within 10 ms of cold cache.
- No shared file system between nodes.

## Acceptance criteria

- Killing the node serving a call mid-session does not lose the caller's remaining quota or last-seen cursor on the next call.
- Enabling a feature flag for a caller propagates to all nodes within 1 second.
- A load test that routes each caller randomly across nodes shows per-caller behavior identical to sticky routing.
- Cold cache for a new node does not cause per-caller rate limits to reset to zero.

## Non-requirements

- No per-caller configuration UI.
- No long-polling or persistent connections.
- No per-region affinity.
- No TLS termination at the app tier.
