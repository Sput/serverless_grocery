# Project plan and current status

## Boundary

**Dev deployed.** Work is in `/home/paul/projects/groceries/serverless_grocery`. Dev resources, 1,943 imported records and static assets are live in AWS. Four Cognito invitations sent and all users are in `household`; authenticated workflow acceptance and production deployment remain. No Git commits/pushes or writes to `grocery_inventory`.

## Approved requirements

- Four users share inventory, locations, shopping lists and meals.
- Feature parity with the existing app, including append/copy/clear behavior and UTC meal dates.
- Cognito email/password, invited users only; persistent login as long as practical (3650-day refresh token configured).
- AWS `us-east-1`, CLI profile `serverless-grocery`, SAM/CloudFormation.
- Migrate six existing tables; exclude `inventory` and `shopping_list` test tables.
- Use the full `(1)` CSV exports, never combine them with truncated 100-row copies.
- Deploy dev stack only; production is not deployed.

## Phases

| Phase | Status | Deliverable / remaining gate |
|---|---|---|
| 1. Requirements and source discovery | Complete for implementation | Original code reviewed; schema metadata and clear RPCs inspected; requirements recorded |
| 2. Project foundation | Complete locally | New repository only, ignored private inputs, pinned dependencies, virtualenv-based Python tests |
| 3. Infrastructure/security | Deployed to dev | Private S3/CloudFront, Cognito, HTTP API, 3 Lambdas, DynamoDB, roles/logs; alarms intentionally deferred |
| 4. Python APIs | Implemented and tested locally | Shared-household auth, validation, revision/record concurrency, transactional retry receipts, bulk clear watermark |
| 5. Static frontend | Built and browser-tested locally | All existing screens, PKCE login, token persistence/renewal, password change, responsive forms/errors/retries |
| 6. Migration | Deployed to dev | 1,943 rows imported into empty table and exactly reconciled; no active list rows in source snapshot |
| 7. Dev deployment and AWS acceptance | **Partially complete** | Dev stack deployed; source data migrated; static frontend up; login page/CORS/unauthenticated checks passed; four users invited. Verify sign-in and authenticated workflows. |
| 8. Production/cutover | Not started | Dev acceptance, final source freeze/export, final migration, backup recovery and release rollback rehearsal |

## Remaining development-release actions

1. Dev stack `serverless-grocery-dev` deployed in `us-east-1`; production is a separate decision.
2. Four Cognito invitations sent; users need to complete temporary-password sign-in.
3. Decide whether to configure an AWS Budgets alert. CloudWatch alarms/SNS are intentionally excluded.
4. Dev reflects the supplied snapshot: all exported shopping/impromptu records are deleted. For production, freeze old writes and obtain a fresh export.
5. After invitations, complete authenticated live acceptance. Production deployment requires separate approval.

The original app remains available and untouched. No current questions about table schemas block the local implementation.

## Remaining acceptance gates

- Anonymous/invalid-token requests denied; authenticated non-household users denied; all four invited group members see shared data.
- PKCE callback and email invitation/first-password challenge work; token renewal, browser restart, password change/recovery and logout work against real Cognito.
- Direct anonymous S3 access blocked; CloudFront loads over HTTPS with required CSP/CORS headers.
- Inventory/location edits, selections, Costco zone grouping, after-Costco copies, Harris Teeter, impromptu add/delete/reset, and meal add/update/delete work on phone and desktop.
- Repeated submission retries do not duplicate writes; separate intentional saves preserve append behavior; stale edits are rejected.
- Imported counts were reconciled before the owner-requested impromptu purge; other table data/source exports remain unchanged.
- Release rollback and DynamoDB restore are exercised before production cutover. Add monitoring alarms later only if operational experience shows a need.

## Known implementation choices

- Clear-all uses an atomic deletion watermark, not physical per-row flags; application reads resolve effective deletion. This avoids partial bulk clears beyond transaction limits.
- Large selection saves are atomic per batch (up to 90 entries), not across all batches. Pending browser jobs retain retry keys.
- No runtime Node/Next.js/Supabase dependency. Node is only a local static asset build/test tool.
- Browser localStorage intentionally persists Cognito tokens. Ten years is a maximum configured refresh lifetime, not a promise of uninterrupted sign-in.
- Household collection reads paginate DynamoDB internally but return a full response. Large-scale pagination/indexing is a future scaling concern, not an extra current feature.
- CloudFront URL and manual SAM release initially; custom domain, offline operation, automated GitHub deployment and barcode/quantity workflows are not added.

## Risks and mitigations

- **Source changes after export:** freeze writes and take a final export before production, never merge live systems blindly.
- **Recovery after cutover:** reconcile new AWS writes before reverting to the old app; switching URLs alone is insufficient.
- **Migration interruption:** importing metadata blocks API writes; resume only with identical inputs; readiness requires full reconciliation.
- **Auth/hosting integration:** local simulations cannot prove AWS callbacks, IAM policies, CORS or delivery behavior; keep live acceptance gates explicit.
- **Shared Python environment:** original requested interpreter used without changing its packages; test tools isolated under `.tools/`; dedicated Python 3.13 venv also checks Lambda runtime compatibility.
- **Costs:** on-demand/serverless is not free; choose notification/budget settings before release.
