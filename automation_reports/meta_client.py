# meta_client.py
from __future__ import annotations
import os, json, requests
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
import pytz

# You can override these via env:
#   META_GRAPH_VERSION (default v24.0)
#   META_ACCESS_TOKEN
#   META_AD_ACCOUNT_ID  (with or without "act_")
#   META_DEBUG=1        (verbose logs)
#   DISABLE_META=1      (skip Meta completely and return 0 spend)
GRAPH_VER = os.getenv("META_GRAPH_VERSION", "v24.0")

_META_WARNED: bool = False

# ----------------- small utils -----------------
def _dbg() -> bool:
    return os.getenv("META_DEBUG", "0") == "1"

def _token() -> str:
    token = (os.getenv("META_ACCESS_TOKEN", "") or "").strip()
    if _dbg():
        # Do NOT print full token, only prefix + length, for sanity check
        print(f"[META] using token prefix={token[:10]}... len={len(token)}")
    return token

def _act_id() -> str:
    aid = (os.getenv("META_AD_ACCOUNT_ID", "") or "").strip()
    if not aid:
        return ""
    return aid if aid.startswith("act_") else f"act_{aid}"

def _print_params(tag: str, url: str, params: Dict[str, Any]) -> None:
    if not _dbg():
        return
    safe = params.copy()
    safe["access_token"] = "***"  # don't leak token in logs
    print(f"[META] {tag} URL={url}")
    print("[META]   params:", json.dumps(safe, indent=2, sort_keys=True))

# ----------------- HTTP helpers -----------------
def _get(url: str, params: Dict[str, Any]) -> dict | None:
    global _META_WARNED
    _print_params("GET", url, params)
    try:
        r = requests.get(url, params=params, timeout=60)
        if not r.ok:
            try:
                payload = r.json()
            except Exception:
                payload = r.text[:400]
            if _dbg():
                print("[META] ERR", r.status_code, payload)
            if not _META_WARNED:
                print("⚠️ Meta Insights warning:", r.status_code, payload)
                _META_WARNED = True
            return None
        return r.json() or {}
    except Exception as e:
        if _dbg():
            print("[META] EXC", e)
        if not _META_WARNED:
            print("⚠️ Meta Insights exception:", e)
            _META_WARNED = True
        return None

def _iterate_paged(url: str, params: dict) -> List[dict]:
    rows: List[dict] = []
    js = _get(url, params)
    while js:
        data = js.get("data") or []
        if not isinstance(data, list):
            break
        rows.extend(data)
        paging = js.get("paging") or {}
        next_url = paging.get("next")
        if not next_url:
            break
        js = _get(next_url, {})  # next URL already includes all params
    return rows

# ----------------- account metadata -----------------
def _fetch_account_meta() -> Tuple[str, str]:
    """
    Returns (timezone_name, currency_3letter) from the AdAccount node.
    Correct field on AdAccount is 'currency' (NOT 'account_currency').
    """
    token, act = _token(), _act_id()
    if not token or not act:
        return ("UTC", "USD")
    url = f"https://graph.facebook.com/{GRAPH_VER}/{act}"
    js = _get(url, {"access_token": token, "fields": "timezone_name,currency"}) or {}
    tz = (js.get("timezone_name") or "UTC").strip() or "UTC"
    cur = (js.get("currency") or "USD").strip().upper() or "USD"
    if _dbg():
        print(f"[META] acct meta tz={tz} currency={cur}")
    return tz, cur

# ----------------- time mapping -----------------
def _shop_window_in_account_tz(day_iso: str, shop_tz_name: str, acct_tz_name: str):
    shop_tz = pytz.timezone(shop_tz_name)
    acct_tz = pytz.timezone(acct_tz_name)
    d = datetime.strptime(day_iso, "%Y-%m-%d").date()
    start_shop = shop_tz.localize(datetime.combine(d, datetime.min.time()))
    end_shop = start_shop + timedelta(days=1)
    return start_shop.astimezone(acct_tz), end_shop.astimezone(acct_tz)

def _allowed_hours_map(start_acct: datetime, end_acct: datetime) -> dict[str, set]:
    out: dict[str, set] = {}
    d0, d1 = start_acct.date(), end_acct.date()
    h0, h1 = start_acct.hour, end_acct.hour
    if d0 == d1:
        out[d0.isoformat()] = set(range(h0, h1))
        return out
    out[d0.isoformat()] = set(range(h0, 24))
    cur = d0 + timedelta(days=1)
    while cur < d1:
        out[cur.isoformat()] = set(range(0, 24))
        cur += timedelta(days=1)
    out[d1.isoformat()] = set(range(0, h1))
    return out

