#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
monitor_orders.py — Multi-store Shopify → Telegram order alerts with:
  • Per-order PSP fee (EUR → USD via FX_EUR_TO_USD) matched by numeric order ID, per store.
  • Approx. Shipping (USD) via shipping matrix (GEO canonicalization + weight tiers).
  • Approx. Profit (USD) = Net + Shipping Charged – COGS – Approx Shipping – PSP Fee (USD).
  • Triggers master_report_mirai.run_once(None) after new orders (rate-limited).
  • Polls continuously with --every N seconds (use 60 seconds on Render).

Adds:
  • Robust UTM campaign extraction (customerJourneySummary + URL query parsing)
  • Safe Telegram sending: will NOT crash if telegram_client signature differs.

Env flags:
  ALERT_FORCE_ON_START=1  → send alerts even if already seen (testing)
  ALERT_EVERY=60          → poll interval default if not passed
  MIN_SHEET_INTERVAL_SEC=60
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlparse, parse_qs

import pytz
import requests
from dotenv import load_dotenv

from config import SHOPIFY_STORES, SHOPIFY_API_VERSION
from shopify_client import (
    fetch_orders_created_between_for_store,
    get_shop_timezone,
)
from telegram_client import send_order_alert
from master_report_mirai import run_once
from channel_normalizer import normalize_channel

load_dotenv()

# ─── files & tunables ───
SEEN_FILE  = Path(os.getenv("SEEN_FILE", "/app/outputs/.monitor_seen_orders.json"))
STATE_FILE = Path(os.getenv("STATE_FILE", "/app/outputs/.orders_state.json"))

SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

try:
    MIN_SHEET_INTERVAL_SEC = int(os.getenv("MIN_SHEET_INTERVAL_SEC", "60"))
except Exception:
    MIN_SHEET_INTERVAL_SEC = 60

ALERT_FORCE_ON_START = os.getenv("ALERT_FORCE_ON_START", "0") == "1"

DEFAULT_ITEM_WEIGHT_KG = float(os.getenv("DEFAULT_ITEM_WEIGHT_KG", "0.25"))  # 250 g default
_MATRIX_PATH = Path(__file__).parent / "shipping_matrix_all.csv"

try:
    from shipping_matrix_source import refresh_if_stale as _refresh_matrix_if_stale
except Exception:  # pragma: no cover - keep working without the live-sheet helper
    def _refresh_matrix_if_stale(*_a, **_k):
        return False

# ───────── ISO2 country helper ─────────
_ISO2_TO_NAME = {
    "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom", "DE": "Germany",
    "FR": "France", "IT": "Italy", "ES": "Spain", "PT": "Portugal", "PL": "Poland",
    "RO": "Romania", "GR": "Greece", "NL": "Netherlands", "BE": "Belgium", "IE": "Ireland",
    "AU": "Australia", "NZ": "New Zealand", "CA": "Canada", "SE": "Sweden", "NO": "Norway",
    "DK": "Denmark", "FI": "Finland", "CH": "Switzerland", "AT": "Austria",
    "AE": "United Arab Emirates", "SA": "Saudi Arabia", "QA": "Qatar", "KW": "Kuwait",
    "OM": "Oman", "BH": "Bahrain", "IL": "Israel", "CY": "Cyprus", "CZ": "Czechia",
    "HU": "Hungary", "SK": "Slovakia", "SI": "Slovenia", "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania",
    "RU": "Russia", "UA": "Ukraine", "TR": "Turkey", "RS": "Serbia", "MK": "North Macedonia",
    "BG": "Bulgaria", "HR": "Croatia", "JP": "Japan", "CN": "China", "HK": "Hong Kong",
    "SG": "Singapore", "MY": "Malaysia", "ID": "Indonesia", "PH": "Philippines", "TH": "Thailand",
    "VN": "Vietnam", "IN": "India", "PK": "Pakistan", "BD": "Bangladesh",
    "ZA": "South Africa", "NG": "Nigeria", "KE": "Kenya", "MA": "Morocco", "EG": "Egypt",
    "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru",
    "PA": "Panama"
}

# ───────── canonical GEO + shipping matrix loader ─────────
_SHIP_MATRIX: Dict[str, Dict[float, float]] = {}
_WARNED_MISSING_GEOS: set[str] = set()

