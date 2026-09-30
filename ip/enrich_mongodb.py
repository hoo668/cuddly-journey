#!/usr/bin/env python3
"""Enrich login-IP documents in MongoDB with normalized lookup results."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from lookup import lookup


DEMO_IPS = (
    "1.1.1.1",
    "1.0.0.1",
    "8.8.8.8",
    "8.8.4.4",
    "9.9.9.9",
    "149.112.112.112",
    "208.67.222.222",
    "208.67.220.220",
)


def build_mongodb_uri(uri: str, username: str | None, password: str | None) -> str:
    if not username and not password:
        return uri
    if not username or not password:
        raise ValueError("MONGODB_USERNAME and MONGODB_PASSWORD must be set together")

    parsed = urlsplit(uri)
    if parsed.scheme not in {"mongodb", "mongodb+srv"}:
        raise ValueError("MONGODB_URI must use mongodb:// or mongodb+srv://")
    host = parsed.netloc.rsplit("@", 1)[-1]
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit(parsed._replace(netloc=netloc))


def seed_demo_documents(collection: Any, count: int = 8) -> int:
    now = datetime.now(timezone.utc)
    chosen_ips = random.sample(DEMO_IPS, k=min(count, len(DEMO_IPS)))
    inserted = 0
    for index, address in enumerate(chosen_ips, start=1):
        document_id = f"demo-login-ip-{index:03d}"
        login_at = now - timedelta(minutes=random.randint(0, 60 * 24 * 30))
        result = collection.update_one(
            {"_id": document_id},
            {
                "$setOnInsert": {
                    "login_id": document_id,
                    "user_id": f"demo-user-{random.randint(1000, 9999)}",
                    "login_at": login_at,
                    "ip": address,
                    "synthetic": True,
                    "created_at": now,
                }
            },
            upsert=True,
        )
        inserted += int(result.upserted_id is not None)
    return inserted


def lookup_status(result: dict[str, Any]) -> str:
    if not result.get("ip"):
        return "failed"
    sources = result.get("sources", [])
    successful = [source for source in sources if source.get("status") == "ok"]
    usable = [source for source in sources if source.get("status") not in {"unsupported", "skipped"}]
    return "complete" if successful and len(successful) == len(usable) else "partial"


def make_ip_info(ip: str, result: dict[str, Any] | None, error: str | None = None) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc)
    if result is None:
        return {
            "ip": ip,
            "status": "invalid_ip",
            "checked_at": checked_at,
            "error": error or "invalid_ip",
            "authoritative": None,
            "field_provenance": {},
            "confidence": {},
            "successful_source_count": 0,
            "sources": [],
        }

    authoritative = result.get("authoritative", {})
    return {
        "ip": ip,
        "status": lookup_status(result),
        "checked_at": checked_at,
        "authoritative": authoritative.get("data"),
        "field_provenance": authoritative.get("field_provenance", {}),
        "selection_policy": authoritative.get("selection_policy"),
        "confidence": result.get("confidence", {}),
        "successful_source_count": result.get("successful_source_count", 0),
        "sources": result.get("sources", []),
    }


def enrich_collection(
    collection: Any,
    limit: int,
    refresh_days: int,
    force: bool = False,
    lookup_fn: Any = lookup,
    batch_size: int = 100,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=refresh_days)
    retry_cutoff = now - timedelta(days=1)
    query: dict[str, Any] = {"ip": {"$type": "string", "$ne": ""}}
    if not force:
        query["$or"] = [
            {"ip_info.checked_at": {"$exists": False}},
            {"ip_info.checked_at": {"$lt": cutoff}},
            {"$expr": {"$ne": ["$ip_info.ip", "$ip"]}},
            {"ip_info.status": "failed", "ip_info.checked_at": {"$lt": retry_cutoff}},
        ]

    documents = collection.find(query, {"ip": 1})
    documents = documents.sort([("ip", 1), ("_id", 1)]).batch_size(batch_size)
    if limit > 0:
        documents = documents.limit(limit)
    status_counts = {"complete": 0, "partial": 0, "failed": 0, "invalid_ip": 0}
    modified = 0
    scanned = 0
    unique_ips_queried = 0
    previous_stored_ip: str | None = None
    cached_result: dict[str, Any] | None = None
    cached_error: str | None = None

    for document in documents:
        scanned += 1
        stored_ip = document["ip"]
        address = stored_ip.strip()
        if stored_ip != previous_stored_ip:
            previous_stored_ip = stored_ip
            unique_ips_queried += 1
            try:
                cached_result = lookup_fn(address, timeout=10.0)
                cached_error = None
            except ValueError:
                cached_result = None
                cached_error = "invalid_ip"

        ip_info = make_ip_info(address, cached_result, cached_error)
        status_counts[ip_info["status"]] += 1
        update = collection.update_one(
            {"_id": document["_id"]},
            {"$set": {"ip_info": ip_info}},
        )
        modified += int(update.modified_count > 0)

    return {
        "matched": scanned,
        "scanned": scanned,
        "modified": modified,
        "unique_ips_queried": unique_ips_queried,
        **status_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich login-IP documents in MongoDB.")
    parser.add_argument("--database", default=os.environ.get("MONGODB_DATABASE", "ip_lookup"))
    parser.add_argument("--collection", default=os.environ.get("MONGODB_COLLECTION", "login_ip"))
    parser.add_argument("--limit", type=int, default=0, help="Maximum documents to scan; 0 scans all matching documents")
    parser.add_argument("--batch-size", type=int, default=100, help="MongoDB cursor batch size; controls memory use")
    parser.add_argument("--refresh-days", type=int, default=30)
    parser.add_argument("--force", action="store_true", help="Recheck matching IP documents even if fresh")
    parser.add_argument("--seed-demo", action="store_true", help="Insert eight idempotent synthetic login records")
    args = parser.parse_args()

    if args.limit < 0 or args.refresh_days < 0 or args.batch_size < 1:
        parser.error("--limit and --refresh-days cannot be negative; --batch-size must be positive")
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        parser.error("MONGODB_URI is required")
    try:
        uri = build_mongodb_uri(uri, os.environ.get("MONGODB_USERNAME"), os.environ.get("MONGODB_PASSWORD"))
    except ValueError as error:
        parser.error(str(error))

    try:
        from pymongo import MongoClient
    except ImportError:
        parser.error("install dependencies with: pip install -r ip/requirements-mongodb.txt")

    from pymongo.errors import PyMongoError

    try:
        with MongoClient(uri, serverSelectionTimeoutMS=15_000) as client:
            client.admin.command("ping")
            collection = client[args.database][args.collection]
            collection.create_index([("ip", 1), ("_id", 1)])
            collection.create_index("ip_info.checked_at")
            collection.create_index("ip_info.status")
            seeded = seed_demo_documents(collection) if args.seed_demo else 0
            summary = enrich_collection(collection, args.limit, args.refresh_days, args.force, batch_size=args.batch_size)
            summary["seeded_demo_documents"] = seeded
            summary["database"] = args.database
            summary["collection"] = args.collection
            print(json.dumps(summary, ensure_ascii=False))
    except PyMongoError as error:
        print(f"MongoDB operation failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())