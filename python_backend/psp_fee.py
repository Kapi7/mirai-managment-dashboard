#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
psp_fees.py — Shopify Payments fee fetcher (EUR/USD) with daily helpers.

- Uses `processed_at` for time filtering (correct for Balance Transactions).
- Returns daily buckets (dict[date] -> fee) summed across configured stores.
- Standalone version - no config.py dependency.

Env:
  SHOPIFY_STORE / SHOPIFY_ACCESS_TOKEN           (main store)
  SHOPIFY_API_VERSION
  REPORT_TZ
"""

from __future__ import annotations
import re, os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

# Config from environment
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "").strip()
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()

# Build stores list
SHOPIFY_STORES = []
if SHOPIFY_STORE and SHOPIFY_ACCESS_TOKEN:
    SHOPIFY_STORES.append({
        "key": "skin",
        "label": "Mirai Skin",
        "domain": SHOPIFY_STORE,
        "access_token": SHOPIFY_ACCESS_TOKEN,
    })


def _headers_for(access_token: str) -> Dict[str, str]:
    return {
        "X-Shopify-Access-Token": access_token,
        "Accept": "application/json",
    }


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = ts.replace("Z", "+00:00")
    if s.endswith("+0000"):
        s = s[:-5] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _extract_next_link(link_header: str) -> Optional[str]:
    for part in (link_header or "").split(","):
        if 'rel="next"' in part:
            m = re.search(r'<([^>]+)>', part)
            if m:
                return m.group(1)
    return None


def _get_tz() -> pytz.BaseTzInfo:
    tz_name = os.getenv("REPORT_TZ") or "UTC"
    return pytz.timezone(tz_name)


def _fetch_until_for_store(
    store_domain: str,
    access_token: str,
    start_dt_local: datetime,
    tz,
    limit: int = 250,
    max_pages: int = 400,
) -> List[dict]:
    base = f"https://{store_domain}/admin/api/{SHOPIFY_API_VERSION}"
    url = f"{base}/shopify_payments/balance/transactions.json"

    params = {"limit": limit}
    out: List[dict] = []
    pages = 0

    while True:
        try:
            r = requests.get(
                url,
                headers=_headers_for(access_token),
                params=params if pages == 0 else None,
                timeout=60,
            )
            if r.status_code == 404:
                break
            r.raise_for_status()
        except Exception as e:
            print(f"[psp_fees] Error fetching: {e}")
            break

        data = r.json() or {}
        txns = data.get("transactions") or data.get("balance_transactions") or []
        if not txns:
            break

        out.extend(txns)

        pts = [_parse_iso(t.get("processed_at")) for t in txns if t.get("processed_at")]
        if pts:
            oldest = min(pts)
            if oldest and oldest.tzinfo is None:
                oldest = pytz.UTC.localize(oldest)
            if oldest and oldest.astimezone(tz) < start_dt_local:
                break

        link = r.headers.get("Link") or ""
        next_url = _extract_next_link(link)
        pages += 1
        if not next_url or pages >= max_pages:
            break

        url = next_url
        params = None

    return out


def get_psp_fees_daily(start_date: date, end_date_exclusive: date) -> Dict[date, float]:
    """
    Returns dict[date] -> total PSP fee for each day in [start_date, end_date_exclusive).
    Fee is returned in the currency from Shopify (typically store currency).
    """
    if not SHOPIFY_STORES:
        print("[psp_fees] No stores configured")
        return {}

    tz = _get_tz()
    start_dt = tz.localize(datetime.combine(start_date, datetime.min.time()))
    end_dt = tz.localize(datetime.combine(end_date_exclusive, datetime.min.time()))

    daily: Dict[date, float] = {}

    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token = store["access_token"]
        label = store["label"]

        txns = _fetch_until_for_store(domain, token, start_dt, tz)
        print(f"[psp_fees] Store '{label}' ({domain}) – transactions fetched: {len(txns)}")

        for t in txns:
            fee = t.get("fee")
            p = _parse_iso(t.get("processed_at"))
            if fee is None or p is None:
                continue
            if p.tzinfo is None:
                p = pytz.UTC.localize(p)
            p_local = p.astimezone(tz)
            if not (start_dt <= p_local < end_dt):
                continue
            try:
                amt = abs(float(fee))
            except Exception:
                continue
            dkey = p_local.date()
            daily[dkey] = round(daily.get(dkey, 0.0) + amt, 2)

    return daily


def get_psp_fee_for_date(target_date: date) -> float:
    """Get PSP fee for a single date."""
    daily = get_psp_fees_daily(target_date, target_date + timedelta(days=1))
    return daily.get(target_date, 0.0)
