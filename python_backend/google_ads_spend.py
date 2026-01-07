#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
google_ads_spend.py — Google Ads daily spend aligned to *Shopify day* across accounts.

Features:
- Auto-discover leaf accounts under your MCC (optional).
- Aligns Shopify day (shop_tz) to each Google Ads account timezone using hourly cost.
- Retries transient gRPC/transport errors.
- Auto-reauthorizes and updates google-ads.yaml if refresh_token is invalid (invalid_grant).
- Converts each account’s currency → USD via FX_<CUR>_TO_USD envs.
- CLI helpers for reauth & testing.

Public API:
    usd = daily_spend_usd_aligned(day_iso, shop_tz, config_path, include_ids=None)

Key env vars:
    GOOGLE_ADS_CONFIG=google-ads.yaml  # or absolute path
    LOGIN_CUSTOMER_ID=<your_MCC_id>     # (also can live inside google-ads.yaml as login_customer_id)
    GOOGLE_ADS_CUSTOMER_IDS=111,222     # explicit *leaf* accounts to include (comma-separated)
    GOOGLE_ADS_CUSTOMER_ID=111          # single leaf fallback
    GOOGLE_ADS_EXCLUDE_IDS=333,444      # exclude specific leaves from discovery/union
    GOOGLE_ADS_DISCOVER=1               # discover leaf accounts under MCC and UNION with explicit list (default 1)
    GOOGLE_ADS_DEBUG=1                  # verbose per-account logs
    GOOGLE_ADS_MAX_RETRIES=5
    GOOGLE_ADS_BACKOFF_BASE=0.7

FX:
    FX_EUR_TO_USD=1.10, FX_GBP_TO_USD=1.30, ...
"""

from __future__ import annotations
import os
import time
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple, Dict, Set

import pytz
import yaml
from dotenv import load_dotenv

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from grpc import RpcError


# Load .env so the module also works when run standalone
load_dotenv()

GOOGLE_ADS_OAUTH_CLIENT = os.getenv("GOOGLE_ADS_OAUTH_CLIENT", "").strip()
_SCOPES = ["https://www.googleapis.com/auth/adwords"]

# --------------------- helpers ---------------------

def _fx_any_to_usd(amount: float, currency: str) -> float:
    try:
        cur = (currency or "USD").upper()
        if cur == "USD":
            return round(float(amount), 2)
        rate = float(os.getenv(f"FX_{cur}_TO_USD", "1.0"))
        return round(float(amount) * rate, 2)
    except Exception:
        return round(float(amount), 2)

def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _parse_id_list(ids: Optional[Iterable[str]]) -> List[str]:
    if ids is None:
        return []
    if isinstance(ids, str):
        ids = ids.split(",")
    out = []
    for raw in ids:
        cid = _only_digits(str(raw))
        if cid:
            out.append(cid)
    return sorted(set(out))

def _load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _save_yaml(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

def _build_flow(config_path: str) -> InstalledAppFlow:
    cfg = _load_yaml(config_path)
    client_id = (cfg.get("client_id") or "").strip()
    client_secret = (cfg.get("client_secret") or "").strip()

    if GOOGLE_ADS_OAUTH_CLIENT and os.path.exists(GOOGLE_ADS_OAUTH_CLIENT):
        return InstalledAppFlow.from_client_secrets_file(GOOGLE_ADS_OAUTH_CLIENT, scopes=_SCOPES)

    if not client_id or not client_secret:
        raise RuntimeError(
            "google-ads.yaml missing client_id/client_secret and no GOOGLE_ADS_OAUTH_CLIENT json provided."
        )
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }
    return InstalledAppFlow.from_client_config(client_config, scopes=_SCOPES)

def _reauthorize_and_update_yaml(config_path: str) -> str:
    """
    Interactive OAuth reauth:
    - Opens a browser (or prints URL + asks for code).
    - Gets a new refresh_token.
    - Writes it back into google-ads.yaml.
    """
    print("🔐 Starting Google Ads reauthorization (invalid_grant detected)...")
    flow = _build_flow(config_path)
    try:
        creds = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            authorization_prompt_message="Please authorize access in your browser...",
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
    except Exception:
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        print("\n🔐 Google Ads reauthorization required (invalid_grant).")
        print("Open this URL in your browser, grant access, then paste the code below:\n")
        print(auth_url, "\n")
        code = input("Paste authorization code: ").strip()
        flow.fetch_token(code=code)
        creds = flow.credentials

    if not creds or not creds.refresh_token:
        raise RuntimeError("Failed to obtain a new refresh_token from Google OAuth.")

    cfg = _load_yaml(config_path)
    cfg["refresh_token"] = creds.refresh_token
    _save_yaml(config_path, cfg)
    print("✅ Saved new refresh_token to", config_path)
    return creds.refresh_token

def _build_client(config_path: str) -> GoogleAdsClient:
    return GoogleAdsClient.load_from_storage(path=config_path)

# --------------------- GAQL pieces ---------------------

_QUERY_ACCOUNT_META = """
    SELECT
      customer.currency_code,
      customer.time_zone
    FROM customer
    LIMIT 1
