"""
Clean report logic - fetch data from APIs and calculate metrics
NO automation, NO Telegram, NO monitoring - just pure data
"""
from datetime import date, timedelta
from typing import List, Dict, Any
import os

# Import only the API clients we need
from shopify_client import fetch_orders_graphql
from meta_client import fetch_meta_insights_day
from paypal_client import fetch_paypal_transactions
from psp_fee import calculate_psp_fee_usd
from transform import orders_to_df, aggregate_shopify, paypal_shipping_total_grouped

# Google Ads - use simplified version
try:
    from google_ads_spend import daily_spend_usd_aligned
except Exception:
    def daily_spend_usd_aligned(day_str, tz_name):
        return 0.0  # Fallback if Google Ads not configured


def fetch_daily_reports(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetch daily reports for the given date range.
    Returns a list of daily metrics.
    """
    shop_tz = os.getenv("REPORT_TZ", "UTC")
    data = []

    current = start_date
    while current <= end_date:
        try:
            day_metrics = calculate_day_metrics(current, shop_tz)
            data.append(day_metrics)
        except Exception as e:
            # If a day fails, log and continue
            print(f"Error calculating metrics for {current}: {e}")
            data.append({
                "date": current.isoformat(),
                "label": current.strftime("%a, %b %d"),
                "error": str(e),
                "orders": 0,
                "net": 0.0,
                "operational_profit": 0.0,
            })

        current += timedelta(days=1)

    return data


def calculate_day_metrics(day: date, shop_tz: str) -> Dict[str, Any]:
    """
    Calculate all metrics for a single day.
    """
    day_str = day.isoformat()

    # 1. Fetch Shopify orders
    orders = fetch_orders_graphql(day_str, day_str)
    df = orders_to_df(orders)
    shopify_metrics = aggregate_shopify(df)

    # 2. Fetch Meta Ads
    meta_data = fetch_meta_insights_day(day_str, day_str) or {}
    meta_spend = meta_data.get("meta_spend", 0.0)
    meta_purchases = meta_data.get("meta_purchases", 0)

    # 3. Fetch Google Ads
    try:
        google_spend = daily_spend_usd_aligned(day_str, shop_tz)
    except Exception as e:
        print(f"Google Ads error for {day_str}: {e}")
        google_spend = 0.0

    # 4. Fetch PayPal (for shipping costs)
    try:
        paypal_txns = fetch_paypal_transactions(day_str, day_str)
        paypal_df = None  # Would need to convert to df
        paypal_shipping = 0.0  # Simplified for now
    except Exception:
        paypal_shipping = 0.0

    # 5. Calculate derived metrics
    orders_count = shopify_metrics["orders"]
    gross = shopify_metrics["gross"]
    net = shopify_metrics["net"]
    cogs = shopify_metrics["cogs"]
    shipping_charged = shopify_metrics["shipping_charged"]

    total_spend = google_spend + meta_spend

    # Estimate Google purchases (total orders minus Meta purchases)
    google_purchases = max(orders_count - meta_purchases, 0)

    # Calculate CPAs
    google_cpa = google_spend / google_purchases if google_purchases > 0 else 0.0
    meta_cpa = meta_spend / meta_purchases if meta_purchases > 0 else 0.0
    general_cpa = total_spend / orders_count if orders_count > 0 else 0.0

    # PSP fees
    psp_fee = calculate_psp_fee_usd(net)

    # Operational profit = net - cogs - ad spend - psp fees - shipping cost
    shipping_cost = paypal_shipping  # Simplified
    operational_profit = net - cogs - total_spend - psp_fee - shipping_cost

    # Margin
    margin_pct = (operational_profit / net * 100) if net > 0 else 0.0

    # AOV
    aov = net / orders_count if orders_count > 0 else 0.0

    return {
        "date": day_str,
        "label": day.strftime("%a, %b %d"),
        "orders": orders_count,
        "gross": round(gross, 2),
        "discounts": round(shopify_metrics["discounts"], 2),
        "refunds": round(shopify_metrics["refunds"], 2),
        "net": round(net, 2),
        "cogs": round(cogs, 2),
        "shipping_charged": round(shipping_charged, 2),
        "shipping_cost": round(shipping_cost, 2),
        "google_spend": round(google_spend, 2),
        "meta_spend": round(meta_spend, 2),
        "total_spend": round(total_spend, 2),
        "google_pur": google_purchases,
        "meta_pur": meta_purchases,
        "google_cpa": round(google_cpa, 2),
        "meta_cpa": round(meta_cpa, 2),
        "general_cpa": round(general_cpa, 2),
        "psp_usd": round(psp_fee, 2),
        "operational_profit": round(operational_profit, 2),
        "net_margin": round(operational_profit, 2),  # Same as operational_profit
        "margin_pct": round(margin_pct, 2),
        "aov": round(aov, 2),
        "returning_customers": shopify_metrics["rcr_count"],
    }