def _canonical_geo(name: Optional[str], iso2: Optional[str] = None) -> str:
    s = (name or "").strip()
    cc = (iso2 or "").strip().upper()
    if cc and cc in _ISO2_TO_NAME:
        return _ISO2_TO_NAME[cc]
    if s:
        return s.title()
    return cc or "Unknown"

def _load_shipping_matrix():
    global _SHIP_MATRIX, _WARNED_MISSING_GEOS
    try:
        import pandas as pd
        df = pd.read_csv(_MATRIX_PATH)
        df.columns = [str(c).strip().upper() for c in df.columns]

        price_col = None
        for c in ("STANDARD", "PRICE_USD", "PRICE"):
            if c in df.columns:
                price_col = c
                break
        if price_col is None:
            raise RuntimeError("Shipping matrix missing STANDARD/PRICE_USD/PRICE column")

        if "GEO" not in df.columns or "WEIGHT" not in df.columns:
            raise RuntimeError("Shipping matrix must have GEO and WEIGHT columns")

        out: Dict[str, Dict[float, float]] = {}
        for _, r in df.iterrows():
            raw_geo = str(r["GEO"]).strip()
            if not raw_geo:
                continue
            try:
                w = float(r["WEIGHT"])
            except Exception:
                continue
            try:
                p = float(r.get(price_col, 0) or 0)
            except Exception:
                p = 0.0

            canon = _canonical_geo(None, raw_geo) if len(raw_geo) == 2 else _canonical_geo(raw_geo, None)
            out.setdefault(canon, {})[w] = p

        _SHIP_MATRIX = out
        _WARNED_MISSING_GEOS.clear()
        print(f"[INFO] Loaded shipping matrix GEOs={len(_SHIP_MATRIX)} from {_MATRIX_PATH}")
    except Exception as e:
        print(f"[WARN] Could not load shipping matrix: {e}")
        _SHIP_MATRIX = {}
        _WARNED_MISSING_GEOS.clear()

_refresh_matrix_if_stale(str(_MATRIX_PATH))
_load_shipping_matrix()

# ───────── PSP fee lookup (per store) ─────────
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

def _fetch_txns_until_for_store(
    store_domain: str,
    access_token: str,
    start_dt_local: datetime,
    tz,
    limit: int = 250,
    max_pages: int = 400,
) -> List[dict]:
    base = f"https://{store_domain}/admin/api/{SHOPIFY_API_VERSION}"
    txn_url = f"{base}/shopify_payments/balance/transactions.json"

    url = txn_url
    params = {"limit": limit}
    out: List[dict] = []
    pages = 0

    while True:
        r = requests.get(url, headers=_headers_for(access_token),
                         params=params if url == txn_url else None, timeout=60)
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

def _build_psp_fee_index_for_store(
    store_domain: str,
    access_token: str,
    start_local: datetime,
    end_local: datetime,
    tz,
) -> Dict[int, float]:
    txns = _fetch_txns_until_for_store(store_domain, access_token, start_local, tz)
    idx: Dict[int, float] = {}

    for t in txns:
        p = _parse_iso(t.get("processed_at"))
        if not p:
            continue
        if p.tzinfo is None:
            p = pytz.UTC.localize(p)
        p_local = p.astimezone(tz)
        if not (start_local <= p_local < end_local):
            continue

        typ = (t.get("type") or "").lower()
        if typ not in ("charge", "payment", "sale"):
            continue

        fee = t.get("fee")
        if fee is None:
            continue
        try:
            amt = abs(float(fee))
        except Exception:
            continue

        for key in ("order_id", "source_order_id", "source_id"):
            oid = t.get(key)
            if isinstance(oid, int) and oid > 0:
                idx[oid] = round(idx.get(oid, 0.0) + amt, 2)
                break

    return idx

# ───────── FX helper ─────────
def _eur_to_usd(amount_eur: float) -> float:
    try:
        rate = float(os.getenv("FX_EUR_TO_USD", "1.0"))
        return round(float(amount_eur) * rate, 2)
    except Exception:
        return round(float(amount_eur), 2)