def _parse_hour(v: str) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    try:
        return int(s[:2])
    except Exception:
        try:
            return int(s)
        except Exception:
            return None

# ----------------- hourly spend fetcher -----------------
def _hourly_sum(level: str, span_start: str, span_end: str, hours_map: dict[str, set]) -> Tuple[float, str, int]:
    token, act = _token(), _act_id()
    if not token or not act:
        return (0.0, "USD", 0)

    url = f"https://graph.facebook.com/{GRAPH_VER}/{act}/insights"
    params = {
        "access_token": token,
        "level": level,  # "ad" or "campaign"
        "time_increment": 1,
        "breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone",
        "fields": "spend,account_currency,date_start",
        "time_range": json.dumps({"since": span_start, "until": span_end}),
        "limit": 5000,
    }

    rows = _iterate_paged(url, params)
    spend = 0.0
    currency = "USD"
    matched = 0

    for r in rows:
        d = (r.get("date_start") or "").strip()
        hr = _parse_hour(r.get("hourly_stats_aggregated_by_advertiser_time_zone"))
        if hr is None:
            continue
        allowed = hours_map.get(d)
        if not allowed or hr not in allowed:
            continue
        try:
            spend += float(r.get("spend") or 0.0)
        except Exception:
            pass
        if r.get("account_currency"):
            currency = (r["account_currency"] or currency)
        matched += 1

    if _dbg():
        print(f"[META] hourly level={level} span={span_start}..{span_end} rows={matched} spend={round(spend,2)} {currency}")
    return (round(spend, 2), currency or "USD", matched)

# ----------------- public API -----------------
def fetch_meta_insights_day(since_yyyy_mm_dd: str, until_yyyy_mm_dd: str) -> Dict[str, Any]:
    """
    Returns: {"meta_spend": float, "currency": "USD"|...}
    """
    # Allow hard disabling from env
    if os.getenv("DISABLE_META", "0") == "1":
        if _dbg():
            print("[META] DISABLE_META=1 → returning 0 spend")
        return {"meta_spend": 0.0, "currency": "USD"}

    # Shopify/store timezone is supplied by your app into env:
    shop_tz = os.getenv("REPORT_TZ") or os.getenv("SHOPIFY_TZ") or os.getenv("SHOP_TZ") or "UTC"

    # -------- single day (aligned hourly) --------
    if since_yyyy_mm_dd == until_yyyy_mm_dd:
        acct_tz, acct_currency = _fetch_account_meta()
        start_acct, end_acct = _shop_window_in_account_tz(since_yyyy_mm_dd, shop_tz, acct_tz)
        hours_map = _allowed_hours_map(start_acct, end_acct)
        span_start, span_end = min(hours_map.keys()), max(hours_map.keys())

        spend, cur, rows = _hourly_sum("ad", span_start, span_end, hours_map)
        if rows == 0 or spend == 0.0:
            spend2, cur2, rows2 = _hourly_sum("campaign", span_start, span_end, hours_map)
            if rows2 > 0:
                spend, cur = spend2, cur2

        final_currency = (cur or acct_currency or "USD").upper()
        if _dbg():
            print(f"[META] aligned result day={since_yyyy_mm_dd} shop_tz={shop_tz} acct_tz={acct_tz} spend={spend} {final_currency}")
        return {"meta_spend": round(spend, 2), "currency": final_currency}

    # -------- multi-day (simple daily account totals) --------
    token, act = _token(), _act_id()
    if not token or not act:
        return {"meta_spend": 0.0, "currency": "USD"}

    url = f"https://graph.facebook.com/{GRAPH_VER}/{act}/insights"
    params = {
        "access_token": token,
        "level": "account",
        "time_increment": 1,
        "fields": "spend,account_currency",
        "time_range": json.dumps({"since": since_yyyy_mm_dd, "until": until_yyyy_mm_dd}),
        "limit": 1000,
    }
    rows = _iterate_paged(url, params)

    spend, currency = 0.0, "USD"
    for row in rows:
        try:
            spend += float(row.get("spend") or 0.0)
        except Exception:
            pass
        currency = row.get("account_currency") or currency

    if _dbg():
        print(f"[META] range {since_yyyy_mm_dd}..{until_yyyy_mm_dd} spend={round(spend,2)} {currency}")
    return {"meta_spend": round(spend, 2), "currency": (currency or "USD").upper()}