"""

def _query_hourly_cost(client: GoogleAdsClient, customer_id: str,
                       start_date: str, end_date: str):
    ga_service = client.get_service("GoogleAdsService")
    req = client.get_type("SearchGoogleAdsRequest")
    req.customer_id = customer_id
    req.query = f"""
        SELECT
          segments.date,
          segments.hour,
          metrics.cost_micros
        FROM customer
        WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
    """
    return ga_service.search(request=req)

def _query_daily_cost(client: GoogleAdsClient, customer_id: str, day: str) -> float:
    ga_service = client.get_service("GoogleAdsService")
    req = client.get_type("SearchGoogleAdsRequest")
    req.customer_id = customer_id
    req.query = f"""
        SELECT
          segments.date,
          metrics.cost_micros
        FROM customer
        WHERE segments.date = '{day}'
    """
    micros = 0
    for row in ga_service.search(request=req):
        micros += int(row.metrics.cost_micros or 0)
    return round(micros / 1_000_000.0, 2)

# --------------------- account discovery ---------------------

def _discover_leaf_accounts(client: GoogleAdsClient, login_customer_id: str) -> List[str]:
    """
    Returns list of child *leaf* customer IDs that are not managers (MCC).
    """
    ga_service = client.get_service("GoogleAdsService")
    q = """
        SELECT
          customer_client.id,
          customer_client.manager,
          customer_client.level,
          customer_client.hidden
        FROM customer_client
        WHERE customer_client.level >= 1
    """
    resp = ga_service.search(customer_id=login_customer_id, query=q)

    leaves: List[str] = []
    for row in resp:
        cc = row.customer_client
        if cc.hidden:
            continue
        if not cc.manager and cc.id:
            leaves.append(str(cc.id))
    return sorted(set(leaves))

# --------------------- core alignment logic ---------------------

def _fetch_account_meta(client: GoogleAdsClient, customer_id: str) -> Tuple[str, str]:
    """
    Return (currency_code, time_zone_name) for the account.
    """
    svc = client.get_service("GoogleAdsService")
    req = client.get_type("SearchGoogleAdsRequest")
    req.customer_id = customer_id
    req.query = _QUERY_ACCOUNT_META
    resp = svc.search(request=req)
    for row in resp:
        return (row.customer.currency_code, row.customer.time_zone)
    return ("USD", "UTC")

def _shop_window_in_account_tz(day_iso: str, shop_tz_name: str, acct_tz_name: str) -> Tuple[datetime, datetime]:
    """
    Convert the Shopify day [00:00, +24h) (shop_tz) into account's timezone.
    """
    shop_tz = pytz.timezone(shop_tz_name)
    acct_tz = pytz.timezone(acct_tz_name)

    day = datetime.strptime(day_iso, "%Y-%m-%d").date()
    start_shop = shop_tz.localize(datetime.combine(day, datetime.min.time()))
    end_shop = start_shop + timedelta(days=1)

    return start_shop.astimezone(acct_tz), end_shop.astimezone(acct_tz)

def _allowed_hours_map(start_acct: datetime, end_acct: datetime) -> Dict[str, Set[int]]:
    """
    Return { 'YYYY-MM-DD': {hours…} } in *account* local time to include for the Shopify day.
    """
    d0 = start_acct.date()
    d1 = end_acct.date()
    h0 = start_acct.hour
    h1 = end_acct.hour

    include_end_hour = (end_acct.minute > 0 or end_acct.second > 0)

    out: Dict[str, Set[int]] = {}
    key = lambda d: d.isoformat()

    if d0 == d1:
        end_inclusive = h1 if include_end_hour else (h1 - 1)
        hours = set(range(h0, max(h0, end_inclusive + 1)))
        out[key(d0)] = hours
        return out

    out[key(d0)] = set(range(h0, 24))
    cur = d0 + timedelta(days=1)
    while cur < d1:
        out[key(cur)] = set(range(0, 24))
        cur += timedelta(days=1)
    end_inclusive = h1 if include_end_hour else (h1 - 1)
    out[key(d1)] = set(range(0, max(0, end_inclusive + 1)))
    return out

def _fetch_cost_one_account_aligned(client: GoogleAdsClient, customer_id: str,
                                    day_iso: str, shop_tz: str) -> Tuple[float, str, str]:
    """
    Return (amount_in_account_currency, currency_code, account_tz) aligned to Shopify day.
    """
    currency, acct_tz = _fetch_account_meta(client, customer_id)
    start_acct, end_acct = _shop_window_in_account_tz(day_iso, shop_tz, acct_tz)
    hours_map = _allowed_hours_map(start_acct, end_acct)

    span_start = min(hours_map.keys())
    span_end   = max(hours_map.keys())

    total_micros = 0
    resp = _query_hourly_cost(client, customer_id, span_start, span_end)
    for row in resp:
        try:
            d = row.segments.date.value  # 'YYYY-MM-DD'
        except Exception:
            d = str(row.segments.date)
        hr = int(getattr(row.segments, "hour", 0) or 0)
        allowed = hours_map.get(d)
        if allowed and hr in allowed:
            total_micros += int(row.metrics.cost_micros or 0)

    amount = round(total_micros / 1_000_000.0, 2)

    if os.getenv("GOOGLE_ADS_DEBUG", "0") == "1":
        native_pairs = []
        for d in sorted({span_start, span_end}):
            try:
                native_pairs.append((d, _query_daily_cost(client, customer_id, d)))
            except Exception:
                native_pairs.append((d, "ERR"))
        s_acct, e_acct = start_acct.strftime('%Y-%m-%d %H:%M'), end_acct.strftime('%Y-%m-%d %H:%M')
        print(f"[GADS][{customer_id}] TZ={acct_tz} shop_window=[{s_acct} .. {e_acct}) "
              f"span={span_start}..{span_end} aligned={amount} {currency} native={native_pairs}")

    return amount, (currency or "USD"), acct_tz

def _with_retries(func, *args, **kwargs):
    """
    Retry transient gRPC/transport issues, rebuilding the client only when needed.
    """
    attempts = int(os.getenv("GOOGLE_ADS_MAX_RETRIES", "5"))
    base = float(os.getenv("GOOGLE_ADS_BACKOFF_BASE", "0.7"))
    last_exc = None
    for i in range(attempts):
        try:
            return func(*args, **kwargs)
        except (GoogleAdsException, RpcError) as e:
            last_exc = e
            msg = str(e)
            transient = any(
                t in msg for t in (
                    "Channel deallocated", "UNAVAILABLE", "INTERNAL", "deadline",
                    "RST_STREAM", "GOAWAY", "connection", "temporar"
                )
            )
            if not transient or i == attempts - 1:
                raise
            time.sleep(base * (2 ** i) + (0.05 * i))
    if last_exc:
        raise last_exc

# ---- account set construction -------------------------------------------------

def _union_account_ids(client: GoogleAdsClient, config_path: str) -> List[str]:
    """
    Build the final set of account IDs to use:
      - Start with explicit GOOGLE_ADS_CUSTOMER_IDS (and/or GOOGLE_ADS_CUSTOMER_ID).
      - If GOOGLE_ADS_DISCOVER=1 (default), UNION all leaf accounts discovered under LOGIN_CUSTOMER_ID.
      - Remove any GOOGLE_ADS_EXCLUDE_IDS.
    """
    explicit = _parse_id_list(os.getenv("GOOGLE_ADS_CUSTOMER_IDS", ""))
    single = _only_digits(os.getenv("GOOGLE_ADS_CUSTOMER_ID", ""))
    if single and single not in explicit:
        explicit.append(single)

    discover = os.getenv("GOOGLE_ADS_DISCOVER", "1") == "1"
    excludes = set(_parse_id_list(os.getenv("GOOGLE_ADS_EXCLUDE_IDS", "")))

    discovered: List[str] = []
    if discover:
        cfg = _load_yaml(config_path)
        login_id = _only_digits(cfg.get("login_customer_id") or os.getenv("LOGIN_CUSTOMER_ID", ""))
        if login_id:
            try:
                discovered = _discover_leaf_accounts(client, login_id)
            except Exception as e:
                if os.getenv("GOOGLE_ADS_DEBUG", "0") == "1":
                    print(f"[GADS] discovery failed (continuing with explicit list only): {e}")
        elif os.getenv("GOOGLE_ADS_DEBUG", "0") == "1":
            print("[GADS] no login_customer_id configured; skipping discovery.")

    union = sorted(set(explicit) | set(discovered))
    final = [cid for cid in union if cid not in excludes]

    if os.getenv("GOOGLE_ADS_DEBUG", "0") == "1":
        print(f"[GADS] accounts_final={final} explicit={explicit} discovered={discovered} exclude={list(excludes)}")

    return final

def _sum_accounts_usd_aligned(day_iso: str, shop_tz: str, config_path: str,
                              include_ids: Optional[List[str]]) -> float:
    client = _build_client(config_path)

    ids = _parse_id_list(include_ids)
    if not ids:
        ids = _union_account_ids(client, config_path)

    if not ids:
        if os.getenv("GOOGLE_ADS_DEBUG", "0") == "1":
            print("[GADS] No accounts to query. Returning 0.")
        return 0.0

    total_usd = 0.0
    debug = os.getenv("GOOGLE_ADS_DEBUG", "0") == "1"
    for cid in ids:
        amt_acct, cur, acct_tz = _with_retries(_fetch_cost_one_account_aligned, client, cid, day_iso, shop_tz)
        usd = _fx_any_to_usd(amt_acct, cur)
        total_usd += usd
        if debug:
            s_acct, e_acct = _shop_window_in_account_tz(day_iso, shop_tz, acct_tz)
            print(f"[GADS][{cid}] {day_iso} shop_tz={shop_tz} acct_tz={acct_tz} "
                  f"window=[{s_acct.strftime('%Y-%m-%d %H:%M')} .. {e_acct.strftime('%Y-%m-%d %H:%M')}) "
                  f"=> {amt_acct} {cur} → {usd} USD")

    return round(total_usd, 2)

# --------------------- public entry ---------------------

def daily_spend_usd_aligned(day_iso: str, shop_tz: str, config_path: str,
                            include_ids: Optional[Iterable[str]] = None) -> float:
    """
    Returns total daily spend (USD) for the Shopify day:
      - For each leaf account, converts the Shopify day to the account's timezone,
        pulls hourly costs for the intersecting local dates, and sums only the hours that
        fall inside the Shopify day window.
      - If include_ids is empty/None, we UNION explicit env lists with discovered leaves.
      - Retries transient errors. On invalid_grant in local env, reauths once and retries.
    """
    try:
        return _sum_accounts_usd_aligned(day_iso, shop_tz, config_path, include_ids)
    except (GoogleAdsException, RefreshError, Exception) as e:
        msg = str(e)
        # Handle invalid_grant regardless of exact exception type
        if "invalid_grant" in msg or "Token has been expired or revoked" in msg:
            # Only attempt reauth in local development (not on headless servers like Render)
            is_production = os.getenv("RENDER") == "true" or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("FLY_APP_NAME")

            if not is_production:
                # Local development - attempt interactive reauth
                print("🔐 Detected invalid_grant in local environment, attempting reauth...")
                _reauthorize_and_update_yaml(config_path)
                return _sum_accounts_usd_aligned(day_iso, shop_tz, config_path, include_ids)
            else:
                # Production - log error and raise (don't attempt interactive reauth)
                print("⚠️ Google Ads refresh token expired!")
                print("⚠️ Please update the refresh_token in google-ads.yaml on your server.")
                print("⚠️ Run locally: python google_ads_spend.py --reauth")
                print("⚠️ Then copy the new refresh_token to your production environment.")
                raise RefreshError(f"Google Ads refresh token expired. Manual reauth required. Error: {msg}")
        raise

# --------------------- CLI for testing & reauth ---------------------

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Test Google Ads daily spend (aligned to Shopify day) and reauth.")
    parser.add_argument(
        "--day", default=None,
        help="YYYY-MM-DD; default = today in REPORT_TZ or UTC."
    )
    parser.add_argument(
        "--shop-tz", default=os.getenv("REPORT_TZ", "UTC"),
        help="Shop timezone (e.g. 'Asia/Nicosia'). Default from REPORT_TZ or UTC."
    )
    parser.add_argument(
        "--config", default=os.getenv("GOOGLE_ADS_CONFIG", "google-ads.yaml"),
        help="Path to google-ads.yaml (default from GOOGLE_ADS_CONFIG or ./google-ads.yaml)."
    )
    parser.add_argument(
        "--include-ids", default=None,
        help="Comma-separated customer IDs to include (overrides env discovery)."
    )
    parser.add_argument(
        "--reauth", action="store_true",
        help="Run OAuth reauthorization flow and update refresh_token in google-ads.yaml."
    )

    args = parser.parse_args()

    cfg_path = args.config

    if args.reauth:
        _reauthorize_and_update_yaml(cfg_path)
        return

    day_iso = args.day
    if not day_iso:
        tz = pytz.timezone(args.shop_tz)
        day_iso = tz.localize(datetime.now()).date().isoformat()

    include_ids = args.include_ids
    if include_ids:
        include_ids = include_ids.split(",")

    usd = daily_spend_usd_aligned(day_iso, args.shop_tz, cfg_path, include_ids=include_ids)
    print(f"Google Ads spend for {day_iso} (shop_tz={args.shop_tz}) = ${usd:,.2f} USD")

if __name__ == "__main__":
    _cli()