# ───────── shipping helpers ─────────
def _geo_from_order(order: dict) -> str:
    addr = order.get("shippingAddress") or {}
    name = (addr.get("country") or "").strip()
    cc = (addr.get("countryCodeV2") or "").strip().upper()
    return _canonical_geo(name, cc)

def _order_weight_kg(order: dict) -> float:
    tw = order.get("totalWeight")
    try:
        if tw is not None:
            val = float(tw)
            if val > 0:
                return round(val / 1000.0, 6)  # grams → kg
    except Exception:
        pass

    total_qty = 0
    for li in (order.get("lineItems") or {}).get("nodes") or []:
        try:
            total_qty += int(li.get("quantity") or 0)
        except Exception:
            pass

    return round(max(0.0, DEFAULT_ITEM_WEIGHT_KG * total_qty), 6)

def _lookup_standard_shipping(geo: str, weight_kg: float) -> float:
    # Live source = Korealy Google Sheet; reload when a fresh copy landed.
    if _refresh_matrix_if_stale(str(_MATRIX_PATH)) or not _SHIP_MATRIX:
        _load_shipping_matrix()
    canon = _canonical_geo(geo if len(geo or "") != 2 else None,
                           geo if len(geo or "") == 2 else None)

    tbl = _SHIP_MATRIX.get(canon)
    if not tbl:
        for g in _SHIP_MATRIX.keys():
            if g.lower() == canon.lower():
                tbl = _SHIP_MATRIX[g]
                break

    if not tbl:
        if canon not in _WARNED_MISSING_GEOS:
            preview = sorted(list(_SHIP_MATRIX.keys()))[:8]
            print(f"[WARN] No shipping matrix for GEO '{geo}' (canonical '{canon}'). "
                  f"Available: {preview}{' ...' if len(_SHIP_MATRIX) > 8 else ''}")
            _WARNED_MISSING_GEOS.add(canon)
        return 0.0

    tiers = sorted(tbl.keys())
    for t in tiers:
        if weight_kg <= t + 1e-9:
            return float(tbl.get(t, 0.0))
    return float(tiers and tbl.get(tiers[-1], 0.0) or 0.0)

# ───────── tiny persistence ─────────
def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()

def _save_seen(seen: set[str]) -> None:
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen)))
    except Exception:
        pass

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}

def _save_state(d: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(d))
    except Exception:
        pass

# ───────── financial helpers ─────────
def _sum_line_gross(order: dict) -> float:
    total = 0.0
    for li in (order.get("lineItems") or {}).get("nodes") or []:
        amt = (((li.get("originalTotalSet") or {}).get("shopMoney") or {}).get("amount"))
        try:
            total += float(amt or 0)
        except Exception:
            pass
    return round(total, 2)

def _net_from_parts(order: dict, gross: float) -> float:
    disc = float((
        ((order.get("totalDiscountsSet") or {}).get("shopMoney") or {}).get("amount")
        or ((order.get("currentTotalDiscountsSet") or {}).get("shopMoney") or {}).get("amount")
        or 0
    ))
    ref  = float((((order.get("totalRefundedSet") or {}).get("shopMoney") or {}).get("amount")) or 0)
    return round(gross - disc - ref, 2)

def _shipping_charged(order: dict) -> float:
    t = (((order.get("totalShippingPriceSet") or {}).get("shopMoney") or {}).get("amount"))
    if t is None:
        t = (((order.get("currentShippingPriceSet") or {}).get("shopMoney") or {}).get("amount"))
    try:
        return float(t or 0)
    except Exception:
        return 0.0

def _cogs(order: dict) -> float:
    c = 0.0
    for li in (order.get("lineItems") or {}).get("nodes") or []:
        qty = li.get("quantity") or 0
        unit = (((li.get("variant") or {}).get("inventoryItem") or {}).get("unitCost") or {})
        try:
            unit_cost = float(unit.get("amount") or 0)
        except Exception:
            unit_cost = 0.0
        c += unit_cost * (qty or 0)
    return round(c, 2)

