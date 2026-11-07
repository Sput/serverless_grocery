# Serverless Grocery

AWS serverless replacement for `grocery_inventory`, for **four users sharing one household**.

- Static HTML/CSS/JS → private S3 + CloudFront HTTPS
- Cognito email/password → PKCE login with persistent sessions
- API Gateway HTTP API → three private Python 3.13 Lambda functions
- One shared household DynamoDB table; `us-east-1`
- Reproducible infrastructure with AWS SAM/CloudFormation

**Dev stack deployed in AWS `us-east-1`; 1,943 source records imported and reconciled; static frontend published.** The proposed public ChatGPT meal endpoint was removed pending approval. Login page and unauthenticated API behavior verified. Four users have been invited; authenticated workflow acceptance is still pending. No production stack or Git push. Original app checkout remains unchanged.

## Documentation

- [Project plan and remaining approval gates](docs/project-plan.md)
- [Architecture](docs/architecture.md) · [SVG diagram](docs/architecture.svg)
- [API contract](docs/api.md)
- [Local development/tests](docs/development.md)
- [Deployment/recovery runbook](docs/deployment.md)
- [Deployment inventory and check-off ledger](docs/deployment-inventory.md)
- [Estimated monthly AWS costs](docs/cost-estimate.md)
- [Validation results](docs/validation.md)
- [Proposed ChatGPT meal-library access plan (not deployed; approval pending)](docs/meal_plan_chatgpt_access.md)

## Layout

```text
frontend/              HTML, CSS, JavaScript source (no runtime Node server)
backend/               Python Lambda code and locked runtime dependencies
template.yaml          SAM infrastructure
scripts/               Local build, configuration, migration, guarded SAM wrapper
prototypes/             Un-deployed ChatGPT meal-access handler prototype
tests/                 Backend/Moto, JavaScript unit, desktop/phone browser tests
migration/private/     Gitignored CSV inputs and generated migration reports
```

All existing workflows are retained: inventory/locations, shopping selections, Costco zones, after-Costco copying, Harris Teeter, impromptu items/clear, meals, sign-in/logout/password change. Test tables `inventory` and `shopping_list` are excluded. Private data/credentials are never frontend assets or Git inputs.
