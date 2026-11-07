# Monthly cost estimate (dev-sized workload)

**Estimated ongoing AWS bill: roughly $0.05–$0.50/month at the stated workload**, assuming US viewers, four users, 40 app visits/month, normal grocery-app use, and no unusual abuse, support plan, custom domain, SES, WAF, or production stack. Route-level detailed metrics and CloudWatch alarms/SNS are excluded; API stage access logs and Lambda logs remain. A conservative planning allowance of **$1/month** leaves room for usage/account variation.

Exact free-tier eligibility/account-wide usage, CloudWatch log volume, and actual table size change the bill. A separate production stack approximately duplicates fixed monitoring/resource costs. Taxes and optional billing alerts are excluded.

## Estimate assumptions

- 4 Cognito users active monthly (40 total sessions/month). Cognito counts active users, not just the number of sign-in sessions.
- Approximately 10 API requests per visit = 400 API/Lambda invocations/month; likely more than necessary for some screens but still negligible at this usage. The `ShoppingFunction` now uses 1,024 MB (other functions remain 256 MB); on-demand memory has no idle charge. In a cold-read benchmark, the higher memory reduced handler time from ~5.17 s to ~1.25 s, leaving cold compute per invocation approximately unchanged.
- No CloudWatch alarm or SNS resources are deployed in the initial stack, as requested.
- Current exports have 1,943 relatively small rows. DynamoDB table + PITR and S3 asset storage assumed well below 1 GB. PITR at $0.20/GB-month; actual size and future history growth matter.
- Requests and file transfer remain within AWS published free allowances: CloudFront 1 TB/10 million viewer requests/month; Cognito direct/social MAU free threshold; Lambda first 1 million requests/400,000 GB-seconds; small HTTP API/DynamoDB usage is only fractions of a cent at this scale. AWS allowances can depend on account/offer eligibility and account-wide usage.
- Cognito default email delivery used for four invitations (quota-limited). No paid SES integration assumed. CloudFormation itself has no resource charge.
- A ChatGPT meal-access prototype was removed from the dev stack pending owner approval; no public meal Lambda, Function URL, or projection table is currently deployed.
- This excludes one-time local development costs, and excludes the separate production stack, both of which would add a second distribution, table, API, pools and logs.

## Approximate line items

| Service/charge | Estimate at this workload |
|---|---:|
| CloudWatch detailed API route metrics | **$0** (disabled in the template) |
| CloudWatch alarms/SNS | **$0** (not deployed) |
| CloudWatch log ingestion/storage (30-day retention, low traffic) | Fractions of a cent at this volume; depends on account free allowance and event volume |
| DynamoDB on-demand reads/writes | Effectively negligible at ~400 API calls; likely fractions of a cent |
| DynamoDB storage + PITR | Likely pennies/month for current data; PITR $0.20/GB-month |
| S3 storage/requests | Pennies or less for small assets/data; CloudFront origin data transfer to S3 is free |
| CloudFront viewer requests/data | $0 at this volume while within the published 10M request/1TB allowances; otherwise usage-based |
| API Gateway HTTP API | About $0.0004 for 400 requests at $1/million (first pricing tier) |
| Lambda request/duration | Usually $0 under the published request/compute free allowances; includes the 1 GB Shopping Lambda at this usage |
| Cognito user pool | Likely $0 for four MAUs under applicable free allowance; the current Hosted UI/Essentials plan needs to be verified in AWS before release |
| Cognito default invitation emails | Four initial invitations within default Cognito email quota; no alarm SNS topic is deployed |
| **Likely total for current template** | **~$0.05–$0.50/month; budget ~$1/month** |

Why the range is broad: free allowances and actual log/table sizes are account-specific. The template has route-level API detailed metrics and alarms disabled; ordinary access/function logs remain. A budget alert remains optional and is not in the template.

## Sources (AWS pricing/docs checked for this estimate)

- [CloudFront pricing and free tier](https://aws.amazon.com/cloudfront/pricing/)
- [HTTP API pricing](https://aws.amazon.com/api-gateway/pricing/)
- [HTTP API detailed metrics](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-metrics.html)
- [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/)
- [DynamoDB PITR](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Point-in-time-recovery.html)
- [Cognito pricing](https://aws.amazon.com/cognito/pricing/)
- [Cognito email quotas](https://docs.aws.amazon.com/cognito/latest/developerguide/quotas.html)
- [Lambda pricing](https://aws.amazon.com/lambda/pricing/)
- [S3 pricing](https://aws.amazon.com/s3/pricing/)

Rates/allowances are subject to change and do not replace AWS Pricing Calculator or actual billing. Review the CloudFormation change set and Cost Explorer/Billing after deployment. A billing alarm/budget is not currently in the SAM template.