def _channel_from_order(order: dict) -> str:
    cj = order.get("customerJourneySummary") or {}
    v  = (cj.get("lastVisit") or {}) or (cj.get("firstVisit") or {})
    utm = v.get("utmParameters") or {}

    # Try to get landing page URL from visit or order level (may contain gclid)
    landing_url = v.get("landingPageUrl") or order.get("landingPageUrl") or ""

    chan_def = ((order.get("channelInformation") or {}).get("channelDefinition")) or {}

    return normalize_channel(
        source_name  = (order.get("sourceName") or ""),
        utm_source   = (utm.get("source") or ""),
        utm_medium   = (utm.get("medium") or ""),
        referrer_url = (v.get("referrerUrl") or ""),
        landing_page_url = landing_url,
        channel_name = (chan_def.get("channelName") or chan_def.get("handle") or ""),
    )

def _is_returning(order: dict) -> bool:
    num = ((order.get("customer") or {}).get("numberOfOrders"))
    try:
        return int(num or 0) > 1
    except Exception:
        return False

# ───────── helpers: order id parsing ─────────
_GID_RE = re.compile(r"gid://shopify/Order/(\d+)$")

def _order_numeric_id(order: dict) -> Optional[int]:
    legacy = order.get("legacyResourceId")
    if isinstance(legacy, int):
        return legacy
    if isinstance(legacy, str) and legacy.isdigit():
        return int(legacy)

    gid = order.get("id") or ""
    if isinstance(gid, str):
        m = _GID_RE.search(gid)
        if m:
            return int(m.group(1))
        if gid.isdigit():
            return int(gid)
    return None

# ───────── UTM Campaign extraction ─────────
def _qs_get(url: str, key: str) -> Optional[str]:
    try:
        q = parse_qs(urlparse(url).query)
        v = q.get(key)
        if v and v[0]:
            return str(v[0]).strip()
    except Exception:
        return None
    return None

def _utm_campaign_from_order(order: dict) -> Optional[str]:
    """
    Returns best available UTM campaign string.
    Priority:
      1) customerJourneySummary.lastVisit.utmParameters.campaign
      2) customerJourneySummary.firstVisit.utmParameters.campaign
      3) Parse utm_campaign from lastVisit/firstVisit landing/referrer URL
      4) Parse utm_campaign from order-level landingPageUrl/referrerUrl
    """
    cjs = order.get("customerJourneySummary") or {}
    last = cjs.get("lastVisit") or {}
    first = cjs.get("firstVisit") or {}

    def _camp_from_visit(v: dict) -> Optional[str]:
        utm = v.get("utmParameters") or {}
        c = utm.get("campaign")
        if isinstance(c, str) and c.strip():
            return c.strip()

        for ukey in ("landingPageUrl", "referrerUrl"):
            u = v.get(ukey)
            if isinstance(u, str) and u:
                c2 = _qs_get(u, "utm_campaign")
                if c2:
                    return c2
        return None

    c = _camp_from_visit(last)
    if c:
        return c
    c = _camp_from_visit(first)
    if c:
        return c

    # Order-level fallbacks
    for ukey in ("landingPageUrl", "referrerUrl"):
        u = order.get(ukey)
        if isinstance(u, str) and u:
            c3 = _qs_get(u, "utm_campaign")
            if c3:
                return c3

    # Shop Campaigns have no UTMs; the campaign name arrives as an order tag
    # (e.g. "New campaign 01") alongside audience tags like "New customers".
    for t in (order.get("tags") or []):
        if isinstance(t, str) and "campaign" in t.lower():
            return t.strip()

    return None

# ───────── sheets refresh gating ─────────
def _maybe_refresh_sheets() -> None:
    state = _load_state()
    now = time.time()
    last = float(state.get("last_sheet_refresh_ts", 0.0))
    if now - last < MIN_SHEET_INTERVAL_SEC:
        return
    try:
        run_once(None)
        state["last_sheet_refresh_ts"] = now
        _save_state(state)
    except Exception as e:
        print("[monitor] Master refresh error:", e)

