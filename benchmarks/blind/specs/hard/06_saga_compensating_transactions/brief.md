# Multi-step booking saga with compensation

## Background

A travel-booking service reserves a flight, a hotel, and a car as a
single **booking saga**. Each leg is its own subsystem with its own
failure modes. If any leg fails, ALL previously-completed legs MUST
be compensated (refunded / released).

Legs are implemented as internal functions in this exercise (no real
external APIs). Each leg can be asked to FAIL to simulate the
downstream being down.

## Requirements

1. `POST /bookings` — body:
   ```json
   {
     "user_id": "<string>",
     "flight": {"code": "<string>", "fail": <bool>},
     "hotel":  {"code": "<string>", "fail": <bool>},
     "car":    {"code": "<string>", "fail": <bool>}
   }
   ```
   - If all three legs succeed → HTTP 201 with
     `{"booking_id": "<uuid>", "status": "confirmed",
       "legs": {"flight": "ok", "hotel": "ok", "car": "ok"}}`.
   - If any leg fails → HTTP 422 with
     `{"status": "compensated",
       "failed_leg": "<flight|hotel|car>",
       "compensated_legs": [<list of already-completed legs that got compensated>]}`.
2. Every booking attempt MUST appear in `GET /bookings/{id}` after the
   response — even the compensated ones, with their final status.
3. `GET /reservations` — returns `{"flight": [...], "hotel": [...],
   "car": [...]}` listing ACTIVE reservations in each leg. After a
   compensated saga there MUST be **no leftover** reservation in any
   leg.
4. Legs are deterministic: `flight.code = "F1"` with `fail=False`
   always succeeds; `fail=True` always fails.
5. `GET /health` → 200 `{"ok": true}`.

## Acceptance criteria

- Happy path: all ok → 201, reservations show flight+hotel+car active.
- Hotel fails after flight succeeded → 422, saga status "compensated",
  flight NOT in active reservations.
- Car fails after flight and hotel succeeded → 422, NEITHER flight
  NOR hotel remain in active reservations.
- Every failed leg is listed as the `failed_leg`; the completed legs
  are listed under `compensated_legs`.
- 50 concurrent bookings where every booking's `hotel.fail=True` →
  ZERO leftover reservations in any leg after the storm.

## Non-requirements

- No persistence.
- No external service calls.
- No auth.
- No multi-process.
