# Deployment inventory and live checklist

**Status: DEV STACK DEPLOYED.** This is the live release ledger. Checkboxes reflect verified AWS state; local builds/tests do not count as deployment.

Deployed dev stack: `serverless-grocery-dev`, region `us-east-1`, AWS profile `serverless-grocery`. Production is **not** included in the first dev deployment.

## A. CloudFormation/SAM resources planned

Template: [`template.yaml`](../template.yaml). SAM transforms named functions into Lambda functions, execution roles, log groups, permissions and aliases/versions; those generated resources are also part of the deployment. CloudFormation stack is currently `UPDATE_COMPLETE`; all listed resources and SAM-generated resources checked against `list-stack-resources`.

| Deployed | Template logical ID / generated resource | Purpose / noteworthy settings |
|---|---|---|
| [x] | `GroceryTable` — DynamoDB table | One shared household table; `pk`/`sk`; on-demand; encryption; PITR; retained on stack deletion. Dev deletion protection currently off. |
| [x] | `FrontendBucket` — S3 bucket | Private static assets; block public access; TLS-only policy; encryption; versioning; retained. |
| [x] | `OriginAccess` — CloudFront OAC | Signed SigV4 access from distribution to S3. |
| [x] | `SecurityHeaders` — CloudFront response headers policy | CSP and browser security headers. |
| [x] | `Distribution` — CloudFront distribution | HTTPS, `index.html`, S3 OAC origin, `PriceClass_100`, AWS default hostname. |
| [x] | `BucketPolicy` — S3 bucket policy | Allows `GetObject` only to this CloudFront distribution; denies insecure transport. |
| [x] | `UserPool` — Cognito user pool | Email login; invited users only; password rules; email recovery; MFA off; dev deletion protection inactive. |
| [x] | `HouseholdGroup` — Cognito group | `household`; API Lambda requires membership. |
| [x] | `ResourceServer` — Cognito resource server | `grocery/read` and `grocery/write` scopes. |
| [x] | `UserPoolDomain` — Cognito hosted-login domain | `${stack}-${account}` domain. |
| [x] | `UserPoolClient` — Cognito SPA app client | Public client; OAuth code + PKCE; exact CloudFront callback/logout; revocation; 60-minute access/ID tokens; up to 3650-day refresh token. |
| [x] | `Api` — API Gateway HTTP API | JWT authorizer/scopes, CloudFront-origin CORS, throttling, access logging; route-level detailed metrics disabled. |
| [x] | `ApiLogs` — CloudWatch log group | API access logs; 30-day retention. |
| [x] | `InventoryFunction` + SAM-generated Lambda version/`live` alias | Python 3.13, arm64, inventory/location routes. |
| [x] | Generated execution role/policies for `InventoryFunction` | Scoped DynamoDB/log permissions; verified `dynamodb:TransactWriteItems`. |
| [x] | Generated Lambda log group for `InventoryFunction` | 30-day retention (`InventoryLogs`). |
| [x] | `ShoppingFunction` + SAM-generated Lambda version/`live` alias | Python 3.13, arm64, shopping/impromptu routes. |
| [x] | Generated execution role/policies for `ShoppingFunction` | Scoped DynamoDB/log permissions; verified `dynamodb:TransactWriteItems`. |
| [x] | Generated Lambda log group for `ShoppingFunction` | 30-day retention (`ShoppingLogs`). |
| [x] | `MealsFunction` + SAM-generated Lambda version/`live` alias | Python 3.13, arm64, meals routes. |
| [x] | Generated execution role/policies for `MealsFunction` | Scoped DynamoDB/log permissions; verified `dynamodb:TransactWriteItems`. |
| [x] | Generated Lambda log group for `MealsFunction` | 30-day retention (`MealsLogs`). |
| [x] | SAM artifact bucket (managed by `--resolve-s3`, if absent) | Deployment package storage; created as `aws-sam-cli-managed-default-samclisourcebucket-e4p0w4fhy6ab`. |

**Not deployed:** public ChatGPT meal endpoint (owner approval pending); production stack; custom domain/Route 53/ACM; AWS Budgets alert; GitHub Actions/OIDC; WAF. Four Cognito users have been invited and added to `household`; first sign-in acceptance is pending.

## B. Deployment gates and release operations

