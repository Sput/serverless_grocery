#!/usr/bin/env python3
"""Rebuild the public, meals-only DynamoDB projection while application writes are paused."""
import argparse
import sys
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

HOUSEHOLD = "HOUSEHOLD#shared"
PUBLIC_PK = "PUBLIC#MEALS"
SYNC_STATE = "syncing_public_meals"


def query_all(table, partition, prefix):
    rows, cursor = [], None
    while True:
        options = {
            "KeyConditionExpression": Key("pk").eq(partition) & Key("sk").begins_with(prefix),
            "ConsistentRead": True,
        }
        if cursor:
            options["ExclusiveStartKey"] = cursor
        page = table.query(**options)
        rows.extend(page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return rows


def project(row):
    identifier = str(row["id"])
    result = {
        "pk": PUBLIC_PK,
        "sk": f"MEAL#{identifier}",
        "meal": row["meal"],
        "tags": row.get("tags") or [],
    }
    if row.get("last_eaten") is not None:
        result["last_eaten"] = row["last_eaten"]
    return result


def apply(profile, source_table_name, public_table_name, expected_account):
    session = boto3.Session(profile_name=profile, region_name="us-east-1")
    identity = session.client("sts").get_caller_identity()
    if identity["Account"] != expected_account:
        raise RuntimeError("AWS account does not match --expected-account")
    source = session.resource("dynamodb").Table(source_table_name)
    public = session.resource("dynamodb").Table(public_table_name)
    client = session.client("dynamodb")
    meta_key = {"pk": HOUSEHOLD, "sk": "META"}

    try:
        client.update_item(
            TableName=source_table_name,
            Key={k: {"S": v} for k, v in meta_key.items()},
            UpdateExpression="SET migrationState = :syncing",
            ConditionExpression="migrationState = :ready",
            ExpressionAttributeValues={":syncing": {"S": SYNC_STATE}, ":ready": {"S": "ready"}},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise RuntimeError("Source household is not ready; refusing to sync.") from None
        raise

    # Keep the source app locked if any stage fails; a partial public projection must
    # not silently serve as current data. Recover and verify before reopening the API.
    source_locked = True
    try:
        public.put_item(Item={"pk": PUBLIC_PK, "sk": "STATUS", "sync_state": "syncing"})
        source_rows = query_all(source, HOUSEHOLD, "MEALS#")
        projected = [project(row) for row in source_rows]
        current = query_all(public, PUBLIC_PK, "MEAL#")
        expected_by_key = {row["sk"]: row for row in projected}
        current_by_key = {row["sk"]: row for row in current}

        with public.batch_writer() as batch:
            for key, row in current_by_key.items():
                if key not in expected_by_key:
                    batch.delete_item(Key={"pk": PUBLIC_PK, "sk": key})
            for row in projected:
                batch.put_item(Item=row)

        actual = query_all(public, PUBLIC_PK, "MEAL#")
        if {row["sk"]: row for row in actual} != expected_by_key:
            raise RuntimeError("Public projection verification failed; source remains locked.")

        public.put_item(Item={"pk": PUBLIC_PK, "sk": "STATUS", "sync_state": "ready"})
        client.update_item(
            TableName=source_table_name,
            Key={k: {"S": v} for k, v in meta_key.items()},
            UpdateExpression="SET migrationState = :ready",
            ConditionExpression="migrationState = :syncing",
            ExpressionAttributeValues={":ready": {"S": "ready"}, ":syncing": {"S": SYNC_STATE}},
        )
        source_locked = False
    finally:
        if source_locked:
            print("WARNING: meal app remains locked; verify/repair the public projection before restoring ready state.", file=sys.stderr)

    print(f"Synchronized and verified {len(projected)} public meal records; application state restored to ready.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the public projection; omitted means no AWS calls")
    parser.add_argument("--profile", default="serverless-grocery")
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--confirm-source-table", required=True)
    parser.add_argument("--public-table", required=True)
    parser.add_argument("--confirm-public-table", required=True)
    parser.add_argument("--expected-account", required=True)
    args = parser.parse_args()
    if args.source_table != args.confirm_source_table:
        parser.error("--confirm-source-table must exactly match --source-table")
    if args.public_table != args.confirm_public_table:
        parser.error("--confirm-public-table must exactly match --public-table")
    if not args.apply:
        print("LOCAL VALIDATION ONLY. No AWS calls or writes performed.")
        return 0
    apply(args.profile, args.source_table, args.public_table, args.expected_account)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
