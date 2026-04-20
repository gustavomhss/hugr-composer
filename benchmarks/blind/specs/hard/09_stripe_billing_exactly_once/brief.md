# Exactly-once billing charge facade

## Background

A subscription service bills customers at the end of every cycle.
Charges must be **exactly once** per (customer_id, cycle_id) pair even
under retries, network glitches, and concurrent workers.

For this exercise the actual "payment processor" is a stub inside the
app — `POST /_stripe/charge` simulates the upstream. It has a 10%
error rate (`simulated_network_error`), and when it succeeds it
returns a `stripe_charge_id` that looks like
`ch_<16-hex>`. The real billing endpoint MUST use this stub.

## Requirements

1. `POST /bill` — body `{"customer_id": "<string>", "cycle_id": "<string>",
   "amount_cents": <int>}`.
   - First successful call for a given (customer_id, cycle_id) →
     HTTP 200 with `{"status": "charged", "stripe_charge_id": "ch_...",
     "amount_cents": <int>}`.
   - Retries for the SAME (customer_id, cycle_id) → HTTP 200 with
     `{"status": "already_charged", "stripe_charge_id": "<same id>",
     "amount_cents": <original>}`. The server MUST NOT make a second
     call to the upstream stub for retries.
   - Simultaneous retries MUST yield exactly ONE real charge.
2. If the upstream stub returned `simulated_network_error`, the
   server retries internally with backoff (up to 3 attempts per
   request). If all 3 attempts fail → HTTP 502 `{"error":
   "upstream_unavailable"}`. A 502 MUST NOT record the request as
   charged — a future retry can succeed.
3. `GET /charges` — returns `{"charges": [...]}` — one entry per
   unique successful (customer_id, cycle_id).
4. `GET /_stripe/calls` — returns `{"count": N}` — how many times the
   stub has been invoked (used for introspection by the judge).
5. `POST /_stripe/charge` — internal stub (see above). Always use
   body `{"amount_cents": N}`. Deterministically fails when body has
   `force_fail: true`; otherwise uses random (10% fail rate).
6. `GET /health` → 200.

## Acceptance criteria

- First /bill → 200 "charged"; second for same (cust,cycle) → 200
  "already_charged" + same charge_id; stub called only ONCE total.
- 50 concurrent /bill requests for the SAME (cust,cycle) → exactly 1
  entry in /charges + stub called exactly 1 time.
- 50 concurrent /bill for 50 DISTINCT (cust,cycle) → 50 charges.
- A forced-failing customer (via a marker) → 502 on /bill, then a
  retry without the marker → 200 "charged".
- Never returns 500.

## Non-requirements

- No real Stripe API integration.
- No persistence.
- No retry rate limiting.
