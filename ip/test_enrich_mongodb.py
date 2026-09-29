import unittest
from datetime import datetime, timezone

from enrich_mongodb import build_mongodb_uri, enrich_collection, make_ip_info, seed_demo_documents


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, key, direction):
        self.documents.sort(key=lambda document: document[key], reverse=direction < 0)
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or []

    def find(self, query, projection):
        return FakeCursor(list(self.documents))

    def update_one(self, selector, update, upsert=False):
        for document in self.documents:
            if document.get("_id") == selector.get("_id"):
                document.update(update.get("$set", {}))
                return type("UpdateResult", (), {"modified_count": 1, "upserted_id": None})()
        if upsert:
            document = {"_id": selector["_id"], **update.get("$setOnInsert", {})}
            self.documents.append(document)
            return type("UpdateResult", (), {"modified_count": 0, "upserted_id": selector["_id"]})()
        return type("UpdateResult", (), {"modified_count": 0, "upserted_id": None})()


class MongoEnrichmentTests(unittest.TestCase):
    def test_build_uri_escapes_credentials(self):
        uri = build_mongodb_uri("mongodb+srv://cluster.example/db", "user@name", "p:a ss")
        self.assertEqual(uri, "mongodb+srv://user%40name:p%3Aa%20ss@cluster.example/db")

    def test_ip_info_keeps_authoritative_and_provider_details(self):
        result = {
            "ip": "1.1.1.1",
            "authoritative": {"data": {"ip": "1.1.1.1"}, "field_provenance": {"ip": {"selected_from": ["ipip.la"]}}},
            "confidence": {"ip": {"agreement": "1/1"}},
            "successful_source_count": 1,
            "sources": [{"name": "ipip.la", "status": "ok"}],
        }
        ip_info = make_ip_info("1.1.1.1", result)
        self.assertEqual(ip_info["status"], "complete")
        self.assertEqual(ip_info["authoritative"], {"ip": "1.1.1.1"})
        self.assertEqual(ip_info["sources"][0]["name"], "ipip.la")
        self.assertIsInstance(ip_info["checked_at"], datetime)

    def test_enrichment_queries_duplicate_ip_once_and_writes_each_document(self):
        documents = [
            {"_id": "login-1", "ip": "1.1.1.1"},
            {"_id": "login-2", "ip": "1.1.1.1"},
            {"_id": "login-3", "ip": "not-an-ip"},
        ]
        collection = FakeCollection(documents)
        calls = []

        def fake_lookup(ip, timeout):
            calls.append(ip)
            if ip == "not-an-ip":
                raise ValueError("invalid_ip")
            return {
                "ip": ip,
                "authoritative": {"data": {"ip": ip}, "field_provenance": {}},
                "confidence": {},
                "successful_source_count": 1,
                "sources": [{"name": "ipip.la", "status": "ok"}],
            }

        summary = enrich_collection(collection, limit=10, refresh_days=30, force=True, lookup_fn=fake_lookup)
        self.assertEqual(calls, ["1.1.1.1", "not-an-ip"])
        self.assertEqual(summary["matched"], 3)
        self.assertEqual(summary["unique_ips_queried"], 2)
        self.assertEqual(summary["modified"], 3)
        self.assertEqual(documents[0]["ip_info"]["authoritative"]["ip"], "1.1.1.1")
        self.assertEqual(documents[2]["ip_info"]["status"], "invalid_ip")

    def test_demo_records_are_idempotent(self):
        collection = FakeCollection()
        first_inserted = seed_demo_documents(collection, count=4)
        second_inserted = seed_demo_documents(collection, count=4)
        self.assertEqual(first_inserted, 4)
        self.assertEqual(second_inserted, 0)
        self.assertTrue(all(document["synthetic"] for document in collection.documents))


if __name__ == "__main__":
    unittest.main()