# ───────── SAFE telegram call (no signature assumptions) ─────────
def _send_order_alert_safe(**kwargs) -> None:
    """
    Tries to call telegram_client.send_order_alert with extra optional kwargs.
    If the function signature doesn't accept them, retries without them.
    """
    try:
        send_order_alert(**kwargs)
        return
    except TypeError as e:
        # Drop ONLY the kwarg named in the TypeError, then retry — dropping a
        # fixed list used to strip `order`/`shop_cost_order` too, silently
        # losing the campaign + Shop-cost lines.
        retry = dict(kwargs)
        removed = []
        for _ in range(4):
            m = re.search(r"unexpected keyword argument '(\w+)'", str(e))
            if not m or m.group(1) not in retry:
                break
            removed.append(m.group(1))
            retry.pop(m.group(1), None)
            try:
                print(f"[monitor] send_order_alert() TypeError ({e}). Retrying without {removed}...")
                send_order_alert(**retry)
                return
            except TypeError as e2:
                e = e2
                continue
            except Exception as e3:
                print("[monitor] send_order_alert retry failed:", e3)
                raise
        print("[monitor] send_order_alert failed:", e)
        raise
    except Exception as e:
        print("[monitor] send_order_alert failed:", e)
        raise

# ───────── alert path ─────────
def _compute_alert_fields(order: dict, psp_index: Dict[int, float], store_label: str,
                          shop_day_counts: Optional[Dict[str, int]] = None,
                          zone: Optional[Any] = None) -> Dict[str, Any]:
    """All per-order figures for the Telegram alert. Shared by the initial
    send AND the late-attribution edit so both render identically."""
    order_name = order.get("name") or "Order"

    gross = _sum_line_gross(order)
    net   = _net_from_parts(order, gross)
    cogs  = _cogs(order)
    shipping_charged = _shipping_charged(order)
    country_code = ((order.get("shippingAddress") or {}).get("countryCodeV2"))
    channel = _channel_from_order(order)
    returning = _is_returning(order)

    geo = _geo_from_order(order)
    weight_kg = _order_weight_kg(order)
    approx_shipping = round(_lookup_standard_shipping(geo, weight_kg), 2)

    psp_fee_usd = 0.0
    oid_num = _order_numeric_id(order)
    if oid_num is not None:
        fee_eur = psp_index.get(oid_num, 0.0)
        psp_fee_usd = _eur_to_usd(fee_eur)

    # Shop Campaigns bills per NEWLY-ACQUIRED customer (the ShopifyQL capture's
    # CAC × acquisitions == day spend). So: returning-customer Shop orders cost
    # $0, and the day's EXACT spend is split across that day's NEW-customer
    # Shop orders only (shop_day_counts is new-customer-only). CAC remains the
    # fallback while shop_campaign_insights still lags behind fresh orders.
    shop_cost_order = None
    if channel == "Shop":
        if returning:
            shop_cost_order = 0.0  # acquisition already paid for — not billed again
        else:
            try:
                import shop_campaign_cost
                day_iso = None
                if zone is not None:
                    dt = _parse_iso(order.get("createdAt"))
                    if dt:
                        day_iso = dt.astimezone(zone).date().isoformat()
                day_spend = shop_campaign_cost.spend_for_day(day_iso) if day_iso else None
                n_new = (shop_day_counts or {}).get(day_iso or "", 0)
                if day_spend and n_new > 0:
                    shop_cost_order = round(day_spend / n_new, 2)
                else:
                    shop_cost_order = shop_campaign_cost.current_cac()
            except Exception as e:
                print(f"[monitor] Shop cost unavailable: {e}")

    approx_sale_profit = round(
        net + shipping_charged - cogs - approx_shipping - psp_fee_usd - (shop_cost_order or 0.0), 2
    )

    return dict(
        order_name=order_name,
        gross=gross,
        net=net,
        cogs=cogs,
        shipping_charged=shipping_charged,
        country_code=country_code,
        marketing=channel,
        is_returning=returning,
        approx_shipping=approx_shipping,
        weight_kg=round(weight_kg, 3),
        psp_usd_order=psp_fee_usd,
        approx_sale_profit=approx_sale_profit,
        store_label=store_label,
        shop_cost_order=shop_cost_order,
        order=order,
    )


