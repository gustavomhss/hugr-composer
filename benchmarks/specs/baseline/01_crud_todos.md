# Todo list CRUD API

## Requirements

- Authenticated users create, list, update, and delete todo items.
- Each todo has: id (server-assigned), title, done flag, created_at, updated_at.
- Users can only see and modify their own todos.
- Pagination is stable: clients can page forward without seeing duplicates or gaps when other users insert.

## Acceptance criteria

- `POST /todos` returns 201 with the created todo; 422 on missing title.
- `GET /todos` returns the caller's todos only; 401 without a valid token.
- `PATCH /todos/{id}` returns 404 when the todo belongs to someone else (never 403 — do not leak existence).
- Listing 10,000 todos and paging through pages of 50 never returns a duplicate or skips an id.
- Automated tests pass against a fresh database.

## Non-requirements

- No team/shared todos.
- No attachments.
- No email notifications.
- No soft-delete or restore.