| Deployed / complete | Gate or action | Evidence to record |
|---|---|---|
| [x] | Owner approves dev resource creation and stack name | User authorized deployment; `serverless-grocery-dev` |
| [ ] | Budget threshold decided and alert configured, or explicitly deferred | Threshold and budget alert ARN; currently absent from template |
| [x] | CloudWatch alarms and SNS notifications deferred from initial deployment | Owner requested omission; can be reconsidered later |
| [x] | SAM transaction permission added; template lint/build rerun | `dynamodb:TransactWriteItems`; SAM validate/build passed |
| [x] | CLI profile/account/region checked immediately before deployment | Expected account confirmed in `us-east-1`; account ID is kept out of this public repository. |
| [x] | CloudFormation change set reviewed, including resource names/IAM/costs | Reviewed before execution; no alarm/SNS resources |
| [x] | Dev change set executed and stack reaches `CREATE_COMPLETE` | Dev stack creation completed in `us-east-1` |
| [x] | Public meal prototype disabled and removed after approval was deferred | Former Function URL returns 403; Lambda, IAM permissions, logs, output, projection table, and data removed; stack `UPDATE_COMPLETE`. |
| [x] | Private Lambda packages rebuilt without the unused public handler/mirror path | Stack `UPDATE_COMPLETE`; no public resources or projection data remain. |
| [x] | DynamoDB read timing instrumentation deployed to dev Lambdas | Stack update completed; no data/permissions changed |
| [x] | Meal tags API deployed | Existing meal items remain compatible; stack update completed |
| [x] | Fixed meal-ID route preservation in timing logger | Verified live meal lookup returns validation (not 404); no data changed |
| [x] | Shopping Lambda memory tuned and cold/warm latency benchmarked | 1,024 MB; cold handler ~1.25 s vs ~5.17 s at 256 MB; no data changes |
| [x] | Outputs saved under gitignored `migration/private/` | `dev-stack-outputs.json`; resource IDs are private/local |
| [x] | Public frontend config generated from outputs and inspected | `app-config.json`; public endpoints only; us-east-1 |
| [x] | 1,943-row migration applied to empty dev table | fingerprint `ea36ffaf7b1f2da50956121a36c1a2c3f4e868710d147fc0b23356c57b682`; exact query count 1,944 including META at import time |
| [x] | Hashed assets, CSS, config, and HTML uploaded to private bucket | Latest `app-RBRH23QD.js` published; includes compact one-line mobile HG banner, meal-list copy, and mobile tag layout; older hashed assets retained for rollback |
| [x] | CloudFront invalidation complete | Initial and subsequent UI invalidations all completed. |
| [x] | Four intended Cognito users created and added to `household` | Cognito reports 4 users in pool/group; invitations sent by email. Addresses/passwords omitted from Git. |
| [ ] | CloudFront/S3, Cognito, API, CRUD/workflows and authorization acceptance passes | Link to test record/checklist |
| [ ] | Public ChatGPT endpoint approval | Owner approval required before any public resources or Custom GPT Action are restored. |
| [ ] | Any separately configured billing/budget alert tested or documented deferred | Test timestamp; budget alert is outside current template |
| [ ] | Dev rollback and data recovery procedure tested | Test record; no production write rollback assumption |

| [x] | Permanently purge impromptu rows | 648 records deleted from DynamoDB; strong-read verification found zero remaining; API lock restored to ready |

## C. Remaining inputs and gates

1. **User invitations:** all four users are invited and in the `household` group; they still need to complete first sign-in.
2. **Budget alerts:** no AWS Budgets resource is in the template. CloudWatch alarms/SNS were explicitly deferred.
3. **Production snapshot:** all supplied shopping/impromptu records were deleted at export time. Re-export after freezing the old application before production cutover.
4. **Production:** separate stack and approval; dev deployment does not authorize production deployment.

## D. Live acceptance checklist

| Passed | Test |
|---|---|
| [x] | Direct anonymous S3 access denied (403); CloudFront app loads over HTTPS (200) |
| [x] | HTTPS response security headers/CSP present; end-to-end Cognito/API CSP flow remains to test after invitations |
| [ ] | PKCE login, first-time invitation/password challenge, callback and logout work |
| [ ] | Refresh token renews after access token expiration and persists after browser restart |
| [ ] | User without `household` group denied; all four household users share same data |
| [x] | Missing token rejected by API Gateway (401); invalid-token/required-scope live test remains |
| [x] | Cognito hosted login screen reached from the deployed app | Login redirect to deployed Cognito domain; no user sign-in attempted yet |
| [x] | API CORS preflight responds for the CloudFront origin | OPTIONS returned 204 with exact allow-origin/headers/methods |
| [x] | Previously deployed ChatGPT meal endpoint is now unavailable | Function URL returns 403; no PublicMeals Lambda, URL, output, IAM policy, or projection table remains deployed. |
| [ ] | Inventory and location create/update |
| [ ] | Shopping list selection append and Costco zone grouping |
| [ ] | After-Costco copies to Harris Teeter and leaves Costco intact |
| [ ] | Impromptu add/soft-delete/Clear behavior | Historical dev impromptu rows were later hard-purged at owner's request |
| [ ] | Meals add/date/tag update/delete and UTC date behavior | Tag limits and create/edit payloads covered by automated tests; live-user workflow acceptance remains pending |
| [ ] | Duplicate network retry does not duplicate a committed batch; separate saves append |
| [ ] | Any separately chosen budget notification verified |
| [ ] | DynamoDB PITR settings confirmed; recovery/rollback rehearsal completed before production |

## Current ledger

**Dev CloudFormation resources: 45; stack status `UPDATE_COMPLETE`; CloudFront distribution: `Deployed`.** **Initial import: 1,943 records exactly reconciled. Subsequently, 648 impromptu records were permanently deleted and zero remain.** **Frontend objects: 4 files uploaded; CloudFront invalidation completed.** **Cognito users invited: 4; all 4 are in `household`.** The ChatGPT prototype was disabled and all public endpoint/projection resources and data were removed. Production stack: not deployed.
