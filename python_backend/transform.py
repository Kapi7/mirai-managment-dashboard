# transform.py — DataFrames + aggregates + channel normalization (no REST needed)
from __future__ import annotations
from typing import List, Dict, Any
import pandas as pd

from channel_normalizer import attach_normalized_channel

def _money(node: Dict[str, Any], path: List[str]) -> float:
    cur = node
    try:
        for k in path:
            cur = cur.get(k) or {}
        return float((cur.get("amount") if isinstance(cur, dict) else 0) or 0)
    except Exception:
        return 0.0

def _utm(o: Dict[str, Any], which: str, key: str) -> str:
    try:
        return (
            ((o.get("customerJourneySummary") or {})
              .get(which) or {})
              .get("utmParameters") or {}
        ).get(key) or ""
    except Exception:
        return ""

def _ref_url(o: Dict[str, Any], which: str) -> str:
    try:
        return (
            ((o.get("customerJourneySummary") or {})
              .get(which) or {})
        ).get("referrerUrl") or ""
    except Exception:
        return ""

def orders_to_df(orders: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for o in orders or []:
        name = o.get("name") or ""
        created = o.get("createdAt")
        source_name = (o.get("sourceName") or "")

        # UTMs and referrerUrl (GraphQL only)
        utm_source = _utm(o, "lastVisit", "source") or _utm(o, "firstVisit", "source")
        utm_medium = _utm(o, "lastVisit", "medium") or _utm(o, "firstVisit", "medium")
        referrer_url = _ref_url(o, "lastVisit") or _ref_url(o, "firstVisit")

        # Line items → gross + COGS
        gross = 0.0
        cogs  = 0.0
        for li in ((o.get("lineItems") or {}).get("nodes") or []):
            qty = int(li.get("quantity") or 0)
            gross += _money(li, ["originalTotalSet", "shopMoney"])
            try:
                unit_cost = float(
                    (((li.get("variant") or {})
                      .get("inventoryItem") or {})
                      .get("unitCost") or {})
                    .get("amount") or 0
                )
            except Exception:
                unit_cost = 0.0
            cogs += unit_cost * qty

        discounts = _money(o, ["currentTotalDiscountsSet", "shopMoney"])
        refunds   = _money(o, ["totalRefundedSet", "shopMoney"])
        shipping_charged = _money(o, ["currentShippingPriceSet", "shopMoney"])
        net = max(gross - discounts - refunds, 0.0)

        # Returning customer
        try:
            rcr = int(((o.get("customer") or {}).get("numberOfOrders") or 0) > 1)
        except Exception:
            rcr = 0

        rows.append({
            "created_at": created,
            "name": name,
            "sourceName": source_name,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "referrer_url": referrer_url,  # <— key for Google detection without UTMs

            "gross": round(gross, 2),
            "discounts": round(discounts, 2),
            "refunds": round(refunds, 2),
            "net": round(net, 2),
            "cogs": round(cogs, 2),
            "shipping_charged": round(shipping_charged, 2),
            "orders": 1,
            "rcr": rcr,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Normalize using Shopify-like rules (UTMs + referrerUrl + sourceName)
    df = attach_normalized_channel(df)
    return df

def aggregate_shopify(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {
            "gross": 0.0, "discounts": 0.0, "refunds": 0.0, "net": 0.0,
            "cogs": 0.0, "shipping_charged": 0.0, "orders": 0, "rcr_count": 0
        }
    return {
        "gross": float(df["gross"].sum()),
        "discounts": float(df["discounts"].sum()),
        "refunds": float(df["refunds"].sum()),
        "net": float(df["net"].sum()),
        "cogs": float(df["cogs"].sum()),
        "shipping_charged": float(df["shipping_charged"].sum()),
        "orders": int(df["orders"].sum()),
        "rcr_count": int(df["rcr"].sum()),
    }

# ---- PayPal helpers (unchanged) ----
def paypal_to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows or [])

def paypal_shipping_total_grouped(df: pd.DataFrame) -> float:
    if df is None or df.empty or "shipping_amount" not in df.columns:
        return 0.0
    return float(df["shipping_amount"].sum())