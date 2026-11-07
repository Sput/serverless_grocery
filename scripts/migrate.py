#!/usr/bin/env python3
"""Validate/normalize private Supabase CSVs. AWS writes require explicit --apply."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import HOUSEHOLD, record_key

INPUTS = {
    "items": "items_rows(1).csv",
    "locations": "location_rows.csv",
    "meals": "meals_rows.csv",
    "costco": "costco_rows(1).csv",
    "harris_teeter": "harris_teeter_rows(1).csv",
    "impromptu": "impromptu_list_rows(1).csv",
}
COLUMNS = {
    "items": {"id", "name", "location", "zone"},
    "locations": {"location"},
    "meals": {"id", "meal", "last_eaten"},
    "costco": {"id", "items", "is_deleted"},
    "harris_teeter": {"id", "items", "is_deleted"},
    "impromptu": {"id", "name", "quantity", "created_at", "updated_at", "is_deleted"},
}


def normalize(folder):
    records, tables, warnings, errors = [], {}, [], []
    digest = hashlib.sha256()
    for kind, filename in INPUTS.items():
        path = folder / filename
        try:
            raw = path.read_bytes()
            digest.update(filename.encode() + b"\0" + raw)
            with path.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if set(reader.fieldnames or []) != COLUMNS[kind]:
                    raise ValueError("Unexpected/missing columns")
                source = list(reader)
        except (OSError, ValueError) as exc:
            errors.append(f"{filename}: {exc}")
            continue
        ids, normalized = set(), []
        for line, original in enumerate(source, 2):
            try:
                if None in original or any(v is None for v in original.values()):
                    raise ValueError("Malformed CSV row")
                row = dict(original)
                if kind == "locations":
                    if not row["location"]:
                        raise ValueError("Blank location primary key")
                    identifier = hashlib.sha256(row["location"].encode()).hexdigest()
                else:
                    identifier = row.pop("id")
                    if not identifier:
                        raise ValueError("Missing primary key")
                if identifier in ids:
                    raise ValueError("Duplicate primary key")
                ids.add(identifier)
                for field in ("zone", "quantity"):
                    if field in row:
                        row[field] = None if row[field] == "" else int(row[field])
                if "zone" in row and row["zone"] not in {None, 1, 2, 3, 4}:
                    warnings.append(f"{filename}:{line}: nonstandard zone retained")
                if "is_deleted" in row:
                    row["is_deleted"] = {"": None, "true": True, "false": False}[row["is_deleted"]]
                # Supabase CSV blank nullable values represent SQL NULL for these exports.
                for field in ("location", "meal", "last_eaten", "created_at", "updated_at"):
                    if field in row and row[field] == "":
                        row[field] = None
                if row.get("last_eaten"):
                    date.fromisoformat(row["last_eaten"])
                for field in ("created_at", "updated_at"):
                    if row.get(field):
                        datetime.fromisoformat(row[field])  # Validate; preserve source timezone/precision verbatim.
                for field in ("name", "items"):
                    if field in row and row[field] == "":
                        warnings.append(f"{filename}:{line}: empty text retained")
                record = {"pk": HOUSEHOLD, "sk": record_key(kind, identifier), "id": identifier,
                          "kind": kind, **row, "version": 1, "createdRevision": 0,
                          "source": {"table": "impromptu_list" if kind == "impromptu" else "location" if kind == "locations" else kind,
                                     "id": original.get("id", original.get("location"))}}
                normalized.append(record)
            except (ValueError, KeyError) as exc:
                errors.append(f"{filename}:{line}: {exc}")
        records.extend(normalized)
        tables[kind] = {"file": filename, "sourceRows": len(source), "normalizedRows": len(normalized)}
        if kind in {"costco", "harris_teeter", "impromptu"}:
            tables[kind]["deletionStates"] = dict(Counter("null" if r["is_deleted"] is None else str(r["is_deleted"]).lower() for r in normalized))
    locations = {r["location"] for r in records if r["kind"] == "locations"}
    unknown = sum(r.get("location") not in locations for r in records if r["kind"] == "items")
    if unknown:
        warnings.append(f"{unknown} catalog items reference absent/null locations; retained, not repaired.")
    for kind, field in [("items", "name"), ("meals", "meal")]:
        names = Counter(r[field] for r in records if r["kind"] == kind)
        duplicates = sum(n - 1 for n in names.values() if n > 1)
        if duplicates:
            warnings.append(f"{kind}: {duplicates} repeated names retained with separate IDs.")
    report = {"sourceFingerprint": digest.hexdigest(), "tables": tables, "totalRows": len(records),
              "warnings": warnings, "errors": errors,
              "excluded": ["inventory", "shopping_list", "older 100-row CSV copies"],
              "nullConvention": "Blank nullable values treated as SQL NULL; false remains distinct from NULL."}
    return records, report


def apply(records, report, table, profile, expected_account):
    import boto3
    from app import DynamoRepository
    session = boto3.Session(profile_name=profile, region_name="us-east-1")
    identity = session.client("sts").get_caller_identity()
    if identity["Account"] != expected_account:
        raise RuntimeError("AWS account does not match --expected-account")
    repo = DynamoRepository.__new__(DynamoRepository)
    from boto3.dynamodb.types import TypeSerializer, TypeDeserializer
    repo.client, repo.table = session.client("dynamodb"), table
    repo.serializer, repo.deserializer = TypeSerializer(), TypeDeserializer()
    repo.ddb_timings = []
    fingerprint = report["sourceFingerprint"]
    meta = repo.raw("META")
    if meta:
        if meta.get("sourceFingerprint") != fingerprint:
            raise RuntimeError("Existing import has a different fingerprint. Refusing to overwrite.")
        if meta.get("migrationState") == "ready":
            print("This dataset has already been imported; no writes performed.")
            return
        if meta.get("migrationState") != "importing":
            raise RuntimeError("Unexpected migration state")
    else:
        page = repo.client.query(TableName=table, KeyConditionExpression="pk = :pk",
                                 ExpressionAttributeValues=repo.pack({":pk": HOUSEHOLD}), Limit=1, ConsistentRead=True)
        if page.get("Items"):
            raise RuntimeError("Target household is not empty. Refusing to overwrite.")
        meta = {"pk": HOUSEHOLD, "sk": "META", "revision": 0, "clearThrough": -1,
                "migrationState": "importing", "sourceFingerprint": fingerprint}
        repo.client.put_item(TableName=table, Item=repo.pack(meta), ConditionExpression="attribute_not_exists(pk)")
    # Checkpoint is the importing metadata. Rerunning the SAME input safely overwrites
    # only its deterministic keys while application writes remain blocked (503).
    resource = session.resource("dynamodb").Table(table)
    with resource.batch_writer() as batch:
        for row in records:
            batch.put_item(Item=row)
    actual = []
    for kind in INPUTS:
        actual.extend(repo.list(kind))
    expected = {r["sk"]: r for r in records}
    if {r["sk"]: r for r in actual} != expected:
        raise RuntimeError("Post-import reconciliation failed; household remains locked for recovery.")
    repo.client.update_item(TableName=table, Key=repo.pack({"pk": HOUSEHOLD, "sk": "META"}),
        UpdateExpression="SET migrationState = :ready",
        ConditionExpression="migrationState = :importing AND sourceFingerprint = :fingerprint",
        ExpressionAttributeValues=repo.pack({":ready": "ready", ":importing": "importing", ":fingerprint": fingerprint}))
    print(f"Imported and reconciled {len(records)} records. Household ready.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "migration/private")
    parser.add_argument("--apply", action="store_true", help="Explicitly write to AWS; omitted means local validation only")
    parser.add_argument("--table")
    parser.add_argument("--confirm-table")
    parser.add_argument("--profile", default="serverless-grocery")
    parser.add_argument("--expected-account")
    args = parser.parse_args()
    records, report = normalize(args.input)
    output = args.input / "validation-report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["errors"]:
        return 1
    (args.input / "normalized.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    if args.apply:
        if not args.table or args.confirm_table != args.table or not args.expected_account:
            parser.error("--apply requires --table, matching --confirm-table, and --expected-account")
        apply(records, report, args.table, args.profile, args.expected_account)
    else:
        print("LOCAL VALIDATION ONLY. No AWS calls or writes performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
