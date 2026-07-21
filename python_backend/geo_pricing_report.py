"""
Geo Pricing Report Module (Phase 1 — dry-run only, no Shopify writes)

Computes proposed per-market prices under the SEO strategy:
  price = competitor_avg_local * (1 - UNDERCUT), floored at
  COGS / (1 - MIN_MARGIN - PSP_FEE) converted to local currency.

No ad-CPA term and no shipping term in the price (delivery is charged
separately; ad CPA does not apply to organic traffic).

Outputs CSV/JSON proposal reports per market for human review.
"""

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from geo_competitor_scan import GEO_CONFIG, get_competitor_stats

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
FX_CACHE_FILE = OUTPUTS_DIR / "fx_rates.json"
SALES_FILE = OUTPUTS_DIR / "variant_sales_2026.json"

# Pricing strategy constants (SEO model)
UNDERCUT = 0.04          # 4% below competitor average
MIN_MARGIN = 0.30        # minimum margin as share of price
PSP_FEE_RATE = 0.05      # payment processing, share of price
FX_MAX_AGE_S = 86400     # refresh FX daily

# Offline fallback FX (USD -> currency), updated 2026-07
FX_FALLBACK = {"USD": 1.0, "AUD": 1.52, "GBP": 0.79, "CAD": 1.37, "EUR": 0.92}

# Market definitions: geo key -> Shopify market currency
MARKETS = {geo: cfg["currency"] for geo, cfg in GEO_CONFIG.items()}


# ================== FX ==================

def get_fx_rates(force_refresh: bool = False) -> Dict[str, float]:
    """USD->currency rates, live from open.er-api.com, cached daily on disk."""
    OUTPUTS_DIR.mkdir(exist_ok=True)
    if not force_refresh and FX_CACHE_FILE.exists():
        try:
            cached = json.loads(FX_CACHE_FILE.read_text())
            if time.time() - cached.get("fetched_at", 0) < FX_MAX_AGE_S:
                return cached["rates"]
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=15)
        resp.raise_for_status()
        rates = resp.json()["rates"]
        FX_CACHE_FILE.write_text(json.dumps(
            {"fetched_at": time.time(), "rates": rates}))
        return rates
    except Exception as e:
        print(f"⚠️ FX fetch failed ({e}); using fallback rates {FX_FALLBACK}")
        return dict(FX_FALLBACK)


# ================== price math ==================

def round_psychological(price: float, floor: float) -> float:
    """
    Round to a .95 ending without going below the floor.
    e.g. 23.40 -> 22.95 (if >= floor, else 23.95).
    """
    if price <= 0:
        return price
    candidate = int(price) - 0.05  # 23.40 -> 22.95
    if candidate < 1:
        candidate = 0.95
    if candidate < floor:
        candidate = int(price) + 0.95  # next .95 above
    return round(candidate, 2)


def propose_price(cogs_usd: float, comp_avg_local: float, fx: float,
                  current_local: float) -> Dict[str, Any]:
    """
    Proposed price for one variant in one market (local currency).

    Returns {proposed, floor, note}. note: "undercut" | "floor" | "no-data".
    """
    floor = round(cogs_usd * fx / (1.0 - MIN_MARGIN - PSP_FEE_RATE), 2) \
        if cogs_usd > 0 else 0.0

    if comp_avg_local and comp_avg_local > 0:
        target = comp_avg_local * (1.0 - UNDERCUT)
        if floor > 0 and target < floor:
            proposed, note = floor, "floor"
        else:
            proposed, note = target, "undercut"
        proposed = round_psychological(proposed, floor)
    else:
        proposed, note = current_local, "no-data"

    return {"proposed": round(proposed, 2), "floor": floor, "note": note}


# ================== 2026 sales weights ==================

def build_sales_weights(store: str, token: str) -> Dict[str, Any]:
    """
    Pull 2026 orders once and aggregate per-variant units/revenue + titles/sku
    (titles feed the competitor search queries). Cached to SALES_FILE.
    """
    OUTPUTS_DIR.mkdir(exist_ok=True)
    orders = []
    url = (f"https://{store}/admin/api/2024-10/orders.json"
           f"?status=any&created_at_min=2026-01-01T00:00:00Z&limit=250"
           f"&fields=id,cancelled_at,financial_status,line_items")
    while url:
        resp = requests.get(url, headers={"X-Shopify-Access-Token": token},
                            timeout=60)
        resp.raise_for_status()
        orders.extend(resp.json().get("orders", []))
        url = None
        for part in resp.headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
        time.sleep(0.3)

    agg: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        if o.get("cancelled_at") or o.get("financial_status") in ("voided", "refunded"):
            continue
        for li in o.get("line_items") or []:
            vid = li.get("variant_id")
            if not vid:
                continue
            vid = str(vid)
            a = agg.setdefault(vid, {
                "variant_id": vid,
                "product_title": li.get("title") or "",
                "variant_title": li.get("variant_title") or "",
                "sku": li.get("sku") or "",
                "units": 0, "revenue": 0.0,
            })
            qty = li.get("quantity") or 0
            disc = sum(float(d.get("amount") or 0)
                       for d in li.get("discount_allocations") or [])
            a["units"] += qty
            a["revenue"] += float(li.get("price") or 0) * qty - disc

    for a in agg.values():
        a["revenue"] = round(a["revenue"], 2)
    out = {"built_at": datetime.utcnow().isoformat() + "Z", "variants": agg}
    SALES_FILE.write_text(json.dumps(out, indent=1))
    print(f"✅ Sales weights: {len(agg)} variants from {len(orders)} orders "
          f"-> {SALES_FILE.name}")
    return out