def _alert_then_sheet(order: dict, psp_index: Dict[int, float], store_label: str, store_domain: str,
                      shop_day_counts: Optional[Dict[str, int]] = None,
                      zone: Optional[Any] = None) -> None:
    order_gid = order.get("id") or order.get("admin_graphql_api_id") or order.get("name") or "Order"

    # Stable, namespaced unique id for Telegram dedup
    order_id_key = f"{store_domain}:{order_gid}"

    fields = _compute_alert_fields(order, psp_index, store_label, shop_day_counts, zone)

    # Send Telegram (safe: will not crash if signature differs).
    # NOTE: do NOT pass extra kwargs send_order_alert doesn't accept — the
    # TypeError fallback used to strip `order` AND `shop_cost_order` from the
    # retry, which is why campaign + Shop-cost lines were missing from alerts.
    # The campaign line is derived inside telegram_client from `order`.
    _send_order_alert_safe(
        order_id=order_id_key,
        **fields,
    )

    # Trigger summary refresh (rate-limited)
    _maybe_refresh_sheets()


# ───────── late-attribution channel updates ─────────
# Shopify populates customerJourneySummary ~5 minutes AFTER the order is
# created, so the first alert often says "Direct" for what is really a Google
# order. Every poll re-fetches the same 24h window with fresh data, so for
# already-alerted orders we re-derive the channel and EDIT the sent message
# once real attribution shows up.
CHANNEL_RECHECK_MAX_AGE_MIN = int(os.getenv("CHANNEL_RECHECK_MAX_AGE_MIN", "120"))


def _maybe_update_channel(order: dict, psp_index: Dict[int, float],
                          store_label: str, store_domain: str,
                          shop_day_counts: Optional[Dict[str, int]] = None,
                          zone: Optional[Any] = None) -> bool:
    try:
        from telegram_client import (
            get_order_alert_record, update_order_alert, mark_order_final,
            PENDING_CHANNELS,
        )
    except ImportError:
        return False

    order_gid = order.get("id") or order.get("admin_graphql_api_id") or order.get("name") or "Order"
    order_id_key = f"{store_domain}:{order_gid}"

    rec = get_order_alert_record(order_id_key)
    if not rec or rec.get("final") or not rec.get("message_id"):
        return False

    age_min = (time.time() - float(rec.get("sent_at") or 0)) / 60.0

    new_channel = _channel_from_order(order)
    old_channel = (rec.get("channel") or "").strip()

    if new_channel.strip().lower() in PENDING_CHANNELS or new_channel == old_channel:
        # Attribution still hasn't arrived (or nothing changed). Give up after
        # the recheck window so we don't re-inspect ancient orders forever.
        if age_min > CHANNEL_RECHECK_MAX_AGE_MIN:
            mark_order_final(order_id_key)
        return False

    print(f"[monitor] Channel resolved for {order_id_key}: "
          f"'{old_channel or 'Direct'}' → '{new_channel}' (after {age_min:.0f} min) — editing alert.")

    fields = _compute_alert_fields(order, psp_index, store_label, shop_day_counts, zone)
    try:
        return update_order_alert(order_id=order_id_key, **fields)
    except Exception as e:
        print(f"[monitor] update_order_alert failed for {order_id_key}: {e}")
        return False

