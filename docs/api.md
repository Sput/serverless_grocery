# API contract

Base URL: stack output `ApiUrl`. JSON requests/responses. HTTP API payload format 2.0.

Every application route requires Cognito access-token authorization and `household` group membership. GET uses `grocery/read`; mutations use `grocery/write`. Browser CORS OPTIONS is not authenticated. API Gateway rejects invalid tokens before Lambda.

## Routes

| Method | Path | Body / result |
|---|---|---|
| GET | `/items` | `{items: [...], revision}` |
| POST | `/items` | `{name, location}`; existing location required; initial zone NULL |
| PATCH | `/items/{id}` | `{location, version}` |
| GET | `/locations` | `{items: [...], revision}` |
| POST | `/locations` | `{location}`; exact case-sensitive uniqueness |
| GET | `/impromptu` | Active `{items: [...], revision}` |
| POST | `/impromptu` | `{name}`; quantity 0, deletion NULL |
| DELETE | `/impromptu/{id}` | `{version}`; soft delete |
| GET | `/shopping` | `{costco: [...], harris_teeter: [...], impromptu: [...], revision}`; active only |
| POST | `/shopping/selections` | `{entries: [{kind: "items" or "impromptu", id, store: "costco" or "harris_teeter"}]}` |
| POST | `/shopping/after-costco` | `{ids: [costcoEntryId, ...]}`; copies to Harris Teeter |
| POST | `/shopping/reset` | `{}`; clears all lists, retains history |
| GET | `/meals` | `{items: [...], revision}`; oldest last-eaten first, never-eaten last |
| POST | `/meals` | `{meal, tags?}`; tags optional, zero to five values |
| PATCH | `/meals/{id}` | `{last_eaten?, tags?, version}`; at least one meal field required |
| DELETE | `/meals/{id}` | `{version}`; hard delete |

A public ChatGPT meal API was prototyped, then removed after owner approval for public access was deferred. There is no `PublicMealsUrl` output or active public meal endpoint. See the [proposal](meal_plan_chatgpt_access.md) and draft [OpenAPI schema](meal_plan_openapi.yaml); do not deploy or configure the Action until approval.

There are no catalog item/location deletes or zone-edit screen in the old frontend; none added here. Imported zones are preserved. Password changes go directly to Cognito using its access-token-authorized API, not a grocery API route.

Names/locations are trimmed, nonempty strings of at most 200 characters for new writes. Meal tags are trimmed strings of 1–50 characters, unique ignoring case, with at most five per meal; send an empty array to clear them. Legacy meals without a `tags` field are treated as having no tags. Imported data is retained without name deduplication. Meal date is validated; frontend sends today's UTC date like the original.

Record `id` is a string. Imported numeric IDs become strings, not new UUIDs. Mutable record `version` is an integer starting at 1. Individual edits/deletes require the version last read; stale versions return 409. Server responses may include original timestamps/source IDs, `kind`, `createdRevision` and `is_deleted`; clients must not invent versions.

## Mutations and retry contract

All mutations require `Idempotency-Key`: 16–100 ASCII letters/digits/hyphens/underscores (UI uses UUIDs).

- Success: `200 {ok: true, changed: N, revision: R}`.
- Same key + identical method/path/body returns the original committed response, without new writes.
- Reusing a key for a different payload returns 409.
- Distinct keys represent distinct submissions; selections intentionally append duplicate names if saved again.
- Receipts persist with the household, without TTL. Do not discard a pending key after a timeout/network failure and invent a new key.
- 90 selections/Costco IDs maximum per request; UI splits larger submissions. Every batch is atomic; multiple batches are not one atomic unit. Earlier successful batches survive a later failure.
- A reset is one transaction changing the deletion watermark. It does not delete records or reset inventory/meals.
- No more than 64,000 UTF-8 bytes per request body. Client must not send owner/household IDs.

Reads return the complete small-household collection. Repository queries follow all DynamoDB pages internally. External cursor pagination is not implemented.

## Errors

JSON errors produced by Lambda: `{error: "message", requestId: "..."}`; API Gateway authorizer errors can have its own standard shape.

- 400: invalid JSON/input/key/date/source
- 401: sign-in required (normally rejected at gateway)
- 403: not a household group member
- 404: route or record not found
- 409: stale edit, concurrent save, removed selection source, duplicate location or reused key
- 413: request body too large
- 429: API/Lambda throttling (AWS response)
- 500: unexpected failure, safe error text only
- 503: data import/setup not complete; household locked

Clients retain retry keys for unknown outcomes (network/5xx), reload stale versions after 409, and never treat CORS as authentication. Responses use `Cache-Control: no-store`.

## DynamoDB read timing logs

Each Lambda invocation that performs DynamoDB operations emits one structured CloudWatch log event (`event: dynamodb_timing`). It includes the sanitized route, first-invocation cold-start flag, repository/client initialization time, total handler time, and per-operation `GetItem`/`Query` duration, retry attempts, HTTP status, and row/page counts. Item names, IDs, request bodies, and tokens are never logged. Use `requestId` to correlate the event with the API Gateway access log. This is diagnostic logging only; it does not add CloudWatch metrics, alarms, or SNS.
