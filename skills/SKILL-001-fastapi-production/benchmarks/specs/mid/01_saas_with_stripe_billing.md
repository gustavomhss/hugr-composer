# SaaS with Stripe billing

## Requirements

- Signup, login, password reset (as in auth-only baseline).
- Subscription plans (free, team, enterprise) billed monthly via Stripe Checkout.
- Receive Stripe webhooks for `invoice.paid`, `customer.subscription.updated`, `customer.subscription.deleted`.
- Maintain a server-side record of each customer's active plan and renewal date.
- When a subscription becomes past-due, transition the account to read-only mode after a 7-day grace period.

## Acceptance criteria

- A duplicate webhook delivery for the same Stripe event id updates internal state exactly once.
- A webhook with a bad signature returns 401 without mutating state.
- Subscription plan change is reflected within one webhook round-trip; no polling Stripe on every request.
- The read-only transition job runs idempotently: running it twice on the same day does not double-notify the user.
- Canceling a subscription immediately ends premium access at period end, not mid-period.

## Non-requirements

- No usage-based metering; plans are flat-rate.
- No invoice PDFs hosted by the app — Stripe-hosted links are fine.
- No refunds flow.
- No multi-currency.
