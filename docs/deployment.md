# Deployment runbook and release guide

Track every planned resource and release step in the [deployment inventory/check-off ledger](deployment-inventory.md).

**Dev stack is deployed.** This runbook records what was deployed and guides remaining dev acceptance and any future production release. Deployment inventory/status is in [deployment-inventory.md](deployment-inventory.md).

## Remaining development-release decisions

- Provide four invitation email addresses privately; do not put a user list or passwords in Git.
- Decide whether to configure an AWS Budgets alert. CloudWatch alarms/SNS notifications are intentionally not included.
- Dev uses the supplied snapshot; all 1,782 shopping/impromptu records were already deleted in that export. For production, freeze old writes and export again.
- Before future production deployment, verify the `serverless-grocery` profile selects the intended account and region, choose a production stack name, and review a separate change set.

Dev URL: https://d3r54arvllzoj6.cloudfront.net/

## 1. Development deployment (complete)

The dev stack `serverless-grocery-dev` is `CREATE_COMPLETE` in `us-east-1`. The SAM wrapper still blocks future remote SAM commands unless `GROCERY_ALLOW_AWS=YES` is explicitly supplied. There is no automatic deployment or git push hook.

```bash
aws login --profile serverless-grocery  # only if session expired
aws sts get-caller-identity --profile serverless-grocery
bash scripts/sam.sh validate --lint
bash scripts/sam.sh build

# REMOTE: uploads build artifacts and creates a change set, but does not execute it.
# --resolve-s3 itself can create SAM's managed artifact bucket/stack.
GROCERY_ALLOW_AWS=YES bash scripts/sam.sh deploy \
  --stack-name serverless-grocery-dev \
  --template-file .aws-sam/build/template.yaml \
  --region us-east-1 --profile serverless-grocery \
  --resolve-s3 --capabilities CAPABILITY_IAM \
  --parameter-overrides Environment=dev RefreshTokenDays=3650 \
  --no-execute-changeset
```

Review the resulting change set in CloudFormation, including IAM changes, retention and resource names. Execute the approved change set explicitly in the console, or with `aws cloudformation execute-change-set`. Wait for completion; investigate rollback events before retrying. This is the first infrastructure deployment, not a local check.

## 2. Stack outputs and configuration (complete)

```bash
aws cloudformation describe-stacks --stack-name serverless-grocery-dev \
  --region us-east-1 --profile serverless-grocery \
  > migration/private/dev-stack-outputs.json

.tools/lambda-venv/bin/python scripts/config_from_outputs.py \
  migration/private/dev-stack-outputs.json
APP_CONFIG_FILE=migration/private/app-config.json npm run build
```

Use `BucketName`, `DistributionId`, `TableName`, `UserPoolId`, `AppUrl` outputs below. Do not use the fitness tracker reference's placeholders. `ApiUrl` has no `/prod` suffix: this is an HTTP API `$default` stage.

## 3. Development data import (complete)

```bash
.tools/lambda-venv/bin/python scripts/migrate.py

# REMOTE WRITES: replace placeholders with reviewed output/account values.
.tools/lambda-venv/bin/python scripts/migrate.py --apply \
  --profile serverless-grocery --table TABLE_NAME --confirm-table TABLE_NAME \
  --expected-account YOUR_ACCOUNT_ID
```

The importer validates input, locks setup as importing, batch-writes, reconciles all normalized fields/IDs and only then allows API access. An empty table remains unavailable (503) until migration succeeds. Do not initialize metadata manually to bypass failed reconciliation. The same input can resume a failed import; changing inputs or overwriting ready live data is deliberately blocked.

**Future-only runbook:** no public meal table or endpoint is currently deployed. Do not run this script or restore public resources until the owner explicitly approves making the fields public. If approved later, deploy the reviewed resources, then rebuild the projection before sharing the endpoint. The endpoint returns 503 until an internal readiness marker is `ready`. The script locks household writes, marks the projection unavailable, copies only `meal`, `tags`, and `last_eaten`, verifies exact meal keys/fields, marks the projection ready, then restores the app to ready:

```bash
.tools/lambda-venv/bin/python scripts/sync_public_meals.py --apply \
  --profile serverless-grocery --source-table SOURCE_TABLE --confirm-source-table SOURCE_TABLE \
  --public-table PUBLIC_MEALS_TABLE --confirm-public-table PUBLIC_MEALS_TABLE \
  --expected-account YOUR_ACCOUNT_ID
```

