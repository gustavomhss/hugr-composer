# Per-user event counter

## Requirements

- Every time a user performs any action, increment the user's lifetime event counter.
- Expose an endpoint that returns a user's current counter within 50 ms p99.
- The counter is eventually consistent; it is fine for two reads seconds apart to differ.
- The counter must NEVER decrement.
- 50 million users, 200 events per user per day average, spiky hot users (top 0.1% produce 20% of events).

## Acceptance criteria

- Under the declared load, p99 read latency on `/users/{id}/count` stays below 50 ms for ≥24 hours.
- Concurrent increments on a hot user record do not produce duplicate counts or lost updates.
- A cold user's first read returns 0 within the same latency budget.
- An operator-facing dashboard shows per-shard write throughput and identifies hot keys.

## Non-requirements

- No admin UI for editing counters.
- No per-action breakdown — one counter per user.
- No real-time notifications on reaching thresholds.
- No historical timeline — current count only.
