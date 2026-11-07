# Target architecture

**Dev stack deployed and smoke-tested; production not deployed.** [Diagram](architecture.svg) · [Plan/status](project-plan.md) · [API contract](api.md)

## Confirmed decisions

Four invited users share one household's inventory, locations, meals and lists. Full grocery feature parity; existing data migrates, excluding the `inventory` and `shopping_list` test tables. AWS region is `us-east-1`; infrastructure uses SAM/CloudFormation. Cognito email/password login should persist as long as practical.

The old `README (2).md` and SVG describe a fitness tracker. We reused the AWS hosting pattern, not workout routes, placeholder deployment values or its universal single-user record schema. The old application checkout is read-only reference material.

## Runtime services

| Component | Implementation |
|---|---|
| Browser | Responsive static HTML/CSS/JS; hash navigation; no Node server at runtime |
| CloudFront | HTTPS, security headers, default `index.html`, asset caching |
| S3 | Private, encrypted, versioned; public access blocked; CloudFront OAC signed requests only |
| Cognito | Email sign-in, admin invitations only, public client without secret, authorization-code flow with PKCE |
| API Gateway HTTP API | Cognito JWT authorizer, required read/write scopes, exact CloudFront-origin CORS, throttling, access logs |
| Python 3.13 Lambdas | Inventory/locations, shopping/impromptu, meals; immutable versions behind `live` aliases |
| DynamoDB | One encrypted on-demand household table with PITR; retained on deletion/replacement; production deletion protection |
| IAM | Generated execution roles scoped to required household-table operations plus logs; API Gateway invokes the private API functions |
| CloudWatch | 30-day API access and Lambda logs; no alarms in initial deployment |

No EC2, VPC/NAT gateway, running Python server, public database or Supabase dependency at runtime. Build tools run locally only. Dev is deployed; production is separate and not deployed. CloudFront is global; all regional resources use `us-east-1`.

## Flows

1. Browser loads CloudFront over HTTPS. CloudFront fetches uncached static assets from the regular S3 bucket origin using OAC. Direct public S3 access is denied.
2. Browser redirects to Cognito for login. The maintained `oidc-client-ts` library implements code + PKCE and state/callback handling. Callback and logout URLs are exactly the distribution root.
3. Browser calls the separate API endpoint with an access token, not an ID token. API Gateway validates JWT issuer/audience/expiry/signature and route scopes (`grocery/read`, `grocery/write`). OPTIONS preflights remain open through HTTP API CORS.
4. Lambda additionally checks the validated `cognito:groups` claim for `household`. Only manually invited users added to that group may access data. No client-selected household/owner IDs are accepted.
5. Lambda validates payloads and uses strongly consistent DynamoDB reads, conditional transactions and bounded writes. API responses have `Cache-Control: no-store`; APIs do not pass through CloudFront caching.
6. Gateway and functions send logs/metrics to CloudWatch. Bodies, credentials, tokens, item names and raw exception messages are not logged by application error handlers.

Cognito is not a proxy for application requests. Public frontend configuration contains only service URLs, region and client ID, never secrets or AWS credentials. No public meal endpoint is currently deployed; the ChatGPT meal-access proposal requires explicit approval before any public resources are restored.

## Persistent login

- Cognito refresh token default: **3650 days**, configurable with `RefreshTokenDays` (1–3650).
- Access and ID tokens: 60 minutes; OIDC client renews using the refresh token.
- OIDC user tokens persist in browser localStorage, intentionally supporting browser restarts. OAuth transaction state and pending save receipts use sessionStorage.
- This is browser-token persistence, not a guaranteed ten-year session: clearing storage, revocation, account changes, expiry or browser policy can require sign-in again. A refresh token does not live forever merely because the app is used.
- Refresh token rotation is disabled deliberately to avoid concurrent browser-tab refresh races. Revocation is enabled; sign-out attempts to revoke the current refresh token, removes local tokens and visits Cognito logout. Other browser sessions are independent. Already issued access tokens may remain valid until expiry.
- Password changes use Cognito's `ChangePassword` API with the `aws.cognito.signin.user.admin` scope. Recovery and first-login password challenges are handled by Cognito login.
- Persistent browser tokens are script-accessible. Mitigations include no third-party runtime scripts, bundled/pinned OIDC dependency, safe text rendering and a restrictive CSP. This tradeoff is documented rather than pretending localStorage is an HttpOnly cookie.

## Single-table model

Physical string keys: `pk`, `sk`. Fixed authorized partition: `HOUSEHOLD#shared`. Four users share it; JWT group membership is the access boundary, not the partition name's secrecy.

