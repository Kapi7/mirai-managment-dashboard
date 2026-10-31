#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
psp_fees.py — Shopify Payments fee fetcher with daily helpers.

- Uses `processed_at` for time filtering (correct for Balance Transactions).
- Converts each balance-transaction fee from its own currency to USD
  (FX_<CUR>_TO_USD) before summing. Daily buckets are USD.
- Standalone version - no config.py dependency.

Env:
  SHOPIFY_STORE / SHOPIFY_ACCESS_TOKEN           (main store)
  SHOPIFY_API_VERSION
  REPORT_TZ
"""

from __future__ import annotations
import re, os, time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

_PSP_FX_MOD = None


def _psp_fx():
    """Load the shared converter from automation_reports/psp_fx.py."""
    global _PSP_FX_MOD
    if _PSP_FX_MOD is None:
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "automation_reports" / "psp_fx.py"
        spec = importlib.util.spec_from_file_location("mirai_psp_fx", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load PSP FX helper from {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PSP_FX_MOD = mod
    return _PSP_FX_MOD


def transaction_fee_usd(txn: dict):
    return _psp_fx().transaction_fee_usd(txn)


def interpret_stored_daily_fee(amount: float, currency: Optional[str] = None) -> float:
    return _psp_fx().interpret_stored_daily_fee(amount, currency)


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


def _tz(tz_name: Optional[str] = None) -> pytz.BaseTzInfo:
    if tz_name:
        return pytz.timezone(tz_name)
    return _get_tz()


def order_fees_from_transactions(txns, start_dt, end_dt, tz) -> Dict[int, float]:
    """Shopify order id → USD charge fee, same rules as the Telegram bot.

    ``psp_fx.charge_order_fee_usd`` keeps charge/payment/sale only. Refunds
    stay in the daily total and are not added onto the order.
    """
    fx = _psp_fx()
    idx: Dict[int, float] = {}
    for txn in txns or []:
        processed = _parse_iso(txn.get("processed_at"))
        if processed is None:
            continue
        if processed.tzinfo is None:
            processed = pytz.UTC.localize(processed)
        processed_local = processed.astimezone(tz)
        if not (start_dt <= processed_local < end_dt):
            continue
        parsed = fx.charge_order_fee_usd(txn)
        if parsed is None:
            continue
        order_id, fee_usd = parsed
        idx[order_id] = round(idx.get(order_id, 0.0) + fee_usd, 2)
    return idx


# 429 and 5xx are retried. A timeout is retried too; giving up marks the
# fetch incomplete instead of pretending the pages we already have are the
# whole history.
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 5


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _fetch_page(url: str, headers: Dict[str, str], params, timeout: int = 60):
    """GET one page. Returns (response, error). error is set when retries are exhausted."""
    delay = 1.0
    last_error = "request failed"
    for _attempt in range(_MAX_ATTEMPTS):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        except requests.Timeout as exc:
            last_error = f"timeout: {exc}"
            _sleep(delay)
            delay = min(delay * 2, 16)
            continue
        except requests.RequestException as exc:
            last_error = f"request error: {exc}"
            _sleep(delay)
            delay = min(delay * 2, 16)
            continue
        status = response.status_code
        if status in _RETRY_STATUS or status >= 500:
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after)
            except (TypeError, ValueError):
                wait = delay
            last_error = f"HTTP {status}"
            _sleep(min(max(wait, 0.0), 30.0))
            delay = min(delay * 2, 16)
            continue
        return response, None
    return None, last_error


def _fetch_until_for_store(
    store_domain: str,
    access_token: str,
    start_dt_local: datetime,
    tz,
    limit: int = 250,
    max_pages: int = 400,
) -> Tuple[List[dict], bool, str]:
    """Balance transactions, newest first, and whether that history is complete.

    Complete means we paged until a transaction older than ``start_dt_local``,
    or we reached the last page (empty page, 404 on the first page, or no
    ``next`` link) with no error. A 429/5xx/timeout after retries, a mid-walk
    HTTP error, or stopping at ``max_pages`` while a next page still exists
    is incomplete: the oldest day in the partial list can be a short sum.
    """
    base = f"https://{store_domain}/admin/api/{SHOPIFY_API_VERSION}"
    url = f"{base}/shopify_payments/balance/transactions.json"
    params = {"limit": limit}
    out: List[dict] = []
    pages = 0

    while True:
        response, error = _fetch_page(url, _headers_for(access_token), params if pages == 0 else None)
        if error:
            print(f"[psp_fees] INCOMPLETE FETCH: {error}")
            return out, False, error
        if response.status_code == 404:
            if pages == 0:
                return out, True, ""
            print("[psp_fees] INCOMPLETE FETCH: HTTP 404 mid-pagination")
            return out, False, "HTTP 404 mid-pagination"
        if response.status_code >= 400:
            reason = f"HTTP {response.status_code}"
            print(f"[psp_fees] INCOMPLETE FETCH: {reason}")
            return out, False, reason

        data = response.json() or {}
        txns = data.get("transactions") or data.get("balance_transactions") or []
        if not txns:
            return out, True, ""

        out.extend(txns)

        pts = [_parse_iso(t.get("processed_at")) for t in txns if t.get("processed_at")]
        if pts:
            oldest = min(pts)
            if oldest and oldest.tzinfo is None:
                oldest = pytz.UTC.localize(oldest)
            if oldest and oldest.astimezone(tz) < start_dt_local:
                return out, True, ""

        next_url = _extract_next_link(response.headers.get("Link") or "")
        pages += 1
        if not next_url:
            return out, True, ""
        if pages >= max_pages:
            reason = f"stopped at max_pages={max_pages} with a next page"
            print(f"[psp_fees] INCOMPLETE FETCH: {reason}")
            return out, False, reason

        url = next_url
        params = None


def _load_store_transactions(start_date: date, end_date_exclusive: date, tz_name: Optional[str] = None):
    """Every store's transactions plus whether each walk finished.

    ``complete`` is False if any store stopped early. Callers must not treat
    a partial ``daily`` map as the real history.
    """
    tz = _tz(tz_name)
    start_dt = tz.localize(datetime.combine(start_date, datetime.min.time()))
    end_dt = tz.localize(datetime.combine(end_date_exclusive, datetime.min.time()))
    if not SHOPIFY_STORES:
        print("[psp_fees] No stores configured")
        return [], False, "no stores configured", tz, start_dt, end_dt

    bundles = []
    reasons = []
    complete = True
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token = store["access_token"]
        label = store["label"]
        txns, ok, reason = _fetch_until_for_store(domain, token, start_dt, tz)
        print(f"[psp_fees] Store '{label}' ({domain}) – transactions fetched: {len(txns)} complete={ok}")
        if not ok:
            complete = False
            reasons.append(f"{label}: {reason}")
        bundles.append(txns)
    if not complete:
        print(f"[psp_fees] INCOMPLETE FETCH: {'; '.join(reasons)}")
    return bundles, complete, "; ".join(reasons), tz, start_dt, end_dt


def _daily_from_transactions(bundles, tz, start_dt, end_dt) -> Dict[date, float]:
    daily: Dict[date, float] = {}
    for txns in bundles:
        for txn in txns:
            processed = _parse_iso(txn.get("processed_at"))
            if processed is None:
                continue
            if processed.tzinfo is None:
                processed = pytz.UTC.localize(processed)
            processed_local = processed.astimezone(tz)
            if not (start_dt <= processed_local < end_dt):
                continue
            fee_usd = transaction_fee_usd(txn)
            if fee_usd is None:
                continue
            day = processed_local.date()
            daily[day] = round(daily.get(day, 0.0) + fee_usd, 2)
    return daily


def get_psp_fees_daily_result(
    start_date: date,
    end_date_exclusive: date,
    tz_name: Optional[str] = None,
) -> Dict[str, object]:
    """``{fees, complete, reason}`` for [start_date, end_date_exclusive).

    ``complete`` is False when pagination stopped on an error, a timeout, or
    max_pages. ``fees`` may still hold a partial sum; do not apply it.
    """
    bundles, complete, reason, tz, start_dt, end_dt = _load_store_transactions(
        start_date, end_date_exclusive, tz_name
    )
    return {
        "fees": _daily_from_transactions(bundles, tz, start_dt, end_dt),
        "complete": complete,
        "reason": reason,
    }


def get_psp_fees_daily(
    start_date: date,
    end_date_exclusive: date,
    tz_name: Optional[str] = None,
) -> Dict[date, float]:
    """
    Returns dict[date] -> total PSP fee in USD for each day in
    [start_date, end_date_exclusive).

    Each balance transaction is converted with its own currency before it is
    added. Do not multiply the result by FX_EUR_TO_USD.

    ``tz_name`` is the report timezone (the Telegram bot's shop timezone).
    When it is omitted, ``REPORT_TZ`` is used, then UTC.

    An incomplete pagination is logged and still returned. Backfill must use
    ``get_psp_fees_daily_result`` and refuse to apply when ``complete`` is false.
    """
    result = get_psp_fees_daily_result(start_date, end_date_exclusive, tz_name=tz_name)
    return result["fees"]  # type: ignore[return-value]


def get_order_psp_fees_result(
    start_date: date,
    end_date_exclusive: date,
    tz_name: Optional[str] = None,
) -> Dict[str, object]:
    """``{fees, complete, reason}``. ``fees`` maps Shopify order id → USD charge fee."""
    bundles, complete, reason, tz, start_dt, end_dt = _load_store_transactions(
        start_date, end_date_exclusive, tz_name
    )
    idx: Dict[int, float] = {}
    for txns in bundles:
        for order_id, fee_usd in order_fees_from_transactions(txns, start_dt, end_dt, tz).items():
            idx[order_id] = round(idx.get(order_id, 0.0) + fee_usd, 2)
    return {"fees": idx, "complete": complete, "reason": reason}


def get_order_psp_fees(
    start_date: date,
    end_date_exclusive: date,
    tz_name: Optional[str] = None,
) -> Dict[int, float]:
    """Shopify order id → USD fee for charge-like balance transactions.

    This is the per-order number the Telegram bot stores on the alert
    (``psp_fx.charge_order_fee_usd``). The window is the report timezone.
    ``end_date_exclusive`` is exclusive, so the last inclusive report day is
    the day before it.
    """
    result = get_order_psp_fees_result(start_date, end_date_exclusive, tz_name=tz_name)
    return result["fees"]  # type: ignore[return-value]


def get_psp_fee_for_date(target_date: date) -> float:
    """Get PSP fee for a single date."""
    daily = get_psp_fees_daily(target_date, target_date + timedelta(days=1))
    return daily.get(target_date, 0.0)
