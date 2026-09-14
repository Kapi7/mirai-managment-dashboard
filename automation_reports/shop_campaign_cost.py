# shop_campaign_cost.py — EXACT Shop Campaigns cost from Shopify ShopifyQL.
#
# Shopify's REST/GraphQL objects (orders, transactions, balance tx, marketing
# activities) expose NO Shop Campaigns cost. But the analytics dataset
# `shop_campaign_insights` does, via the `shopifyqlQuery` GraphQL field —
# currently only on the `unstable` Admin API version. This is the same data
# the Shop "campaign insights" report + Sidekick use, so it's the real billed
# ad spend per day (self-updating; nothing to configure).
#
# Fields available on shop_campaign_insights:
#   shop_campaign_ad_spend                              (MONEY, per day)
#   shop_campaign_average_customer_acquisition_cost     (MONEY)
#   shop_campaign_return_on_ad_spend                    (MULTIPLIER)
#
# Usage:
#   from shop_campaign_cost import spend_for_day
#   spend = spend_for_day("2026-07-12")   # -> float USD, or None if unavailable
#
# CLI:  python shop_campaign_cost.py --days 30

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import requests

from config import SHOPIFY_STORES

# ShopifyQL is only exposed on the unstable channel today. Override if Shopify
# promotes it to a dated version.
_QL_API_VERSION = os.getenv("SHOPIFYQL_API_VERSION", "unstable").strip() or "unstable"

_WINDOW_DAYS = int(os.getenv("SHOP_CAMPAIGN_WINDOW_DAYS", "60") or 60)
_CACHE_TTL_SEC = int(os.getenv("SHOP_CAMPAIGN_CACHE_SEC", "1800") or 1800)  # 30 min

_GQL = """
query ($q: String!) {
  shopifyqlQuery(query: $q) {
    tableData {
      rows
      columns { name dataType }
    }
    parseErrors
  }
}
"""

# module-level cache: {store_domain: {"map": {day_iso: float}, "ts": epoch}}
_CACHE: Dict[str, Dict[str, Any]] = {}


def _ql_for_store(domain: str, token: str, since_days: int) -> Optional[Dict[str, Dict[str, Optional[float]]]]:
    """Return {day_iso: {"ad_spend": usd, "cac": usd|None}} for one store, or None on failure."""
    ql = (
        "FROM shop_campaign_insights "
        "SHOW shop_campaign_ad_spend, shop_campaign_average_customer_acquisition_cost "
        f"TIMESERIES day SINCE startOfDay(-{int(since_days)}d) UNTIL today"
    )
    url = f"https://{domain}/admin/api/{_QL_API_VERSION}/graphql.json"
    try:
        r = requests.post(
            url,
            json={"query": _GQL, "variables": {"q": ql}},
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
    except Exception as e:
        print(f"[shop-campaign] ShopifyQL request failed for {domain}: {e}")
        return None

    if body.get("errors"):
        # e.g. field missing on a stable version, or access denied
        print(f"[shop-campaign] ShopifyQL errors for {domain}: {json.dumps(body['errors'])[:300]}")
        return None

    resp = ((body.get("data") or {}).get("shopifyqlQuery")) or {}
    pe = resp.get("parseErrors")
    if pe:
        print(f"[shop-campaign] ShopifyQL parseErrors for {domain}: {json.dumps(pe)[:300]}")
        return None

    td = resp.get("tableData") or {}
    rows = td.get("rows") or []
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = row.get("day")
        if not day:
            continue
        try:
            spend = float(row.get("shop_campaign_ad_spend") or 0)
        except (TypeError, ValueError):
            spend = 0.0
        cac_raw = row.get("shop_campaign_average_customer_acquisition_cost")
        try:
            cac = float(cac_raw) if cac_raw not in (None, "") else None
        except (TypeError, ValueError):
            cac = None
        out[str(day)[:10]] = {"ad_spend": spend, "cac": cac}
    return out


def _store_map(domain: str, token: str) -> Optional[Dict[str, float]]:
    """Cached per-store daily spend map."""
    now = time.time()
    cached = _CACHE.get(domain)
    if cached and now - cached["ts"] < _CACHE_TTL_SEC:
        return cached["map"]

    m = _ql_for_store(domain, token, _WINDOW_DAYS)
    if m is None:
        # keep stale cache if we have one, else signal failure
        return cached["map"] if cached else None

    _CACHE[domain] = {"map": m, "ts": now}
    return m


def daily_rich_map() -> Optional[Dict[str, Dict[str, Optional[float]]]]:
    """
    Combined {day_iso: {"ad_spend": usd, "cac": usd|None}} across all stores.
    Returns None if NO store produced data (caller should use a fallback).
    """
    combined: Dict[str, Dict[str, Optional[float]]] = {}
    any_ok = False
    for store in SHOPIFY_STORES:
        m = _store_map(store["domain"], store["access_token"])
        if m is None:
            continue
        any_ok = True
        for day, vals in m.items():
            cur = combined.setdefault(day, {"ad_spend": 0.0, "cac": None})
            cur["ad_spend"] = round((cur["ad_spend"] or 0.0) + (vals.get("ad_spend") or 0.0), 2)
            # keep any non-null CAC (single active store in practice)
            if vals.get("cac") is not None:
                cur["cac"] = vals["cac"]
    return combined if any_ok else None


def daily_spend_map() -> Optional[Dict[str, float]]:
    """
    Combined {day_iso: total ad_spend USD} across all stores.
    Returns None if NO store produced data (caller should use a fallback).
    """
    rich = daily_rich_map()
    if rich is None:
        return None
    return {day: float(vals.get("ad_spend") or 0.0) for day, vals in rich.items()}


def current_cac() -> Optional[float]:
    """
    Most recent per-customer acquisition cost Shopify reports for Shop
    Campaigns (today's if present, else the latest day with data). Used to
    price a single acquired order in real time. None if no data.
    """
    rich = daily_rich_map()
    if not rich:
        return None
    for day in sorted(rich.keys(), reverse=True):
        cac = rich[day].get("cac")
        if cac is not None and cac > 0:
            return round(float(cac), 2)
    return None


def spend_for_day(day_iso: str) -> Optional[float]:
    """
    Exact Shop Campaigns ad spend for a given YYYY-MM-DD (shop timezone).
    Returns 0.0 for a covered day with no spend, None if data is unavailable
    (outside the fetched window or ShopifyQL failed) so callers can fall back.
    """
    m = daily_spend_map()
    if m is None:
        return None
    return m.get(str(day_iso)[:10])


def total_spend(days: int = 30) -> Optional[float]:
    """Sum of exact ad spend over the trailing `days` (for debug/summary)."""
    m = daily_spend_map()
    if m is None:
        return None
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return round(sum(v for d, v in m.items() if d >= cutoff), 2)


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser(description="Fetch exact Shop Campaigns cost via ShopifyQL")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    m = daily_rich_map()
    if m is None:
        print("No ShopifyQL data (unavailable). Check API version / access scope.")
    else:
        for day in sorted(m):
            if m[day].get("ad_spend"):
                cac = m[day].get("cac")
                cac_txt = f"  CAC ${cac:.2f}" if cac else ""
                print(f"  {day}  ${m[day]['ad_spend']:>8.2f}{cac_txt}")
        print(f"\nTrailing {args.days}d total: ${total_spend(args.days):.2f}")
        print(f"Current CAC: {current_cac()}")
