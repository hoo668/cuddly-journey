#!/usr/bin/env python3
"""Collect and normalize public IP information from lightweight HTTP sources."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
import urllib.error
from collections import defaultdict
import urllib.request
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Any


PING0_URL = "https://ipv4.ping0.cc/geo/jsonp/ipv4cb"
USER_AGENT = "ip-lookup/1.0 (+https://github.com/)"
IPIP_URL = "https://ipip.la/"
COFFEE_URL = "https://ip.net.coffee/api/ipv2/lookup/"

FIELD_PRIORITY = {"ip.net.coffee": 0, "ipip.la": 1, "ping0.cc": 2}
VOTED_FIELDS = (
    "ip",
    "country_code",
    "country",
    "region",
    "city",
    "asn",
    "isp",
    "network_type",
    "is_datacenter",
    "is_residential",
    "is_vpn",
    "is_proxy",
    "is_tor",
)


def fetch_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html, */*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(1_000_000).decode("utf-8", errors="replace")

def fetch_ping0(timeout: float) -> dict[str, Any]:
    body = fetch_text(PING0_URL, timeout)
    match = re.fullmatch(
        r'\s*ipv4cb\("([^"\n]+)"\s*,\s*"([^"\n]*)"\s*,\s*'
        r'"([^"\n]*)"\s*,\s*"([^"\n]*)"\s*,\s*"([^"\n]*)"\s*\)\s*',
        body,
    )
    if not match:
        raise ValueError("ping0 returned an unexpected response")

    address, location, asn, organization, country_code = match.groups()
    address = str(ipaddress.ip_address(address))
    return {
        "ip": address,
        "country_code": country_code or None,
        "asn": asn or None,
        "isp": organization or None,
        "location_text": location or None,
    }


def fetch_ipip(ip: str | None, timeout: float) -> dict[str, Any]:
    url = IPIP_URL if ip is None else f"{IPIP_URL}?ip={quote(ip, safe=':.')}"
    body = fetch_text(url, timeout)
    match = re.search(r"window\.__IPINFO__\s*=\s*(\{.*?\})\s*;", body, re.DOTALL)
    if not match:
        raise ValueError("ipip.la did not include its structured IP result")

    data = json.loads(match.group(1))
    asn_data = data.get("asn") if isinstance(data.get("asn"), dict) else {}
    company_data = data.get("company") if isinstance(data.get("company"), dict) else {}
    organization = data.get("org") or asn_data.get("name") or company_data.get("name")
    asn_match = re.search(r"\bAS\d+\b", str(asn_data.get("asn") or organization or ""), re.I)
    asn = asn_match.group(0).upper() if asn_match else None
    isp = re.sub(r"^AS\d+\s*", "", str(organization)).strip() if organization else None
    result_ip = str(ipaddress.ip_address(data["ip"]))
    if ip is not None and result_ip != ip:
        raise ValueError("ipip.la returned a different IP")
    return {
        "ip": result_ip,
        "country_code": data.get("country") or None,
        "country": data.get("country_name") or None,
        "region": data.get("region") or None,
        "city": data.get("city") or None,
        "asn": asn,
        "isp": isp,
        "network_type": asn_data.get("type") or company_data.get("type"),
        "location_text": None,
    }


def fetch_coffee(ip: str, timeout: float) -> dict[str, Any]:
    body = fetch_text(f"{COFFEE_URL}{quote(ip, safe=':.')}", timeout)
    data = json.loads(body)
    result_ip = str(ipaddress.ip_address(data["ip"]))
    return {
        "ip": result_ip,
        "country_code": data.get("countryCode", "").upper() or None,
        "country": data.get("country"),
        "region": data.get("region"),
        "city": data.get("city"),
        "asn": f"AS{data['asn']}" if data.get("asn") else None,
        "isp": data.get("asOrganization") or data.get("company_name"),
        "network_type": data.get("company_type") or data.get("asn_kind"),
        "is_datacenter": data.get("is_datacenter"),
        "is_residential": data.get("isResidential"),
        "is_vpn": data.get("is_vpn"),
        "is_proxy": data.get("is_proxy"),
        "is_tor": data.get("is_tor"),
        "trust_score": data.get("trust_score"),
        "abuser_score": data.get("abuser_score"),
        "geo_source_count": len(data.get("geo_sources", [])),
        "location_text": None,
    }


def collect(name: str, fetcher: Any, timeout: float) -> dict[str, Any]:
    try:
        return {"name": name, "status": "ok", "weight": 1, **fetcher(timeout)}
    except (OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError) as error:
        return {"name": name, "status": "error", "weight": 1, "error": str(error)}


def consensus(sources: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    fields: dict[str, Any] = {}
    confidence: dict[str, Any] = {}
    for field in VOTED_FIELDS:
        groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "sources": [], "value": None})
        total = 0
        for source in sources:
            value = source.get(field)
            if source["status"] != "ok" or value is None or value == "":
                continue
            total += source["weight"]
            normalized = str(value).strip().casefold() if isinstance(value, str) else json.dumps(value, sort_keys=True)
            group = groups[normalized]
            group["count"] += source["weight"]
            group["sources"].append(source["name"])
            group["value"] = value
        if not groups:
            fields[field] = None
            continue
        winner = min(
            groups.values(),
            key=lambda group: (
                -group["count"],
                min(FIELD_PRIORITY.get(name, 99) for name in group["sources"]),
            ),
        )
        fields[field] = winner["value"]
        confidence[field] = {
            "agreement": f"{winner['count']}/{total}",
            "ratio": round(winner["count"] / total, 3),
            "source_count": winner["count"],
            "level": "high" if winner["count"] >= 3 and winner["count"] / total >= 0.67 else "medium" if winner["count"] >= 2 else "low",
            "sources": winner["sources"],
        }
    return fields, confidence


def lookup(ip: str | None, timeout: float) -> dict[str, Any]:
    if ip is not None:
        ip = str(ipaddress.ip_address(ip))

    sources: list[dict[str, Any]] = []
    ipip_source = collect("ipip.la", lambda per_source_timeout: fetch_ipip(ip, per_source_timeout), timeout)
    sources.append(ipip_source)
    effective_ip = ip or ipip_source.get("ip")

    if ip is None:
        ping0_source = collect("ping0.cc", fetch_ping0, timeout)
        sources.append(ping0_source)
        effective_ip = effective_ip or ping0_source.get("ip")
    else:
        sources.append({"name": "ping0.cc", "status": "skipped", "reason": "Only reports the requester's IP"})

    if effective_ip:
        coffee_source = collect("ip.net.coffee", lambda per_source_timeout: fetch_coffee(effective_ip, per_source_timeout), timeout)
        if coffee_source.get("status") == "ok" and coffee_source.get("ip") != effective_ip:
            coffee_source = {"name": "ip.net.coffee", "status": "error", "weight": 1, "error": "Returned a different IP"}
        sources.append(coffee_source)
    else:
        sources.append({"name": "ip.net.coffee", "status": "skipped", "reason": "No IP address could be discovered"})

    fields, confidence = consensus(sources)
    successful_sources = [source for source in sources if source["status"] == "ok"]
    trust_score = next((source.get("trust_score") for source in sources if source.get("trust_score") is not None), None)
    abuser_score = next((source.get("abuser_score") for source in sources if source.get("abuser_score") is not None), None)
    geo_source_count = next((source.get("geo_source_count") for source in sources if source.get("geo_source_count") is not None), None)

    authoritative_data = {
        "ip": fields["ip"],
        "geo": {
            "country_code": fields["country_code"],
            "country_name": fields["country"],
            "region": fields["region"],
            "city": fields["city"],
        },
        "network": {
            "asn": fields["asn"],
            "isp": fields["isp"],
            "type": fields["network_type"],
        },
        "risk": {
            "is_datacenter": fields["is_datacenter"],
            "is_residential": fields["is_residential"],
            "is_vpn": fields["is_vpn"],
            "is_proxy": fields["is_proxy"],
            "is_tor": fields["is_tor"],
            "scores": {
                "trust_score": trust_score,
                "abuser_score": abuser_score,
            },
        },
    }
    field_provenance: dict[str, Any] = {}
    provenance_fields = {
        "ip": "ip",
        "geo.country_code": "country_code",
        "geo.country_name": "country",
        "geo.region": "region",
        "geo.city": "city",
        "network.asn": "asn",
        "network.isp": "isp",
        "network.type": "network_type",
        "risk.is_datacenter": "is_datacenter",
        "risk.is_residential": "is_residential",
        "risk.is_vpn": "is_vpn",
        "risk.is_proxy": "is_proxy",
        "risk.is_tor": "is_tor",
    }
    for path, field in provenance_fields.items():
        vote = confidence.get(field)
        if vote:
            if vote["ratio"] <= 0.5:
                selection = "source_priority_tiebreak"
            elif vote["source_count"] == 1:
                selection = "single_reporting_source"
            else:
                selection = "majority"
            field_provenance[path] = {
                "selected_from": vote["sources"],
                "agreement": vote["agreement"],
                "ratio": vote["ratio"],
                "confidence": vote["level"],
                "selection": selection,
            }
    for field in ("trust_score", "abuser_score"):
        provider = next((source for source in sources if source.get(field) is not None), None)
        if provider:
            field_provenance[f"risk.scores.{field}"] = {
                "selected_from": [provider["name"]],
                "confidence": "source_only",
                "selection": "provider_value_not_cross_compared",
            }

    return {
        "schema_version": "1.0",
        "queried_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query_ip": ip or fields.get("ip"),
        "authoritative": {
            "data": authoritative_data,
            "field_provenance": field_provenance,
            "selection_policy": "per_field_majority_then_source_priority",
        },
        **fields,
        "trust_score": trust_score,
        "abuser_score": abuser_score,
        "geo_source_count": geo_source_count,
        "confidence": confidence,
        "successful_source_count": len(successful_sources),
        "sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Query and normalize public IP information.")
    parser.add_argument("--ip", help="IPv4 or IPv6 address to query; defaults to this runner's public IP")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-source timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    try:
        result = lookup(args.ip, args.timeout)
    except ValueError as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ip"]:
        print(f"IP: {result['ip']}")
        print(f"国家/地区: {result['country'] or result['country_code'] or '未知'} ({result['country_code'] or '未知'})")
        print(f"地区/城市: {', '.join(value for value in (result['region'], result['city']) if value) or '未知'}")
        print(f"ASN: {result['asn'] or '未知'}")
        print(f"运营商: {result['isp'] or '未知'}")
        print(f"网络类型: {result['network_type'] or '未知'}")
        print(f"数据中心/住宅: {result['is_datacenter']!s}/{result['is_residential']!s}")
        print(f"VPN/代理/Tor: {result['is_vpn']!s}/{result['is_proxy']!s}/{result['is_tor']!s}")
        print(f"信任分: {result['trust_score'] if result['trust_score'] is not None else '未知'}")
        print(f"有效来源: {result['successful_source_count']}")
        for field in ("country_code", "city", "asn", "isp", "is_proxy"):
            agreement = result["confidence"].get(field, {}).get("agreement")
            if agreement:
                print(f"  {field}: {agreement}")
    else:
        print("查询失败：没有数据源返回有效 IP。", file=sys.stderr)
        for source in result["sources"]:
            if source["status"] == "error":
                print(f"{source['name']}: {source['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())