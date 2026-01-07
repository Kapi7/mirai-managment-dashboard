# paypal_client.py — PayPal Transaction Search (robust, with graceful fallbacks)
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import requests

# ──────────────────────────────────────────────────────────────────────────────
# ENV
#   PAYPAL_API_BASE   = https://api-m.paypal.com        (LIVE)
#                    or https://api-m.sandbox.paypal.com (SANDBOX)
#   PAYPAL_CLIENT_ID
#   PAYPAL_SECRET
# ──────────────────────────────────────────────────────────────────────────────

PAYPAL_API_BASE = os.getenv("PAYPAL_API_BASE", "https://api-m.paypal.com").rstrip("/")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")

_session = requests.Session()
_session.headers.update({"Accept": "application/json"})
_session_timeout = 60

_token_cache: Dict[str, Tuple[str, float]] = {}  # {base: (token, expiry_epoch)}
_warned_auth = False  # only warn once per run on 401/403


# ───────────────────────── helpers ─────────────────────────

def _pp_ts(dt: datetime) -> str:
    """RFC 3339 Zulu: 2025-09-01T04:00:00Z (PayPal requires UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_access_token() -> str:
    """Return cached OAuth2 token; refresh if expired."""
    now = time.time()
    tok, exp = _token_cache.get(PAYPAL_API_BASE, ("", 0.0))
    if tok and now < exp - 30:
        return tok

    if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET:
        raise RuntimeError("PayPal credentials missing (PAYPAL_CLIENT_ID / PAYPAL_SECRET).")

    url = f"{PAYPAL_API_BASE}/v1/oauth2/token"
    r = _session.post(
        url,
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        timeout=_session_timeout,
    )
    r.raise_for_status()
    data = r.json() or {}
    token = data.get("access_token")
    expires_in = int(data.get("expires_in") or 310)  # seconds
    if not token:
        raise RuntimeError("Failed to obtain PayPal access token.")
    _token_cache[PAYPAL_API_BASE] = (token, now + expires_in)
    return token


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_get_access_token()}"}


# ───────────────────── main fetch function ─────────────────────

def fetch_transactions(start_dt: datetime, end_dt: datetime) -> List[Dict]:
    """
    Return raw 'transaction_details' from PayPal Transaction Search.

    - Sends RFC-3339 UTC timestamps
    - Clamps end_dt to (now - 1s)
    - Paginates via HATEOAS 'next'
    - Gracefully handles 401/403/404 by returning []
    """
    global _warned_auth

    # Normalize to UTC
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    # Guard: empty / inverted ranges
    if end_dt <= start_dt:
        return []

    # Clamp end slightly before "now"
    now_utc = datetime.now(timezone.utc) - timedelta(seconds=1)
    if end_dt > now_utc:
        end_dt = now_utc
        if end_dt <= start_dt:
            return []

    params = {
        "start_date": _pp_ts(start_dt),
        "end_date": _pp_ts(end_dt),
        "fields": "all",
        "page_size": "500",
    }

    out: List[Dict] = []
    url = f"{PAYPAL_API_BASE}/v1/reporting/transactions"
    headers = _auth_headers()

    while True:
        try:
            r = _session.get(url, headers=headers, params=params, timeout=_session_timeout)
            r.raise_for_status()
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            # Treat 401/403/404 as "no data" so your pipeline keeps running
            if status in (401, 403, 404):
                if not _warned_auth and status in (401, 403):
                    print(
                        "⚠️ PayPal reporting unauthorized (HTTP "
                        f"{status}). Treating shipping cost as $0.\n"
                        "   Check credentials / app permissions / live vs sandbox."
                    )
                    _warned_auth = True
                return []
            raise

        data = r.json() or {}
        details = data.get("transaction_details") or []
        out.extend(details)

        # Pagination
        next_url = None
        for link in (data.get("links") or []):
            if isinstance(link, dict) and link.get("rel") == "next":
                next_url = link.get("href")
                break
        if not next_url:
            break

        url = next_url
        params = None  # next link includes the query

    return out



# ───────────────────── extraction helpers ─────────────────────

def _to_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _money_at(node: Dict, path: List[str]) -> Tuple[float, str]:
    """
    Safely read a money field like {"value": "1.23", "currency_code": "USD"}.
    Returns (amount_float, currency_code_str)
    """
    cur = node
    for k in path:
        if not isinstance(cur, dict):
            return 0.0, ""
        cur = cur.get(k)
    if not isinstance(cur, dict):
        return 0.0, ""
    return _to_float(cur.get("value")), (cur.get("currency_code") or "")


def extract_shipping_and_fees(details: List[Dict]) -> List[Dict]:
    """
    Convert PayPal 'transaction_details' rows into a flat list with a 'shipping_amount' column.
    We sum this later in paypal_shipping_total_grouped().

    Strategy:
      - Prefer transaction_info.shipping_amount
      - Fallback to cart_info/shipping_amount if present
      - Keep only positive numbers (treat as expense)
    """
    rows: List[Dict] = []
    for d in details or []:
        ti = d.get("transaction_info") or {}
        ci = d.get("cart_info") or {}

        amt, cur = _money_at(ti, ["shipping_amount"])
        if amt <= 0:
            # some payloads put it under cart_info
            amt2, cur2 = _money_at(ci, ["shipping_amount"])
            if amt2 > 0:
                amt, cur = amt2, cur2

        # Only include when > 0
        if amt > 0:
            rows.append(
                {
                    "transaction_id": ti.get("transaction_id") or "",
                    "transaction_event_code": ti.get("transaction_event_code") or "",
                    "transaction_initiation_date": ti.get("transaction_initiation_date") or "",
                    "shipping_amount": amt,  # assume account currency (usually USD)
                    "currency": cur or "",
                }
            )
    return rows
