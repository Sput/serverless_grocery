# Validation and deployment results

**Dev stack deployed; no public meal endpoint is currently deployed.** A public-access prototype was tested and then removed when approval was deferred. Local test results are below. Live smoke checks verified CloudFront 200, direct S3 403, API unauthenticated 401, API CORS preflight 204, Cognito hosted login page reached, four users invited and assigned to the household group, and migration reconciliation (1,943 data rows). Authenticated workflows still need user sign-in/acceptance.

## Build and automated checks

| Check | Result |
|---|---|
| Backend/Moto tests, Python 3.13 Lambda-compatible venv | **32 passed** |
| Same backend tests, requested Python 3.14 venv with isolated test tools | **20 passed** |
| JavaScript unit tests | **3 passed** |
| Chromium desktop + phone browser checks | **28 passed, 4 scoped skips** |
| `sam validate --lint` | Passed |
| `sam build` (Python 3.13, arm64 target) | Passed |
| Static frontend bundle | Passed; hashed JS asset generated |

Backend checks include household authorization, input validation, stale-version rejection, conditional transaction conflicts, append versus retry behavior, copy semantics, NULL-versus-false activity, reset/history preservation, internal query pagination, meal dates/tags/deletion, setup locking, expected-account guard, interrupted-import resumption, import reconciliation/rerun protection, data-free DynamoDB timing logs, and verification that route sanitization does not alter mutation paths.

Browser checks cover all screens at desktop/phone viewport sizes, safe text rendering, PKCE authorization redirect, persistent login across reload, expired access-token refresh, selection payloads/idempotency keys, network retry with the same payload/key, clear confirmation, Costco zones/impromptu inclusion, home-page impromptu add/delete/clear with legacy-route redirect, meals-page layout/button labels, and hidden login-callback errors. Mobile meal rows show only name, last-eaten date, and Delete; existing tag display/edit controls are hidden on phone, while the Add New Meal card retains its tag field. The mobile header stays on one compact line with `HG` branding. The Meals page's Copy Meal List button copies a TSV header and rows containing meal name, last-eaten date (or Never), and tags. Tag create/edit/limit tests run on desktop. The updated static app (`app-RBRH23QD.js`) was published to dev; after invalidation, CloudFront returned 200 for the app and copy-button bundle. API/Cognito responses are mocked in browser tests; this does not prove live Cognito/IAM/CORS behavior.

SAM build was native on the local x86_64 machine targeting arm64. Runtime dependencies are pure Python; Python 3.13 tests passed. An actual arm64 Lambda/container invocation is not claimed. Docker daemon was not available for SAM container execution.

## Migration input validation and mocked rehearsal

| Entity | Rows normalized and reconciled |
|---|---:|
| Catalog items | 138 |
| Locations | 5 |
| Meals | 18 |
| Costco | 858 |
| Harris Teeter | 278 |
| Impromptu | 646 |
| **Total** | **1,943** |

- All normalized records reconciled by exact field/key comparison in local mocked DynamoDB.
- No validation errors, duplicate primary keys, or missing catalog location references detected.
- Two catalog zones are NULL and remain NULL.
- All 1,782 list/impromptu records are marked deleted. Active lists are therefore initially empty; no historical records were dropped.
- Same-input completed import rerun performed no writes; different-fingerprint overwrite refused.
- `inventory`, `shopping_list`, and the old 100-row copies are excluded.
- Source CSVs were not modified; private inputs, normalized data and detailed reports are gitignored.
- After import, 648 impromptu records (including entries created after migration) were permanently deleted from the live DynamoDB table. A strongly consistent query verified zero `IMPROMPTU#` items remain. Other entity types were untouched; private CSV/normalized files remain unchanged.

Read-only invocations of deployed `ShoppingFunction:live` validated the timing log. At 256 MB, the cold handler took ~5.17 s with `repositoryInitMs` ~4.97 s; `GetItem` was ~190 ms, `Query` ~10 ms, and retries were zero. At 1,024 MB, the cold handler took ~1.25 s with repository initialization ~1.18 s; DynamoDB reads totaled ~65 ms, with zero retries. Warm handler time was ~18 ms at 256 MB and ~8 ms at 1,024 MB. This identifies Python/Boto3 repository initialization, not query time, as the cold-path delay; the memory increase reduced it substantially.

A live read-only validation against an existing meal now returns the expected five-tag validation error rather than 404; the database check confirms no meal tags were saved during the failed attempts.

A public meal-access prototype was briefly deployed and smoke-tested: GET returned HTTP 200 with only the proposed fields, POST returned HTTP 405, and CORS preflight allowed GET. After the owner deferred approval, the Function URL was deleted and now returns HTTP 403; CloudFormation resources, IAM permissions, output, projection table, and its data were removed. No public meal endpoint is currently active. The local handler/sync prototype and tests remain in the repository for possible future review; do not deploy them until explicit approval.

Reproduce local checks with the commands in [development.md](development.md). Private dataset reports are in `migration/private/validation-report.json` and `migration/private/rehearsal-report.json`.

## Remaining live acceptance

Cognito login-page redirect is verified, but actual account sign-in, invitations, token renewal/password changes and authenticated application workflows await the four email addresses. API rejection without a token and CORS preflight passed; invalid-token/scope behavior needs additional live tests. Table restore and production release rollback remain future production gates. CloudWatch alarms are intentionally omitted.

See [deployment-inventory.md](deployment-inventory.md) for live statuses and [deployment.md](deployment.md) for future production/recovery steps.
