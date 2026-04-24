# billing-invoice-page

> **Status:** STUB — content authoring deferred to Gustavo pre-tag.

## Requirements

[Gustavo: paginated invoice listing keyed off Stripe subscription. Cursor
pagination (created_at, id). Each invoice has line items, total, currency.]

## Acceptance criteria

- GET `/invoices?page_size=20` returns at most 20 items + next_cursor.
- Cursor pagination is stable under concurrent invoice creation.
- An unauthenticated request returns 401.
- A user requesting another user's invoice id returns 404.

## Non-requirements

- No PDF generation at v1.
- No invoice editing.
