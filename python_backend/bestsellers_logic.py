"""
Best Sellers Report Logic - Analyze top selling products by orders and revenue
"""
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict
import os
import pytz
import re

from config import SHOPIFY_STORES
from shopify_client import fetch_orders_created_between_for_store, get_shop_timezone


def _parse_dt(s: str) -> datetime:
    """Parse ISO datetime string"""
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except:
        return None


def _money_at(obj: dict, path: list) -> float:
    """Extract money value from nested dict"""
    for key in path:
        if obj is None:
            return 0.0
        obj = obj.get(key)
    try:
        return float(obj) if obj else 0.0
    except:
        return 0.0


def _line_nodes(order: dict) -> list:
    """Get line items from order"""
    li = order.get("lineItems") or {}
    edges = li.get("edges") or []
    return [e.get("node") or {} for e in edges]


def fetch_bestsellers(days: int = 30) -> Dict[str, Any]:
    """
    Fetch best selling products for the specified number of days

    Args:
        days: Number of days to look back (7, 30, or 60)

    Returns:
        Dict with bestsellers list and analytics summary
    """
    shop_tz = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"
    tz = pytz.timezone(shop_tz)

    end_date = datetime.now(tz).date()
    start_date = end_date - timedelta(days=days)

    start_local = tz.localize(datetime.combine(start_date, datetime.min.time()))
    end_local = tz.localize(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

    print(f"📊 Fetching best sellers for last {days} days ({start_date} to {end_date})")

    # Fetch orders from all stores
    all_orders = []
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token = store["access_token"]
        orders = fetch_orders_created_between_for_store(
            domain, token,
            start_local.isoformat(),
            end_local.isoformat(),
            exclude_cancelled=True  # Exclude cancelled orders
        )
        for o in orders:
            o["_store"] = domain
        all_orders.extend(orders)

    # Deduplicate by ID
    seen_ids = set()
    unique_orders = []
    for o in all_orders:
        oid = o.get("id")
        if oid and oid not in seen_ids:
            seen_ids.add(oid)
            unique_orders.append(o)

    print(f"📦 Found {len(unique_orders)} orders")

    # Aggregate by product variant
    product_stats = defaultdict(lambda: {
        "variant_id": "",
        "product_title": "",
        "variant_title": "",
        "sku": "",
        "total_qty": 0,
        "total_sales": 0.0,
        "total_revenue": 0.0,
        "total_cogs": 0.0,
        "total_profit": 0.0,
        "order_count": 0,
        "order_ids": set()
    })

    for order in unique_orders:
        try:
            # Skip cancelled orders
            if order.get("cancelledAt"):
                continue

            order_id = order.get("id", "")

            for li in _line_nodes(order):
                qty = int(li.get("quantity") or 0)
                if qty <= 0:
                    continue

                # Extract variant info
                variant = li.get("variant") or {}
                variant_gid = variant.get("id", "") or li.get("variantId", "")

                # Extract numeric variant ID
                match = re.search(r'(\d+)$', variant_gid)
                variant_id = match.group(1) if match else variant_gid

                if not variant_id:
                    continue

                product_title = li.get("title", "") or (li.get("product") or {}).get("title", "")
                variant_title = li.get("variantTitle", "") or variant.get("title", "")
                sku = variant.get("sku", "") or li.get("sku", "")

                # Calculate line financials
                line_gross = _money_at(li, ["originalTotalSet", "shopMoney", "amount"])
                unit_cost = _money_at(li, ["variant", "inventoryItem", "unitCost", "amount"])
                cogs = unit_cost * qty if unit_cost else 0

                # Discounted amount for net calculation
                line_discount = _money_at(li, ["totalDiscountSet", "shopMoney", "amount"])
                line_net = line_gross - line_discount

                # Update stats
                stats = product_stats[variant_id]
                stats["variant_id"] = variant_id
                stats["product_title"] = product_title
                stats["variant_title"] = variant_title
                stats["sku"] = sku
                stats["total_qty"] += qty
                stats["total_sales"] += line_gross
                stats["total_revenue"] += line_net
                stats["total_cogs"] += cogs
                stats["total_profit"] += line_net - cogs
                stats["order_ids"].add(order_id)

        except Exception as e:
            print(f"❌ Error processing order: {e}")
            continue

    # Calculate order count and convert to list
    bestsellers = []
    for variant_id, stats in product_stats.items():
        stats["order_count"] = len(stats["order_ids"])
        del stats["order_ids"]  # Remove set from output

        # Calculate margin
        if stats["total_revenue"] > 0:
            stats["margin_pct"] = round((stats["total_profit"] / stats["total_revenue"]) * 100, 1)
        else:
            stats["margin_pct"] = 0

        # Round financial values
        stats["total_sales"] = round(stats["total_sales"], 2)
        stats["total_revenue"] = round(stats["total_revenue"], 2)
        stats["total_cogs"] = round(stats["total_cogs"], 2)
        stats["total_profit"] = round(stats["total_profit"], 2)

        bestsellers.append(stats)

    # Sort by quantity sold (descending)
    bestsellers.sort(key=lambda x: x["total_qty"], reverse=True)

    # Build summary analytics
    total_products = len(bestsellers)
    total_qty_sold = sum(p["total_qty"] for p in bestsellers)
    total_revenue = sum(p["total_revenue"] for p in bestsellers)
    total_profit = sum(p["total_profit"] for p in bestsellers)

    # Top 10 by different metrics
    top_by_qty = sorted(bestsellers, key=lambda x: x["total_qty"], reverse=True)[:10]
    top_by_revenue = sorted(bestsellers, key=lambda x: x["total_revenue"], reverse=True)[:10]
    top_by_profit = sorted(bestsellers, key=lambda x: x["total_profit"], reverse=True)[:10]

    analytics = {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_products_sold": total_products,
        "total_units_sold": total_qty_sold,
        "total_revenue": round(total_revenue, 2),
        "total_profit": round(total_profit, 2),
        "avg_profit_per_unit": round(total_profit / total_qty_sold, 2) if total_qty_sold > 0 else 0,
        "total_orders": len(unique_orders)
    }

    print(f"✅ Processed {total_products} products, {total_qty_sold} units sold")

    return {
        "bestsellers": bestsellers[:100],  # Top 100
        "top_by_quantity": top_by_qty,
        "top_by_revenue": top_by_revenue,
        "top_by_profit": top_by_profit,
        "analytics": analytics
    }


def get_variant_order_count(variant_ids: List[str], days: int = 30) -> Dict[str, int]:
    """
    Get order count for specific variant IDs in the last N days

    Args:
        variant_ids: List of variant IDs to check
        days: Number of days to look back (default 30)

    Returns:
        Dict mapping variant_id -> order_count
    """
    shop_tz = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"
    tz = pytz.timezone(shop_tz)

    end_date = datetime.now(tz).date()
    start_date = end_date - timedelta(days=days)

    start_local = tz.localize(datetime.combine(start_date, datetime.min.time()))
    end_local = tz.localize(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

    print(f"📊 Getting order counts for {len(variant_ids)} variants (last {days} days)")

    # Convert to set for faster lookup
    target_variants = set(str(v) for v in variant_ids)

    # Fetch orders from all stores
    all_orders = []
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token = store["access_token"]
        orders = fetch_orders_created_between_for_store(
            domain, token,
            start_local.isoformat(),
            end_local.isoformat(),
            exclude_cancelled=True
        )
        all_orders.extend(orders)

    # Deduplicate by ID
    seen_ids = set()
    unique_orders = []
    for o in all_orders:
        oid = o.get("id")
        if oid and oid not in seen_ids:
            seen_ids.add(oid)
            unique_orders.append(o)

    # Count orders per variant
    variant_order_sets = defaultdict(set)

    for order in unique_orders:
        if order.get("cancelledAt"):
            continue

        order_id = order.get("id", "")

        for li in _line_nodes(order):
            variant = li.get("variant") or {}
            variant_gid = variant.get("id", "") or li.get("variantId", "")

            match = re.search(r'(\d+)$', variant_gid)
            variant_id = match.group(1) if match else variant_gid

            if variant_id in target_variants:
                variant_order_sets[variant_id].add(order_id)

    # Convert to counts
    result = {v: len(variant_order_sets.get(v, set())) for v in variant_ids}

    print(f"✅ Found order counts for {sum(1 for v in result.values() if v > 0)} variants with orders")

    return result
