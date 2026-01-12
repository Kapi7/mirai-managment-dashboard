#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# master_report_mirai.py — month-only orchestrator (USD, Shopify TZ) + summary upsert
# BEHAVIOR (as requested):
#   - Uses LIVE spend for TODAY (no shifting to yesterday)
#   - After the day ends, "yesterday" is computed normally by date roll

from __future__ import annotations
import os, re, csv
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Tuple, Optional

import pytz
from dotenv import load_dotenv

from utils.date_range import local_day_window
from shopify_client import (
    fetch_orders_created_between_for_store,
    get_shop_timezone,
)
from config import SHOPIFY_STORES
from paypal_client import fetch_transactions, extract_shipping_and_fees
from transform import paypal_to_df, paypal_shipping_total_grouped
# Make sheets_client optional
try:
    from sheets_client import ensure_month_tab, update_single_day_row
    HAS_SHEETS = True
except ImportError:
    ensure_month_tab = None
    update_single_day_row = None
    HAS_SHEETS = False
from telegram_client import upsert_daily_summary
from psp_fee import get_psp_fees_daily
from google_ads_spend import daily_spend_usd_aligned
from meta_client import fetch_meta_insights_day

# Quiet the gRPC/absl spam
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_LOG_SEVERITY_THRESHOLD", "ERROR")

load_dotenv()

# ------------------------------------------------------------------------------
_GADS_DISABLED   = os.getenv("DISABLE_GOOGLE_ADS", "0") == "1"
_META_DISABLED   = os.getenv("DISABLE_META", "0") == "1"
_GADS_WARNED     = False
_GADS_CACHE: Dict[str, Tuple[float, datetime]] = {}  # value, timestamp
_GADS_CACHE_TTL_MINUTES = int(os.getenv("GOOGLE_ADS_CACHE_TTL_MINUTES", "30"))

MONTH_HEADERS = [
    "Date", "Orders", "Gross", "Discounts", "Refunds", "Net",
    "COGS", "Shipping Charged (Shopify)",
    "Est. Shipping (Matrix)", "Shipping Cost (PayPal)",
    "Spend (Google)", "Spend (Meta)", "Total Spend",
    "PSP Fee (USD)", "Operational Profit", "Net Margin", "Margin %",
    "AOV", "Returning Customers", "General CPA",
]

# ------------------------------------------------------------------------------
# SHIPPING MATRIX (GEO + WEIGHT tier -> price)
# ------------------------------------------------------------------------------

_MATRIX_PATH = os.path.join(os.path.dirname(__file__), "shipping_matrix_all.csv")

_ISO2_TO_NAME = {
    "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom",
    "DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain", "PT": "Portugal",
    "PL": "Poland", "RO": "Romania", "GR": "Greece", "NL": "Netherlands", "BE": "Belgium",
    "IE": "Ireland", "AU": "Australia", "NZ": "New Zealand", "CA": "Canada",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "CH": "Switzerland", "AT": "Austria", "AE": "United Arab Emirates", "SA": "Saudi Arabia",
    "QA": "Qatar", "KW": "Kuwait", "OM": "Oman", "BH": "Bahrain", "IL": "Israel",
    "CY": "Cyprus", "CZ": "Czechia", "HU": "Hungary", "SK": "Slovakia", "SI": "Slovenia",
    "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania", "TR": "Turkey",
}

_SHIP_MATRIX: Dict[str, Dict[float, float]] = {}
_WARNED_MISSING_GEOS: set[str] = set()
_WARNED_MATRIX = False

def _canonical_geo(country_name: Optional[str], iso2: Optional[str]) -> str:
    s = (country_name or "").strip()
    cc = (iso2 or "").strip().upper()

    if cc and cc in _ISO2_TO_NAME:
        return _ISO2_TO_NAME[cc]
    if s:
        return s.title()
    return cc or "Unknown"