| sk prefix | Purpose |
|---|---|
| `ITEMS#<id>` | Catalog name, location text, nullable Costco zone |
| `LOCATIONS#<sha256(location)>` | Case-sensitive unique storage location |
| `MEALS#<id>` | Meal name, nullable `last_eaten` date, optional list of up to five tags |
| `COSTCO#<id>` | Store entry text and nullable `is_deleted` |
| `HARRIS_TEETER#<id>` | Store entry text and nullable `is_deleted` |
| `IMPROMPTU#<id>` | Name, quantity, timestamps, nullable `is_deleted` |
| `META` | Global revision, clear watermark and migration state/fingerprint |
| `REQUEST#<idempotency-key>` | Submission fingerprint and committed response |

Imported primary keys are preserved as strings (scoped by entity type); new entities use UUIDs. Imported rows retain source table/ID and source fields/timestamps. Records carry `version` and `createdRevision`. No foreign-key conversion or destructive name deduplication occurs. No GSI is needed for this small shared household.

## Proposed ChatGPT meal library (not deployed)

A separate on-demand `PublicMealsTable` and anonymous GET-only Lambda Function URL were prototyped, then removed from the dev stack when the owner deferred approval for public access. The URL, Lambda, IAM permissions, log group, and projection table have been removed; the URL returns 403. No public meal data endpoint is active. See [the proposal](meal_plan_chatgpt_access.md). Do not redeploy the public resources or share an Action schema until the owner approves.

Private API queries use partition + sort-key prefix and follow DynamoDB pagination internally. Responses return the full household collection; there is no public cursor API. These choices fit a small four-person household, not large tenants. Growing archives increase read work; monitor latency/payload size and introduce active-record indexes/pagination before approaching Lambda/API size/time limits.

### Preserved shopping semantics

- Saving selections **appends** entries. Separate saves may append the same item again.
- After-Costco selections **copy** entries to Harris Teeter; Costco originals remain.
- Costco combines its active store rows with **all** active impromptu rows, matches catalog zones by trimmed name, and shows unzoned names under Impromptu. Duplicate display entries remain duplicates.
- Only `is_deleted = NULL` means active; `false` is not treated as active.
- Individual impromptu deletion is a soft delete. Meal deletion is a hard delete.
- Clear List clears all three lists while retaining history. The old RPCs were verified to set all rows' flags to true.

DynamoDB implements bulk clear with an **atomic logical deletion watermark** (`META.clearThrough`) rather than hundreds of physical updates. List records created at or before that revision are effectively deleted; subsequent appends survive. The read layer resolves effective `is_deleted` to true. Raw DynamoDB items alone do not express effective deletion after a reset; any future export/report must apply the watermark. Historical rows are retained unless an explicit hard purge is requested; no TTL deletes them. On 2026-11-07 the owner requested a permanent purge of all dev impromptu records: 648 DynamoDB items were deleted and zero remain. The gitignored source CSV/normalized migration files were left unchanged.

### Concurrency and retry safety

Every mutation transaction conditionally advances the global revision and writes both data and an idempotency receipt. Concurrent conflicts retry against fresh state up to five times, then return 409. The global condition protects records read during planning; explicit versions protect stale individual edits.

Maximum 90 entries per selection/after-Costco request; with metadata/receipt this stays below DynamoDB's 100-action limit. UI chunks larger selections and remembers each batch's key and progress. Each batch is atomic; an entire multi-batch selection is **not** atomic, matching the old non-atomic multiple-insert behavior. An interrupted request can be retried without appending that same batch again. Distinct user submissions intentionally append again. Request receipts are retained (no expiry).

## Migration

Six explicit CSV inputs are selected; old 100-row copies and test tables are ignored. Validation and normalized JSONL/report remain in gitignored `migration/private/`. Current export: **1,943 records** (138 items, 5 locations, 18 meals, 858 Costco, 278 Harris Teeter, 646 impromptu). All exported list entries were deleted at export time. After import, the owner explicitly purged all 648 dev impromptu records; zero impromptu entities remain in DynamoDB. The source CSV remains private and unchanged.

Importer requires explicit write flags, matching table confirmation and expected account. It only initializes an empty household, locks application access as `importing`, writes deterministic keys, reconciles every imported record and finally marks it `ready`. Interrupted imports can resume with the identical fingerprint. Rerunning after readiness is a no-op; different inputs are refused rather than overwriting live data. A development rehearsal used Moto locally, not AWS.

## Release controls

SAM built and deployed the dev stack; data import completed. Hashed JS assets, S3 versioning, retained assets, Lambda versions/aliases and stack outputs support recovery. Publish config/HTML/CSS with revalidation and explicit invalidation; publish immutable JS first. See [deployment inventory](deployment-inventory.md) for verified resources and remaining live acceptance gates.

Four invitation addresses and authenticated acceptance are still needed. CloudWatch alarms are intentionally deferred. No custom domain, GitHub Actions, offline sync or AWS budget resource is silently enabled.

## References

- [CloudFront private S3 origin/OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [HTTP API JWT authorizers/scopes](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)
- [Cognito app client configuration/token lifetime](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpoolclient.html)
- [Boto3 login-session credentials and CRT](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html#login-with-console-credentials)
