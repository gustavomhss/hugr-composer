# Financial ledger with exact conservation

## Background

A B2B fintech needs a canonical ledger service. Every movement of money
is a **transfer** between two accounts. The only operations are:

- **open_account** (POST `/accounts`) — create a new account with a zero balance.
- **deposit** (POST `/accounts/{id}/deposit`) — external funds entering the system.
- **withdraw** (POST `/accounts/{id}/withdraw`) — external funds leaving.
- **transfer** (POST `/transfers`) — move funds from one internal account to another.
- **balance** (GET `/accounts/{id}`) — current balance + transaction history.

## Requirements

1. Balances and amounts are denominated in **integer cents** (USD minor
   units). The API MUST accept and return integer cents only; there is
   no currency conversion and no rounding tolerance.
2. Every transfer is **atomic**: both legs (debit + credit) succeed or
   neither. A transfer MUST NOT leave either account in a partial state.
3. Each transfer request carries a caller-supplied `idempotency_key`.
   Retrying the same request (same key, same body) MUST produce the
   same result without double-applying the transfer.
4. The system is eventually-audited: **every** successful movement
   (deposit, withdraw, transfer) emits an audit entry that is **append-
   only** and **tamper-evident**. Modifying an audit record MUST be
   detectable by a verifier endpoint.
5. Reads of a single account (`GET /accounts/{id}`) MUST be
   **consistent snapshots**: the returned `balance` equals the
   algebraic sum of that account's audit entries as of some coherent
   point in time. No torn reads.

## Acceptance criteria

- Total money conservation: after any sequence of internal transfers,
  the sum of all account balances equals the initial deposit minus
  withdrawn funds, exactly (integer equality).
- Concurrent transfers between the same pair of accounts never produce
  a negative balance on the source account (no oversold account).
- The same `idempotency_key` replayed 100 times results in **exactly
  one** debit and **one** credit.
- `GET /audit/verify` returns `{"ok": true}` on an untouched ledger and
  `{"ok": false, "broken_index": N}` after any audit record is mutated.
- Under a burst of 200 concurrent transfers randomly between 10
  accounts, the ledger still balances and no API returns 500 (HTTP
  errors must be 4xx user-level failures only).

## Non-requirements

- No multi-currency.
- No interest accrual or fees.
- No user authentication; accounts are identified by opaque UUIDs.
- No persistence across process restarts (in-process state is fine if
  consistent snapshots hold during one boot).
- No admin UI.
