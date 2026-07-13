# shop_bills.py — automatic Shop Campaigns cost from Shopify billing emails.
#
# Shopify does not expose Shop Campaigns charges via any Admin API (verified:
# order transactions/fees, balance transactions, marketing activities,
# metafields, ShopifyQL — nothing). The only machine-readable source is the
# billing receipts Shopify emails to the store owner.
#
# This module:
#   1. Reads those emails from Gmail (existing GMAIL_* env credentials,
#      read-only, plain REST — no extra dependencies).
#   2. Parses out Shop Campaigns / Shop Cash charge amounts per bill.
#   3. Derives an EFFECTIVE RATE = billed Shop charges / Shop-order gross over
#      a trailing window, so daily spend estimates self-calibrate to whatever
#      offer is currently configured — even if it changes every day.
#
# Env:
#   GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN  (required)
#   SHOP_BILLS_STATE_FILE      state path (default alongside other state files)
#   SHOP_BILLS_LOOKBACK_DAYS   trailing window for rate calc (default 30)
#   SHOP_BILLS_CACHE_HOURS     Gmail re-scan interval (default 6)
#
# CLI debug (run where GMAIL_* env exists, e.g. on Render):
#   python shop_bills.py --days 60            # scan & parse, print bills found
#   python shop_bills.py --days 60 --raw      # also dump matched email snippets

from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

def _default_state_dir() -> str:
    explicit = os.getenv("OUTPUTS_DIR")
    if explicit:
        return explicit
    # mirai-reports Render service has a persistent disk at /app/outputs;
    # the dashboard service does not — fall back to /tmp there.
    return "/app/outputs" if os.path.isdir("/app/outputs") else "/tmp"


_STATE_FILE = Path(
    os.getenv("SHOP_BILLS_STATE_FILE")
    or os.path.join(_default_state_dir(), ".shop_bills_state.json")
)

_GMAIL_SEARCH = (
    'from:(billing@shopify.com OR noreply@shopify.com OR mailer@shopify.com) '
    '(subject:(bill) OR subject:(invoice) OR subject:(receipt) OR "Shop Campaigns" OR "Shop Cash")'
)

# Money next to a shop-campaign-ish label, tolerant of HTML in between.
# Matches e.g. "Shop Campaigns ... $12.34" or "Shop Cash campaign ... USD 12.34"
_LINE_RE = re.compile(
    r"shop\s*(?:cash|campaigns?)[^$€£\d]{0,400}?(?:USD\s*)?[$€£]\s*([0-9][0-9,]*\.?[0-9]{0,2})",
    re.IGNORECASE | re.DOTALL,
)


# ---------------- state ----------------
def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))
    except Exception as e:
        print(f"[shop_bills] Could not write state file {_STATE_FILE}: {e}")


# ---------------- Gmail (plain REST) ----------------
def _gmail_access_token() -> Optional[str]:
    cid = (os.getenv("GMAIL_CLIENT_ID") or "").strip()
    secret = (os.getenv("GMAIL_CLIENT_SECRET") or "").strip()
    refresh = (os.getenv("GMAIL_REFRESH_TOKEN") or "").strip()
    if not (cid and secret and refresh):
        return None
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": cid,
                "client_secret": secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        r.raise_for_status()
        return (r.json() or {}).get("access_token")
    except Exception as e:
        print(f"[shop_bills] Gmail token refresh failed: {e}")
        return None


def _gmail_get(token: str, path: str, params: Optional[dict] = None) -> dict:
    r = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=60,
    )
    r.raise_for_status()
    return r.json() or {}


def _walk_parts(payload: dict) -> List[str]:
    """Collect decoded text/plain + text/html bodies from a message payload."""
    out: List[str] = []
    stack = [payload or {}]
    while stack:
        part = stack.pop()
        mime = part.get("mimeType") or ""
        body = part.get("body") or {}
        data = body.get("data")
        if data and (mime.startswith("text/") or not mime):
            try:
                out.append(base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace"))
            except Exception:
                pass
        stack.extend(part.get("parts") or [])
    return out


def _strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s)


def _parse_shop_amounts(texts: List[str]) -> float:
    """Max Shop Campaigns amount found across message bodies (plain preferred)."""
    best = 0.0
    for t in texts:
        cleaned = _strip_html(t)
        total = 0.0
        for m in _LINE_RE.finditer(cleaned):
            try:
                total += float(m.group(1).replace(",", ""))
            except Exception:
                continue
        best = max(best, round(total, 2))
    return best


