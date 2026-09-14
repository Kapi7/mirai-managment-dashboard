#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
psp_fees.py — Shopify Payments fee fetcher (EUR) with daily + MTD helpers,
for MULTIPLE Shopify stores.

- Uses `processed_at` for time filtering (correct for Balance Transactions).
- Supports many stores via config.SHOPIFY_STORES.
- Returns daily buckets (dict[date] -> fee_eur) summed across all stores.
- MTD total is also summed across all stores.
- No writes; just a library to import.

Env:
  SHOPIFY_STORE / SHOPIFY_ACCESS_TOKEN           (main store)
  SHOPIFY_STORE_C / SHOPIFY_ACCESS_TOKEN_C       (cosmetics store)
  SHOPIFY_API_VERSION
"""

from __future__ import annotations
import re, os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

import pytz
import requests
from dotenv import load_dotenv

from config import SHOPIFY_STORES, SHOPIFY_API_VERSION
from shopify_client import get_shop_timezone


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
    tz_name = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"
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
        r = requests.get(
            url,
            headers=_headers_for(access_token),
            params=params if pages == 0 else None,
            timeout=60,
        )
        if r.status_code == 404:
            break
        r.raise_for_status()
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
    Returns dict[date] -> total PSP fee (EUR) for each day in [start_date, end_date_exclusive),
    summed across ALL stores in config.SHOPIFY_STORES.

    Missing days are omitted (0 not included).
    """
    from os.path import dirname, join
    load_dotenv(join(dirname(__file__), ".env"))

    if not SHOPIFY_STORES:
        return {}

    tz = _get_tz()
    start_dt = tz.localize(datetime.combine(start_date, datetime.min.time()))
    end_dt   = tz.localize(datetime.combine(end_date_exclusive, datetime.min.time()))

    daily: Dict[date, float] = {}

    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token  = store["access_token"]
        label  = store["label"]

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


def get_psp_fee_mtd(today_local: date | None = None) -> float:
    """
    Returns MTD total PSP fees (EUR) across ALL stores up to 'today_local'
    (exclusive of tomorrow boundary).
    """
    tz = _get_tz()
    now_local = datetime.now(tz)
    if today_local is None:
        today_local = now_local.date()

    start = today_local.replace(day=1)
    end_excl = today_local + timedelta(days=1)

    daily = get_psp_fees_daily(start, end_excl)
    return round(sum(daily.values()), 2)