def load_sales_weights() -> Dict[str, Any]:
    if SALES_FILE.exists():
        try:
            return json.loads(SALES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"built_at": None, "variants": {}}


def top_variants_by_revenue(n: int) -> List[Dict[str, Any]]:
    """Top-n sold variants with titles/sku, for scan target selection."""
    variants = list(load_sales_weights()["variants"].values())
    variants.sort(key=lambda v: -v["revenue"])
    return variants[:n]


# ================== report generation ==================

def generate_market_report(geo: str, items: List[Dict[str, Any]],
                           fx_rates: Dict[str, float],
                           date_tag: Optional[str] = None) -> Dict[str, Any]:
    """
    Dry-run proposal for one market.

    items: fetch_items() output (variant_id, item, cogs, retail_base, ...).
    Writes outputs/geo_pricing_proposal_{geo}_{date}.csv and returns summary.
    """
    currency = MARKETS[geo]
    fx = fx_rates.get(currency)
    if not fx:
        raise ValueError(f"No FX rate for {currency}")

    sales = load_sales_weights()["variants"]
    date_tag = date_tag or datetime.utcnow().strftime("%Y-%m-%d")
    OUTPUTS_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUTS_DIR / f"geo_pricing_proposal_{geo}_{date_tag}.csv"

    rows = []
    for it in items:
        vid = str(it["variant_id"])
        cogs = it.get("cogs") or 0.0
        current_local = round((it.get("retail_base") or 0.0) * fx, 2)

        stats = get_competitor_stats(geo, vid)
        comp_avg_local, comp_source = 0.0, ""
        comp_low = comp_high = 0.0
        if stats and stats.get("comp_avg"):
            comp_avg_local = stats["comp_avg"]
            comp_low, comp_high = stats.get("comp_low", 0), stats.get("comp_high", 0)
            comp_source = stats.get("source", "geo_scan")
            # sanity: stats stored in local currency already
        elif geo != "us":
            us = get_competitor_stats("us", vid)
            if us and us.get("comp_avg"):
                comp_avg_local = round(us["comp_avg"] * fx, 2)
                comp_low = round(us.get("comp_low", 0) * fx, 2)
                comp_high = round(us.get("comp_high", 0) * fx, 2)
                comp_source = "us_proxy"

        p = propose_price(cogs, comp_avg_local, fx, current_local)
        note = p["note"] if comp_source != "us_proxy" else f"{p['note']}(proxy)"

        s = sales.get(vid, {})
        margin_at_proposed = (1 - (cogs * fx) / p["proposed"]) if p["proposed"] > 0 else 0
        delta_pct = ((p["proposed"] - current_local) / current_local * 100) \
            if current_local > 0 else 0

        rows.append({
            "variant_id": vid,
            "item": it.get("item", ""),
            "units_2026": s.get("units", 0),
            "revenue_2026_usd": s.get("revenue", 0.0),
            "cogs_usd": cogs,
            f"current_{currency}": current_local,
            f"comp_low_{currency}": comp_low,
            f"comp_avg_{currency}": comp_avg_local,
            f"comp_high_{currency}": comp_high,
            f"proposed_{currency}": p["proposed"],
            f"floor_{currency}": p["floor"],
            "delta_pct": round(delta_pct, 1),
            "margin_pct_at_proposed": round(margin_at_proposed * 100, 1),
            "note": note,
        })

    rows.sort(key=lambda r: -r["revenue_2026_usd"])

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    # summary
    priced = [r for r in rows if r["note"] != "no-data"]
    weighted = [r for r in priced if r["revenue_2026_usd"] > 0]
    tot_rev = sum(r["revenue_2026_usd"] for r in weighted)
    rev_weighted_delta = (
        sum(r["delta_pct"] * r["revenue_2026_usd"] for r in weighted) / tot_rev
        if tot_rev > 0 else 0.0
    )
    summary = {
        "geo": geo, "currency": currency, "fx_usd": fx,
        "variants_total": len(rows),
        "with_comp_data": len(priced),
        "via_us_proxy": sum(1 for r in rows if "(proxy)" in r["note"]),
        "at_floor": sum(1 for r in rows if r["note"].startswith("floor")),
        "no_data": sum(1 for r in rows if r["note"] == "no-data"),
        "rev_weighted_delta_pct": round(rev_weighted_delta, 1),
        "csv": str(csv_path),
    }
    print(f"📊 {geo.upper()}: {summary['with_comp_data']}/{summary['variants_total']} "
          f"priced ({summary['via_us_proxy']} proxy, {summary['at_floor']} at floor, "
          f"{summary['no_data']} no-data) | rev-weighted Δ "
          f"{summary['rev_weighted_delta_pct']}% -> {csv_path.name}")
    return summary
