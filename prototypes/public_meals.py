"""Anonymous, read-only projection of the household meal library for ChatGPT."""
from __future__ import annotations

import json
import os

import boto3
from boto3.dynamodb.conditions import Key

_table = None


def lambda_handler(event, context):
    global _table
    request_id = getattr(context, "aws_request_id", "unknown")
    request_context = event.get("requestContext", {})
    method = request_context.get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    if method != "GET":
        return _response(405, {"error": "Only GET is supported."}, {"Allow": "GET"})
    if path not in {"", "/"}:
        return _response(404, {"error": "Not found."})

    try:
        if _table is None:
            _table = boto3.resource("dynamodb").Table(os.environ["PUBLIC_MEALS_TABLE_NAME"])
        readiness = _table.query(
            KeyConditionExpression=Key("pk").eq("PUBLIC#MEALS") & Key("sk").eq("STATUS"),
            ProjectionExpression="sync_state",
            ConsistentRead=True,
            Limit=1,
        )
        if not readiness.get("Items") or readiness["Items"][0].get("sync_state") != "ready":
            return _response(503, {"error": "Meal data is temporarily unavailable."}, {"Retry-After": "30"})
        meals, cursor = [], None
        while True:
            options = {
                "KeyConditionExpression": Key("pk").eq("PUBLIC#MEALS") & Key("sk").begins_with("MEAL#"),
                "ProjectionExpression": "#meal, tags, last_eaten",
                "ExpressionAttributeNames": {"#meal": "meal"},
                "ConsistentRead": True,
            }
            if cursor:
                options["ExclusiveStartKey"] = cursor
            page = _table.query(**options)
            for row in page.get("Items", []):
                meals.append({
                    "meal": row["meal"],
                    "tags": row.get("tags") or [],
                    "last_eaten": row.get("last_eaten"),
                })
            cursor = page.get("LastEvaluatedKey")
            if not cursor:
                break
        meals.sort(key=lambda row: row["meal"].casefold())
        return _response(200, {"meals": meals})
    except Exception as exc:
        # Never log meal contents, table keys, tokens, or raw AWS exception strings.
        print(json.dumps({"event": "public_meal_read_failed", "requestId": request_id,
                          "errorType": type(exc).__name__}, separators=(",", ":")))
        return _response(500, {"error": "Meal data is temporarily unavailable."})


def _response(status, body, extra_headers=None):
    headers = {"Content-Type": "application/json", "Cache-Control": "public, max-age=30"}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status, "headers": headers, "body": json.dumps(body)}