def _load_shipping_matrix_geo_weight() -> None:
    global _SHIP_MATRIX, _WARNED_MATRIX
    if _SHIP_MATRIX:
        return

    if not os.path.exists(_MATRIX_PATH):
        if not _WARNED_MATRIX:
            print(f"⚠️ Shipping matrix CSV not found at {_MATRIX_PATH}")
            _WARNED_MATRIX = True
        return

    try:
        with open(_MATRIX_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            cols = [str(c or "").strip().upper() for c in (reader.fieldnames or [])]

            def _col(name: str) -> Optional[str]:
                u = name.upper()
                for i, c in enumerate(cols):
                    if c == u:
                        return reader.fieldnames[i]
                return None

            geo_col = _col("GEO")
            w_col   = _col("WEIGHT")

            price_col = None
            for candidate in ("STANDARD", "PRICE_USD", "PRICE"):
                pc = _col(candidate)
                if pc:
                    price_col = pc
                    break

            if not geo_col or not w_col or not price_col:
                raise RuntimeError(
                    f"Matrix must include GEO, WEIGHT, and (STANDARD or PRICE_USD or PRICE). "
                    f"Found: {reader.fieldnames}"
                )

            out: Dict[str, Dict[float, float]] = {}
            for row in reader:
                raw_geo = str(row.get(geo_col) or "").strip()
                if not raw_geo:
                    continue

                canon = _canonical_geo(None, raw_geo) if len(raw_geo) == 2 else _canonical_geo(raw_geo, None)

                try:
                    tier_kg = float(str(row.get(w_col) or "").strip())
                except Exception:
                    continue
                if tier_kg <= 0:
                    continue

                try:
                    price = float(str(row.get(price_col) or "0").strip())
                except Exception:
                    price = 0.0

                out.setdefault(canon, {})[tier_kg] = float(price)

            _SHIP_MATRIX = out
            print(f"[matrix] Loaded GEOs={len(_SHIP_MATRIX)} from {_MATRIX_PATH}")

    except Exception as e:
        print(f"⚠️ Shipping matrix load error: {e}")
        _SHIP_MATRIX = {}

def _order_geo(order: dict) -> str:
    addr = order.get("shippingAddress") or {}
    cn = (addr.get("country") or "").strip()
    cc = (addr.get("countryCodeV2") or "").strip().upper()
    return _canonical_geo(cn, cc)

def _order_weight_kg_from_totalWeight(order: dict) -> float:
    try:
        tw_g = float(order.get("totalWeight") or 0.0)
    except Exception:
        tw_g = 0.0
    if tw_g <= 0:
        return 0.0
    return max(0.0, tw_g / 1000.0)

def _lookup_matrix_shipping_usd(geo: str, weight_kg: float) -> float:
    if not _SHIP_MATRIX:
        _load_shipping_matrix_geo_weight()
    if not _SHIP_MATRIX:
        return 0.0

    canon = _canonical_geo(geo if len(geo or "") != 2 else None, geo if len(geo or "") == 2 else None)
    tbl = _SHIP_MATRIX.get(canon)

    if not tbl:
        for g in _SHIP_MATRIX.keys():
            if g.lower() == canon.lower():
                tbl = _SHIP_MATRIX[g]
                break

    if not tbl:
        if canon not in _WARNED_MISSING_GEOS:
            preview = sorted(list(_SHIP_MATRIX.keys()))[:10]
            print(f"⚠️ No matrix GEO match for '{geo}' (canon '{canon}'). Example GEOs: {preview}")
            _WARNED_MISSING_GEOS.add(canon)
        return 0.0

    tiers = sorted(tbl.keys())
    for t in tiers:
        if weight_kg <= t + 1e-9:
            return float(tbl.get(t, 0.0))
    return float(tbl.get(tiers[-1], 0.0)) if tiers else 0.0

# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------

def _fx_any_to_usd(amount: float, currency: str) -> float:
    try:
        cur = (currency or "USD").upper()
        if cur == "USD":
            return float(amount)
        rate = float(os.getenv(f"FX_{cur}_TO_USD", "1.0"))
        return float(amount) * rate
    except Exception:
        return float(amount)

def _money_at(d: dict, path: List[str]) -> float:
    cur = d or {}
    for k in path:
        if not isinstance(cur, dict):
            return 0.0
        cur = cur.get(k)
    try:
        return float(cur or 0.0)
    except Exception:
        return 0.0

def _line_nodes(o: dict) -> List[dict]:
    return ((o.get("lineItems") or {}).get("nodes")) or []

def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

# ---------- Shopify channel (Google/Meta) detection ----------
_GOOGLE_PAT = re.compile(
    r"""(?ix)
        \bgoogle\b
        | gclid=
        | utm_source=(google|google[-_ ]?search|google[-_ ]?shopping)
        | (google\.[a-z.]{2,11})
        | \bgoogle\s*search\b
    """
)
_META_PAT = re.compile(
    r"""(?ix)
        \b(facebook|instagram|meta)\b
        | utm_source=(facebook|fb|instagram|ig)
        | (facebook\.com|instagram\.com|fb\.com)
    """
)

def _collect_value(x):
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        out = []
        for v in x.values():
            if isinstance(v, str) and v:
                out.append(v)
        return out
    return []

def _extract_urls_and_source(order: dict) -> str:
    bits: List[str] = []
    for k in ("referrerUrl", "sourceName", "referrer", "customerUrl"):
        v = order.get(k)
        bits.extend(_collect_value(v))
    cjs = order.get("customerJourneySummary") or {}
    for edge in ("firstVisit", "lastVisit"):
        visit = cjs.get(edge) or {}
        if not isinstance(visit, dict):
            continue
        for k in ("referrerUrl"):
            u = visit.get(k)
            if isinstance(u, str) and u:
                bits.append(u)
                try:
                    q = parse_qs(urlparse(u).query)
                    for kk in ("utm_source", "utm_medium", "utm_campaign", "gclid", "utm_content", "utm_term"):
                        vv = q.get(kk)
                        if vv:
                            bits.extend(vv)
                except Exception:
                    pass
        utm = visit.get("utmParameters") or {}
        if isinstance(utm, dict):
            for kk in ("source", "medium", "campaign", "content", "term"):
                vv = utm.get(kk)
                if isinstance(vv, str) and vv:
                    bits.append(f"utm_{kk}={vv}")
    return " | ".join(bits)

def _shopify_channel(order: dict) -> str | None:
    blob = _extract_urls_and_source(order)
    if not blob:
        return None
    if _GOOGLE_PAT.search(blob):
        return "google"
    if _META_PAT.search(blob):
        return "meta"
    return None

# ------------------------------------------------------------------------------
# KPIs
# ------------------------------------------------------------------------------

@dataclass
class KPIs:
    day: str
    gross: float
    discounts: float
    refunds: float
    net: float
    cogs: float
    shipping_charged: float
    shipping_cost: float       # PayPal ONLY (Cash)
    shipping_estimated: float  # Matrix ONLY (Op)
    psp_usd: float
    google_spend: float
    meta_spend: float
    total_spend: float
    operational: float
    margin: float
    margin_pct: float | None
    orders: int
    aov: float
    returning_count: int
    google_pur: int
    google_cpa: float | None
    meta_pur: int
    meta_cpa: float | None
    general_cpa: float | None

# ---------- Google Ads spend ----------
def _google_spend_usd(day_iso: str, shop_tz: str) -> float:
    global _GADS_WARNED, _GADS_CACHE
    if _GADS_DISABLED:
        print(f"[GADS] Disabled via DISABLE_GOOGLE_ADS=1")
        return 0.0

    ids_key = (os.getenv("GOOGLE_ADS_CUSTOMER_IDS", "") or "").strip() \
              or (os.getenv("GOOGLE_ADS_CUSTOMER_ID", "") or "").strip()

    key = f"{day_iso}|{shop_tz}|{ids_key}"
    print(f"[GADS] Fetching spend for {day_iso}, tz={shop_tz}, ids={ids_key}")

    # Check cache and TTL (with safety check for old cache format)
    if key in _GADS_CACHE:
        try:
            cached_entry = _GADS_CACHE[key]
            # Handle both old (float) and new (tuple) cache formats
            if isinstance(cached_entry, tuple):
                cached_value, cached_time = cached_entry
                age_minutes = (datetime.now() - cached_time).total_seconds() / 60
                if age_minutes < _GADS_CACHE_TTL_MINUTES:
                    print(f"[GADS] Using cached value: ${cached_value:.2f} (age={age_minutes:.1f}m)")
                    return cached_value
                else:
                    print(f"[GADS] Cache expired for {day_iso} (age={age_minutes:.1f}m), refreshing...")
            else:
                # Old cache format (float) - clear it
                print(f"[GADS] Old cache format detected, clearing cache entry")
                del _GADS_CACHE[key]
        except Exception as cache_err:
            print(f"[GADS] Cache error: {cache_err}, clearing cache entry")
            _GADS_CACHE.pop(key, None)

    # Get config file path - use absolute path if relative doesn't exist
    cfg = os.getenv("GOOGLE_ADS_CONFIG", "google-ads.yaml")
    if not os.path.isabs(cfg):
        # Try current directory first
        if not os.path.exists(cfg):
            # Try /app directory (Render)
            cfg_abs = os.path.join("/app", cfg)
            if os.path.exists(cfg_abs):
                cfg = cfg_abs
            else:
                # Try script directory
                cfg_abs = os.path.join(os.path.dirname(__file__), cfg)
                if os.path.exists(cfg_abs):
                    cfg = cfg_abs

    print(f"[GADS] Config file: {cfg}")
    print(f"[GADS] Config exists: {os.path.exists(cfg)}")

    if not os.path.exists(cfg):
        print(f"⚠️ Google Ads config file not found at: {cfg}")
        return 0.0

    include_ids = None
    ids_env = (os.getenv("GOOGLE_ADS_CUSTOMER_IDS", "") or "").strip()
    if ids_env:
        include_ids = ids_env
        print(f"[GADS] Using customer IDs: {include_ids}")
    else:
        print(f"[GADS] No customer IDs specified in env")

    try:
        print(f"[GADS] Calling daily_spend_usd_aligned...")
        usd = daily_spend_usd_aligned(day_iso, shop_tz, cfg, include_ids=include_ids)
        print(f"[GADS] ✅ Fetched spend: ${usd:.2f} for {day_iso}")
        _GADS_CACHE[key] = (usd, datetime.now())
        return usd
    except Exception as e:
        print(f"⚠️ Google Ads spend ERROR for {day_iso}: {e}")
        print(f"⚠️ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        if not _GADS_WARNED:
            print(f"⚠️ Google Ads spend fallback (treating as 0): {e}")
            _GADS_WARNED = True
        # Don't cache errors - let it retry next time
        return 0.0

def _uniq_by_id(nodes: List[dict]) -> List[dict]:
    out, seen = [], set()
    for o in nodes:
        oid = o.get("id")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        out.append(o)
    return out

def _kpis_from_orders(
    orders: List[dict],
    day_label: str,
    start_local: datetime,
    end_local: datetime,
    tz_name: str
) -> KPIs:
    tz = pytz.timezone(tz_name)

    discounts = refunds = ship_chg = 0.0
    gross = cogs = 0.0
    matrix_shipping_total = 0.0
    returning_customers: set[str] = set()

    in_window: List[dict] = []
    boundary_orders = []  # Track orders near boundaries for debugging

    for o in orders:
        dt = _parse_dt(o.get("createdAt"))
        if not dt:
            continue
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        dt_local = dt.astimezone(tz)

        # Check for boundary orders (within 5 minutes of start/end)
        seconds_from_start = abs((dt_local - start_local).total_seconds())
        seconds_from_end = abs((dt_local - end_local).total_seconds())

        if seconds_from_start < 300 or seconds_from_end < 300:
            boundary_orders.append({
                "order_name": o.get("name"),
                "created_at_utc": o.get("createdAt"),
                "created_at_local": dt_local.isoformat(),
                "in_window": start_local <= dt_local < end_local
            })

        if start_local <= dt_local < end_local:
            in_window.append(o)

    # Log boundary orders if any found
    if boundary_orders:
        print(f"  [KPIs] {day_label}: Found {len(boundary_orders)} boundary order(s):")
        for bo in boundary_orders:
            status = "INCLUDED" if bo["in_window"] else "EXCLUDED"
            print(f"    - {bo['order_name']}: {bo['created_at_local']} [{status}]")

    orders_created = len(in_window)
    orders_net_count = 0
    g_orders_created = 0
    m_orders_created = 0

    for o in in_window:
        is_cancelled = bool(o.get("cancelledAt"))

        ch = _shopify_channel(o)
        if ch == "google":
            g_orders_created += 1
        elif ch == "meta":
            m_orders_created += 1

        if is_cancelled:
            continue

        orders_net_count += 1

        discounts += (
            _money_at(o, ["totalDiscountsSet", "shopMoney", "amount"])
            or _money_at(o, ["currentTotalDiscountsSet", "shopMoney", "amount"])
        )
        refunds += _money_at(o, ["totalRefundedSet", "shopMoney", "amount"])

        sc = _money_at(o, ["totalShippingPriceSet", "shopMoney", "amount"])
        if sc == 0:
            sc = _money_at(o, ["currentShippingPriceSet", "shopMoney", "amount"])
        ship_chg += sc

        cust = o.get("customer") or {}
        cid  = cust.get("id")
        try:
            if int(cust.get("numberOfOrders") or 0) > 1 and cid:
                returning_customers.add(cid)
        except Exception:
            pass

        for li in _line_nodes(o):
            qty = int(li.get("quantity") or 0)
            gross += _money_at(li, ["originalTotalSet", "shopMoney", "amount"])
            unit_cost = _money_at(li, ["variant", "inventoryItem", "unitCost", "amount"])
            if qty > 0 and unit_cost:
                cogs += unit_cost * qty

        geo = _order_geo(o)
        wkg = _order_weight_kg_from_totalWeight(o)
        matrix_shipping_total += _lookup_matrix_shipping_usd(geo, wkg)

    net = gross - discounts - refunds

    df_pp = paypal_to_df(extract_shipping_and_fees(fetch_transactions(start_local, end_local)))
    ship_cost_paypal = float(paypal_shipping_total_grouped(df_pp) or 0.0)

    matrix_only = float(matrix_shipping_total)

    day_iso = start_local.date().isoformat()

    # ✅ LIVE spend for the same day
    g_spend = _google_spend_usd(day_iso, tz_name)

    if _META_DISABLED:
        m_spend = 0.0
        m_cpa = None
    else:
        try:
            meta_resp = fetch_meta_insights_day(day_iso, day_iso) or {}
            m_spend_raw = float(meta_resp.get("meta_spend") or 0.0)
            m_currency = (meta_resp.get("currency") or "USD").upper()
            m_spend = _fx_any_to_usd(m_spend_raw, m_currency)
        except Exception:
            m_spend = 0.0
        m_cpa = round(m_spend / m_orders_created, 2) if m_orders_created > 0 else None

    g_cpa = round(g_spend / g_orders_created, 2) if g_orders_created > 0 else None

    psp_eur = get_psp_fees_daily(start_local.date(), end_local.date()).get(start_local.date(), 0.0)
    psp_usd = _fx_any_to_usd(psp_eur, "EUR")

    total_spend = g_spend + m_spend

    operational = (net + ship_chg) - matrix_only - cogs - psp_usd
    margin = operational - total_spend

    revenue_base = net + ship_chg
    margin_pct = (margin / revenue_base) if revenue_base > 0 else 0.0
    aov = (gross / orders_net_count) if orders_net_count else 0.0
    general_cpa = round(total_spend / orders_created, 2) if orders_created else None

    return KPIs(
        day=day_label,
        gross=round(gross, 2),
        discounts=round(discounts, 2),
        refunds=round(refunds, 2),
        net=round(net, 2),
        cogs=round(cogs, 2),
        shipping_charged=round(ship_chg, 2),
        shipping_cost=round(ship_cost_paypal, 2),
        shipping_estimated=round(matrix_only, 2),
        psp_usd=round(psp_usd, 2),
        google_spend=round(g_spend, 2),
        meta_spend=round(m_spend, 2),
        total_spend=round(total_spend, 2),
        operational=round(operational, 2),
        margin=round(margin, 2),
        margin_pct=None if margin_pct is None else round(margin_pct, 2),
        orders=orders_created,
        aov=round(aov, 2),
        returning_count=len(returning_customers),
        google_pur=g_orders_created,
        google_cpa=g_cpa,
        meta_pur=m_orders_created,
        meta_cpa=m_cpa,
        general_cpa=general_cpa,
    )

# ------------------------------------------------------------------------------
# day KPIs (explicit fetch per day, createdAt only)
# ------------------------------------------------------------------------------

def compute_day_kpis(day: date, tz_name: str) -> KPIs:
    tz = pytz.timezone(tz_name)
    start_local = tz.localize(datetime.combine(day, datetime.min.time()))
    end_local   = tz.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    _, _, _, _, label = local_day_window(tz_name, day.strftime("%Y-%m-%d"))

    nodes: List[dict] = []
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token  = store["access_token"]
        created = fetch_orders_created_between_for_store(
            domain, token, start_local.isoformat(), end_local.isoformat(), exclude_cancelled=False
        )
        nodes.extend(created)

    nodes = _uniq_by_id(nodes)
    return _kpis_from_orders(nodes, label, start_local, end_local, tz_name)

def compute_mtd_kpis(anchor_day: date, tz_name: str) -> KPIs:
    """
    Compute Month-To-Date KPIs by summing all days from the 1st to anchor_day.
    """
    first_d, _ = _month_bounds(anchor_day)
    _, _, _, _, kpi_by_date = build_month_rows(anchor_day, tz_name)

    # Sum all KPIs from first to anchor_day
    total_orders = total_gross = total_discounts = total_refunds = total_net = 0.0
    total_cogs = total_ship_chg = total_ship_est = total_ship_cost = 0.0
    total_psp = total_g_spend = total_m_spend = total_total_spend = 0.0
    total_op = total_margin = 0.0
    total_returning = total_g_pur = total_m_pur = 0

    for d in range(1, anchor_day.day + 1):
        day = date(anchor_day.year, anchor_day.month, d)
        k = kpi_by_date.get(day)
        if not k:
            continue

        total_orders += k.orders
        total_gross += k.gross
        total_discounts += k.discounts
        total_refunds += k.refunds
        total_net += k.net
        total_cogs += k.cogs
        total_ship_chg += k.shipping_charged
        total_ship_est += k.shipping_estimated
        total_ship_cost += k.shipping_cost
        total_psp += k.psp_usd
        total_g_spend += k.google_spend
        total_m_spend += k.meta_spend
        total_total_spend += k.total_spend
        total_op += k.operational
        total_margin += k.margin
        total_returning += k.returning_count
        total_g_pur += k.google_pur
        total_m_pur += k.meta_pur

    # Compute aggregated metrics
    revenue_base = total_net + total_ship_chg
    margin_pct = (total_margin / revenue_base) if revenue_base > 0 else 0.0
    aov = (total_gross / total_orders) if total_orders else 0.0
    g_cpa = round(total_g_spend / total_g_pur, 2) if total_g_pur > 0 else None
    m_cpa = round(total_m_spend / total_m_pur, 2) if total_m_pur > 0 else None
    general_cpa = round(total_total_spend / total_orders, 2) if total_orders else None

    return KPIs(
        day=f"MTD ({first_d.isoformat()} to {anchor_day.isoformat()})",
        gross=round(total_gross, 2),
        discounts=round(total_discounts, 2),
        refunds=round(total_refunds, 2),
        net=round(total_net, 2),
        cogs=round(total_cogs, 2),
        shipping_charged=round(total_ship_chg, 2),
        shipping_cost=round(total_ship_cost, 2),
        shipping_estimated=round(total_ship_est, 2),
        psp_usd=round(total_psp, 2),
        google_spend=round(total_g_spend, 2),
        meta_spend=round(total_m_spend, 2),
        total_spend=round(total_total_spend, 2),
        operational=round(total_op, 2),
        margin=round(total_margin, 2),
        margin_pct=None if margin_pct is None else round(margin_pct, 2),
        orders=int(total_orders),
        aov=round(aov, 2),
        returning_count=int(total_returning),
        google_pur=int(total_g_pur),
        google_cpa=g_cpa,
        meta_pur=int(total_m_pur),
        meta_cpa=m_cpa,
        general_cpa=general_cpa,
    )

# ------------------------------------------------------------------------------
# month build (createdAt only)
# ------------------------------------------------------------------------------

def _month_bounds(d: date) -> Tuple[date, date]:
    first = d.replace(day=1)
    if first.month == 12:
        nxt = date(first.year + 1, 1, 1)
    else:
        nxt = date(first.year, first.month + 1, 1)
    return first, nxt

def build_month_rows(anchor_day: date, tz_name: str) -> Tuple[str, int, int, Dict[int, List[Any]], Dict[date, KPIs]]:
    tz = pytz.timezone(tz_name)
    first_d, _ = _month_bounds(anchor_day)

    start_local = tz.localize(datetime.combine(first_d, datetime.min.time()))
    end_local   = tz.localize(datetime.combine(anchor_day + timedelta(days=1), datetime.min.time()))

    month_orders: List[dict] = []
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token  = store["access_token"]
        created = fetch_orders_created_between_for_store(
            domain, token, start_local.isoformat(), end_local.isoformat(), exclude_cancelled=False
        )
        month_orders.extend(created)

    month_orders = _uniq_by_id(month_orders)

    buckets: Dict[date, List[dict]] = {}
    for o in month_orders:
        dt = _parse_dt(o.get("createdAt"))
        if not dt:
            continue
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        d_local = dt.astimezone(tz).date()
        if d_local < first_d or d_local > anchor_day:
            continue
        buckets.setdefault(d_local, []).append(o)

    rows_by_day: Dict[int, List[Any]] = {}
    kpi_by_date: Dict[date, KPIs] = {}

    month_name = anchor_day.strftime("%Y-%m")
    year, month = anchor_day.year, anchor_day.month

    for d in range(1, anchor_day.day + 1):
        day = date(year, month, d)
        s = tz.localize(datetime.combine(day, datetime.min.time()))
        e = tz.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
        _, _, _, _, label = local_day_window(tz_name, day.strftime("%Y-%m-%d"))

        day_orders = buckets.get(day, [])
        k = _kpis_from_orders(day_orders, label, s, e, tz_name)
        kpi_by_date[day] = k

        rows_by_day[d] = [
            day.isoformat(),
            k.orders, k.gross, k.discounts, k.refunds, k.net,
            k.cogs, k.shipping_charged,
            k.shipping_estimated,
            k.shipping_cost,
            k.google_spend, k.meta_spend, k.total_spend,
            k.psp_usd, k.operational, k.margin, k.margin_pct,
            k.aov, k.returning_count, k.general_cpa,
        ]

    return month_name, year, month, rows_by_day, kpi_by_date

# ------------------------------------------------------------------------------
# Summary sheet upsert (optional)
# ------------------------------------------------------------------------------

def _upsert_sheet_summary(ws_month, month_name: str, today_kpi: KPIs, yday_kpi: KPIs):
    try:
        import gspread
    except Exception:
        print("ℹ️ gspread not available; skipping Summary sheet upsert.")
        return

    sh = ws_month.spreadsheet
    try:
        ws_sum = sh.worksheet("Summary")
    except Exception:
        ws_sum = sh.add_worksheet(title="Summary", rows=200, cols=30)

    headers = [
        "Label","Orders","Gross","Discounts","Refunds","Net","COGS",
        "Ship Charged","Est Ship (Matrix)","Ship Cost (PayPal)",
        "Spend (Google)","Spend (Meta)","Total Spend",
        "PSP Fee (USD)","Operational Profit","Net Margin","Margin %","AOV",
        "Returning Customers","Google Purchases","Google CPA","Meta Purchases","Meta CPA","General CPA"
    ]

    def _row_from_k(k: KPIs, lbl: str):
        return [
            f"{lbl} ({k.day})", k.orders, k.gross, k.discounts, k.refunds, k.net, k.cogs,
            k.shipping_charged, k.shipping_estimated, k.shipping_cost,
            k.google_spend, k.meta_spend, k.total_spend,
            k.psp_usd, k.operational, k.margin, ("" if k.margin_pct is None else k.margin_pct),
            k.aov, k.returning_count, k.google_pur, ("" if k.google_cpa is None else k.google_cpa),
            k.meta_pur, ("" if k.meta_cpa is None else k.meta_cpa), ("" if k.general_cpa is None else k.general_cpa)
        ]

    rows = [
        _row_from_k(today_kpi, "Today"),
        _row_from_k(yday_kpi, "Yesterday"),
    ]

    ws_sum.update("A1", [headers] + rows, value_input_option="USER_ENTERED")
    print("✅ Summary sheet upserted.")

# ------------------------------------------------------------------------------
# orchestrator
# ------------------------------------------------------------------------------

def run_once(day_str: str | None = None, debug_day: str | None = None) -> None:
    shop_tz = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"
    os.environ["REPORT_TZ"] = shop_tz
    tz = pytz.timezone(shop_tz)

    if day_str:
        anchor = datetime.strptime(day_str, "%Y-%m-%d").date()
    else:
        anchor = datetime.now(tz).date()

    print(f"[Master] Running smart update for: {anchor} (tz={shop_tz})")

    # Build month rows (for sheet update of TODAY only)
    month_name, year, month, rows_by_day, _ = build_month_rows(anchor, shop_tz)

    day_number = anchor.day
    day_row_data = rows_by_day.get(day_number)

    # A) Update Google Sheet Row (today only) - only if sheets_client is available
    if HAS_SHEETS and ensure_month_tab and update_single_day_row:
        _, ws_month = ensure_month_tab(month_name)
        if day_row_data:
            update_single_day_row(
                ws_month,
                day_number,
                day_row_data,
                year=year,
                month=month,
                headers=MONTH_HEADERS,
            )
            print(f"✅ Successfully patched Sheet for Day {day_number}")
        else:
            print(f"⚠️ No Sheet data found for Day {day_number}")
    else:
        print(f"ℹ️ Skipping Google Sheets update (gspread not available)")

    # B) Telegram Summary — compute today, yesterday, and MTD
    yday = anchor - timedelta(days=1)
    k_today = compute_day_kpis(anchor, shop_tz)
    k_yday  = compute_day_kpis(yday, shop_tz)
    k_mtd   = compute_mtd_kpis(anchor, shop_tz)

    upsert_daily_summary(
        today_kpi=k_today,
        yday_kpi=k_yday,
        mtd_kpi=k_mtd,
        pin=True,
        summary_key="DAILY"
    )
    print("📨 Telegram summary upserted.")

    # C) Summary tab
    _upsert_sheet_summary(ws_month, month_name, k_today, k_yday)

    if debug_day:
        dd = datetime.strptime(debug_day, "%Y-%m-%d").date()
        k_dbg = compute_day_kpis(dd, shop_tz)
        print(
            f"🔎 Debug KPIs {debug_day}: orders={k_dbg.orders} "
            f"net={k_dbg.net} ship_matrix={k_dbg.shipping_estimated} paypal_ship={k_dbg.shipping_cost}"
        )

if __name__ == "__main__":
    from os.path import dirname, join
    load_dotenv(join(dirname(__file__), ".env"))
    import argparse

    ap = argparse.ArgumentParser(description="Mirai master — month-only report (USD, Shopify TZ)")
    ap.add_argument("--day", required=False, help="YYYY-MM-DD (default: today in Shopify TZ)")
    ap.add_argument("--every", type=int, default=0, help="If >0, loop and run every N seconds.")
    ap.add_argument("--debug-day", help="YYYY-MM-DD — print KPI summary for that date", default=None)
    args = ap.parse_args()

    if args.every and args.every > 0:
        while True:
            run_once(args.day, debug_day=args.debug_day)
            try:
                import time
                time.sleep(args.every)
            except KeyboardInterrupt:
                break
    else:
        run_once(args.day, debug_day=args.debug_day)
