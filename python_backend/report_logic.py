"""
Real report logic using exact same calculations as mirai_report
Fetches from Shopify → Google Ads → Meta → PayPal → PSP
"""
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
import os
import pytz

# Import the REAL logic from master_report_mirai
import sys
sys.path.insert(0, os.path.dirname(__file__))

from master_report_mirai import compute_day_kpis, get_shop_timezone


def fetch_daily_reports(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetch daily reports using the REAL mirai_report logic.
    This ensures numbers match exactly.
    """
    # Get timezone from Shopify (same as mirai_report does)
    shop_tz = get_shop_timezone() or os.getenv("REPORT_TZ") or "UTC"

    data = []
    current = start_date

    while current <= end_date:
        try:
            # Use the REAL compute_day_kpis from master_report_mirai
            kpis = compute_day_kpis(current, shop_tz)

            # Convert to API format
            data.append({
                "date": current.isoformat(),
                "label": kpis.day,
                "orders": kpis.orders,
                "gross": kpis.gross,
                "discounts": kpis.discounts,
                "refunds": kpis.refunds,
                "net": kpis.net,
                "cogs": kpis.cogs,
                "shipping_charged": kpis.shipping_charged,
                "shipping_cost": kpis.shipping_estimated,  # Use matrix shipping for display
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
            })

            print(f"✅ Calculated {current}: {kpis.orders} orders, ${kpis.net} net")

        except Exception as e:
            print(f"❌ Error calculating {current}: {e}")
            import traceback
            traceback.print_exc()

            # Return zeros on error
            data.append({
                "date": current.isoformat(),
                "label": current.strftime("%a, %b %d"),
                "orders": 0,
                "net": 0.0,
                "operational_profit": 0.0,
                "margin_pct": 0.0,
                "error": str(e),
            })

        current += timedelta(days=1)

    return data
