"""
Real report logic using exact same calculations as mirai_report
Fetches from Shopify → Google Ads → Meta → PayPal → PSP
Uses parallel execution for faster multi-day fetching
"""
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import pytz

# Import the REAL logic from master_report_mirai
import sys
sys.path.insert(0, os.path.dirname(__file__))

from master_report_mirai import compute_day_kpis, get_shop_timezone

# Max workers for parallel fetching (balance between speed and API rate limits)
MAX_WORKERS = int(os.getenv("REPORT_PARALLEL_WORKERS", "5"))


def _fetch_single_day(day: date, shop_tz: str) -> Dict[str, Any]:
    """Fetch KPIs for a single day - used for parallel execution"""
    try:
        kpis = compute_day_kpis(day, shop_tz)
        result = {
            "date": day.isoformat(),
            "label": kpis.day,
            "orders": kpis.orders,
            "gross": kpis.gross,
            "discounts": kpis.discounts,
            "refunds": kpis.refunds,
            "net": kpis.net,
            "cogs": kpis.cogs,
            "shipping_charged": kpis.shipping_charged,
            "shipping_cost": kpis.shipping_estimated,
            "google_spend": kpis.google_spend,
            "meta_spend": kpis.meta_spend,
            "total_spend": kpis.total_spend,
            "google_pur": kpis.google_pur,
            "meta_pur": kpis.meta_pur,
            "google_cpa": kpis.google_cpa or 0.0,
            "meta_cpa": kpis.meta_cpa or 0.0,
            "general_cpa": kpis.general_cpa or 0.0,
            "psp_usd": kpis.psp_usd,
            "operational_profit": kpis.operational,
            "net_margin": kpis.margin,
            "margin_pct": kpis.margin_pct or 0.0,
            "aov": kpis.aov,
            "returning_customers": kpis.returning_count,
        }
        print(f"✅ Calculated {day}: {kpis.orders} orders, ${kpis.net:.2f} net")
        return result
    except Exception as e:
        print(f"❌ Error calculating {day}: {e}")
        return {
            "date": day.isoformat(),
            "label": day.strftime("%a, %b %d"),
            "orders": 0,
            "net": 0.0,
            "operational_profit": 0.0,
            "margin_pct": 0.0,
            "error": str(e),
        }


def fetch_daily_reports(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetch daily reports using the REAL mirai_report logic.
    Uses parallel execution for faster fetching of multiple days.
    """
    shop_tz = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"

    # Build list of days to fetch
    days = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)

    num_days = len(days)
    print(f"📊 Fetching {num_days} days of reports (parallel workers: {min(MAX_WORKERS, num_days)})")

    # For single day, just fetch directly (no overhead)
    if num_days == 1:
        return [_fetch_single_day(days[0], shop_tz)]

    # Use ThreadPoolExecutor for parallel fetching
    results_dict = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, num_days)) as executor:
        future_to_day = {executor.submit(_fetch_single_day, day, shop_tz): day for day in days}

        for future in as_completed(future_to_day):
            day = future_to_day[future]
            try:
                result = future.result()
                results_dict[day] = result
            except Exception as e:
                print(f"❌ Future failed for {day}: {e}")
                results_dict[day] = {
                    "date": day.isoformat(),
                    "label": day.strftime("%a, %b %d"),
                    "orders": 0,
                    "net": 0.0,
                    "operational_profit": 0.0,
                    "margin_pct": 0.0,
                    "error": str(e),
                }

    # Return results in chronological order
    return [results_dict[day] for day in days]
