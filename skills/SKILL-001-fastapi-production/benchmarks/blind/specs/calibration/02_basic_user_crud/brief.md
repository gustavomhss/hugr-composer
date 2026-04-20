# Basic user CRUD service

## Background

A small internal tool needs a user directory: create a user, list
them, fetch by id, update, and delete. The service is trusted —
no auth is required for this exercise.

## Requirements

1. `POST /users` — create a user. Request body JSON:
   `{"email": "<string>", "display_name": "<string>"}`.
   Response 201 with `{"id": "<uuid>", "email": "...", "display_name": "..."}`.
2. `GET /users/{id}` — return the user if it exists, else 404.
3. `GET /users` — return `{"users": [...]}` with ALL users, most recent
   created first.
4. `PATCH /users/{id}` — partial update; request body may contain
   either or both of `email`, `display_name`. Unknown fields are
   ignored. Returns the updated user.
5. `DELETE /users/{id}` — deletes the user; returns 204 on success or
   404 if the user does not exist. A subsequent `GET /users/{id}` MUST
   return 404.
6. `email` MUST be a non-empty string containing `@`. A missing or
   malformed email MUST fail with HTTP 422 (or 400).
7. Creating a user with an `email` that already exists MUST fail with
   HTTP 409.
8. `GET /health` MUST return 200 with `{"ok": true}`.

## Acceptance criteria

- Create → GET by id returns the same record.
- Listing is ordered most-recent-first.
- PATCH updates only the supplied fields.
- DELETE makes subsequent GET return 404.
- Duplicate email create returns 409, not 201 (no silent overwrite).
- Malformed email (missing `@` or empty) returns 4xx.

## Non-requirements

- No authentication or sessions.
- No password storage.
- No pagination (small n is fine for this exercise).
- No persistence across process restarts.
- No admin UI.