# ───────── polling ─────────
def _poll_once(window_hours: int, tz_name: Optional[str], force: bool) -> int:
    if not SHOPIFY_STORES:
        print("[monitor] No Shopify stores configured in config.SHOPIFY_STORES.")
        return 0

    tz = tz_name or get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"
    zone = pytz.timezone(tz)
    now = datetime.now(zone)

    start_local = (now - timedelta(hours=window_hours)).replace(second=0, microsecond=0)
    end_local   = (now + timedelta(minutes=2))

    print(f"[monitor] Poll window {tz}: {start_local.isoformat()} → {end_local.isoformat()} (force={force or ALERT_FORCE_ON_START})")

    seen = _load_seen()
    changed = False
    sent = 0

    # Phase 1 — fetch every store's orders first, so the per-day Shop-order
    # counts below cover ALL stores before any alert math runs.
    fetched: List[Tuple[str, str, list, Dict[int, float]]] = []
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token  = store["access_token"]
        label  = store["label"]

        try:
            orders = fetch_orders_created_between_for_store(
                domain, token, start_local.isoformat(), end_local.isoformat()
            )
        except Exception as e:
            # A dead/uninstalled store must not block alerts for other stores
            print(f"[monitor] Store '{label}' ({domain}) fetch failed, skipping: {e}")
            continue
        print(f"[monitor] Store '{label}' ({domain}) – orders fetched: {len(orders)}")

        try:
            psp_index = _build_psp_fee_index_for_store(domain, token, start_local, end_local, zone)
        except Exception as e:
            print(f"[monitor] Store '{label}' PSP index failed (using empty): {e}")
            psp_index = {}
        print(f"[monitor] Store '{label}' PSP index size: {len(psp_index)}")

        fetched.append((domain, label, orders, psp_index))

    # NEW-customer Shop orders per local day → per-order ad spend = day spend ÷ this.
    # Shop Campaigns bills per ACQUIRED customer, so returning-customer Shop
    # orders carry $0 ad cost and must not dilute the split.
    shop_day_counts: Dict[str, int] = {}
    for _, _, orders, _ in fetched:
        for o in orders:
            if o.get("cancelledAt") or _channel_from_order(o) != "Shop" or _is_returning(o):
                continue
            dt = _parse_iso(o.get("createdAt"))
            if dt:
                day = dt.astimezone(zone).date().isoformat()
                shop_day_counts[day] = shop_day_counts.get(day, 0) + 1
    if shop_day_counts:
        print(f"[monitor] NEW-customer Shop orders per day: {shop_day_counts}")

    # Phase 2 — alerts / channel-recheck edits
    for domain, label, orders, psp_index in fetched:
        for o in sorted(orders, key=lambda x: x.get("createdAt") or ""):
            oid = o.get("id")
            if not oid:
                continue

            seen_key = f"{domain}:{oid}"
            if not force and not ALERT_FORCE_ON_START and seen_key in seen:
                # Already alerted — but the channel may have been "Direct"
                # only because attribution hadn't landed yet. Re-derive it
                # from this poll's fresh data and edit the message if needed.
                try:
                    _maybe_update_channel(o, psp_index, label, domain, shop_day_counts, zone)
                except Exception as e:
                    print(f"[monitor] channel recheck failed for {seen_key}: {e}")
                continue

            try:
                _alert_then_sheet(o, psp_index, label, domain, shop_day_counts, zone)
                seen.add(seen_key)
                changed = True
                sent += 1
                # Stay under Telegram's per-chat rate limit (~20 msg/min) on
                # backfills. 3.5s gap = ~17/min, well below the throttle.
                time.sleep(3.5)
            except Exception as e:
                print(f"[monitor] Failed to alert order {seen_key}: {e}")

    if changed:
        _save_seen(seen)

    if sent == 0:
        print("[monitor] No alerts sent this cycle (no new orders or already seen).")

    return sent

def run(window_hours: int = 24, tz_name: Optional[str] = None, force: bool = False) -> int:
    return _poll_once(window_hours, tz_name, force)


def backfill_today_and_send(hours: int = 24, force: bool = False) -> int:
    """
    One-shot backfill: re-scans the last `hours` of Shopify orders across all
    configured stores and sends Telegram alerts for any that haven't been
    alerted yet. Honors the seen-orders file when force=False.

    Exposed for server.py's /force-backfill-today endpoint.
    """
    return _poll_once(window_hours=int(hours), tz_name=None, force=bool(force))

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Multi-store Shopify → Telegram order alerts (polling)")
    ap.add_argument("--every", type=int, default=int(os.getenv("ALERT_EVERY", "0")),
                    help="If >0, poll every N seconds (env ALERT_EVERY also supported).")
    ap.add_argument("--hours", type=int, default=24, help="Look back this many hours each poll.")
    ap.add_argument("--tz", default=None, help="Override timezone (default: shop tz or REPORT_TZ or UTC).")
    ap.add_argument("--force", action="store_true", help="Ignore seen list (send all in window).")
    args = ap.parse_args()

    if args.every and args.every > 0:
        while True:
            try:
                run(window_hours=args.hours, tz_name=args.tz, force=args.force)
            except Exception as e:
                print("[monitor] Polling error:", e)
            time.sleep(args.every)
    else:
        run(window_hours=args.hours, tz_name=args.tz, force=args.force)

if __name__ == "__main__":
    main()
