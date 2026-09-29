# MongoDB Login-IP Enrichment

## What it does

The workflow `.github/workflows/ip-mongodb-enrichment.yml` runs daily at 05:37 UTC and can also be started manually. It:

1. Connects to MongoDB using GitHub Actions Secrets.
2. Idempotently inserts up to eight synthetic login records.
3. Finds login records with a non-empty string `ip` whose `ip_info` is missing, older than 30 days, for a different IP, or previously failed.
4. Looks up each distinct IP once per workflow run.
5. Writes normalized results, authoritative values, vote metadata, and per-provider statuses under `ip_info`.

The current lookup implementation has three active sources, not all eight candidate websites. Partial provider failures are saved as source statuses and do not prevent successful fields from being written.

## Credential safety

MongoDB credentials were pasted into a chat message. Treat those credentials as exposed: rotate the MongoDB database user's password in Atlas before using the workflow. Never place the URI, username, or password in source files, workflow literals, artifacts, or logs.

Create these GitHub repository or environment Secrets after rotating the password:

- `MONGODB_URI`: cluster URI, preferably without embedded username/password, for example `mongodb+srv://cluster0.example.mongodb.net/?retryWrites=true&w=majority`.
- `MONGODB_USERNAME`: the rotated database user's username.
- `MONGODB_PASSWORD`: the rotated password.

The script safely URL-encodes the separate username/password and inserts them into the URI. Optional GitHub Actions Variables:

- `MONGODB_DATABASE`: defaults to `ip_lookup`.
- `MONGODB_COLLECTION`: defaults to `login_ip`.

In MongoDB Atlas, create a database user with only the permissions needed for the target database/collection. GitHub-hosted runners do not have a stable single outbound IP range; prefer a self-hosted runner with a fixed egress IP or private networking. Do not leave Atlas open to `0.0.0.0/0` in production.

## Document shape

The collection is created on the first insert. The job ensures indexes on `ip`, `ip_info.checked_at`, and `ip_info.status` for the scan. Login records use a stable synthetic `_id` so repeated runs do not duplicate them:

```json
{
  "_id": "demo-login-ip-001",
  "login_id": "demo-login-ip-001",
  "user_id": "demo-user-4821",
  "login_at": "2026-09-29T08:24:00+00:00",
  "ip": "1.1.1.1",
  "synthetic": true,
  "created_at": "2026-09-29T12:00:00+00:00",
  "ip_info": {
    "ip": "1.1.1.1",
    "status": "partial",
    "checked_at": "2026-09-29T12:01:00+00:00",
    "authoritative": {
      "ip": "1.1.1.1",
      "geo": {
        "country_code": "AU",
        "country_name": "Australia",
        "region": "Queensland",
        "city": "Brisbane"
      },
      "network": {
        "asn": "AS13335",
        "isp": "Cloudflare, Inc.",
        "type": "hosting"
      },
      "risk": {
        "is_datacenter": true,
        "is_residential": false,
        "is_vpn": false,
        "is_proxy": false,
        "is_tor": false,
        "scores": {
          "trust_score": 41,
          "abuser_score": ""
        }
      }
    },
    "field_provenance": {},
    "selection_policy": "per_field_majority_then_source_priority",
    "confidence": {},
    "successful_source_count": 2,
    "sources": []
  }
}
```

`status` can be `complete`, `partial`, `failed`, or `invalid_ip`. `sources` stores the lookup service's normalized response/status records; it does not store full HTML pages. Synthetic logins are marked `synthetic: true` and use a fixed pool of well-known public resolver IPs for predictable demos. Do not use this option to create production login events.

## Run locally

From the repository root:

```bash
python3 -m pip install -r ip/requirements-mongodb.txt
export MONGODB_URI='mongodb+srv://cluster0.example.mongodb.net/?retryWrites=true&w=majority'
export MONGODB_USERNAME='rotated-db-user'
export MONGODB_PASSWORD='rotated-password'
python3 ip/enrich_mongodb.py --seed-demo --limit 100 --refresh-days 30
```

For a local dry test without a database connection, run:

```bash
python3 -m unittest discover -s ip -p 'test_enrich_mongodb.py' -v
```

## Run in GitHub Actions

Open **Actions → Enrich login IPs in MongoDB → Run workflow**. The manual inputs allow a batch limit and optional force refresh. The scheduled run processes at most 100 stale/missing documents per day and seeds the synthetic records idempotently. The job summary reports counts only; it does not print IP documents or credentials.

Atlas must accept connections from the runner, and the three Secrets must exist. Without these prerequisites the Action will fail at connection time; it cannot be verified from this repository alone without access to the rotated secret and Atlas network policy.

## Refresh behavior

By default, records are rechecked when `ip_info` is missing, more than 30 days old, for an IP different from the document's current `ip`, or marked failed/invalid. `--force` makes every matching IP document eligible. Duplicate IPs share one upstream lookup during each workflow run.