# ---------------- scan ----------------
def scan_bills(days: int = 60, keep_raw: bool = False, force: bool = False) -> Dict[str, Any]:
    """
    Scan Gmail for Shopify billing emails, parse Shop Campaigns charges,
    merge into state. Returns state. Cached (SHOP_BILLS_CACHE_HOURS).
    """
    state = _load_state()
    cache_hours = float(os.getenv("SHOP_BILLS_CACHE_HOURS", "6") or 6)
    last = float(state.get("last_scan_ts") or 0)
    if not force and time.time() - last < cache_hours * 3600:
        return state

    token = _gmail_access_token()
    if not token:
        print("[shop_bills] GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN not configured — skipping scan.")
        return state

    bills: Dict[str, Any] = dict(state.get("bills") or {})
    try:
        q = f"{_GMAIL_SEARCH} newer_than:{int(days)}d"
        page_token = None
        msg_ids: List[str] = []
        while True:
            params = {"q": q, "maxResults": 100}
            if page_token:
                params["pageToken"] = page_token
            res = _gmail_get(token, "messages", params)
            msg_ids.extend(m["id"] for m in res.get("messages") or [])
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        print(f"[shop_bills] Gmail matched {len(msg_ids)} billing-ish messages ({int(days)}d)")

        for mid in msg_ids:
            if mid in bills and not keep_raw:
                continue  # already parsed
            msg = _gmail_get(token, f"messages/{mid}", {"format": "full"})
            headers = {h["name"].lower(): h["value"] for h in (msg.get("payload") or {}).get("headers") or []}
            internal_ms = int(msg.get("internalDate") or 0)
            when = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)
            texts = _walk_parts(msg.get("payload") or {})
            amount = _parse_shop_amounts(texts)
            entry: Dict[str, Any] = {
                "date": when.date().isoformat(),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "shop_campaign_amount": amount,
            }
            if keep_raw:
                joined = _strip_html(" ".join(texts))
                idx = joined.lower().find("shop")
                entry["snippet"] = joined[max(0, idx - 200): idx + 400] if idx >= 0 else joined[:300]
            bills[mid] = entry

        state["bills"] = bills
        state["last_scan_ts"] = time.time()
        _save_state(state)
    except Exception as e:
        print(f"[shop_bills] Scan failed: {e}")

    return state


# ---------------- public: effective rate & spend ----------------
def billed_total(days: int = 30, state: Optional[Dict[str, Any]] = None) -> float:
    """Sum of parsed Shop Campaigns charges in the trailing `days`."""
    state = state or scan_bills()
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    total = 0.0
    for b in (state.get("bills") or {}).values():
        try:
            d = datetime.fromisoformat(b["date"]).replace(tzinfo=timezone.utc)
            if d.timestamp() >= cutoff:
                total += float(b.get("shop_campaign_amount") or 0)
        except Exception:
            continue
    return round(total, 2)


def effective_rate(shop_gross_window: float, days: int = None) -> Optional[float]:
    """
    Actual billed Shop Campaigns charges / Shop-order gross over the trailing
    window. Returns None when there is no bill data yet (caller falls back).
    Self-calibrates to offer changes — no configuration needed.
    """
    days = days or int(os.getenv("SHOP_BILLS_LOOKBACK_DAYS", "30") or 30)
    total = billed_total(days)
    if total <= 0 or shop_gross_window <= 0:
        return None
    return total / shop_gross_window


def shop_spend_for(shop_gross_day: float, shop_orders_day: int, shop_gross_window: float) -> Optional[float]:
    """
    Day's Shop Campaigns spend from real bills (rate × day gross).
    None if no bill data (caller should use its fallback estimate).
    """
    rate = effective_rate(shop_gross_window)
    if rate is None:
        return None
    return round(shop_gross_day * rate, 2)


# ---------------- CLI debug ----------------
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    ap = argparse.ArgumentParser(description="Scan Gmail for Shopify Shop Campaigns charges")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--raw", action="store_true", help="store + print matched snippets")
    args = ap.parse_args()

    st = scan_bills(days=args.days, keep_raw=args.raw, force=True)
    bills = st.get("bills") or {}
    print(f"\nParsed bills: {len(bills)}")
    for mid, b in sorted(bills.items(), key=lambda kv: kv[1]["date"], reverse=True):
        print(f"  {b['date']}  ${b['shop_campaign_amount']:>8.2f}  {b['subject'][:70]}")
        if args.raw and b.get("snippet"):
            print(f"      snippet: {b['snippet'][:300]}")
    print(f"\nTrailing 30d Shop Campaigns billed: ${billed_total(30):.2f}")
