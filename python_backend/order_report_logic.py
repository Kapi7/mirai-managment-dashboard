"""
Order Report Logic - Fetch order-level breakdown with analytics
"""
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _shopify_channel(order: dict) -> str:
    """Determine order source channel"""
    attrs = order.get("customAttributes") or []
    for attr in attrs:
        if attr.get("key") == "_attribution_source":
            val = (attr.get("value") or "").lower()
            if "google" in val:
                return "google"
            if "meta" in val or "facebook" in val or "instagram" in val:
                return "meta"
    return "organic"


def _line_nodes(order: dict) -> list:
    """Get line items from order"""
    li = order.get("lineItems") or {}
    edges = li.get("edges") or []
    return [e.get("node") or {} for e in edges]


def fetch_order_report(start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Fetch order-level breakdown for the date range

    Returns:
        Dict with orders list and analytics summary
    """
    shop_tz = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"
    tz = pytz.timezone(shop_tz)

    start_local = tz.localize(datetime.combine(start_date, datetime.min.time()))
    end_local = tz.localize(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

    print(f"📦 Fetching orders from {start_date} to {end_date}")

    # Fetch orders from all stores
    all_orders = []
    for store in SHOPIFY_STORES:
        domain = store["domain"]
        token = store["access_token"]
        orders = fetch_orders_created_between_for_store(
            domain, token,
            start_local.isoformat(),
            end_local.isoformat(),
            exclude_cancelled=False
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

    # Process orders
    orders_data = []

    # Analytics accumulators
    total_gross = 0.0
    total_discounts = 0.0
    total_refunds = 0.0
    total_net = 0.0
    total_cogs = 0.0
    total_shipping = 0.0
    channel_counts = {"google": 0, "meta": 0, "organic": 0}
    country_counts = {}
    hourly_counts = {h: 0 for h in range(24)}

    for order in unique_orders:
        try:
            created_at = _parse_dt(order.get("createdAt"))
            if not created_at:
                continue

            # Convert to local time
            if created_at.tzinfo is None:
                created_at = pytz.UTC.localize(created_at)
            created_local = created_at.astimezone(tz)

            # Check if cancelled
            is_cancelled = bool(order.get("cancelledAt"))

            # Get channel
            channel = _shopify_channel(order)

            # Get customer info
            customer = order.get("customer") or {}
            customer_name = f"{customer.get('firstName', '')} {customer.get('lastName', '')}".strip() or "Guest"
            customer_email = customer.get("email", "")
            is_returning = int(customer.get("numberOfOrders") or 0) > 1

            # Get shipping address
            shipping_addr = order.get("shippingAddress") or {}
            country = shipping_addr.get("country", "") or shipping_addr.get("countryCodeV2", "") or "Unknown"
            city = shipping_addr.get("city", "")

            # Calculate financials
            gross = 0.0
            cogs = 0.0
            items = []

            for li in _line_nodes(order):
                qty = int(li.get("quantity") or 0)
                line_gross = _money_at(li, ["originalTotalSet", "shopMoney", "amount"])
                unit_cost = _money_at(li, ["variant", "inventoryItem", "unitCost", "amount"])

                gross += line_gross
                if qty > 0 and unit_cost:
                    cogs += unit_cost * qty

                items.append({
                    "title": li.get("title", ""),
                    "variant": li.get("variantTitle", ""),
                    "quantity": qty,
                    "price": line_gross,
                    "unit_cost": unit_cost
                })

            discounts = (
                _money_at(order, ["totalDiscountsSet", "shopMoney", "amount"]) or
                _money_at(order, ["currentTotalDiscountsSet", "shopMoney", "amount"])
            )
            refunds = _money_at(order, ["totalRefundedSet", "shopMoney", "amount"])
            shipping = (
                _money_at(order, ["totalShippingPriceSet", "shopMoney", "amount"]) or
                _money_at(order, ["currentShippingPriceSet", "shopMoney", "amount"])
            )

            net = gross - discounts - refunds
            profit = net + shipping - cogs
            margin_pct = (profit / (net + shipping)) * 100 if (net + shipping) > 0 else 0

            # Extract order number
            order_name = order.get("name", "")
            order_id = order.get("id", "")
            # Extract numeric ID from gid
            order_id_num = re.search(r'(\d+)$', order_id)
            order_id_num = order_id_num.group(1) if order_id_num else order_id

            order_record = {
                "order_id": order_id_num,
                "order_name": order_name,
                "created_at": created_local.isoformat(),
                "date": created_local.strftime("%Y-%m-%d"),
                "time": created_local.strftime("%H:%M"),
                "hour": created_local.hour,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "is_returning": is_returning,
                "channel": channel,
                "country": country,
                "city": city,
                "is_cancelled": is_cancelled,
                "gross": round(gross, 2),
                "discounts": round(discounts, 2),
                "refunds": round(refunds, 2),
                "net": round(net, 2),
                "shipping": round(shipping, 2),
                "cogs": round(cogs, 2),
                "profit": round(profit, 2),
                "margin_pct": round(margin_pct, 1),
                "items_count": len(items),
                "items": items,
                "store": order.get("_store", "")
            }

            orders_data.append(order_record)

            # Update analytics (exclude cancelled)
            if not is_cancelled:
                total_gross += gross
                total_discounts += discounts
                total_refunds += refunds
                total_net += net
                total_cogs += cogs
                total_shipping += shipping
                channel_counts[channel] = channel_counts.get(channel, 0) + 1
                country_counts[country] = country_counts.get(country, 0) + 1
                hourly_counts[created_local.hour] += 1

        except Exception as e:
            print(f"❌ Error processing order: {e}")
            continue

    # Sort orders by date/time descending
    orders_data.sort(key=lambda x: x["created_at"], reverse=True)

    # Build analytics summary
    total_orders = len([o for o in orders_data if not o["is_cancelled"]])
    total_profit = total_net + total_shipping - total_cogs
    avg_order_value = total_gross / total_orders if total_orders > 0 else 0
    avg_margin = (total_profit / (total_net + total_shipping)) * 100 if (total_net + total_shipping) > 0 else 0

    # Top countries
    top_countries = sorted(country_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Peak hours
    peak_hours = sorted(hourly_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    analytics = {
        "total_orders": total_orders,
        "cancelled_orders": len([o for o in orders_data if o["is_cancelled"]]),
        "total_gross": round(total_gross, 2),
        "total_discounts": round(total_discounts, 2),
        "total_refunds": round(total_refunds, 2),
        "total_net": round(total_net, 2),
        "total_shipping": round(total_shipping, 2),
        "total_cogs": round(total_cogs, 2),
        "total_profit": round(total_profit, 2),
        "avg_order_value": round(avg_order_value, 2),
        "avg_margin_pct": round(avg_margin, 1),
        "returning_customers": len([o for o in orders_data if o["is_returning"] and not o["is_cancelled"]]),
        "channels": channel_counts,
        "top_countries": [{"country": c, "count": n} for c, n in top_countries],
        "peak_hours": [{"hour": h, "count": n} for h, n in peak_hours]
    }

    print(f"✅ Processed {len(orders_data)} orders")

    return {
        "orders": orders_data,
        "analytics": analytics
    }