Never point the public Function URL at the shared `GroceryTable`.

Imported data preserves original IDs/timestamps and deleted history. Blank nullable fields in these exports are treated as NULL; false remains distinct. All list rows in the supplied snapshot are deleted, so active lists initially appear empty.

## 4. Static frontend publication (complete)

Review `dist/config.js`; confirm its URLs point to the intended stack. Upload hashed assets before the HTML that references them. Never upload `migration/`, `.tools/`, `.env`, backend code or the repository root.

```bash
aws s3 sync dist/assets/ s3://BUCKET_NAME/assets/ \
  --cache-control 'public,max-age=31536000,immutable' \
  --region us-east-1 --profile serverless-grocery

aws s3 cp dist/styles.css s3://BUCKET_NAME/styles.css \
  --content-type text/css --cache-control 'no-cache' \
  --region us-east-1 --profile serverless-grocery
aws s3 cp dist/config.js s3://BUCKET_NAME/config.js \
  --content-type application/javascript --cache-control 'no-cache' \
  --region us-east-1 --profile serverless-grocery
aws s3 cp dist/index.html s3://BUCKET_NAME/index.html \
  --content-type text/html --cache-control 'no-cache' \
  --region us-east-1 --profile serverless-grocery

aws cloudfront create-invalidation --distribution-id DISTRIBUTION_ID \
  --paths / /index.html /config.js /styles.css \
  --profile serverless-grocery
```

CloudFront's managed optimized cache has a one-second minimum TTL; explicit invalidation ensures HTML/config changes propagate. Do not delete older hashed assets during release: existing tabs/rollback HTML may still reference them. Save a release manifest of asset hash, S3 versions, built template, Lambda versions/aliases and input fingerprint.

## 5. Invite exactly the four users (complete)

The four requested users were created through Cognito `AdminCreateUser` with email delivery and added to the **`household`** group. Cognito reports four pool users and four group members. Users must complete the emailed temporary-password challenge. No addresses or passwords are recorded in the repository.

Public self-registration is disabled. No user/password exports from Supabase are needed. Old app passwords are not copied. The four emails must not be committed to Git.

## 6. Live AWS acceptance (required; local tests do not substitute)

- CloudFront HTTPS loads the app on desktop/phone. Direct anonymous bucket/object requests fail.
- CSP is present; real login redirects/callbacks work without CORS or OAuth scope errors.
- Invalid/absent JWT denied at gateway; valid user outside household group denied by Lambda. All four members see shared data.
- Verify token refresh after expiry, persistence after browser restart, password change, recovery, and logout/revocation. Do not claim ten-year uninterrupted login from a short test.
- Exercise every workflow: locations/items, selections, Costco zones + automatic impromptu display, after-Costco copying, Harris Teeter, impromptu soft delete/clear, meals and UTC date handling.
- Retry a submission and verify one committed batch; make a new save and confirm existing append semantics. Test a stale edit with two users.
- Compare migration counts and representative rows; retain deleted history, preserve NULL vs false semantics.
- Confirm CloudWatch access/function logs and any separately configured budget notifications. CloudWatch alarms are intentionally deferred.

Only after dev acceptance: approve production resources, repeat with `Environment=prod` and a separate stack/user pool/table/bucket/distribution. Never reuse dev migration state or browser config for production. Perform a final source freeze/export and validate the updated files before production import.

## Recovery and cutover

- Frontend rollback: restore previous S3 object versions for HTML/config/CSS, retain referenced hashed JS, invalidate changed paths. Verify config still targets the correct environment.
- Backend rollback: redeploy the reviewed previous SAM build or move `live` aliases to known-good versions, then reconcile the stack configuration. Never roll schema/data contracts back blindly.
- Data recovery: restore PITR to a **new table**; validate it and reconfigure the approved stack/function table reference in a controlled recovery change. Default template owns a new table, so recovery needs an explicit infrastructure adjustment, not a casual console toggle. Drill this in dev before production.
- Application reset uses a watermark; reports/exports must resolve effective deletion, not just raw row flags.
- If reverting to the old app after AWS writes, freeze AWS writes and reconcile new data first. Do not simply switch URLs and lose changes.
- Retained/versioned buckets and retained DynamoDB table can continue billing after stack deletion. Production deletion protection and Cognito pool protection require deliberate handling; never delete data to resolve a failed stack update.

**Current status:** dev resources, migration and frontend are deployed. Four Cognito invitations and authenticated live workflow tests remain. Production is not deployed.
