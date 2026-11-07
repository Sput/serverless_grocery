# Proposal: ChatGPT Meal Planning from the Household Meal Library

## Status — NOT DEPLOYED; owner approval pending

The owner deferred approval for making meal data public. The dev Function URL has been disabled and removed from CloudFormation; its Lambda, IAM permissions, log group, and meal projection table have been removed/deleted. The former URL returns 403. No public meal endpoint is currently active. **Do not restore or share the public integration until the owner explicitly approves.**

The read-only handler, projection/sync prototype, tests, and draft OpenAPI schema remain in the repository for possible later review. They are not part of the deployed SAM template.

## Objective and current data

After approval, the proposed integration would let ChatGPT retrieve the household's existing meal ideas and use tags and last-eaten dates to draft a fresh schedule in its response. Generated plans would not be saved to the grocery application or DynamoDB.

The Meals page is a library, not a calendar. It currently has 18 meals with fields including `meal`, `tags`, and nullable `last_eaten`. There are no planned-date or ingredient-list fields. ChatGPT could propose a fresh combination, but because generated schedules would not be stored, it could not guarantee a combination had never appeared in another conversation. `last_eaten` is the available repeat-avoidance signal.

The proposed public response is limited to:

```json
{
  "meals": [
    { "meal": "Egg quiche", "tags": ["egg", "breakfast"], "last_eaten": "2026-11-01" }
  ]
}
```

Meal names, tags, and last-eaten dates would be intentionally public. Never include grocery inventory, shopping lists, user/account details, record IDs, timestamps, or other household data. The proposed endpoint is read-only and would not accept a plan to save.

## Proposed architecture (not deployed)

```text
Custom GPT Action (only after owner approval)
    |
    | Public HTTPS GET, no authentication
    v
Dedicated read-only Lambda Function URL
    |
    | IAM: dynamodb:Query only
    v
Dedicated meals-only projection table

Private grocery app -> authorized Meals API -> atomic projection updates
```

The public reader must query only the dedicated projection table—not the shared `GroceryTable`, which also contains inventory and shopping data. The projection should be synchronized by authorized meal create/update/delete transactions and a guarded backfill. A readiness marker should make the public endpoint return 503 until a verified projection is ready. The public Lambda role must have Query-only access to that table, with no access to the shared table and no write permission.

If approved, use reserved concurrency as a modest safeguard, while recognizing it is not a full rate limit or spending cap. Public availability means third parties can call the endpoint.

## ChatGPT integration (manual, only after approval)

The draft OpenAPI schema is [`meal_plan_openapi.yaml`](meal_plan_openapi.yaml); its server URL is deliberately a placeholder. **Do not configure a Custom GPT Action using it yet.** After approval and deployment, replace the placeholder with the approved endpoint, configure Action authentication as None, and test it in ChatGPT. AWS deployment cannot configure the owner's ChatGPT account.

Suggested Custom GPT instructions, for use only after approval:

> When asked to create a meal plan, call `getMealLibrary` first and build a fresh schedule from the returned meal ideas. Use tags to balance meal types/preferences and use `last_eaten` to avoid recent repeats (treat null as never eaten; use today's date unless the user gives another planning date). Past generated schedules are not stored, so do not claim the schedule has never appeared before. Do not claim the library contains ingredients or a previously saved calendar. The action is read-only and does not save plans. Ask how many days/meals if unclear; otherwise offer a practical one-week dinner plan. Favor variety and explain any repeats if the library is too small. You may suggest new meal ideas separately only if the user asks; distinguish them from library meals.

If approved, create a Custom GPT, open **Configure → Actions → Create new action**, import the OpenAPI schema, select **Authentication: None**, and test `getMealLibrary` and a sample plan. Review whether the GPT is private or shared; anyone allowed to use it could retrieve the intentionally public meal library.

Ordinary ChatGPT conversations (rather than a Custom GPT Action) may require a separately available app/MCP integration; the proposed endpoint alone does not provide that.

## Work status and release gates

- [x] Scope limited to existing meal ideas; no plan persistence or ingredient claims.
- [x] Read-only handler, projection logic, sync tooling, and tests prototyped locally.
- [x] Prototype endpoint was smoke-tested, then disabled and removed after the owner deferred public-access approval.
- [x] Confirm former endpoint returns 403; remove projection data and public resources from dev.
- [ ] Owner explicitly approves making the selected meal fields public.
- [ ] Re-add and review the SAM resources/IAM, deploy only after approval, backfill, and verify the endpoint.
- [ ] Owner configures and tests the Custom GPT Action manually.
- [ ] Reassess public invocation volume, rate/cost controls, and sharing settings before release.
- [ ] Production remains a separate approval and deployment.

## Expected cost if later approved

At approximately 20 lookups/month, a small on-demand projection table, low-memory Lambda Function URL, and 30-day logs would likely be inexpensive, subject to account-wide free-tier eligibility and actual public usage. This is a planning estimate only; no public meal Lambda/table is currently deployed. No CloudWatch alarms/SNS are added under the current project constraints.
