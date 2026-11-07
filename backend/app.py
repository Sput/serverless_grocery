"""Shared-household grocery API. API Gateway owns JWT validation and CORS."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

HOUSEHOLD = "HOUSEHOLD#shared"
LISTS = {"costco", "harris_teeter", "impromptu"}
DOMAIN_KINDS = {
    "inventory": {"items", "locations"},
    "shopping": LISTS,
    "meals": {"meals"},
}


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def text(value, label="Name", maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ApiError(400, f"{label} must contain 1–{maximum} characters.")
    return value.strip()


def record_key(kind, identifier):
    return f"{kind.upper()}#{identifier}"


def meal_tags(value):
    if not isinstance(value, list):
        raise ApiError(400, "Tags must be a list.")
    if len(value) > 5:
        raise ApiError(400, "A meal may have at most 5 tags.")
    result, seen = [], set()
    for raw_tag in value:
        tag = text(raw_tag, "Tag", 50)
        folded = tag.casefold()
        if folded in seen:
            raise ApiError(400, "Meal tags must be unique, ignoring case.")
        seen.add(folded)
        result.append(tag)
    return result


def visible(row, meta):
    result = {k: v for k, v in row.items() if k not in {"pk", "sk"}}
    if row["kind"] in LISTS and row.get("createdRevision", 0) <= meta.get("clearThrough", -1):
        result["is_deleted"] = True
    return result


class Service:
    """Business rules independent of AWS; repository commits are atomic and versioned."""

    def __init__(self, repo):
        self.repo = repo

    def get(self, path):
        kind = {"/items": "items", "/locations": "locations", "/meals": "meals",
                "/impromptu": "impromptu"}.get(path)
        if kind:
            meta = self.repo.meta()
            rows = [visible(r, meta) for r in self.repo.list(kind)]
            if kind == "impromptu":
                rows = [r for r in rows if r.get("is_deleted") is None]
            if kind == "meals":
                rows.sort(key=lambda r: (r.get("last_eaten") is None, r.get("last_eaten") or "", r["id"]))
            else:
                rows.sort(key=lambda r: (r.get("name", r.get("location", "")).casefold(), r["id"]))
            return {"items": rows, "revision": meta["revision"]}
        if path == "/shopping":
            # Retry a read if a mutation happened during the queries. Avoid mixed reset/save views.
            for _ in range(3):
                meta = self.repo.meta()
                result = {}
                for kind in sorted(LISTS):
                    rows = [visible(r, meta) for r in self.repo.list(kind)]
                    result[kind] = sorted([r for r in rows if r.get("is_deleted") is None], key=lambda r: r["id"])
                if self.repo.meta()["revision"] == meta["revision"]:
                    return {**result, "revision": meta["revision"]}
            raise ApiError(409, "Lists changed while loading. Please reload.")
        raise ApiError(404, "Route not found.")

    def mutate(self, method, path, body, key):
        if not isinstance(body, dict):
            raise ApiError(400, "Request body must be a JSON object.")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key):
            raise ApiError(400, "A 16–100 character Idempotency-Key is required.")
        fingerprint = hashlib.sha256(json.dumps([method, path, body], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        for _ in range(5):
            cached = self.repo.receipt(key)
            if cached:
                if cached["fingerprint"] != fingerprint:
                    raise ApiError(409, "Idempotency key was already used for another request.")
                return cached["response"]
            meta = self.repo.meta()
            new_meta = dict(meta, revision=meta["revision"] + 1)
            writes, deletes, response = self.plan(method, path, body, new_meta)
            if self.repo.commit(meta, new_meta, writes, deletes, key, fingerprint, response):
                return response
        raise ApiError(409, "Another user is saving. Retry this submission.")

    def plan(self, method, path, body, meta):
        now = datetime.now(timezone.utc).isoformat()
        writes, deletes = [], []

        def create(kind, fields, identifier=None):
            identifier = identifier or str(uuid.uuid4())
            row = {"id": identifier, "kind": kind, **fields, "created_at": now,
                   "updated_at": now, "version": 1, "createdRevision": meta["revision"]}
            writes.append(row)
            return row

        if method == "POST" and path == "/locations":
            name = text(body.get("location"), "Location")
            # Location is the source primary key; preserve exact case-sensitive uniqueness.
            identifier = hashlib.sha256(name.encode()).hexdigest()
            if self.repo.get("locations", identifier):
                raise ApiError(409, "Location already exists.")
            create("locations", {"location": name}, identifier)
        elif method == "POST" and path == "/items":
            location = text(body.get("location"), "Location")
            if not any(r["location"] == location for r in self.repo.list("locations")):
                raise ApiError(400, "Choose an existing location.")
            create("items", {"name": text(body.get("name")), "location": location, "zone": None})
        elif method == "POST" and path == "/impromptu":
            create("impromptu", {"name": text(body.get("name")), "quantity": 0, "is_deleted": None})
        elif method == "POST" and path == "/meals":
            create("meals", {"meal": text(body.get("meal")), "last_eaten": None,
                              "tags": meal_tags(body.get("tags", []))})
        elif method in {"PATCH", "DELETE"} and re.fullmatch(r"/(items|meals|impromptu)/[^/]+", path):
            _, kind, identifier = path.split("/")
            row = self.repo.get(kind, identifier)
            if not row:
                raise ApiError(404, "Record not found.")
            version = body.get("version")
            if type(version) is not int or version != row["version"]:
                raise ApiError(409, "Record changed. Reload before editing.")
            if method == "DELETE" and kind == "meals":
                deletes.append((kind, identifier))
            elif method == "DELETE" and kind == "impromptu":
                writes.append(dict(row, is_deleted=True, updated_at=now, version=version + 1))
            elif method == "PATCH" and kind == "items":
                location = text(body.get("location"), "Location")
                if not any(r["location"] == location for r in self.repo.list("locations")):
                    raise ApiError(400, "Choose an existing location.")
                writes.append(dict(row, location=location, updated_at=now, version=version + 1))
            elif method == "PATCH" and kind == "meals":
                changes = {}
                if "last_eaten" in body:
                    value = body["last_eaten"]
                    try:
                        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                            raise ValueError()
                    except ValueError:
                        raise ApiError(400, "last_eaten must be YYYY-MM-DD.") from None
                    changes["last_eaten"] = value
                if "tags" in body:
                    changes["tags"] = meal_tags(body["tags"])
                if not changes:
                    raise ApiError(400, "Provide a meal field to update.")
                writes.append(dict(row, **changes, updated_at=now, version=version + 1))
            else:
                raise ApiError(404, "Route not found.")
        elif method == "POST" and path == "/shopping/selections":
            entries = body.get("entries")
            if not isinstance(entries, list) or not 1 <= len(entries) <= 90:
                raise ApiError(400, "Send between 1 and 90 selections per request.")
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("store") not in {"costco", "harris_teeter"}:
                    raise ApiError(400, "Invalid selection/store.")
                kind = entry.get("kind")
                if kind not in {"items", "impromptu"}:
                    raise ApiError(400, "Invalid selection source.")
                source = self.repo.get(kind, text(entry.get("id"), "Item ID"))
                if not source or (kind == "impromptu" and visible(source, meta).get("is_deleted") is not None):
                    raise ApiError(409, "An item was removed. Reload the list.")
                create(entry["store"], {"items": source["name"], "is_deleted": None})
        elif method == "POST" and path == "/shopping/after-costco":
            entries = body.get("ids")
            if not isinstance(entries, list) or not 1 <= len(entries) <= 90:
                raise ApiError(400, "Send between 1 and 90 Costco IDs per request.")
            for identifier in entries:
                source = self.repo.get("costco", text(identifier, "Costco ID"))
                if not source or visible(source, meta).get("is_deleted") is not None:
                    raise ApiError(409, "Costco list changed. Reload before saving.")
                create("harris_teeter", {"items": source["items"], "is_deleted": None})
        elif method == "POST" and path == "/shopping/reset":
            # Atomic logical tombstone, including previously-false entries. Retains every record.
            # Later appends have larger createdRevision values and are not cleared.
            meta["clearThrough"] = meta["revision"] - 1
        else:
            raise ApiError(404, "Route not found.")
        return writes, deletes, {"ok": True, "changed": len(writes) + len(deletes), "revision": meta["revision"]}


class DynamoRepository:
    def __init__(self, table_name):
        import boto3
        from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
        self.client = boto3.client("dynamodb")
        self.table = table_name
        self.serializer, self.deserializer = TypeSerializer(), TypeDeserializer()
        self.ddb_timings = []

    def reset_timings(self):
        self.ddb_timings = []

    def _record_timing(self, operation, started, **details):
        self.ddb_timings.append({
            "operation": operation,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            **details,
        })

    def pack(self, value):
        return {k: self.serializer.serialize(v) for k, v in value.items()}

    def unpack(self, value):
        def normalize(v):
            if isinstance(v, Decimal):
                return int(v) if v == int(v) else float(v)
            if isinstance(v, dict):
                return {k: normalize(x) for k, x in v.items()}
            if isinstance(v, list):
                return [normalize(x) for x in v]
            return v
        return normalize({k: self.deserializer.deserialize(v) for k, v in value.items()})

    def raw(self, sk):
        started = time.perf_counter()
        label = sk.split("#", 1)[0]
        try:
            response = self.client.get_item(TableName=self.table, Key=self.pack({"pk": HOUSEHOLD, "sk": sk}), ConsistentRead=True)
        except Exception as exc:
            metadata = getattr(exc, "response", {}).get("ResponseMetadata", {})
            self._record_timing("GetItem", started, keyType=label,
                                retryAttempts=metadata.get("RetryAttempts"),
                                statusCode=metadata.get("HTTPStatusCode"), errorType=type(exc).__name__)
            raise
        metadata = response.get("ResponseMetadata", {})
        self._record_timing("GetItem", started, keyType=label,
                            retryAttempts=metadata.get("RetryAttempts", 0),
                            statusCode=metadata.get("HTTPStatusCode"),
                            itemCount=int("Item" in response))
        return self.unpack(response["Item"]) if "Item" in response else None

    def meta(self):
        meta = self.raw("META")
        if not meta or meta.get("migrationState") != "ready":
            raise ApiError(503, "Data setup is not complete.")
        return {k: v for k, v in meta.items() if k not in {"pk", "sk"}}

    def receipt(self, key):
        return self.raw(f"REQUEST#{key}")

    def get(self, kind, identifier):
        return self.raw(record_key(kind, identifier))

    def list(self, kind):
        started = time.perf_counter()
        result, cursor, pages, retries, status_code = [], None, 0, 0, None
        try:
            while True:
                options = {"TableName": self.table, "ConsistentRead": True,
                           "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                           "ExpressionAttributeValues": self.pack({":pk": HOUSEHOLD, ":prefix": kind.upper() + "#"})}
                if cursor:
                    options["ExclusiveStartKey"] = cursor
                page = self.client.query(**options)
                metadata = page.get("ResponseMetadata", {})
                pages += 1
                retries += metadata.get("RetryAttempts", 0)
                status_code = metadata.get("HTTPStatusCode", status_code)
                result.extend(self.unpack(item) for item in page.get("Items", []))
                cursor = page.get("LastEvaluatedKey")
                if not cursor:
                    self._record_timing("Query", started, kind=kind, pages=pages,
                                        itemCount=len(result), retryAttempts=retries,
                                        statusCode=status_code)
                    return result
        except Exception as exc:
            metadata = getattr(exc, "response", {}).get("ResponseMetadata", {})
            retries += metadata.get("RetryAttempts", 0)
            self._record_timing("Query", started, kind=kind, pages=pages,
                                itemCount=len(result), retryAttempts=retries or metadata.get("RetryAttempts"),
                                statusCode=metadata.get("HTTPStatusCode", status_code),
                                errorType=type(exc).__name__)
            raise

    def commit(self, old, new, writes, deletes, key, fingerprint, response):
        from botocore.exceptions import ClientError
        actions = [{"Put": {"TableName": self.table,
                    "Item": self.pack({"pk": HOUSEHOLD, "sk": "META", **new}),
                    "ConditionExpression": "revision = :old AND migrationState = :ready",
                    "ExpressionAttributeValues": self.pack({":old": old["revision"], ":ready": "ready"})}},
                   {"Put": {"TableName": self.table,
                    "Item": self.pack({"pk": HOUSEHOLD, "sk": f"REQUEST#{key}", "fingerprint": fingerprint,
                                       "response": response}),
                    "ConditionExpression": "attribute_not_exists(pk)"}}]
        for row in writes:
            actions.append({"Put": {"TableName": self.table, "Item": self.pack({**row, "pk": HOUSEHOLD, "sk": record_key(row["kind"], row["id"])})}})
        for kind, identifier in deletes:
            actions.append({"Delete": {"TableName": self.table, "Key": self.pack({"pk": HOUSEHOLD, "sk": record_key(kind, identifier)})}})
        try:
            self.client.transact_write_items(TransactItems=actions)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"TransactionCanceledException", "TransactionConflictException"}:
                reasons = exc.response.get("CancellationReasons", [])
                if any(r.get("Code") not in {None, "None", "ConditionalCheckFailed", "TransactionConflict"} for r in reasons):
                    raise
                time.sleep(0.02)
                return False
            raise


_repo = None
_cold_start = True


def lambda_handler(event, context):
    global _repo, _cold_start
    request_id = getattr(context, "aws_request_id", "local")
    started = time.perf_counter()
    cold_start = _cold_start
    _cold_start = False
    if _repo is not None:
        _repo.reset_timings()
    repository_init_ms = None
    method = event.get("requestContext", {}).get("http", {}).get("method", "UNKNOWN")
    path = event.get("rawPath", "unknown").rstrip("/") or "/"
    route_path = path
    if re.fullmatch(r"/(items|meals|impromptu)/[^/]+", route_path):
        route_path = re.sub(r"/[^/]+$", "/{id}", route_path)
    elif route_path not in {"/items", "/locations", "/meals", "/impromptu", "/shopping",
                             "/shopping/selections", "/shopping/after-costco", "/shopping/reset"}:
        route_path = "<other>"
    route = f"{method} {route_path}"
    try:
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        if not claims.get("sub"):
            raise ApiError(401, "Sign in required.")
        # JWT scope is enforced by API Gateway; group controls shared-household membership.
        groups = claims.get("cognito:groups", "")
        if isinstance(groups, str):
            groups = groups.strip("[]").replace('"', '').replace("'", "").replace(" ", "").split(",")
        if not isinstance(groups, list) or "household" not in groups:
            raise ApiError(403, "Household membership required.")
        domain = os.environ.get("DOMAIN", "")
        prefix = path.split("/")[1]
        allowed = {"inventory": {"items", "locations"}, "shopping": {"shopping", "impromptu"}, "meals": {"meals"}}
        if prefix not in allowed.get(domain, set()):
            raise ApiError(404, "Route not found.")
        if _repo is None:
            init_started = time.perf_counter()
            _repo = DynamoRepository(os.environ["TABLE_NAME"])
            repository_init_ms = round((time.perf_counter() - init_started) * 1000, 2)
        service = Service(_repo)
        if method == "GET":
            response = service.get(path)
        else:
            raw = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw, validate=True).decode("utf-8")
            if len(raw.encode()) > 64_000:
                raise ApiError(413, "Request is too large.")
            body = json.loads(raw)
            headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
            response = service.mutate(method, path, body, headers.get("idempotency-key"))
        status = 200
    except ApiError as exc:
        status, response = exc.status, {"error": exc.message, "requestId": request_id}
    except (ValueError, UnicodeError):
        status, response = 400, {"error": "Invalid JSON/encoding.", "requestId": request_id}
    except Exception as exc:
        # Do not log bodies, tokens, or database exception strings.
        print(json.dumps({"requestId": request_id, "errorType": type(exc).__name__}))
        status, response = 500, {"error": "Request failed. Retry or contact the owner.", "requestId": request_id}
    if _repo is not None and _repo.ddb_timings:
        print(json.dumps({
            "event": "dynamodb_timing",
            "requestId": request_id,
            "route": route,
            "coldStart": cold_start,
            "repositoryInitMs": repository_init_ms,
            "handlerDurationMs": round((time.perf_counter() - started) * 1000, 2),
            "operations": _repo.ddb_timings,
        }, separators=(",", ":")))
    return {"statusCode": status, "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
            "body": json.dumps(response)}
